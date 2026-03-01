"""
aeOS Agent Monitor — Background portfolio health monitor.

Purpose:
- Scan for threshold breaches, approaching deadlines, and “stuck” work.
- Produce actionable alerts designed to run on a schedule (daemon/scheduler).

Design notes:
- Works with either “Phase 4 simplified tables” (Pain_Registry/Solution_Registry/etc.)
  or Blueprint-aligned tables (Pain_Point_Register/Solution_Design/Prediction_Registry/etc.).
- Graceful degradation: if a table/column is missing, that check returns an empty result
  instead of crashing the monitor loop.
"""

from __future__ import annotations

from src.ai.ai_infer import infer, infer_json

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


# ----------------------------
# Internal helpers (safe + small)
# ----------------------------

def _now() -> datetime:
    """Return current local datetime (naive)."""
    return datetime.now()


def _safe_str(x: Any) -> str:
    """Coerce value to a safe string."""
    try:
        return "" if x is None else str(x)
    except Exception:
        return ""


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse a SQLite-stored datetime/date string to datetime, best-effort."""
    try:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value

        s = _safe_str(value).strip()
        if not s:
            return None

        # Common ISO variants
        s_clean = s.replace("Z", "").replace("z", "").strip()
        try:
            return datetime.fromisoformat(s_clean)
        except Exception:
            pass

        # Common fallback formats
        for fmt in (
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%m/%d/%Y",
            "%m/%d/%Y %H:%M:%S",
        ):
            try:
                return datetime.strptime(s_clean, fmt)
            except Exception:
                continue

        return None
    except Exception:
        return None


def _days_between(a: datetime, b: datetime) -> int:
    """Return integer day delta (b - a) in days."""
    try:
        return (b - a).days
    except Exception:
        return 0


def _table_name_case_insensitive(conn: sqlite3.Connection, name: str) -> Optional[str]:
    """Return the real table name if exists, matched case-insensitively."""
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND lower(name)=lower(?) LIMIT 1",
            (name,),
        )
        row = cur.fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _resolve_table(conn: sqlite3.Connection, candidates: List[str]) -> Optional[str]:
    """Pick the first existing table from candidates (case-insensitive)."""
    try:
        for t in candidates:
            real = _table_name_case_insensitive(conn, t)
            if real:
                return real
        return None
    except Exception:
        return None


def _table_columns(conn: sqlite3.Connection, table: str) -> Dict[str, str]:
    """
    Return mapping of lowercase column name -> real column name for a table.
    Example: {'created_at': 'created_at', 'pain_id': 'Pain_ID', ...}
    """
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        rows = cur.fetchall() or []
        cols = {}
        for r in rows:
            # (cid, name, type, notnull, dflt_value, pk)
            name = r[1]
            if name:
                cols[_safe_str(name).lower()] = _safe_str(name)
        return cols
    except Exception:
        return {}


def _pick_col(cols_lc_map: Dict[str, str], candidates: List[str]) -> Optional[str]:
    """Pick the first existing column from candidates (case-insensitive)."""
    try:
        for c in candidates:
            key = _safe_str(c).lower()
            if key in cols_lc_map:
                return cols_lc_map[key]
        return None
    except Exception:
        return None


def _coerce_float(x: Any) -> Optional[float]:
    """Best-effort float coercion."""
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        s = _safe_str(x).strip()
        if not s:
            return None
        return float(s)
    except Exception:
        return None


def _is_inactive_status(status: Any) -> bool:
    """Heuristic: treat these statuses as inactive/closed."""
    s = _safe_str(status).strip().lower()
    if not s:
        return False
    inactive_markers = (
        "done",
        "complete",
        "completed",
        "archived",
        "abandoned",
        "shelved",
        "cancelled",
        "canceled",
        "inactive",
        "closed",
        "resolved",
        "killed",
    )
    return any(m in s for m in inactive_markers)


def _severity_bucket(sev_value: Optional[float]) -> str:
    """Map numeric severity to alert severity string."""
    try:
        if sev_value is None:
            return "medium"
        if sev_value >= 9:
            return "critical"
        if sev_value >= 7:
            return "high"
        if sev_value >= 4:
            return "medium"
        return "low"
    except Exception:
        return "medium"


def _severity_rank(sev: str) -> int:
    """Sort key: higher is more severe."""
    s = _safe_str(sev).lower()
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(s, 0)


def _extract_llm_text(result: Any) -> Optional[str]:
    """Extract response text from infer() output (multiple shapes supported)."""
    try:
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            if isinstance(result.get("response"), str):
                return result["response"]
            if isinstance(result.get("text"), str):
                return result["text"]
            # fallback
            for k in ("content", "output"):
                if isinstance(result.get(k), str):
                    return result[k]
        return None
    except Exception:
        return None


def _extract_llm_json(result: Any) -> Optional[dict]:
    """Extract JSON dict from infer_json() output (multiple shapes supported)."""
    try:
        if isinstance(result, dict):
            if isinstance(result.get("data"), dict):
                return result["data"]
            if isinstance(result.get("response"), dict):
                return result["response"]
            if isinstance(result.get("json"), dict):
                return result["json"]
            if isinstance(result.get("response"), str):
                try:
                    return json.loads(result["response"])
                except Exception:
                    return None
        if isinstance(result, str):
            try:
                return json.loads(result)
            except Exception:
                return None
        return None
    except Exception:
        return None


def _ensure_alert_log_table(conn: sqlite3.Connection) -> None:
    """Create Alert_Log table if it does not exist."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS Alert_Log (
            alert_id TEXT PRIMARY KEY,
            alert_type TEXT,
            entity_id TEXT,
            message TEXT,
            severity TEXT,
            resolved INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


# ----------------------------
# Public API (required functions)
# ----------------------------

def check_pain_thresholds(conn: sqlite3.Connection, severity_threshold: float = 7.0) -> dict:
    """
    Finds all pain points above severity threshold with no active solution.

    Returns:
        {flagged_pains: [{pain_id, title, severity, days_open, status}], count: int, success: bool}
    """
    try:
        pain_table = _resolve_table(conn, ["Pain_Registry", "Pain_Point_Register"])
        sol_table = _resolve_table(conn, ["Solution_Registry", "Solution_Design"])

        if not pain_table:
            return {"flagged_pains": [], "count": 0, "success": True}

        pcols = _table_columns(conn, pain_table)
        pid = _pick_col(pcols, ["pain_id", "Pain_ID", "id", "PainID"])
        ptitle = _pick_col(pcols, ["title", "Pain_Name", "pain_name", "name"])
        pseverity = _pick_col(pcols, ["severity_score", "Severity", "severity"])
        pstatus = _pick_col(pcols, ["status", "Status"])
        pcreated = _pick_col(pcols, ["created_at", "Created_At", "Date_Identified", "date_identified"])

        if not pid or not pseverity:
            return {"flagged_pains": [], "count": 0, "success": True}

        select_title = f"{ptitle} AS title" if ptitle else "NULL AS title"
        select_status = f"{pstatus} AS status" if pstatus else "NULL AS status"
        select_created = f"{pcreated} AS created_at" if pcreated else "NULL AS created_at"

        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT
                {pid} AS pain_id,
                {select_title},
                {pseverity} AS severity,
                {select_created},
                {select_status}
            FROM {pain_table}
            """
        )
        pains = cur.fetchall() or []

        # Candidate pains above threshold
        candidate = []
        for row in pains:
            pain_id, title, sev_raw, created_raw, status_raw = row
            sev = _coerce_float(sev_raw)
            if sev is None:
                continue
            if sev >= float(severity_threshold):
                candidate.append((pain_id, title, sev, created_raw, status_raw))

        if not candidate:
            return {"flagged_pains": [], "count": 0, "success": True}

        # If no solution table, treat as "no active solution" for all candidates
        solutions_by_pain: Dict[str, List[Any]] = {}
        if sol_table:
            scols = _table_columns(conn, sol_table)
            sid_fk = _pick_col(scols, ["pain_id", "Pain_ID", "painId"])
            sstatus = _pick_col(scols, ["status", "Status"])
            if sid_fk:
                pain_ids = [c[0] for c in candidate if c[0] is not None]
                if pain_ids:
                    placeholders = ",".join(["?"] * len(pain_ids))
                    if sstatus:
                        cur.execute(
                            f"SELECT {sid_fk} AS pain_id, {sstatus} AS status FROM {sol_table} WHERE {sid_fk} IN ({placeholders})",
                            tuple(pain_ids),
                        )
                    else:
                        cur.execute(
                            f"SELECT {sid_fk} AS pain_id, NULL AS status FROM {sol_table} WHERE {sid_fk} IN ({placeholders})",
                            tuple(pain_ids),
                        )
                    for pr, st in (cur.fetchall() or []):
                        k = _safe_str(pr)
                        solutions_by_pain.setdefault(k, []).append(st)

        flagged = []
        now = _now()
        for pain_id, title, sev, created_raw, status_raw in candidate:
            pid_s = _safe_str(pain_id)
            sts_list = solutions_by_pain.get(pid_s, [])

            # Active if any non-inactive status (or unknown status treated as active)
            has_active_solution = False
            if sts_list:
                for st in sts_list:
                    if st is None:
                        has_active_solution = True
                        break
                    if not _is_inactive_status(st):
                        has_active_solution = True
                        break

            if not has_active_solution:
                created_dt = _parse_dt(created_raw)
                days_open = _days_between(created_dt, now) if created_dt else 0
                flagged.append(
                    {
                        "pain_id": pid_s,
                        "title": _safe_str(title) if title is not None else "",
                        "severity": float(sev),
                        "days_open": int(days_open),
                        "status": _safe_str(status_raw),
                    }
                )

        return {"flagged_pains": flagged, "count": len(flagged), "success": True}
    except Exception as e:
        return {"flagged_pains": [], "count": 0, "success": False, "error": str(e)}


def check_prediction_deadlines(conn: sqlite3.Connection, days_ahead: int = 7) -> dict:
    """
    Finds predictions resolving within days_ahead.

    Returns:
        {approaching: [{prediction_id, statement, resolution_date, days_remaining, probability}], count: int, success: bool}
    """
    try:
        pred_table = _resolve_table(conn, ["Prediction_Registry"])
        if not pred_table:
            return {"approaching": [], "count": 0, "success": True}

        cols = _table_columns(conn, pred_table)
        pid = _pick_col(cols, ["prediction_id", "Prediction_ID", "Pred_ID", "id"])
        stmt = _pick_col(cols, ["statement", "Prediction_Text", "prediction_text", "text"])
        rdate = _pick_col(cols, ["resolution_date", "Resolution_Date", "resolutionDate"])
        prob = _pick_col(cols, ["probability", "Confidence_Pct", "confidence", "probability_pct"])
        outcome = _pick_col(cols, ["outcome", "Outcome"])

        if not pid or not rdate:
            return {"approaching": [], "count": 0, "success": True}

        select_stmt = f"{stmt} AS statement" if stmt else "NULL AS statement"
        select_prob = f"{prob} AS probability" if prob else "NULL AS probability"
        select_outcome = f"{outcome} AS outcome" if outcome else "NULL AS outcome"

        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT
                {pid} AS prediction_id,
                {select_stmt},
                {rdate} AS resolution_date,
                {select_prob},
                {select_outcome}
            FROM {pred_table}
            """
        )

        now = _now()
        out = []
        for pred_id, statement, res_raw, prob_raw, outcome_raw in (cur.fetchall() or []):
            res_dt = _parse_dt(res_raw)
            if not res_dt:
                continue

            # If already resolved, skip (when outcome column exists)
            if outcome is not None:
                if _safe_str(outcome_raw).strip():
                    continue

            days_remaining = _days_between(now, res_dt)
            if 0 <= days_remaining <= int(days_ahead):
                out.append(
                    {
                        "prediction_id": _safe_str(pred_id),
                        "statement": _safe_str(statement),
                        "resolution_date": _safe_str(res_raw),
                        "days_remaining": int(days_remaining),
                        "probability": prob_raw,
                    }
                )

        return {"approaching": out, "count": len(out), "success": True}
    except Exception as e:
        return {"approaching": [], "count": 0, "success": False, "error": str(e)}


def check_stalled_solutions(conn: sqlite3.Connection, stall_days: int = 14) -> dict:
    """
    Finds solutions with no status update in stall_days.

    Returns:
        {stalled: [{solution_id, title, pain_id, last_updated, days_stalled}], count: int, success: bool}
    """
    try:
        sol_table = _resolve_table(conn, ["Solution_Registry", "Solution_Design"])
        if not sol_table:
            return {"stalled": [], "count": 0, "success": True}

        cols = _table_columns(conn, sol_table)
        sid = _pick_col(cols, ["solution_id", "Solution_ID", "Sol_ID", "id"])
        title = _pick_col(cols, ["title", "Solution_Name", "solution_name", "name"])
        pain_fk = _pick_col(cols, ["pain_id", "Pain_ID", "painId"])
        updated = _pick_col(cols, ["updated_at", "last_updated", "Last_Updated", "updatedAt"])
        status = _pick_col(cols, ["status", "Status"])

        if not sid or not updated:
            return {"stalled": [], "count": 0, "success": True}

        select_title = f"{title} AS title" if title else "NULL AS title"
        select_pain = f"{pain_fk} AS pain_id" if pain_fk else "NULL AS pain_id"
        select_status = f"{status} AS status" if status else "NULL AS status"

        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT
                {sid} AS solution_id,
                {select_title},
                {select_pain},
                {updated} AS last_updated,
                {select_status}
            FROM {sol_table}
            """
        )

        now = _now()
        stalled = []
        for sol_id, sol_title, pain_id, last_up_raw, st in (cur.fetchall() or []):
            # Skip inactive/completed solutions if status exists
            if status is not None and _is_inactive_status(st):
                continue

            last_dt = _parse_dt(last_up_raw)
            if not last_dt:
                continue

            days_stalled = _days_between(last_dt, now)
            if days_stalled >= int(stall_days):
                stalled.append(
                    {
                        "solution_id": _safe_str(sol_id),
                        "title": _safe_str(sol_title),
                        "pain_id": _safe_str(pain_id),
                        "last_updated": _safe_str(last_up_raw),
                        "days_stalled": int(days_stalled),
                    }
                )

        return {"stalled": stalled, "count": len(stalled), "success": True}
    except Exception as e:
        return {"stalled": [], "count": 0, "success": False, "error": str(e)}


def _check_experiment_overdue(conn: sqlite3.Connection) -> List[dict]:
    """
    Internal: best-effort experiment overdue detection.
    Looks for common experiment tables and common 'due' fields.
    """
    try:
        exp_table = _resolve_table(
            conn,
            [
                "Experiment_Log",
                "Micro_Experiment_Log",
                "Experiment_Registry",
                "Micro_Experiment_Registry",
                "Experiment_Register",
                "Micro_Experiment_Register",
            ],
        )
        if not exp_table:
            return []

        cols = _table_columns(conn, exp_table)
        eid = _pick_col(cols, ["experiment_id", "Experiment_ID", "id"])
        title = _pick_col(cols, ["title", "Experiment_Name", "name"])
        due = _pick_col(cols, ["due_date", "Due_Date", "target_date", "Target_Date", "end_date", "End_Date"])
        status = _pick_col(cols, ["status", "Status"])
        updated = _pick_col(cols, ["updated_at", "last_updated", "Last_Updated", "updatedAt"])

        if not eid or not due:
            return []

        select_title = f"{title} AS title" if title else "NULL AS title"
        select_status = f"{status} AS status" if status else "NULL AS status"
        select_updated = f"{updated} AS last_updated" if updated else "NULL AS last_updated"

        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT
                {eid} AS experiment_id,
                {select_title},
                {due} AS due_date,
                {select_status},
                {select_updated}
            FROM {exp_table}
            """
        )

        now = _now()
        overdue = []
        for ex_id, ex_title, due_raw, st, last_up_raw in (cur.fetchall() or []):
            if status is not None and _is_inactive_status(st):
                continue

            due_dt = _parse_dt(due_raw)
            if not due_dt:
                continue

            days_overdue = _days_between(due_dt, now)
            if days_overdue > 0:
                overdue.append(
                    {
                        "experiment_id": _safe_str(ex_id),
                        "title": _safe_str(ex_title),
                        "due_date": _safe_str(due_raw),
                        "days_overdue": int(days_overdue),
                        "status": _safe_str(st),
                        "last_updated": _safe_str(last_up_raw),
                    }
                )

        return overdue
    except Exception:
        return []


def _build_prediction_alerts(conn: sqlite3.Connection, days_ahead: int = 7) -> List[dict]:
    """Internal: build alerts for overdue + due-soon predictions (type kept as 'overdue_prediction')."""
    try:
        pred_table = _resolve_table(conn, ["Prediction_Registry"])
        if not pred_table:
            return []

        cols = _table_columns(conn, pred_table)
        pid = _pick_col(cols, ["prediction_id", "Prediction_ID", "Pred_ID", "id"])
        stmt = _pick_col(cols, ["statement", "Prediction_Text", "prediction_text", "text"])
        rdate = _pick_col(cols, ["resolution_date", "Resolution_Date", "resolutionDate"])
        prob = _pick_col(cols, ["probability", "Confidence_Pct", "confidence", "probability_pct"])
        outcome = _pick_col(cols, ["outcome", "Outcome"])

        if not pid or not rdate:
            return []

        select_stmt = f"{stmt} AS statement" if stmt else "NULL AS statement"
        select_prob = f"{prob} AS probability" if prob else "NULL AS probability"
        select_outcome = f"{outcome} AS outcome" if outcome else "NULL AS outcome"

        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT
                {pid} AS prediction_id,
                {select_stmt},
                {rdate} AS resolution_date,
                {select_prob},
                {select_outcome}
            FROM {pred_table}
            """
        )

        now = _now()
        alerts: List[dict] = []
        for pred_id, statement, res_raw, prob_raw, outcome_raw in (cur.fetchall() or []):
            res_dt = _parse_dt(res_raw)
            if not res_dt:
                continue

            # Skip resolved predictions if outcome exists
            if outcome is not None and _safe_str(outcome_raw).strip():
                continue

            days_to = _days_between(now, res_dt)  # positive = due in future
            if days_to < 0:
                days_over = abs(days_to)
                sev = "critical" if days_over >= 30 else ("high" if days_over >= 7 else "medium")
                alerts.append(
                    {
                        "type": "overdue_prediction",
                        "entity_id": _safe_str(pred_id),
                        "message": f"Prediction overdue by {days_over} days: {_safe_str(statement)} (was due {_safe_str(res_raw)}).",
                        "severity": sev,
                        "recommended_action": "Set Outcome (resolve) or move Resolution_Date with a clear reason; capture what evidence would falsify/confirm.",
                    }
                )
            elif 0 <= days_to <= int(days_ahead):
                sev = "high" if days_to <= 1 else "medium"
                alerts.append(
                    {
                        "type": "overdue_prediction",
                        "entity_id": _safe_str(pred_id),
                        "message": f"Prediction due in {days_to} days: {_safe_str(statement)} (due {_safe_str(res_raw)}).",
                        "severity": sev,
                        "recommended_action": "Prepare the resolution check now (gather evidence) and set Outcome on/near the due date.",
                    }
                )

        return alerts
    except Exception:
        return []


def scan_for_alerts(conn: sqlite3.Connection) -> dict:
    """
    Scans entire portfolio for alert conditions.

    Alert types:
    - high_severity_pain
    - overdue_prediction
    - stalled_solution
    - experiment_overdue

    Returns:
        {alerts: [{type, entity_id, message, severity, recommended_action}], total: int, critical: int, success: bool}
    """
    try:
        alerts: List[dict] = []

        # 1) High severity pains without active solutions
        pains_res = check_pain_thresholds(conn)
        for p in pains_res.get("flagged_pains", []) or []:
            sev_num = _coerce_float(p.get("severity"))
            alerts.append(
                {
                    "type": "high_severity_pain",
                    "entity_id": _safe_str(p.get("pain_id")),
                    "message": (
                        f"High-severity pain has no active solution: {_safe_str(p.get('title'))} "
                        f"(severity {sev_num}, open {int(p.get('days_open', 0))} days)."
                    ),
                    "severity": _severity_bucket(sev_num),
                    "recommended_action": "Create/activate a solution linked to this pain (or explicitly mark the pain as resolved/closed).",
                }
            )

        # 2) Predictions overdue or due soon
        alerts.extend(_build_prediction_alerts(conn, days_ahead=7))

        # 3) Stalled solutions
        stalled_res = check_stalled_solutions(conn)
        for s in stalled_res.get("stalled", []) or []:
            days_stalled = int(s.get("days_stalled", 0) or 0)
            sev = "high" if days_stalled >= 30 else "medium"
            alerts.append(
                {
                    "type": "stalled_solution",
                    "entity_id": _safe_str(s.get("solution_id")),
                    "message": (
                        f"Solution appears stalled ({days_stalled} days since last update): {_safe_str(s.get('title'))} "
                        f"(pain_id {_safe_str(s.get('pain_id'))})."
                    ),
                    "severity": sev,
                    "recommended_action": "Update status with next step (or mark as blocked with a blocker) and set a concrete next review date.",
                }
            )

        # 4) Experiment overdue (best-effort)
        for ex in _check_experiment_overdue(conn):
            days_over = int(ex.get("days_overdue", 0) or 0)
            sev = "high" if days_over >= 14 else "medium"
            alerts.append(
                {
                    "type": "experiment_overdue",
                    "entity_id": _safe_str(ex.get("experiment_id")),
                    "message": (
                        f"Experiment overdue by {days_over} days: {_safe_str(ex.get('title'))} "
                        f"(due {_safe_str(ex.get('due_date'))})."
                    ),
                    "severity": sev,
                    "recommended_action": "Close the loop: record result/learning, or extend due date with a clear hypothesis and next checkpoint.",
                }
            )

        total = len(alerts)
        critical = sum(1 for a in alerts if _safe_str(a.get("severity")).lower() == "critical")
        return {"alerts": alerts, "total": total, "critical": critical, "success": True}
    except Exception as e:
        return {"alerts": [], "total": 0, "critical": 0, "success": False, "error": str(e)}


def generate_alert_summary(conn: sqlite3.Connection) -> dict:
    """
    Calls scan_for_alerts and formats into an LLM-enhanced summary.
    Uses LLM to prioritize and add context to alerts.

    Returns:
        {summary: str, critical_count: int, alerts: [], recommended_first_action: str, success: bool}
    """
    try:
        scan = scan_for_alerts(conn)
        alerts = scan.get("alerts", []) or []
        critical_count = int(scan.get("critical", 0) or 0)

        if not alerts:
            return {
                "summary": "✅ No alerts detected. Portfolio looks stable right now.",
                "critical_count": 0,
                "alerts": [],
                "recommended_first_action": "No action needed. Next scan on schedule.",
                "success": True,
            }

        # Baseline deterministic ordering
        ordered = sorted(alerts, key=lambda a: _severity_rank(_safe_str(a.get("severity"))), reverse=True)
        top = ordered[:5]

        baseline = []
        baseline.append(f"Found {len(alerts)} alert(s), {critical_count} critical.")
        baseline.append("Top priorities:")
        for a in top:
            baseline.append(f"- [{_safe_str(a.get('severity')).upper()}] {_safe_str(a.get('message'))}")

        baseline_summary = "\n".join(baseline)
        baseline_first_action = _safe_str(top[0].get("recommended_action")) if top else "Review alerts."

        # LLM enhancement (best-effort)
        llm_payload = {
            "alerts": ordered,
            "counts": {"total": len(alerts), "critical": critical_count},
        }

        prompt = (
            "You are aeOS. Create a concise alert briefing for the Sovereign.\n"
            "Return STRICT JSON with keys:\n"
            '  "summary" (string, <= 180 words, prioritized, actionable)\n'
            '  "recommended_first_action" (string, one concrete next step)\n\n'
            f"ALERTS_JSON:\n{json.dumps(llm_payload, ensure_ascii=False)}"
        )

        summary = baseline_summary
        first_action = baseline_first_action

        try:
            llm_res = infer_json(prompt)
            data = _extract_llm_json(llm_res)
            if isinstance(data, dict):
                if isinstance(data.get("summary"), str) and data["summary"].strip():
                    summary = data["summary"].strip()
                if isinstance(data.get("recommended_first_action"), str) and data["recommended_first_action"].strip():
                    first_action = data["recommended_first_action"].strip()
            else:
                # fallback to infer() if infer_json isn't usable
                llm_res2 = infer(prompt)
                text = _extract_llm_text(llm_res2)
                if isinstance(text, str) and text.strip():
                    summary = text.strip()
        except Exception:
            # Keep baseline
            pass

        return {
            "summary": summary,
            "critical_count": critical_count,
            "alerts": ordered,
            "recommended_first_action": first_action,
            "success": True,
        }
    except Exception as e:
        return {
            "summary": "",
            "critical_count": 0,
            "alerts": [],
            "recommended_first_action": "",
            "success": False,
            "error": str(e),
        }


def log_alert(conn: sqlite3.Connection, alert: dict) -> dict:
    """
    Logs an alert to Alert_Log table (engine-only).
    Dedupe behavior: if an unresolved identical alert exists (type+entity_id+message), do not re-insert.

    Creates table if not exists:
      CREATE TABLE IF NOT EXISTS Alert_Log (
          alert_id TEXT PRIMARY KEY,
          alert_type TEXT,
          entity_id TEXT,
          message TEXT,
          severity TEXT,
          resolved INTEGER DEFAULT 0,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )

    Returns:
        {logged: bool, alert_id: str, success: bool}
    """
    try:
        _ensure_alert_log_table(conn)

        alert_type = _safe_str(alert.get("type"))
        entity_id = _safe_str(alert.get("entity_id"))
        message = _safe_str(alert.get("message"))
        severity = _safe_str(alert.get("severity"))

        cur = conn.cursor()

        # Dedup unresolved alerts
        cur.execute(
            """
            SELECT alert_id
            FROM Alert_Log
            WHERE resolved = 0
              AND alert_type = ?
              AND entity_id = ?
              AND message = ?
            LIMIT 1
            """,
            (alert_type, entity_id, message),
        )
        row = cur.fetchone()
        if row:
            return {"logged": False, "alert_id": _safe_str(row[0]), "success": True}

        alert_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO Alert_Log (alert_id, alert_type, entity_id, message, severity, resolved)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (alert_id, alert_type, entity_id, message, severity),
        )
        conn.commit()

        return {"logged": True, "alert_id": alert_id, "success": True}
    except Exception as e:
        return {"logged": False, "alert_id": "", "success": False, "error": str(e)}


# S✅ T✅ L✅ A✅