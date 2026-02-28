"""
solution_persist.py
aeOS — Solution persistence layer (DB bridge)
Purpose
-------
Persist `Solution_Design` candidate records to SQLite.
This module bridges Phase 1 outputs (e.g., Solution Bridge candidates) to the
database layer. It writes/reads rows using the canonical Blueprint field names
as defined in `aeOS_PERSIST_v1.0.sql`.
Public API
----------
- save_solution(conn, solution_dict) -> str
- load_solution(conn, solution_id) -> dict
- list_solutions_by_pain(conn, pain_id) -> list[dict]
- update_solution_status(conn, solution_id, status) -> bool
- get_top_solutions(conn, limit=5) -> list[dict]
Notes
-----
- `conn` may be either:
    * an existing sqlite3.Connection, OR
    * a path (str/Path) to a SQLite DB file, OR
    * None (uses db_connect.get_connection() default DB path)
- The SQLite schema expects code-table constrained values for:
    * Solution_Type   → CT_Sol_Type
    * Complexity      → CT_Complexity
    * Status          → CT_Sol_Status
    * Monetization_Path (optional) → CT_Rev_Model
- If the caller passes a Solution Bridge candidate dict (fields like
  `candidate_id`, `solution_type`, `effort_score`, `expected_impact`,
  `confidence`, `rationale`), this module will:
    1) require `pain_id` to be provided, and
    2) auto-fill required Solution_Design fields using deterministic mappings,
       while preserving the original candidate fields in Notes.
Stamp: S✅ T✅ L✅ A✅
"""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# -----------------------------------------------------------------------------
# Optional project imports (keep module usable in different layouts)
# -----------------------------------------------------------------------------
try:  # package-relative (src/db)
    from .db_connect import close_connection, execute_query, get_connection  # type: ignore
except Exception:  # pragma: no cover
    try:  # flat import (scripts/ or project root)
        from db_connect import close_connection, execute_query, get_connection  # type: ignore
    except Exception:  # pragma: no cover
        close_connection = None  # type: ignore
        execute_query = None  # type: ignore
        get_connection = None  # type: ignore

ConnLike = Union[sqlite3.Connection, str, Path, None]

__all__ = [
    "save_solution",
    "load_solution",
    "list_solutions_by_pain",
    "update_solution_status",
    "get_top_solutions",
]

# -----------------------------------------------------------------------------
# Canonical code values (mirrors aeOS_PERSIST_v1.0.sql seed data)
# -----------------------------------------------------------------------------
_SOL_TYPE_VALUES: Tuple[str, ...] = ("Product", "Service", "Content", "System", "Community", "Tool", "Framework")
_COMPLEXITY_VALUES: Tuple[str, ...] = ("Low", "Medium", "High", "Very_High")
_SOL_STATUS_VALUES: Tuple[str, ...] = ("Concept", "Designing", "Validated", "Building", "Live", "Shelved")

# -----------------------------------------------------------------------------
# Candidate → CT mappings (for Solution Bridge candidate dicts)
# -----------------------------------------------------------------------------
# Key decision:
# - Solution Bridge emits fine-grained solution_type labels (automation, pivot, etc.)
# - Solution_Design schema expects coarse CT_Sol_Type (Product/Service/Content/...)
# - We map deterministically and store the original label in Notes for traceability.
_CANDIDATE_TO_CT_SOL_TYPE: Dict[str, str] = {
    # financial
    "cost_reduction": "System",
    "revenue_increase": "Service",
    # operational
    "process_improvement": "System",
    "automation": "Tool",
    # strategic
    "pivot": "Framework",
    "partnership": "Community",
    "new_market": "Framework",
    # personal
    "skill_development": "Content",
    "delegation": "Service",
    # technical
    "build": "Product",
    "buy": "Tool",
    "integrate": "System",
}

# -----------------------------------------------------------------------------
# Internal helpers (pain_persist.py style: strict, explicit, non-magical)
# -----------------------------------------------------------------------------
_SOL_ID_RE = re.compile(r"^SOL-\d{8}-\d{3}$")
_PAIN_ID_RE = re.compile(r"^PAIN-\d{8}-\d{3}$")


def _now_iso_utc() -> str:
    """Return timezone-aware ISO-8601 datetime string in UTC."""
    return datetime.now(timezone.utc).isoformat()


def _as_non_empty_str(value: Any, *, name: str, min_len: int = 1) -> str:
    """Validate a non-empty string and return it trimmed."""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string, got {type(value).__name__}")
    v = value.strip()
    if len(v) < int(min_len):
        raise ValueError(f"{name} must be at least {min_len} characters long")
    return v


def _as_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s if s else None
    return str(value)


def _as_optional_float(value: Any, *, name: str) -> Optional[float]:
    """Return float(value) or None (best-effort), rejecting booleans."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a number or None, got bool")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise TypeError(f"{name} must be a number or None, got {type(value).__name__}")


def _as_int(value: Any, *, name: str) -> int:
    """Coerce an int-like value to int, rejecting booleans."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    return int(value)


def _get(d: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    """Get the first present key from mapping (supports multiple aliases)."""
    for k in keys:
        if k in d:
            return d.get(k)
    return default


def _normalize_code(value: Any, *, allowed: Sequence[str], name: str) -> str:
    """Normalize a code-table value using a case-insensitive match."""
    v = _as_non_empty_str(value, name=name, min_len=1)
    if v in allowed:
        return v
    low = v.lower()
    for a in allowed:
        if a.lower() == low:
            return a
    raise ValueError(f"{name} must be one of {list(allowed)}, got {v!r}")


def _code_exists(conn: sqlite3.Connection, table: str, value: str) -> bool:
    """Return True if `value` exists in `table`. Best-effort; returns False on errors."""
    try:
        row = conn.execute(f'SELECT 1 FROM "{table}" WHERE "Value" = ? LIMIT 1;', (value,)).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _record_exists(conn: sqlite3.Connection, table: str, pk_col: str, pk_value: str) -> bool:
    """Return True if a PK value exists in a table. Best-effort; returns False on errors."""
    try:
        row = conn.execute(
            f'SELECT 1 FROM "{table}" WHERE "{pk_col}" = ? LIMIT 1;',
            (pk_value,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def _coerce_connection(conn: ConnLike) -> Tuple[sqlite3.Connection, bool]:
    """Return (connection, should_close).

    If `conn` is already a sqlite3.Connection, it is returned as-is.
    Otherwise, a new connection is created via db_connect.get_connection().
    """
    if isinstance(conn, sqlite3.Connection):
        return conn, False
    if get_connection is None:
        raise ImportError("db_connect.get_connection could not be imported")
    new_conn = get_connection(conn)  # type: ignore[arg-type]
    return new_conn, True


def _safe_close(conn: Optional[sqlite3.Connection]) -> None:
    if conn is None:
        return
    if close_connection is not None:
        try:
            close_connection(conn)  # type: ignore[misc]
            return
        except Exception:
            pass
    try:
        conn.close()
    except Exception:
        logger.exception("Failed to close SQLite connection")


def _fetch_dicts(cur: sqlite3.Cursor) -> List[Dict[str, Any]]:
    """Fetch all rows from cursor and return list[dict] regardless of row_factory."""
    rows = cur.fetchall()
    if not rows:
        return []
    if isinstance(rows[0], sqlite3.Row):
        return [dict(r) for r in rows]
    cols = [d[0] for d in (cur.description or [])]
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({cols[i]: r[i] for i in range(min(len(cols), len(r)))})
    return out


def _fetchone_dict(cur: sqlite3.Cursor) -> Optional[Dict[str, Any]]:
    row = cur.fetchone()
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        return dict(row)
    cols = [d[0] for d in (cur.description or [])]
    return {cols[i]: row[i] for i in range(min(len(cols), len(row)))}


def _next_solution_id(conn: sqlite3.Connection) -> str:
    """Generate a new Solution_ID in the format SOL-YYYYMMDD-NNN.

    Key decision:
    - Uses the DB as the source of truth (reads the current max for today).
    - Avoids global in-memory counters (works across processes).
    """
    yyyymmdd = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"SOL-{yyyymmdd}-"
    row = conn.execute(
        'SELECT "Solution_ID" FROM "Solution_Design" WHERE "Solution_ID" LIKE ? ORDER BY "Solution_ID" DESC LIMIT 1;',
        (prefix + "%",),
    ).fetchone()
    if not row:
        return f"{prefix}001"
    last_id = str(row[0])
    try:
        n = int(last_id.split("-")[-1])
    except Exception:
        n = 0
    return f"{prefix}{(n + 1):03d}"


def _map_candidate_to_ct_sol_type(candidate_solution_type: str) -> str:
    """Map Solution Bridge `solution_type` → CT_Sol_Type value."""
    key = (candidate_solution_type or "").strip().lower()
    for k, v in _CANDIDATE_TO_CT_SOL_TYPE.items():
        if k.lower() == key:
            return v
    # Safe default: "System" (broad, least misleading for unknown labels).
    return "System"


def _effort_to_complexity(effort_score: Optional[float]) -> str:
    """Map an effort score (1–10) to CT_Complexity."""
    if effort_score is None:
        return "Medium"
    e = float(effort_score)
    if e <= 3.0:
        return "Low"
    if e <= 6.0:
        return "Medium"
    if e <= 8.0:
        return "High"
    return "Very_High"


def _effort_to_time_to_mvp(effort_score: Optional[float]) -> str:
    """Map an effort score (1–10) to a human Time_To_MVP string."""
    if effort_score is None:
        return "2-6 weeks"
    e = float(effort_score)
    if e <= 3.0:
        return "1-2 weeks"
    if e <= 6.0:
        return "2-6 weeks"
    if e <= 8.0:
        return "1-3 months"
    return "3-6 months"


def _default_delivery_mechanism(ct_sol_type: str) -> str:
    """Return a deterministic Delivery_Mechanism default by CT_Sol_Type."""
    if ct_sol_type == "Product":
        return "Build a minimal MVP and onboard pilot users for feedback."
    if ct_sol_type == "Service":
        return "Deliver as a packaged service with a clear scope and SLA."
    if ct_sol_type == "Content":
        return "Publish a structured guide/course and iterate based on usage."
    if ct_sol_type == "Community":
        return "Run a community workflow (members, rules, cadence) to drive outcomes."
    if ct_sol_type == "Tool":
        return "Deploy a tool/script/app to reduce manual work and measure adoption."
    if ct_sol_type == "Framework":
        return "Document a repeatable framework and test it in a small pilot."
    # System
    return "Implement an SOP + workflow and measure cycle-time improvement."


def _humanize_candidate_label(label: str) -> str:
    """Convert 'cost_reduction' -> 'Cost reduction' (best-effort)."""
    s = (label or "").strip().replace("_", " ").replace("-", " ")
    s = " ".join([w for w in s.split() if w])
    return (s[:1].upper() + s[1:]) if s else "Solution"


def _ensure_min_len(text: str, *, min_len: int, suffix: str) -> str:
    """Ensure a minimum trimmed length by appending a suffix if needed."""
    t = (text or "").strip()
    if len(t) >= min_len:
        return t
    # Append enough content to cross the threshold, without being weirdly long.
    pad = (" " + suffix.strip()) if suffix.strip() else ""
    out = (t + pad).strip()
    if len(out) >= min_len:
        return out
    # Last resort: repeat suffix.
    while len(out) < min_len:
        out = (out + " " + suffix.strip()).strip()
    return out


def _validate_and_normalize_solution_id(value: Any, *, name: str) -> str:
    """Validate Solution_ID format SOL-YYYYMMDD-NNN."""
    sid = _as_non_empty_str(value, name=name, min_len=5)
    if not _SOL_ID_RE.match(sid):
        raise ValueError(f"{name} must match SOL-YYYYMMDD-NNN, got {sid!r}")
    return sid


def _validate_and_normalize_pain_id(value: Any, *, name: str) -> str:
    """Validate Pain_ID format PAIN-YYYYMMDD-NNN (best-effort, strict by default)."""
    pid = _as_non_empty_str(value, name=name, min_len=5)
    if not _PAIN_ID_RE.match(pid):
        raise ValueError(f"{name} must match PAIN-YYYYMMDD-NNN, got {pid!r}")
    return pid


def _validate_limit(limit: Any) -> int:
    """Validate and clamp list limits to a safe range."""
    n = _as_int(limit, name="limit")
    if n <= 0:
        raise ValueError("limit must be a positive integer")
    return min(n, 200)


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
def save_solution(conn: ConnLike, solution_dict: dict) -> str:
    """Insert a solution record into the Solution_Design table.

    Args:
        conn:
            sqlite3.Connection, or a DB path (str/Path), or None.
            If not a Connection, a new one is opened via get_connection().
        solution_dict:
            Dict representing a solution design entry.

            This function supports two input shapes:

            A) Canonical schema keys (preferred):
              - Pain_ID, Solution_Name, Solution_Type, Description,
                Delivery_Mechanism, Complexity, Time_To_MVP,
                (optional) Monetization_Path, Pain_Fit_Score, Linked_Idea_ID,
                (optional) Notes, Status, Date_Created, Last_Updated

            B) Solution Bridge candidate dict + minimal context:
              - pain_id (required)
              - candidate_id or solution_id (optional; auto-generated if missing)
              - solution_type (candidate label, e.g. "automation")
              - effort_score / expected_impact / confidence / rationale (optional)
              - You MAY also pass overrides for canonical fields like
                solution_name, description, complexity, time_to_mvp, status.

    Returns:
        str: The Solution_ID of the inserted record.

    Raises:
        TypeError/ValueError on invalid inputs.
        sqlite3.Error on DB failures.
    """
    if not isinstance(solution_dict, dict):
        raise TypeError(f"solution_dict must be a dict, got {type(solution_dict).__name__}")

    db, should_close = _coerce_connection(conn)
    try:
        # Required linkage
        pain_id = _validate_and_normalize_pain_id(
            _get(solution_dict, "Pain_ID", "pain_id"),
            name="Pain_ID",
        )
        # Foreign key: Pain must exist for a helpful error (FK will also enforce).
        if not _record_exists(db, "Pain_Point_Register", "Pain_ID", pain_id):
            raise ValueError(f"Pain_ID does not exist in Pain_Point_Register: {pain_id}")

        # Solution_ID: accept provided id or generate
        provided_id = _get(solution_dict, "Solution_ID", "solution_id", "candidate_id")
        if provided_id is None or (isinstance(provided_id, str) and not provided_id.strip()):
            solution_id = _next_solution_id(db)
        else:
            solution_id = _validate_and_normalize_solution_id(provided_id, name="Solution_ID")

        # Prevent confusing IntegrityErrors with a friendlier message.
        if _record_exists(db, "Solution_Design", "Solution_ID", solution_id):
            raise ValueError(f"Solution_ID already exists: {solution_id}")

        # Candidate label (if present)
        candidate_label = _as_optional_str(_get(solution_dict, "solution_type", "candidate_solution_type"))
        candidate_label = candidate_label or ""

        # Solution_Name
        solution_name = _as_optional_str(_get(solution_dict, "Solution_Name", "solution_name"))
        if not solution_name:
            base = _humanize_candidate_label(candidate_label)
            solution_name = f"{base} for {pain_id}"
        solution_name = _as_non_empty_str(solution_name, name="Solution_Name", min_len=1)

        # Solution_Type (CT_Sol_Type)
        raw_sol_type = _as_optional_str(_get(solution_dict, "Solution_Type", "solution_type_ct"))
        if raw_sol_type:
            ct_sol_type = _normalize_code(raw_sol_type, allowed=_SOL_TYPE_VALUES, name="Solution_Type")
        else:
            # If caller passed a candidate label (solution_bridge), map it.
            ct_sol_type = _map_candidate_to_ct_sol_type(candidate_label)

        # Description
        desc_raw = _as_optional_str(_get(solution_dict, "Description", "description", "rationale"))
        if not desc_raw:
            desc_raw = f"Auto-generated solution candidate ({candidate_label}) for pain {pain_id}."
        description = _ensure_min_len(
            desc_raw,
            min_len=20,
            suffix=f"(Generated from Solution Bridge; candidate_label={candidate_label or 'n/a'}.)",
        )

        # Delivery_Mechanism
        delivery = _as_optional_str(_get(solution_dict, "Delivery_Mechanism", "delivery_mechanism"))
        delivery = delivery or _default_delivery_mechanism(ct_sol_type)
        delivery = _as_non_empty_str(delivery, name="Delivery_Mechanism", min_len=1)

        # Complexity (CT_Complexity)
        raw_complexity = _as_optional_str(_get(solution_dict, "Complexity", "complexity"))
        if raw_complexity:
            complexity = _normalize_code(raw_complexity, allowed=_COMPLEXITY_VALUES, name="Complexity")
        else:
            complexity = _effort_to_complexity(_as_optional_float(_get(solution_dict, "effort_score"), name="effort_score"))

        # Time_To_MVP
        time_to_mvp = _as_optional_str(_get(solution_dict, "Time_To_MVP", "time_to_mvp"))
        if not time_to_mvp:
            effort = _as_optional_float(_get(solution_dict, "effort_score"), name="effort_score")
            time_to_mvp = _effort_to_time_to_mvp(effort)
        time_to_mvp = _as_non_empty_str(time_to_mvp, name="Time_To_MVP", min_len=1)

        # Monetization_Path (optional)
        monetization_path = _as_optional_str(_get(solution_dict, "Monetization_Path", "monetization_path"))

        # Pain_Fit_Score (optional, 0–10)
        pain_fit = _as_optional_float(_get(solution_dict, "Pain_Fit_Score", "pain_fit_score"), name="Pain_Fit_Score")
        if pain_fit is None:
            impact = _as_optional_float(_get(solution_dict, "expected_impact"), name="expected_impact")
            if impact is not None:
                pain_fit = max(0.0, min(10.0, float(impact) / 10.0))
        if pain_fit is not None and not (0.0 <= pain_fit <= 10.0):
            raise ValueError("Pain_Fit_Score must be between 0 and 10")

        linked_idea_id = _as_optional_str(_get(solution_dict, "Linked_Idea_ID", "linked_idea_id"))

        # Dates + status
        now = _now_iso_utc()
        date_created = _as_optional_str(_get(solution_dict, "Date_Created", "date_created")) or now
        last_updated = _as_optional_str(_get(solution_dict, "Last_Updated", "last_updated")) or now
        status_raw = _as_optional_str(_get(solution_dict, "Status", "status")) or "Concept"
        status = _normalize_code(status_raw, allowed=_SOL_STATUS_VALUES, name="Status")

        # Notes (keep candidate fields for traceability)
        notes_raw = _as_optional_str(_get(solution_dict, "Notes", "notes"))
        if not notes_raw:
            # Build a compact note from candidate fields when present.
            bits: List[str] = []
            if candidate_label:
                bits.append(f"candidate_label={candidate_label}")
            for k in ("effort_score", "expected_impact", "confidence", "rank"):
                v = _as_optional_str(solution_dict.get(k))
                if v is not None:
                    bits.append(f"{k}={v}")
            notes_raw = "; ".join(bits) if bits else None

        # ---- Code table existence checks (defensive; FK also enforces) ----
        if not _code_exists(db, "CT_Sol_Type", ct_sol_type):
            raise ValueError(f"Solution_Type not found in CT_Sol_Type: {ct_sol_type}")
        if not _code_exists(db, "CT_Complexity", complexity):
            raise ValueError(f"Complexity not found in CT_Complexity: {complexity}")
        if not _code_exists(db, "CT_Sol_Status", status):
            raise ValueError(f"Status not found in CT_Sol_Status: {status}")
        if monetization_path is not None and not _code_exists(db, "CT_Rev_Model", monetization_path):
            raise ValueError(f"Monetization_Path not found in CT_Rev_Model: {monetization_path}")

        # ---- Insert ----
        sql = """
        INSERT INTO "Solution_Design" (
            "Solution_ID",
            "Pain_ID",
            "Solution_Name",
            "Solution_Type",
            "Description",
            "Delivery_Mechanism",
            "Complexity",
            "Time_To_MVP",
            "Monetization_Path",
            "Pain_Fit_Score",
            "Linked_Idea_ID",
            "Date_Created",
            "Status",
            "Notes",
            "Last_Updated"
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        params = (
            solution_id,
            pain_id,
            solution_name,
            ct_sol_type,
            description,
            delivery,
            complexity,
            time_to_mvp,
            monetization_path,
            pain_fit,
            linked_idea_id,
            date_created,
            status,
            notes_raw,
            last_updated,
        )

        if execute_query is not None:
            execute_query(db, sql, params)  # type: ignore[misc]
        else:
            db.execute(sql, params)
            db.commit()

        return solution_id

    finally:
        if should_close:
            _safe_close(db)


def load_solution(conn: ConnLike, solution_id: str) -> Dict[str, Any]:
    """Load a solution record by Solution_ID.

    Args:
        conn: sqlite3.Connection, or DB path, or None (see module notes).
        solution_id: Solution_ID in the format SOL-YYYYMMDD-NNN.

    Returns:
        dict: Row as a dict if found; otherwise {}.

    Raises:
        TypeError/ValueError on invalid inputs.
        sqlite3.Error on DB failures.
    """
    sid = _validate_and_normalize_solution_id(solution_id, name="solution_id")
    db, should_close = _coerce_connection(conn)
    try:
        cur = db.execute('SELECT * FROM "Solution_Design" WHERE "Solution_ID" = ? LIMIT 1;', (sid,))
        row = _fetchone_dict(cur)
        return row or {}
    finally:
        if should_close:
            _safe_close(db)


def list_solutions_by_pain(conn: ConnLike, pain_id: str) -> List[Dict[str, Any]]:
    """Return all solutions linked to a Pain_ID.

    Args:
        conn: sqlite3.Connection, or DB path, or None (see module notes).
        pain_id: Pain_ID in the format PAIN-YYYYMMDD-NNN.

    Returns:
        list[dict]: Solutions ordered by Date_Created DESC, then Last_Updated DESC.

    Raises:
        TypeError/ValueError on invalid inputs.
        sqlite3.Error on DB failures.
    """
    pid = _validate_and_normalize_pain_id(pain_id, name="pain_id")
    db, should_close = _coerce_connection(conn)
    try:
        cur = db.execute(
            """
            SELECT *
            FROM "Solution_Design"
            WHERE "Pain_ID" = ?
            ORDER BY "Date_Created" DESC, "Last_Updated" DESC;
            """,
            (pid,),
        )
        return _fetch_dicts(cur)
    finally:
        if should_close:
            _safe_close(db)


def update_solution_status(conn: ConnLike, solution_id: str, status: str) -> bool:
    """Update Status for a solution.

    Args:
        conn: sqlite3.Connection, or DB path, or None (see module notes).
        solution_id: Solution_ID in the format SOL-YYYYMMDD-NNN.
        status: New status value from CT_Sol_Status.

    Returns:
        bool: True if at least one row was updated, False otherwise.

    Raises:
        TypeError/ValueError on invalid inputs.
        sqlite3.Error on DB failures.
    """
    sid = _validate_and_normalize_solution_id(solution_id, name="solution_id")
    st = _normalize_code(status, allowed=_SOL_STATUS_VALUES, name="status")
    db, should_close = _coerce_connection(conn)
    try:
        if not _code_exists(db, "CT_Sol_Status", st):
            raise ValueError(f"Status not found in CT_Sol_Status: {st}")
        now = _now_iso_utc()
        sql = 'UPDATE "Solution_Design" SET "Status" = ?, "Last_Updated" = ? WHERE "Solution_ID" = ?;'
        params = (st, now, sid)
        if execute_query is not None:
            cur = execute_query(db, sql, params)  # type: ignore[misc]
            return bool(cur.rowcount and cur.rowcount > 0)
        else:
            cur = db.execute(sql, params)
            db.commit()
            return bool(cur.rowcount and cur.rowcount > 0)
    finally:
        if should_close:
            _safe_close(db)


def get_top_solutions(conn: ConnLike, limit: int = 5) -> List[Dict[str, Any]]:
    """Return the "top" solutions across all pains.

    Since Solution_Design does not store a single canonical score field, we rank
    using an explicit, auditable proxy:
      1) Pain_Fit_Score (0–10) DESC (primary)
      2) Linked Pain_Score (0–100) DESC (tie-break)
      3) Last_Updated DESC

    Args:
        conn: sqlite3.Connection, or DB path, or None (see module notes).
        limit: Max rows to return (default 5). Clamped to 200.

    Returns:
        list[dict]: Rows including an extra column `Pain_Score` from the join.

    Raises:
        TypeError/ValueError on invalid inputs.
        sqlite3.Error on DB failures.
    """
    n = _validate_limit(limit)
    db, should_close = _coerce_connection(conn)
    try:
        cur = db.execute(
            """
            SELECT
                s.*,
                p."Pain_Score" AS "Pain_Score"
            FROM "Solution_Design" AS s
            JOIN "Pain_Point_Register" AS p
              ON p."Pain_ID" = s."Pain_ID"
            ORDER BY
                COALESCE(s."Pain_Fit_Score", 0) DESC,
                COALESCE(p."Pain_Score", 0) DESC,
                s."Last_Updated" DESC
            LIMIT ?;
            """,
            (n,),
        )
        return _fetch_dicts(cur)
    finally:
        if should_close:
            _safe_close(db)
