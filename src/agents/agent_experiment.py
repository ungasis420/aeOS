"""
src/agents/agent_experiment.py

Micro-experiment design + tracking agent for aeOS.

Purpose:
- Convert pain points and hypotheses into structured, testable experiments.
- Persist experiments in SQLite (Experiment_Registry) with basic lifecycle tracking.
- Provide evaluation + insights loops using LLM when available, with graceful offline fallbacks.

All public functions return:
  { "success": True, ... } OR { "success": False, "error": "<message>" }
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from src.ai.ai_infer import infer, infer_json
from src.ai.ai_context import build_pain_context, build_kb_context


# -----------------------------
# Internal helpers
# -----------------------------

_ALLOWED_EVAL_STATUSES = {"active", "success", "failure", "partial", "unresolved"}


def _now_utc() -> datetime:
    """Return current UTC timestamp (naive datetime)."""
    return datetime.utcnow()


def _iso_date(dt: datetime) -> str:
    """Return YYYY-MM-DD date string."""
    return dt.date().isoformat()


def _safe_commit(conn: Any) -> None:
    """Commit if possible; never raise."""
    try:
        if conn is not None and hasattr(conn, "commit"):
            conn.commit()
    except Exception:
        pass


def _safe_cursor(conn: Any) -> Optional[Any]:
    """Return a cursor if possible; never raise."""
    try:
        if conn is None:
            return None
        return conn.cursor()
    except Exception:
        return None


def _table_exists(conn: Any, table_name: str) -> bool:
    """Best-effort SQLite table existence check."""
    try:
        cur = _safe_cursor(conn)
        if cur is None:
            return False
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table_name,),
        )
        row = cur.fetchone()
        return bool(row)
    except Exception:
        return False


def _ensure_experiment_registry(conn: Any) -> Dict[str, Any]:
    """
    Ensure Experiment_Registry exists. Adds lightweight indexes.
    """
    try:
        cur = _safe_cursor(conn)
        if cur is None:
            return {"success": False, "error": "No DB cursor available."}

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS Experiment_Registry (
                experiment_id TEXT PRIMARY KEY,
                pain_id INTEGER,
                hypothesis TEXT,
                test_design TEXT,
                duration_days INTEGER,
                start_date TEXT,
                success_criteria TEXT,
                status TEXT DEFAULT 'active',
                outcome TEXT,
                learning TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Helpful indexes (safe, additive)
        try:
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_experiment_registry_pain_id ON Experiment_Registry(pain_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_experiment_registry_status ON Experiment_Registry(status)"
            )
        except Exception:
            # Index creation isn't critical
            pass

        _safe_commit(conn)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": f"Failed to ensure Experiment_Registry: {e}"}


def _extract_json_from_text(text: str) -> Optional[Union[Dict[str, Any], List[Any]]]:
    """
    Extract first JSON object/array found in text and parse it.
    Handles common LLM wrappers (```json ... ```).
    """
    try:
        if not text:
            return None

        # Strip code fences if present
        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            text = fenced.group(1).strip()

        # Try direct parse first
        try:
            parsed = json.loads(text)
            if isinstance(parsed, (dict, list)):
                return parsed
        except Exception:
            pass

        # Find first JSON object or array substring
        obj_match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        arr_match = re.search(r"\[.*\]", text, flags=re.DOTALL)

        candidates = []
        if obj_match:
            candidates.append(obj_match.group(0))
        if arr_match:
            candidates.append(arr_match.group(0))

        for cand in candidates:
            try:
                parsed = json.loads(cand)
                if isinstance(parsed, (dict, list)):
                    return parsed
            except Exception:
                continue

        return None
    except Exception:
        return None


def _infer_structured(prompt: str, default: Any) -> Any:
    """
    Best-effort structured inference.
    Prefers infer_json, falls back to infer + JSON extraction, then default.
    Never raises.
    """
    # 1) Try infer_json (if it returns structured)
    try:
        r = infer_json(prompt)
        if isinstance(r, dict) and r.get("success") is True:
            payload = r.get("data")
            if isinstance(payload, (dict, list)):
                return payload
            # Some wrappers may store JSON as string under response/text
            txt = r.get("response") or r.get("text") or r.get("output")
            if isinstance(txt, str):
                parsed = _extract_json_from_text(txt)
                if parsed is not None:
                    return parsed
    except Exception:
        pass

    # 2) Try infer and parse JSON
    try:
        r = infer(prompt)
        if isinstance(r, dict):
            txt = r.get("response") or r.get("text") or r.get("output") or ""
        else:
            txt = str(r)
        parsed = _extract_json_from_text(txt)
        if parsed is not None:
            return parsed
    except Exception:
        pass

    return default


def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    """Clamp to int within [lo, hi]."""
    try:
        n = int(value)
        return max(lo, min(hi, n))
    except Exception:
        return default


def _clamp_float(value: Any, lo: float, hi: float, default: float) -> float:
    """Clamp to float within [lo, hi]."""
    try:
        x = float(value)
        if x != x:  # NaN
            return default
        return max(lo, min(hi, x))
    except Exception:
        return default


def _normalize_status(status: Any) -> str:
    """Map loose status strings into canonical set."""
    s = str(status or "").strip().lower()
    mapping = {
        "active": "active",
        "in_progress": "active",
        "in progress": "active",
        "success": "success",
        "succeeded": "success",
        "passed": "success",
        "met": "success",
        "failure": "failure",
        "failed": "failure",
        "did_not_meet": "failure",
        "partial": "partial",
        "partially_met": "partial",
        "mixed": "partial",
        "unresolved": "unresolved",
        "inconclusive": "unresolved",
        "needs_data": "unresolved",
        "unknown": "unresolved",
    }
    out = mapping.get(s, s if s in _ALLOWED_EVAL_STATUSES else "unresolved")
    return out if out in _ALLOWED_EVAL_STATUSES else "unresolved"


def _row_to_dict(cur: Any, row: Any) -> Dict[str, Any]:
    """Convert cursor row to dict using cursor.description when possible."""
    try:
        if row is None:
            return {}
        cols = [d[0] for d in (cur.description or [])]
        if cols and isinstance(row, (tuple, list)) and len(cols) == len(row):
            return {cols[i]: row[i] for i in range(len(cols))}
        # If it's already dict-like
        if isinstance(row, dict):
            return dict(row)
        return {}
    except Exception:
        return {}


def _fetch_one_dict(conn: Any, sql: str, params: Tuple[Any, ...]) -> Dict[str, Any]:
    """Fetch one row and return as dict; never raises."""
    try:
        cur = _safe_cursor(conn)
        if cur is None:
            return {}
        cur.execute(sql, params)
        row = cur.fetchone()
        return _row_to_dict(cur, row)
    except Exception:
        return {}


def _fetch_all_dicts(conn: Any, sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
    """Fetch all rows and return as list of dicts; never raises."""
    try:
        cur = _safe_cursor(conn)
        if cur is None:
            return []
        cur.execute(sql, params)
        rows = cur.fetchall() or []
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append(_row_to_dict(cur, r))
        return out
    except Exception:
        return []


def _parse_start_date(exp_row: Dict[str, Any]) -> Optional[datetime]:
    """Parse start_date from row; fallback to created_at if available."""
    try:
        sd = (exp_row.get("start_date") or "").strip()
        if sd:
            # Accept YYYY-MM-DD or full ISO datetime
            try:
                return datetime.fromisoformat(sd)
            except Exception:
                # Try date-only
                return datetime.fromisoformat(sd + "T00:00:00")
        created = exp_row.get("created_at")
        if isinstance(created, str) and created.strip():
            try:
                return datetime.fromisoformat(created.strip())
            except Exception:
                pass
        return None
    except Exception:
        return None


def _compute_due_date(start_dt: Optional[datetime], duration_days: int) -> Optional[datetime]:
    """Compute due date; returns None if start_dt missing."""
    try:
        if start_dt is None:
            return None
        return start_dt + timedelta(days=int(duration_days))
    except Exception:
        return None


def _fetch_pain_bundle(conn: Any, pain_id: int) -> Dict[str, Any]:
    """
    Try to fetch a pain record and linked solutions from common aeOS table names.
    Works best-effort across schema variants.
    """
    try:
        pain: Dict[str, Any] = {}
        solutions: List[Dict[str, Any]] = []

        if _table_exists(conn, "Pain_Registry"):
            pain = _fetch_one_dict(conn, "SELECT * FROM Pain_Registry WHERE id = ? LIMIT 1", (pain_id,))
        elif _table_exists(conn, "Pain_Point_Register"):
            # Some installs may use integer PK "id" even if blueprint uses text IDs.
            pain = _fetch_one_dict(conn, "SELECT * FROM Pain_Point_Register WHERE id = ? LIMIT 1", (pain_id,))
            if not pain:
                pain = _fetch_one_dict(conn, "SELECT * FROM Pain_Point_Register WHERE Pain_ID = ? LIMIT 1", (str(pain_id),))

        if _table_exists(conn, "Solution_Registry"):
            solutions = _fetch_all_dicts(
                conn,
                "SELECT * FROM Solution_Registry WHERE pain_id = ? ORDER BY roi_score DESC, updated_at DESC",
                (pain_id,),
            )
        elif _table_exists(conn, "Solution_Design") and pain:
            # Blueprint variant uses Solution_Design linked to Pain_ID (likely text); attempt if possible.
            pid = pain.get("Pain_ID") or pain.get("pain_id") or pain.get("id")
            if pid is not None:
                solutions = _fetch_all_dicts(
                    conn,
                    "SELECT * FROM Solution_Design WHERE Pain_ID = ? ORDER BY Last_Updated DESC",
                    (str(pid),),
                )

        return {"pain": pain, "solutions": solutions, "success": True}
    except Exception as e:
        return {"pain": {}, "solutions": [], "success": False, "error": str(e)}


def _search_local_context(conn: Any, topic: str, limit: int = 5) -> Dict[str, Any]:
    """Search common tables for topic mentions (best-effort)."""
    try:
        t = (topic or "").strip()
        if not t:
            return {"success": True, "matches": []}

        like = f"%{t}%"
        matches: List[Dict[str, Any]] = []

        if _table_exists(conn, "Pain_Registry"):
            rows = _fetch_all_dicts(
                conn,
                "SELECT * FROM Pain_Registry WHERE title LIKE ? OR status LIKE ? LIMIT ?",
                (like, like, limit),
            )
            matches.extend([{"table": "Pain_Registry", "row": r} for r in rows])

        if _table_exists(conn, "Solution_Registry"):
            rows = _fetch_all_dicts(
                conn,
                "SELECT * FROM Solution_Registry WHERE title LIKE ? OR status LIKE ? LIMIT ?",
                (like, like, limit),
            )
            matches.extend([{"table": "Solution_Registry", "row": r} for r in rows])

        if _table_exists(conn, "Experiment_Registry"):
            rows = _fetch_all_dicts(
                conn,
                "SELECT * FROM Experiment_Registry WHERE hypothesis LIKE ? OR test_design LIKE ? OR outcome LIKE ? LIMIT ?",
                (like, like, like, limit),
            )
            matches.extend([{"table": "Experiment_Registry", "row": r} for r in rows])

        return {"success": True, "matches": matches[:limit]}
    except Exception as e:
        return {"success": False, "error": f"Search failed: {e}", "matches": []}


# -----------------------------
# Public API
# -----------------------------

def design_experiment(conn: sqlite3.Connection, pain_id: int) -> dict:
    """
    Takes a pain point ID, designs a testable micro-experiment, and persists it.
    Returns:
      {pain_id, hypothesis, test_design, duration_days, success_criteria, measurement_method, experiment_id, success}
    """
    try:
        if conn is None:
            return {"success": False, "error": "conn is required"}

        ensured = _ensure_experiment_registry(conn)
        can_persist = bool(ensured.get("success"))

        pain_ctx = ""
        try:
            pain_ctx = build_pain_context(conn, pain_id) or ""
        except Exception:
            pain_ctx = ""

        bundle = _fetch_pain_bundle(conn, pain_id)
        pain = bundle.get("pain") or {}
        solutions = bundle.get("solutions") or []

        # Prior experiments for this pain (if any)
        prior_exps: List[Dict[str, Any]] = []
        try:
            prior_exps = _fetch_all_dicts(
                conn,
                "SELECT experiment_id, hypothesis, status, outcome, learning, created_at "
                "FROM Experiment_Registry WHERE pain_id = ? AND status != 'active' "
                "ORDER BY created_at DESC LIMIT 10",
                (pain_id,),
            )
        except Exception:
            prior_exps = []

        prompt = f"""
You are aeOS Micro-Experiment Designer.
Goal: Turn a pain point into a low-cost, reversible, testable micro-experiment.

Return ONLY valid JSON with keys:
- hypothesis (string)
- test_design (string; step-by-step; include daily/weekly cadence)
- duration_days (integer; prefer 3-14)
- success_criteria (string; measurable and falsifiable)
- measurement_method (string; how to collect data consistently)

Pain_ID: {pain_id}

Pain_Record (may be partial):
{json.dumps(pain, ensure_ascii=False)}

Pain_Context (may be empty):
{pain_ctx}

Candidate_Solutions (may be empty):
{json.dumps(solutions[:5], ensure_ascii=False)}

Past_Experiments (may be empty):
{json.dumps(prior_exps, ensure_ascii=False)}

Constraints:
- Keep it small enough to run even on a bad week.
- Define a single primary metric + optional secondary metric.
- Avoid vague criteria like "feel better" unless you operationalize it.
"""

        default_plan = {
            "hypothesis": "If I run a small, structured test for 7 days, this pain will reduce measurably.",
            "test_design": "For 7 days, implement one targeted change tied to the pain. Track baseline (day 0), then track daily.",
            "duration_days": 7,
            "success_criteria": "Primary metric improves by at least 20% vs baseline OR pain severity drops by ≥2 points (1-10 scale).",
            "measurement_method": "Daily log: pain severity (1-10) + primary metric count/time. Compare to baseline.",
        }

        llm = _infer_structured(prompt, default_plan)
        if not isinstance(llm, dict):
            llm = default_plan

        hypothesis = str(llm.get("hypothesis") or default_plan["hypothesis"]).strip()
        test_design = str(llm.get("test_design") or default_plan["test_design"]).strip()
        duration_days = _clamp_int(llm.get("duration_days"), 1, 60, int(default_plan["duration_days"]))
        success_criteria = str(llm.get("success_criteria") or default_plan["success_criteria"]).strip()
        measurement_method = str(llm.get("measurement_method") or default_plan["measurement_method"]).strip()

        # Ensure measurement method is preserved even if schema doesn't store it separately
        if measurement_method and "measurement method" not in test_design.lower():
            test_design = f"{test_design}\n\nMeasurement method: {measurement_method}"

        experiment_id = f"EXP-{uuid.uuid4().hex.upper()}"
        start_date = _iso_date(_now_utc())

        record = {
            "experiment_id": experiment_id,
            "pain_id": pain_id,
            "hypothesis": hypothesis,
            "test_design": test_design,
            "duration_days": duration_days,
            "start_date": start_date,
            "success_criteria": success_criteria,
            "status": "active",
            "outcome": None,
            "learning": None,
        }

        saved_to_db = False
        if can_persist:
            try:
                cur = _safe_cursor(conn)
                if cur is not None:
                    cur.execute(
                        """
                        INSERT INTO Experiment_Registry (
                            experiment_id, pain_id, hypothesis, test_design,
                            duration_days, start_date, success_criteria, status,
                            outcome, learning
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record["experiment_id"],
                            record["pain_id"],
                            record["hypothesis"],
                            record["test_design"],
                            record["duration_days"],
                            record["start_date"],
                            record["success_criteria"],
                            record["status"],
                            record["outcome"],
                            record["learning"],
                        ),
                    )
                    _safe_commit(conn)
                    saved_to_db = True
            except Exception:
                saved_to_db = False

        out = {
            "pain_id": pain_id,
            "hypothesis": hypothesis,
            "test_design": test_design,
            "duration_days": duration_days,
            "success_criteria": success_criteria,
            "measurement_method": measurement_method,
            "experiment_id": experiment_id,
            "saved_to_db": saved_to_db,
            "success": True,
        }

        if not saved_to_db:
            out["experiment_json"] = json.dumps(record, ensure_ascii=False)

        return out

    except Exception as e:
        return {"success": False, "error": f"design_experiment failed: {e}"}


def evaluate_experiment(conn: sqlite3.Connection, experiment_id: str) -> dict:
    """
    Evaluate an experiment if its duration has passed.
    Uses LLM to compare available evidence/outcome notes against success criteria.
    Returns:
      {experiment_id, status, outcome, learning, confidence, success}
    """
    try:
        if conn is None:
            return {"success": False, "error": "conn is required"}
        if not experiment_id or not str(experiment_id).strip():
            return {"success": False, "error": "experiment_id is required"}

        ensured = _ensure_experiment_registry(conn)
        if not ensured.get("success"):
            return {"success": False, "error": "Experiment_Registry not available."}

        exp = _fetch_one_dict(
            conn,
            "SELECT * FROM Experiment_Registry WHERE experiment_id = ? LIMIT 1",
            (str(experiment_id).strip(),),
        )
        if not exp:
            return {"success": False, "error": f"Experiment not found: {experiment_id}"}

        start_dt = _parse_start_date(exp)
        duration_days = _clamp_int(exp.get("duration_days"), 1, 3650, 7)
        due_dt = _compute_due_date(start_dt, duration_days)
        now = _now_utc()

        current_status = _normalize_status(exp.get("status") or "active")
        existing_outcome = (exp.get("outcome") or "").strip()
        existing_learning = (exp.get("learning") or "").strip()

        due_iso = due_dt.isoformat() if due_dt else None
        is_due = bool(due_dt and now >= due_dt)

        # If not due yet and still active, return early
        if not is_due and current_status == "active":
            return {
                "experiment_id": exp.get("experiment_id"),
                "status": "active",
                "outcome": "Not due yet. Re-run after the due date.",
                "learning": "",
                "confidence": 0.0,
                "due_date": due_iso,
                "success": True,
            }

        # If already evaluated (status not active), return what we have
        if current_status != "active":
            return {
                "experiment_id": exp.get("experiment_id"),
                "status": current_status,
                "outcome": existing_outcome or "No outcome text recorded.",
                "learning": existing_learning or "",
                "confidence": 0.6 if existing_outcome else 0.3,
                "due_date": due_iso,
                "success": True,
            }

        # Build context for evaluation
        pain_ctx = ""
        try:
            if exp.get("pain_id") is not None:
                pain_ctx = build_pain_context(conn, int(exp.get("pain_id"))) or ""
        except Exception:
            pain_ctx = ""

        prompt = f"""
You are aeOS Experiment Evaluator.
Task: Decide whether the experiment met its success criteria based on available evidence.

Return ONLY valid JSON with keys:
- status: one of ["success","failure","partial","unresolved"]
- outcome: concise outcome statement (what happened)
- learning: key learning (what to do next / what changed your mind)
- confidence: float 0.0-1.0 (how confident you are in the evaluation)

Experiment:
{json.dumps(exp, ensure_ascii=False)}

Pain_Context (may be empty):
{pain_ctx}

Notes:
- If outcome/measurement evidence is missing, set status="unresolved" and specify what evidence is missing in outcome.
- Be strict: success requires meeting the written success_criteria, not vibes.
"""

        default_eval = {
            "status": "unresolved",
            "outcome": "Insufficient measurement evidence recorded to evaluate against success criteria.",
            "learning": "Record primary metric results and rerun evaluation.",
            "confidence": 0.25,
        }

        llm = _infer_structured(prompt, default_eval)
        if not isinstance(llm, dict):
            llm = default_eval

        status = _normalize_status(llm.get("status") or default_eval["status"])
        if status == "active":
            status = "unresolved"

        outcome = str(llm.get("outcome") or default_eval["outcome"]).strip()
        learning = str(llm.get("learning") or default_eval["learning"]).strip()
        confidence = _clamp_float(llm.get("confidence"), 0.0, 1.0, float(default_eval["confidence"]))

        # Persist evaluation
        try:
            cur = _safe_cursor(conn)
            if cur is not None:
                cur.execute(
                    "UPDATE Experiment_Registry SET status = ?, outcome = ?, learning = ? WHERE experiment_id = ?",
                    (status, outcome, learning, exp.get("experiment_id")),
                )
                _safe_commit(conn)
        except Exception:
            pass

        return {
            "experiment_id": exp.get("experiment_id"),
            "status": status,
            "outcome": outcome,
            "learning": learning,
            "confidence": confidence,
            "due_date": due_iso,
            "success": True,
        }

    except Exception as e:
        return {"success": False, "error": f"evaluate_experiment failed: {e}"}


def list_active_experiments(conn: sqlite3.Connection) -> dict:
    """
    Return all experiments in progress; flag overdue; also return completed.
    Returns:
      {active: [], overdue: [], completed: [], total: int, success: bool}
    """
    try:
        if conn is None:
            return {"success": False, "error": "conn is required"}

        ensured = _ensure_experiment_registry(conn)
        if not ensured.get("success"):
            return {"active": [], "overdue": [], "completed": [], "total": 0, "success": True}

        rows = _fetch_all_dicts(
            conn,
            "SELECT * FROM Experiment_Registry ORDER BY created_at DESC",
            (),
        )

        now = _now_utc()
        active: List[Dict[str, Any]] = []
        overdue: List[Dict[str, Any]] = []
        completed: List[Dict[str, Any]] = []

        for r in rows:
            status = _normalize_status(r.get("status") or "active")
            start_dt = _parse_start_date(r)
            duration_days = _clamp_int(r.get("duration_days"), 1, 3650, 7)
            due_dt = _compute_due_date(start_dt, duration_days)

            item = {
                "experiment_id": r.get("experiment_id"),
                "pain_id": r.get("pain_id"),
                "status": status,
                "start_date": r.get("start_date"),
                "duration_days": duration_days,
                "due_date": due_dt.date().isoformat() if due_dt else None,
                "hypothesis": r.get("hypothesis"),
            }

            if status == "active":
                if due_dt and now >= due_dt:
                    overdue.append(item)
                else:
                    active.append(item)
            else:
                completed.append(item)

        return {
            "active": active,
            "overdue": overdue,
            "completed": completed,
            "total": len(rows),
            "success": True,
        }

    except Exception as e:
        return {"success": False, "error": f"list_active_experiments failed: {e}"}


def generate_hypothesis(conn: sqlite3.Connection, kb_conn: Any, topic: str) -> dict:
    """
    Given a topic, generate 3 testable hypotheses using KB + DB context.
    Returns:
      {topic, hypotheses: [{statement, rationale, testability_score, suggested_test}], success: bool}
    """
    try:
        topic = (topic or "").strip()
        if not topic:
            return {"success": False, "error": "topic is required"}

        db_matches = _search_local_context(conn, topic, limit=7) if conn is not None else {"matches": []}
        kb_ctx = ""
        try:
            kb_ctx = build_kb_context(kb_conn, topic) or ""
        except Exception:
            kb_ctx = ""

        prompt = f"""
You are aeOS Hypothesis Generator.
Given a topic, produce 3 testable hypotheses.

Return ONLY valid JSON as:
{{
  "topic": "<topic>",
  "hypotheses": [
    {{
      "statement": "...",
      "rationale": "...",
      "testability_score": 0.0,
      "suggested_test": "..."
    }}
  ]
}}

Constraints:
- Exactly 3 hypotheses.
- Each suggested_test must be a micro-experiment runnable in 3-14 days.
- testability_score is 0.0-1.0 (higher = easier to test cleanly).

Topic: {topic}

DB_Matches (may be empty):
{json.dumps(db_matches.get("matches", []), ensure_ascii=False)}

KB_Context (may be empty):
{kb_ctx}
"""

        default_payload = {
            "topic": topic,
            "hypotheses": [
                {
                    "statement": f"If I apply a focused intervention related to '{topic}' for 7 days, the primary metric will improve by ≥20%.",
                    "rationale": "Short, time-boxed change reduces noise and forces measurable output.",
                    "testability_score": 0.7,
                    "suggested_test": "Run a 7-day test with one change only; track baseline day 0 and daily results.",
                },
                {
                    "statement": f"If I remove the top bottleneck in '{topic}', total time/cost will drop measurably within 10 days.",
                    "rationale": "Bottleneck removal often yields nonlinear gains versus broad optimization.",
                    "testability_score": 0.65,
                    "suggested_test": "Identify the #1 bottleneck; do one targeted fix; measure time-to-complete before/after.",
                },
                {
                    "statement": f"If I standardize the workflow for '{topic}' using a checklist, error rate will decrease within 14 days.",
                    "rationale": "Checklists reduce variance and prevent repeated mistakes.",
                    "testability_score": 0.6,
                    "suggested_test": "Create a one-page checklist; use it for 2 weeks; track errors/rework counts.",
                },
            ],
        }

        llm = _infer_structured(prompt, default_payload)
        if not isinstance(llm, dict):
            llm = default_payload

        hyps = llm.get("hypotheses")
        if not isinstance(hyps, list) or len(hyps) != 3:
            hyps = default_payload["hypotheses"]

        normalized: List[Dict[str, Any]] = []
        for h in hyps[:3]:
            if not isinstance(h, dict):
                continue
            normalized.append(
                {
                    "statement": str(h.get("statement") or "").strip(),
                    "rationale": str(h.get("rationale") or "").strip(),
                    "testability_score": _clamp_float(h.get("testability_score"), 0.0, 1.0, 0.5),
                    "suggested_test": str(h.get("suggested_test") or "").strip(),
                }
            )

        # If normalization broke, fallback
        if len(normalized) != 3:
            normalized = default_payload["hypotheses"]

        return {"topic": topic, "hypotheses": normalized, "success": True}

    except Exception as e:
        return {"success": False, "error": f"generate_hypothesis failed: {e}"}


def get_experiment_insights(conn: sqlite3.Connection) -> dict:
    """
    Reviews all completed experiments and identifies patterns.
    Returns:
      {total_experiments, success_rate, key_learnings, patterns, success}
    """
    try:
        if conn is None:
            return {"success": False, "error": "conn is required"}

        ensured = _ensure_experiment_registry(conn)
        if not ensured.get("success"):
            return {
                "total_experiments": 0,
                "success_rate": 0.0,
                "key_learnings": [],
                "patterns": [],
                "success": True,
            }

        rows = _fetch_all_dicts(
            conn,
            "SELECT experiment_id, pain_id, hypothesis, test_design, success_criteria, status, outcome, learning, created_at "
            "FROM Experiment_Registry WHERE status != 'active' ORDER BY created_at DESC",
            (),
        )

        total_completed = len(rows)
        successes = sum(1 for r in rows if _normalize_status(r.get("status")) == "success")
        success_rate = (successes / total_completed) if total_completed > 0 else 0.0

        # Basic key learnings (non-empty learning fields)
        learnings = [str(r.get("learning") or "").strip() for r in rows if str(r.get("learning") or "").strip()]
        key_learnings = learnings[:10]

        # Ask LLM for higher-level pattern extraction (bounded)
        sample = rows[:30]  # keep prompt bounded
        prompt = f"""
You are aeOS Experiment Insight Synthesizer.
Given completed experiments, extract patterns on what tends to work vs fail.

Return ONLY valid JSON with keys:
- patterns: [string, ...]   (5-10 concise bullets)
- key_learnings: [string, ...] (5-10, deduped)

Data:
{json.dumps(sample, ensure_ascii=False)}
"""

        default_patterns = {
            "patterns": [],
            "key_learnings": key_learnings[:10],
        }

        llm = _infer_structured(prompt, default_patterns)
        patterns: List[str] = []
        if isinstance(llm, dict) and isinstance(llm.get("patterns"), list):
            patterns = [str(p).strip() for p in llm.get("patterns") if str(p).strip()][:10]

        llm_learnings: List[str] = []
        if isinstance(llm, dict) and isinstance(llm.get("key_learnings"), list):
            llm_learnings = [str(p).strip() for p in llm.get("key_learnings") if str(p).strip()][:10]

        # Merge learnings, dedupe
        merged_learnings: List[str] = []
        for x in (llm_learnings + key_learnings):
            if x and x not in merged_learnings:
                merged_learnings.append(x)
        merged_learnings = merged_learnings[:10]

        return {
            "total_experiments": total_completed,
            "success_rate": round(success_rate, 4),
            "key_learnings": merged_learnings,
            "patterns": patterns,
            "success": True,
        }

    except Exception as e:
        return {"success": False, "error": f"get_experiment_insights failed: {e}"}


# S✅ T✅ L✅ A✅