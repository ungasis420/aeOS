"""
aeOS Phase 5 — agent_report.py

Autonomous daily briefing generator.
Pulls portfolio signals from SQLite + KB context, synthesizes a morning report,
formats for terminal display, and provides storage hooks.

Design goals:
- Graceful degradation (works even if some tables/agents are missing)
- DB-schema tolerant (supports both legacy table names and Blueprint-style tables)
- LLM optional (falls back to deterministic heuristics if infer/infer_json fails)
"""

from __future__ import annotations

import json
import sqlite3
import textwrap
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.ai.ai_context import build_portfolio_context
from src.ai.ai_infer import infer, infer_json


# ----------------------------
# Internal helpers
# ----------------------------

def _now_iso() -> str:
    """Return local timestamp ISO string (seconds precision)."""
    return datetime.now().isoformat(timespec="seconds")


def _safe_int(val: Any, default: int = 0) -> int:
    """Best-effort int cast with fallback."""
    try:
        if val is None:
            return default
        return int(val)
    except Exception:
        return default


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Best-effort float cast with fallback."""
    try:
        if val is None:
            return default
        return float(val)
    except Exception:
        return default


def _table_exists(conn: Any, table_name: str) -> bool:
    """Return True if table exists in SQLite; safe for mocked connections."""
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        return cur.fetchone() is not None
    except Exception:
        return False


def _list_tables(conn: Any) -> List[str]:
    """List tables in SQLite (best-effort)."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        rows = cur.fetchall() or []
        return [r[0] for r in rows if r and len(r) > 0]
    except Exception:
        return []


def _get_columns(conn: Any, table_name: str) -> List[str]:
    """Return column names for a table (best-effort)."""
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table_name})")
        rows = cur.fetchall() or []
        # PRAGMA table_info -> (cid, name, type, notnull, dflt_value, pk)
        return [r[1] for r in rows if r and len(r) > 1]
    except Exception:
        return []


def _fetchone_scalar(conn: Any, sql: str, params: Tuple[Any, ...] = ()) -> Any:
    """Fetch a single scalar value (best-effort)."""
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        if not row:
            return None
        return row[0]
    except Exception:
        return None


def _fetchall_rows(conn: Any, sql: str, params: Tuple[Any, ...] = ()) -> List[Tuple[Any, ...]]:
    """Fetch all rows (best-effort)."""
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall() or []
    except Exception:
        return []


def _health_emoji(score: float) -> str:
    """Health indicator emoji by score."""
    if score >= 80:
        return "🟢"
    if score >= 60:
        return "🟡"
    return "🔴"


def _trend_emoji(trend: str) -> str:
    """Trend indicator emoji."""
    t = (trend or "").strip().lower()
    if t in {"up", "improving", "better"}:
        return "📈"
    if t in {"down", "declining", "worse"}:
        return "📉"
    if t in {"flat", "steady", "stable"}:
        return "➖"
    return "❔"


def _wrap_lines(text: str, width: int) -> List[str]:
    """Word-wrap text into lines <= width."""
    if not text:
        return [""]
    return textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False) or [""]


def _box(inner_width: int, lines: List[str]) -> str:
    """Build an ASCII box with the given inner width."""
    top = "╔" + ("═" * inner_width) + "╗"
    mid = "╠" + ("═" * inner_width) + "╣"
    bot = "╚" + ("═" * inner_width) + "╝"

    out: List[str] = [top]
    for i, line in enumerate(lines):
        if line == "__SEP__":
            out.append(mid)
            continue
        clipped = (line or "")[:inner_width]
        out.append("║" + clipped.ljust(inner_width) + "║")
    out.append(bot)
    return "\n".join(out)


def _coerce_actions(payload: Any) -> List[Dict[str, Any]]:
    """Normalize actions payload to list[dict] with required keys."""
    actions: List[Dict[str, Any]] = []
    if isinstance(payload, dict):
        payload = payload.get("actions", [])
    if not isinstance(payload, list):
        return actions

    for item in payload:
        if not isinstance(item, dict):
            continue
        pr = _safe_int(item.get("priority"), default=0)
        act = (item.get("action") or "").strip()
        rat = (item.get("rationale") or "").strip()
        est = (item.get("estimated_time") or "").strip()
        if not act:
            continue
        actions.append(
            {
                "priority": pr if pr > 0 else (len(actions) + 1),
                "action": act,
                "rationale": rat,
                "estimated_time": est or "—",
            }
        )

    # sort by priority ascending, keep top 5
    actions.sort(key=lambda x: _safe_int(x.get("priority"), 999))
    return actions[:5]


def _infer_json_payload(prompt: str) -> Optional[Any]:
    """
    Call infer_json(prompt) and attempt to extract a JSON payload across common return shapes.
    Returns parsed object or None.
    """
    try:
        res = infer_json(prompt)
        # Common shapes:
        # 1) {"success": True, "data": {...}}
        # 2) {"success": True, "response": {...}} or {"response": "<json str>"}
        # 3) plain dict already the payload
        if isinstance(res, dict):
            if isinstance(res.get("data"), (dict, list)):
                return res["data"]
            if isinstance(res.get("response"), (dict, list)):
                return res["response"]
            if isinstance(res.get("response"), str):
                try:
                    return json.loads(res["response"])
                except Exception:
                    return None
            # If it's already in desired shape
            if "actions" in res:
                return res
        # If infer_json returns a string
        if isinstance(res, str):
            try:
                return json.loads(res)
            except Exception:
                return None
        return None
    except Exception:
        return None


# ----------------------------
# Section builders
# ----------------------------

def _count_open_pains(conn: Any) -> int:
    """Count open/active pains across possible schemas."""
    try:
        # Legacy: Pain_Registry(id,title,severity_score,status,...)
        if _table_exists(conn, "Pain_Registry"):
            cols = set(_get_columns(conn, "Pain_Registry"))
            if "status" in cols:
                return _safe_int(
                    _fetchone_scalar(
                        conn,
                        "SELECT COUNT(*) FROM Pain_Registry WHERE LOWER(status) IN ('open','active','in_progress')",
                    ),
                    0,
                )
            return _safe_int(_fetchone_scalar(conn, "SELECT COUNT(*) FROM Pain_Registry"), 0)

        # Blueprint: Pain_Point_Register(Status = Active/Solved/Abandoned/Monitoring)
        if _table_exists(conn, "Pain_Point_Register"):
            cols = set(_get_columns(conn, "Pain_Point_Register"))
            if "Status" in cols:
                return _safe_int(
                    _fetchone_scalar(conn, "SELECT COUNT(*) FROM Pain_Point_Register WHERE Status='Active'"),
                    0,
                )
            if "status" in cols:
                return _safe_int(
                    _fetchone_scalar(conn, "SELECT COUNT(*) FROM Pain_Point_Register WHERE LOWER(status)='active'"),
                    0,
                )
            return _safe_int(_fetchone_scalar(conn, "SELECT COUNT(*) FROM Pain_Point_Register"), 0)

        return 0
    except Exception:
        return 0


def _count_active_solutions(conn: Any) -> int:
    """Count active solutions across possible schemas."""
    try:
        # Legacy: Solution_Registry(id,pain_id,title,roi_score,status,...)
        if _table_exists(conn, "Solution_Registry"):
            cols = set(_get_columns(conn, "Solution_Registry"))
            if "status" in cols:
                return _safe_int(
                    _fetchone_scalar(
                        conn,
                        "SELECT COUNT(*) FROM Solution_Registry WHERE LOWER(status) IN ('active','in_progress','building','validated','live')",
                    ),
                    0,
                )
            return _safe_int(_fetchone_scalar(conn, "SELECT COUNT(*) FROM Solution_Registry"), 0)

        # Blueprint: Solution_Design(Status = Concept/Designing/Validated/Building/Live/Shelved)
        if _table_exists(conn, "Solution_Design"):
            cols = set(_get_columns(conn, "Solution_Design"))
            if "Status" in cols:
                return _safe_int(
                    _fetchone_scalar(
                        conn,
                        "SELECT COUNT(*) FROM Solution_Design WHERE Status NOT IN ('Shelved')",
                    ),
                    0,
                )
            if "status" in cols:
                return _safe_int(
                    _fetchone_scalar(conn, "SELECT COUNT(*) FROM Solution_Design WHERE LOWER(status) <> 'shelved'"),
                    0,
                )
            return _safe_int(_fetchone_scalar(conn, "SELECT COUNT(*) FROM Solution_Design"), 0)

        return 0
    except Exception:
        return 0


def _count_open_predictions(conn: Any) -> int:
    """Count open/unresolved predictions across possible schemas."""
    try:
        if _table_exists(conn, "Prediction_Registry"):
            cols = set(_get_columns(conn, "Prediction_Registry"))
            if "Outcome" in cols:
                return _safe_int(
                    _fetchone_scalar(
                        conn,
                        "SELECT COUNT(*) FROM Prediction_Registry WHERE Outcome IS NULL OR Outcome IN ('Unresolved')",
                    ),
                    0,
                )
            if "outcome" in cols:
                return _safe_int(
                    _fetchone_scalar(
                        conn,
                        "SELECT COUNT(*) FROM Prediction_Registry WHERE outcome IS NULL OR LOWER(outcome)='unresolved'",
                    ),
                    0,
                )
            # Legacy minimal schema may not have outcome; assume open if resolution_date is null
            if "resolution_date" in cols:
                return _safe_int(
                    _fetchone_scalar(conn, "SELECT COUNT(*) FROM Prediction_Registry WHERE resolution_date IS NULL"),
                    0,
                )
            return _safe_int(_fetchone_scalar(conn, "SELECT COUNT(*) FROM Prediction_Registry"), 0)

        return 0
    except Exception:
        return 0


def _count_running_experiments(conn: Any) -> int:
    """Count running experiments if any experiment-like table exists; else 0."""
    try:
        tables = _list_tables(conn)
        candidates = [t for t in tables if "experiment" in t.lower()]
        if not candidates:
            return 0

        # Choose the most likely table name first
        table = sorted(candidates, key=lambda x: len(x))[0]
        cols = set(_get_columns(conn, table))

        # Try common status conventions
        status_col = None
        for c in ["status", "Status", "state", "State"]:
            if c in cols:
                status_col = c
                break

        if status_col:
            sql = f"SELECT COUNT(*) FROM {table} WHERE LOWER({status_col}) IN ('running','active','in_progress')"
            return _safe_int(_fetchone_scalar(conn, sql), 0)

        # No status column: count all rows
        return _safe_int(_fetchone_scalar(conn, f"SELECT COUNT(*) FROM {table}"), 0)
    except Exception:
        return 0


def _count_blocked_tasks(conn: Any) -> int:
    """Count blocked tasks in Project_Execution_Log if present."""
    try:
        if not _table_exists(conn, "Project_Execution_Log"):
            return 0
        cols = set(_get_columns(conn, "Project_Execution_Log"))
        if "Exec_Status" in cols:
            return _safe_int(
                _fetchone_scalar(conn, "SELECT COUNT(*) FROM Project_Execution_Log WHERE Exec_Status='Blocked'"),
                0,
            )
        if "exec_status" in cols:
            return _safe_int(
                _fetchone_scalar(conn, "SELECT COUNT(*) FROM Project_Execution_Log WHERE LOWER(exec_status)='blocked'"),
                0,
            )
        return 0
    except Exception:
        return 0


def _get_top_pains(conn: Any, limit: int = 5) -> List[Dict[str, Any]]:
    """Return top pains list across schemas."""
    try:
        pains: List[Dict[str, Any]] = []

        if _table_exists(conn, "Pain_Registry"):
            cols = set(_get_columns(conn, "Pain_Registry"))
            id_col = "id" if "id" in cols else ("pain_id" if "pain_id" in cols else None)
            title_col = "title" if "title" in cols else ("Pain_Name" if "Pain_Name" in cols else None)
            sev_col = "severity_score" if "severity_score" in cols else ("severity" if "severity" in cols else None)
            status_col = "status" if "status" in cols else None
            created_col = "created_at" if "created_at" in cols else None

            order = sev_col or created_col or (id_col or "rowid")
            sql = f"SELECT {id_col or 'rowid'}, {title_col or 'title'}, {sev_col or 'NULL'}, {status_col or 'NULL'}, {created_col or 'NULL'} FROM Pain_Registry ORDER BY {order} DESC LIMIT ?"
            rows = _fetchall_rows(conn, sql, (limit,))
            for r in rows:
                pains.append(
                    {
                        "pain_id": r[0],
                        "pain_name": r[1],
                        "pain_score": _safe_float(r[2], 0.0),
                        "status": r[3],
                        "created_at": r[4],
                    }
                )
            return pains

        if _table_exists(conn, "Pain_Point_Register"):
            cols = set(_get_columns(conn, "Pain_Point_Register"))
            id_col = "Pain_ID" if "Pain_ID" in cols else ("pain_id" if "pain_id" in cols else "rowid")
            name_col = "Pain_Name" if "Pain_Name" in cols else ("pain_name" if "pain_name" in cols else "rowid")
            score_col = "Pain_Score" if "Pain_Score" in cols else ("pain_score" if "pain_score" in cols else None)
            status_col = "Status" if "Status" in cols else ("status" if "status" in cols else None)
            date_col = "Date_Identified" if "Date_Identified" in cols else ("created_at" if "created_at" in cols else None)

            where = ""
            if status_col:
                where = f"WHERE {status_col}='Active' OR LOWER({status_col})='active'"

            order = score_col or date_col or id_col
            sql = f"SELECT {id_col}, {name_col}, {score_col or 'NULL'}, {status_col or 'NULL'}, {date_col or 'NULL'} FROM Pain_Point_Register {where} ORDER BY {order} DESC LIMIT ?"
            rows = _fetchall_rows(conn, sql, (limit,))
            for r in rows:
                pains.append(
                    {
                        "pain_id": r[0],
                        "pain_name": r[1],
                        "pain_score": _safe_float(r[2], 0.0),
                        "status": r[3],
                        "created_at": r[4],
                    }
                )
            return pains

        return []
    except Exception:
        return []


def _get_prediction_accuracy(conn: Any) -> Dict[str, Any]:
    """Compute prediction accuracy stats across schemas (best-effort)."""
    try:
        if not _table_exists(conn, "Prediction_Registry"):
            return {
                "total": 0,
                "resolved": 0,
                "accuracy_rate": 0.0,
                "avg_brier": None,
                "success": True,
            }

        cols = set(_get_columns(conn, "Prediction_Registry"))
        total = _safe_int(_fetchone_scalar(conn, "SELECT COUNT(*) FROM Prediction_Registry"), 0)

        resolved = 0
        correct = 0
        avg_brier: Optional[float] = None

        if "Outcome" in cols or "outcome" in cols:
            oc = "Outcome" if "Outcome" in cols else "outcome"
            resolved = _safe_int(
                _fetchone_scalar(conn, f"SELECT COUNT(*) FROM Prediction_Registry WHERE {oc} IS NOT NULL AND LOWER({oc}) <> 'unresolved'"),
                0,
            )
            correct = _safe_int(
                _fetchone_scalar(conn, f"SELECT COUNT(*) FROM Prediction_Registry WHERE LOWER({oc}) = 'correct'"),
                0,
            )

        # Legacy: brier_score column
        if "brier_score" in cols:
            avg_brier = _fetchone_scalar(
                conn,
                "SELECT AVG(brier_score) FROM Prediction_Registry WHERE brier_score IS NOT NULL",
            )
            avg_brier = _safe_float(avg_brier, default=0.0) if avg_brier is not None else None

        accuracy_rate = (correct / resolved) if resolved > 0 else 0.0

        return {
            "total": total,
            "resolved": resolved,
            "correct": correct,
            "accuracy_rate": accuracy_rate,
            "avg_brier": avg_brier,
            "success": True,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _get_kb_highlights(conn: Any, kb_conn: Any, limit: int = 3) -> List[Dict[str, Any]]:
    """
    Fetch KB highlights.
    Primary: KB_Entry_Log (SQLite) if present.
    Secondary: attempt to use kb_conn metadata if available (best-effort).
    """
    try:
        if _table_exists(conn, "KB_Entry_Log"):
            cols = set(_get_columns(conn, "KB_Entry_Log"))
            collection_col = "collection" if "collection" in cols else ("Collection" if "Collection" in cols else None)
            summary_col = "summary" if "summary" in cols else ("Summary" if "Summary" in cols else None)
            created_col = "created_at" if "created_at" in cols else ("Created_At" if "Created_At" in cols else None)

            sql = f"""
                SELECT
                    {collection_col or "NULL"},
                    {summary_col or "NULL"},
                    {created_col or "NULL"}
                FROM KB_Entry_Log
                ORDER BY {created_col or "rowid"} DESC
                LIMIT ?
            """
            rows = _fetchall_rows(conn, sql, (limit,))
            out: List[Dict[str, Any]] = []
            for r in rows:
                out.append(
                    {
                        "collection": r[0],
                        "summary": r[1],
                        "created_at": r[2],
                    }
                )
            return out

        # Best-effort fallback if there is no SQLite log.
        # We do not assume a specific ChromaDB client shape here; keep it safe.
        highlights: List[Dict[str, Any]] = []
        try:
            if kb_conn is not None and hasattr(kb_conn, "list_collections"):
                cols = kb_conn.list_collections()  # type: ignore[attr-defined]
                for c in (cols or [])[:limit]:
                    name = getattr(c, "name", None) or str(c)
                    highlights.append({"collection": name, "summary": "Collection active", "created_at": None})
        except Exception:
            pass

        return highlights
    except Exception:
        return []


def _get_active_experiments(conn: Any, limit: int = 5) -> List[Dict[str, Any]]:
    """List active experiments if an experiment table exists (best-effort)."""
    try:
        tables = _list_tables(conn)
        candidates = [t for t in tables if "experiment" in t.lower()]
        if not candidates:
            return []

        table = sorted(candidates, key=lambda x: len(x))[0]
        cols = set(_get_columns(conn, table))

        # Choose some common columns if present
        title_col = None
        for c in ["title", "Title", "name", "Name", "experiment_name", "Experiment_Name"]:
            if c in cols:
                title_col = c
                break

        status_col = None
        for c in ["status", "Status", "state", "State"]:
            if c in cols:
                status_col = c
                break

        start_col = None
        for c in ["start_date", "Start_Date", "started_at", "Started_At", "created_at", "Created_At"]:
            if c in cols:
                start_col = c
                break

        where = ""
        if status_col:
            where = f"WHERE LOWER({status_col}) IN ('running','active','in_progress')"

        order = start_col or "rowid"
        sql = f"SELECT {title_col or 'rowid'}, {status_col or 'NULL'}, {start_col or 'NULL'} FROM {table} {where} ORDER BY {order} DESC LIMIT ?"
        rows = _fetchall_rows(conn, sql, (limit,))
        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append({"experiment": r[0], "status": r[1], "started_at": r[2]})
        return out
    except Exception:
        return []


# ----------------------------
# Public API
# ----------------------------

def generate_portfolio_health(conn: Any) -> dict:
    """
    Calculates overall portfolio health score (0–100) and key counts.

    Returns:
        {
          "health_score": float,
          "open_pains": int,
          "active_solutions": int,
          "open_predictions": int,
          "experiments_running": int,
          "trend": str,
          "success": bool
        }
    """
    try:
        open_pains = _count_open_pains(conn)
        active_solutions = _count_active_solutions(conn)
        open_predictions = _count_open_predictions(conn)
        experiments_running = _count_running_experiments(conn)
        blocked_tasks = _count_blocked_tasks(conn)

        # Simple, explainable scoring model (clamped 0–100):
        # - Open pains, open predictions, blocked tasks reduce health
        # - Active solutions + experiments add health (shows motion)
        score = 100.0
        score -= min(open_pains * 4.0, 40.0)
        score -= min(open_predictions * 2.0, 20.0)
        score -= min(blocked_tasks * 6.0, 30.0)
        score += min(active_solutions * 2.0, 20.0)
        score += min(experiments_running * 3.0, 15.0)
        score = max(0.0, min(100.0, score))

        # Trend from Daily_Report_Log if available
        trend = "Unknown"
        if _table_exists(conn, "Daily_Report_Log"):
            rows = _fetchall_rows(
                conn,
                "SELECT health_score FROM Daily_Report_Log ORDER BY generated_at DESC LIMIT 2",
            )
            if rows and len(rows) >= 2:
                latest = _safe_float(rows[0][0], score)
                prev = _safe_float(rows[1][0], latest)
                delta = latest - prev
                if delta > 1.0:
                    trend = "Up"
                elif delta < -1.0:
                    trend = "Down"
                else:
                    trend = "Flat"

        return {
            "health_score": float(round(score, 2)),
            "open_pains": int(open_pains),
            "active_solutions": int(active_solutions),
            "open_predictions": int(open_predictions),
            "experiments_running": int(experiments_running),
            "blocked_tasks": int(blocked_tasks),
            "trend": trend,
            "success": True,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def generate_action_items(conn: Any, kb_conn: Any) -> dict:
    """
    Produces top 5 recommended actions for today ranked by urgency + impact.

    Returns:
        {
          "actions": [{"priority","action","rationale","estimated_time"}, ...],
          "success": bool
        }
    """
    try:
        # Gather minimal context for LLM (and for heuristics).
        health = generate_portfolio_health(conn)
        top_pains = _get_top_pains(conn, limit=5)
        pred_stats = _get_prediction_accuracy(conn)
        kb_highlights = _get_kb_highlights(conn, kb_conn, limit=3)
        active_experiments = _get_active_experiments(conn, limit=5)

        # Build portfolio context (best-effort; tolerant to differing return types).
        portfolio_ctx = ""
        try:
            ctx_res = build_portfolio_context(conn, kb_conn)
            if isinstance(ctx_res, dict):
                portfolio_ctx = str(ctx_res.get("context") or ctx_res.get("portfolio_context") or ctx_res)
            else:
                portfolio_ctx = str(ctx_res)
        except Exception:
            portfolio_ctx = ""

        # LLM attempt first (optional).
        prompt = f"""
You are aeOS. Generate the TOP 5 actions for TODAY.
Rank by urgency + impact. Keep actions concrete and executable.
Return JSON ONLY in this exact shape:

{{
  "actions": [
    {{"priority": 1, "action": "...", "rationale": "...", "estimated_time": "30m"}},
    ...
  ]
}}

DATA:
- Portfolio Health: {health}
- Top Pains: {top_pains}
- Active Experiments: {active_experiments}
- Prediction Stats: {pred_stats}
- KB Highlights: {kb_highlights}

Portfolio Context (may be empty):
{portfolio_ctx[:4000]}
""".strip()

        payload = _infer_json_payload(prompt)
        actions = _coerce_actions(payload)

        # Deterministic fallback if LLM unavailable or empty result.
        if not actions:
            blocked = _safe_int(health.get("blocked_tasks"), 0) if isinstance(health, dict) else 0
            open_pains = _safe_int(health.get("open_pains"), 0) if isinstance(health, dict) else 0
            open_preds = _safe_int(health.get("open_predictions"), 0) if isinstance(health, dict) else 0

            actions = []

            if blocked >= 3:
                actions.append(
                    {
                        "priority": 1,
                        "action": "Unblock execution: review all Blocked tasks and escalate owners/dates",
                        "rationale": "3+ blocked tasks triggers a portfolio stall risk; clearing blockers restores momentum.",
                        "estimated_time": "45m",
                    }
                )

            if open_pains > 0:
                top = (top_pains[0].get("pain_name") if top_pains else None) or "top pain"
                actions.append(
                    {
                        "priority": 2,
                        "action": f"Pick '{top}' and define a smallest-possible fix experiment for today",
                        "rationale": "Highest pain reduction per unit time; creates a concrete next step and learning loop.",
                        "estimated_time": "30m",
                    }
                )

            if open_preds > 0:
                actions.append(
                    {
                        "priority": 3,
                        "action": "Review open predictions due soon and write 1 evidence-for / evidence-against update",
                        "rationale": "Improves calibration and decision quality; prevents stale, untracked beliefs.",
                        "estimated_time": "20m",
                    }
                )

            if not kb_highlights:
                actions.append(
                    {
                        "priority": 4,
                        "action": "Ingest 1 new KB note from yesterday and tag it to a pain/solution",
                        "rationale": "Keeps knowledge compounding and connected to execution targets.",
                        "estimated_time": "15m",
                    }
                )

            actions.append(
                {
                    "priority": 5,
                    "action": "Do a 10-minute daily ops update: update next actions + time invested on active tasks",
                    "rationale": "Maintains execution truth and keeps the system’s dashboards meaningful.",
                    "estimated_time": "10m",
                }
            )

            # Keep top 5, sorted
            actions = _coerce_actions({"actions": actions})

        return {"actions": actions, "success": True}
    except Exception as e:
        return {"success": False, "error": str(e), "actions": []}


def generate_daily_report(conn: Any, kb_conn: Any) -> dict:
    """
    Assembles complete daily briefing.

    Sections:
      - Portfolio Health
      - Top Pains
      - Active Experiments
      - Prediction Accuracy
      - KB Highlights
      - Recommended Actions

    Returns:
        {
          "report": str,
          "sections": dict,
          "generated_at": str,
          "success": bool
        }
    """
    try:
        generated_at = _now_iso()

        health = generate_portfolio_health(conn)
        top_pains = _get_top_pains(conn, limit=5)
        active_experiments = _get_active_experiments(conn, limit=5)
        pred_stats = _get_prediction_accuracy(conn)
        kb_highlights = _get_kb_highlights(conn, kb_conn, limit=3)
        actions_res = generate_action_items(conn, kb_conn)

        sections = {
            "portfolio_health": health if isinstance(health, dict) else {"success": False},
            "top_pains": top_pains,
            "active_experiments": active_experiments,
            "prediction_accuracy": pred_stats,
            "kb_highlights": kb_highlights,
            "recommended_actions": actions_res.get("actions", []) if isinstance(actions_res, dict) else [],
        }

        report_dict = {
            "generated_at": generated_at,
            "sections": sections,
            "success": True,
        }

        report_text = format_report_terminal(report_dict)

        return {
            "report": report_text,
            "sections": sections,
            "generated_at": generated_at,
            "success": True,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "report": "", "sections": {}, "generated_at": _now_iso()}


def format_report_terminal(report_dict: dict) -> str:
    """
    Formats report dict as clean terminal output.
    Uses ASCII borders + emoji indicators + clear sections.

    Note: This function intentionally returns a string (not a dict) to be print-ready.
    """
    try:
        generated_at = report_dict.get("generated_at") or _now_iso()
        try:
            dt = datetime.fromisoformat(str(generated_at))
        except Exception:
            dt = datetime.now()

        date_line = dt.strftime("%A %b %d %Y")

        sections = report_dict.get("sections", {}) or {}
        health = sections.get("portfolio_health", {}) or {}
        actions = sections.get("recommended_actions", []) or []
        top_pains = sections.get("top_pains", []) or []
        active_experiments = sections.get("active_experiments", []) or []
        pred = sections.get("prediction_accuracy", {}) or {}
        kb = sections.get("kb_highlights", []) or {}

        health_score = _safe_float(health.get("health_score"), 0.0)
        open_pains = _safe_int(health.get("open_pains"), 0)
        active_solutions = _safe_int(health.get("active_solutions"), 0)
        open_predictions = _safe_int(health.get("open_predictions"), 0)
        experiments_running = _safe_int(health.get("experiments_running"), 0)
        trend = str(health.get("trend") or "Unknown")

        indicator = _health_emoji(health_score)
        trend_icon = _trend_emoji(trend)

        # Prepare top box
        title = "aeOS DAILY BRIEFING"
        top_action = actions[0] if actions else {}
        top_action_text = str(top_action.get("action") or "No action items generated")
        top_action_rat = str(top_action.get("rationale") or "")

        # Determine inner width (bounded for terminal sanity)
        stat1 = f"Portfolio Health: {int(round(health_score))}/100 {indicator} {trend_icon}"
        stat2 = f"Open Pains: {open_pains}  Active Sol: {active_solutions}"
        stat3 = f"Open Pred: {open_predictions}  Active Exp: {experiments_running}"

        inner_width = max(38, len(title) + 6, len(date_line) + 6, len(stat1) + 4, len(stat2) + 4, len(stat3) + 4)
        inner_width = min(inner_width, 76)

        box_lines: List[str] = []
        box_lines.append(title.center(inner_width))
        box_lines.append(date_line.center(inner_width))
        box_lines.append("__SEP__")
        box_lines.append(stat1.ljust(inner_width))
        box_lines.append(stat2.ljust(inner_width))
        box_lines.append(stat3.ljust(inner_width))
        box_lines.append("__SEP__")
        box_lines.append("TOP PRIORITY TODAY".ljust(inner_width))
        for ln in _wrap_lines(f"1. {top_action_text}", width=inner_width):
            box_lines.append(ln.ljust(inner_width))
        if top_action_rat:
            for ln in _wrap_lines(f"   — {top_action_rat}", width=inner_width):
                box_lines.append(ln.ljust(inner_width))

        header_box = _box(inner_width, box_lines)

        # Lower sections (clear headings)
        out: List[str] = [header_box, ""]

        sep = "═" * min(inner_width + 2, 78)

        # Recommended actions
        out.append("✅ RECOMMENDED ACTIONS")
        out.append(sep)
        if actions:
            for a in actions:
                pr = _safe_int(a.get("priority"), 0)
                act = str(a.get("action") or "")
                est = str(a.get("estimated_time") or "—")
                rat = str(a.get("rationale") or "")
                out.append(f"{pr}. {act} ⏱️ {est}")
                if rat:
                    out.append(f"   ↳ {rat}")
        else:
            out.append("— None generated —")
        out.append("")

        # Top pains
        out.append("📌 TOP PAINS")
        out.append(sep)
        if top_pains:
            for p in top_pains:
                name = str(p.get("pain_name") or p.get("title") or p.get("pain_id") or "—")
                score = p.get("pain_score")
                score_txt = f"{_safe_float(score, 0.0):.0f}" if score is not None else "—"
                out.append(f"- {name} (score: {score_txt})")
        else:
            out.append("— No pain records found —")
        out.append("")

        # Active experiments
        out.append("🧪 ACTIVE EXPERIMENTS")
        out.append(sep)
        if active_experiments:
            for ex in active_experiments:
                out.append(f"- {ex.get('experiment')} ({ex.get('status')})")
        else:
            out.append("— None running —")
        out.append("")

        # Prediction accuracy
        out.append("🎯 PREDICTION ACCURACY")
        out.append(sep)
        if isinstance(pred, dict) and pred.get("success", True):
            total = _safe_int(pred.get("total"), 0)
            resolved = _safe_int(pred.get("resolved"), 0)
            correct = _safe_int(pred.get("correct"), 0)
            acc = _safe_float(pred.get("accuracy_rate"), 0.0) * 100.0
            avg_brier = pred.get("avg_brier")
            brier_txt = f"{_safe_float(avg_brier, 0.0):.3f}" if avg_brier is not None else "—"
            out.append(f"Resolved: {resolved}/{total} | Correct: {correct} | Accuracy: {acc:.1f}% | Avg Brier: {brier_txt}")
        else:
            out.append("— Prediction stats unavailable —")
        out.append("")

        # KB highlights
        out.append("🧠 KB HIGHLIGHTS")
        out.append(sep)
        if kb:
            if isinstance(kb, list):
                for h in kb:
                    col = h.get("collection") or "—"
                    summ = (h.get("summary") or "").strip()
                    summ = summ[:160] + ("…" if len(summ) > 160 else "")
                    out.append(f"- [{col}] {summ}" if summ else f"- [{col}]")
            else:
                out.append(str(kb))
        else:
            out.append("— No KB highlights found —")

        return "\n".join(out).strip() + "\n"
    except Exception:
        # Absolute fallback: never crash terminal printing
        return "aeOS DAILY BRIEFING\n(Formatting error — report unavailable)\n"


def save_report(conn: Any, report_dict: dict) -> dict:
    """
    Saves to Daily_Report_Log table.

    Creates table if not exists:
      CREATE TABLE IF NOT EXISTS Daily_Report_Log (
          report_id TEXT PRIMARY KEY,
          report TEXT,
          health_score REAL,
          generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )

    Returns:
        { "saved": bool, "report_id": str, "success": bool }
    """
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS Daily_Report_Log (
                report_id TEXT PRIMARY KEY,
                report TEXT,
                health_score REAL,
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        report_id = f"RPT-{uuid.uuid4()}"
        generated_at = report_dict.get("generated_at") or _now_iso()

        sections = report_dict.get("sections", {}) or {}
        health = sections.get("portfolio_health", {}) or {}
        health_score = _safe_float(health.get("health_score"), 0.0)

        report_text = report_dict.get("report")
        if not report_text:
            # If caller passed the dict that generate_daily_report returns
            if "sections" in report_dict:
                report_text = format_report_terminal(report_dict)
            else:
                report_text = ""

        cur.execute(
            """
            INSERT INTO Daily_Report_Log (report_id, report, health_score, generated_at)
            VALUES (?, ?, ?, ?)
            """,
            (report_id, report_text, health_score, generated_at),
        )
        conn.commit()

        return {"saved": True, "report_id": report_id, "success": True}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"saved": False, "report_id": "", "success": False, "error": str(e)}


# S✅ T✅ L✅ A✅