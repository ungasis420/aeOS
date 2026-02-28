"""pain_persist.py
aeOS — Pain persistence layer (DB bridge)
Purpose
-------
Persist `Pain_Point_Register` records to SQLite.
This module bridges the pure calculation layer (e.g., `calc_pain.py`) to the
database layer. It writes/reads rows using the canonical Blueprint field names
as defined in `aeOS_PERSIST_v1.0.sql`.
Public API
----------
- save_pain_record(conn, pain_dict) -> str
- load_pain_record(conn, pain_id) -> dict
- list_pain_records(conn, limit=50) -> list[dict]
- update_pain_status(conn, pain_id, status) -> bool
Notes
-----
- `conn` may be either:
    * an existing sqlite3.Connection, OR
    * a path (str/Path) to a SQLite DB file, OR
    * None (uses db_connect.get_connection() default DB path)
- Pain_Score is computed using `calc_pain.calculate_pain_score()` when not
  provided. Because the DB schema stores `Frequency` as a code (CT_Freq) rather
  than a numeric, we support an optional `frequency_num` key in `pain_dict`.
  If absent, a small deterministic mapping (Daily→10, Weekly→7, Monthly→4,
  Occasional→2, Rare→1) is used.
Stamp: S✅ T✅ L✅ A✅
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

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

try:  # package-relative
    from ..calc_pain import calculate_pain_score, validate_pain_inputs  # type: ignore
except Exception:  # pragma: no cover
    try:  # flat import
        from calc_pain import calculate_pain_score, validate_pain_inputs  # type: ignore
    except Exception:  # pragma: no cover
        calculate_pain_score = None  # type: ignore
        validate_pain_inputs = None  # type: ignore

ConnLike = Union[sqlite3.Connection, str, Path, None]

__all__ = [
    "save_pain_record",
    "load_pain_record",
    "list_pain_records",
    "update_pain_status",
]

# -----------------------------------------------------------------------------
# Canonical code values (mirrors aeOS_PERSIST_v1.0.sql code tables)
# -----------------------------------------------------------------------------
_FREQ_VALUES: Tuple[str, ...] = ("Daily", "Weekly", "Monthly", "Occasional", "Rare")

_PHASE_VALUES: Tuple[str, ...] = (
    "Phase_0",
    "Phase_1",
    "Phase_2",
    "Phase_3",
    "Phase_4",
    "Phase_5",
    "Phase_6",
)

_PAIN_STATUS_VALUES: Tuple[str, ...] = ("Active", "Solved", "Abandoned", "Monitoring")

# Deterministic mapping used only when `frequency_num` isn't supplied.
# Key decision:
# - We keep these values on a 1–10 scale so they are directly compatible with
#   the slider-style input supported by calc_pain.
_FREQ_TO_NUM_SLIDER: Dict[str, int] = {
    "Daily": 10,
    "Weekly": 7,
    "Monthly": 4,
    "Occasional": 2,
    "Rare": 1,
}


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------
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


def _as_int(value: Any, *, name: str) -> int:
    """Coerce an int-like value to int, rejecting booleans."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")
    return int(value)


def _as_bool(value: Any, *, name: str) -> bool:
    """Coerce common boolean representations to bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in {"true", "t", "yes", "y", "1"}:
            return True
        if s in {"false", "f", "no", "n", "0"}:
            return False
    raise TypeError(f"{name} must be a bool (or 0/1), got {type(value).__name__}")


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


def _as_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s if s else None
    return str(value)


def _get(d: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    """Get the first present key from mapping (supports multiple aliases)."""
    for k in keys:
        if k in d:
            return d.get(k)
    return default


def _normalize_code(value: Any, *, allowed: Sequence[str], name: str) -> str:
    """Normalize a code-table value using a case-insensitive match."""
    v = _as_non_empty_str(value, name=name, min_len=1)
    # Fast path: exact
    if v in allowed:
        return v
    # Case-insensitive match
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
            # Fall back to raw close
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


def _next_pain_id(conn: sqlite3.Connection) -> str:
    """Generate a new Pain_ID in the format PAIN-YYYYMMDD-NNN.

    Key decision:
    - Uses the DB as the source of truth (reads the current max for today).
    - Avoids global in-memory counters (works across processes).
    """
    yyyymmdd = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"PAIN-{yyyymmdd}-"
    row = conn.execute(
        "SELECT Pain_ID FROM Pain_Point_Register WHERE Pain_ID LIKE ? ORDER BY Pain_ID DESC LIMIT 1;",
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


def _infer_freq_num(
    *,
    frequency_code: str,
    severity: float,
    impact_score: float,
    explicit_frequency_num: Optional[float],
) -> float:
    """Return the numeric frequency input used by calc_pain.

    If `explicit_frequency_num` is provided, it wins.
    Otherwise, we derive a number from the Frequency code.
    """
    if explicit_frequency_num is not None:
        return float(explicit_frequency_num)
    # Key decision:
    # - The SQLite schema stores Severity/Impact_Score as integers 1–10.
    # - Therefore the default mapping must be on the same 1–10 scale.
    # - Normalized 0–1 inputs are supported by calc_pain, but NOT by the DB schema.
    return float(_FREQ_TO_NUM_SLIDER[frequency_code])


def _compute_pain_score(
    *,
    severity: float,
    frequency_num: float,
    monetizability_flag: bool,
    impact_score: float,
) -> float:
    """Compute Pain_Score using calc_pain; raise if calc layer not available."""
    if calculate_pain_score is None or validate_pain_inputs is None:
        raise ImportError("calc_pain.calculate_pain_score could not be imported")
    # Use calc_pain's own validator so we match its scaling rules.
    is_valid, errors = validate_pain_inputs(severity, frequency_num, monetizability_flag, impact_score)  # type: ignore[misc]
    if not is_valid:
        raise ValueError("Invalid pain inputs: " + "; ".join(errors))
    return float(calculate_pain_score(severity, frequency_num, monetizability_flag, impact_score))  # type: ignore[misc]


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
def save_pain_record(conn: ConnLike, pain_dict: dict) -> str:
    """Insert a pain record into the Pain_Point_Register table.

    Args:
        conn:
            sqlite3.Connection, or a DB path (str/Path), or None.
            If not a Connection, a new one is opened via get_connection().
        pain_dict:
            Dict representing a pain entry. Keys may use either canonical DB
            column names (e.g., "Pain_Name") or snake_case aliases
            (e.g., "pain_name").

            Required (by schema):
              - Pain_Name (min 1 char)
              - Description (min 20 chars)
              - Affected_Population
              - Frequency (CT_Freq)
              - Severity (1–10)
              - Impact_Score (1–10)
              - Monetizability_Flag (bool/0/1)
              - Evidence (min 10 chars)
              - Phase_Created (CT_Phase)  (default: Phase_0)
              - Date_Identified (date/datetime string) (default: now)
              - Status (CT_Pain_Status)   (default: Active)
              - Last_Updated (date/datetime string) (default: now)

            Optional:
              - Pain_ID (auto-generated if missing)
              - Pain_Score (computed if missing)
              - frequency_num (used only for pain_score computation)
              - Root_Cause, WTP_Estimate, Linked_Idea_IDs, Validated_By,
                Validation_Date, Notes, Created_By

    Returns:
        str: The Pain_ID of the inserted record.

    Raises:
        TypeError/ValueError: On invalid inputs.
        sqlite3.Error: On database failure.
    """
    if not isinstance(pain_dict, dict):
        raise TypeError(f"pain_dict must be a dict, got {type(pain_dict).__name__}")

    c, should_close = _coerce_connection(conn)
    try:
        # --- Required field extraction + validation -------------------------
        pain_name = _as_non_empty_str(_get(pain_dict, "Pain_Name", "pain_name"), name="Pain_Name", min_len=1)
        description = _as_non_empty_str(
            _get(pain_dict, "Description", "description"),
            name="Description",
            min_len=20,
        )
        affected_population = _as_non_empty_str(
            _get(pain_dict, "Affected_Population", "affected_population"),
            name="Affected_Population",
            min_len=1,
        )
        frequency = _normalize_code(
            _get(pain_dict, "Frequency", "frequency"),
            allowed=_FREQ_VALUES,
            name="Frequency",
        )
        severity = _as_int(_get(pain_dict, "Severity", "severity"), name="Severity")
        if severity < 1 or severity > 10:
            raise ValueError("Severity must be between 1 and 10")

        impact = _as_int(_get(pain_dict, "Impact_Score", "impact_score", "impact"), name="Impact_Score")
        if impact < 1 or impact > 10:
            raise ValueError("Impact_Score must be between 1 and 10")

        monetizable_bool = _as_bool(_get(pain_dict, "Monetizability_Flag", "monetizability_flag"), name="Monetizability_Flag")
        evidence = _as_non_empty_str(_get(pain_dict, "Evidence", "evidence"), name="Evidence", min_len=10)

        phase_created = _normalize_code(
            _get(pain_dict, "Phase_Created", "phase_created", default="Phase_0"),
            allowed=_PHASE_VALUES,
            name="Phase_Created",
        )
        status = _normalize_code(
            _get(pain_dict, "Status", "status", default="Active"),
            allowed=_PAIN_STATUS_VALUES,
            name="Status",
        )

        # Best-effort code-table verification (keeps errors human-friendly).
        # If the DB isn't migrated yet, these checks may return False; we only
        # raise if the code tables exist but the value does not.
        if _code_exists(c, "CT_Freq", frequency) is False:
            # If CT_Freq table is missing, a later FK error will occur; keep message helpful.
            logger.debug("CT_Freq check failed for value=%r (table missing or value absent).", frequency)
        if _code_exists(c, "CT_Phase", phase_created) is False:
            logger.debug("CT_Phase check failed for value=%r (table missing or value absent).", phase_created)
        if _code_exists(c, "CT_Pain_Status", status) is False:
            logger.debug("CT_Pain_Status check failed for value=%r (table missing or value absent).", status)

        # Dates: accept user-provided strings, otherwise default to now.
        date_identified = _as_optional_str(_get(pain_dict, "Date_Identified", "date_identified")) or _now_iso_utc()
        last_updated = _as_optional_str(_get(pain_dict, "Last_Updated", "last_updated")) or _now_iso_utc()

        # Optional fields
        root_cause = _as_optional_str(_get(pain_dict, "Root_Cause", "root_cause"))
        linked_idea_ids = _as_optional_str(_get(pain_dict, "Linked_Idea_IDs", "linked_idea_ids"))
        validated_by = _as_optional_str(_get(pain_dict, "Validated_By", "validated_by"))
        validation_date = _as_optional_str(_get(pain_dict, "Validation_Date", "validation_date"))
        notes = _as_optional_str(_get(pain_dict, "Notes", "notes"))
        created_by = _as_optional_str(_get(pain_dict, "Created_By", "created_by"))
        wtp_estimate = _as_optional_float(_get(pain_dict, "WTP_Estimate", "wtp_estimate"), name="WTP_Estimate")

        # Pain_ID (generate if missing)
        pain_id_raw = _as_optional_str(_get(pain_dict, "Pain_ID", "pain_id"))
        pain_id = pain_id_raw if pain_id_raw else _next_pain_id(c)

        # Pain_Score (use provided value if valid, otherwise compute)
        pain_score_raw = _get(pain_dict, "Pain_Score", "pain_score", default=None)
        pain_score: float
        if pain_score_raw is not None and pain_score_raw != "":
            try:
                pain_score = float(pain_score_raw)
            except (TypeError, ValueError):
                raise TypeError("Pain_Score must be a number in [0, 100] or omitted")
            if pain_score < 0.0 or pain_score > 100.0:
                raise ValueError("Pain_Score must be within [0, 100]")
        else:
            freq_num_raw = _get(pain_dict, "frequency_num", "Frequency_num", "frequencyNum", default=None)
            freq_num = _infer_freq_num(
                frequency_code=frequency,
                severity=float(severity),
                impact_score=float(impact),
                explicit_frequency_num=float(freq_num_raw) if freq_num_raw is not None and freq_num_raw != "" else None,
            )
            pain_score = _compute_pain_score(
                severity=float(severity),
                frequency_num=float(freq_num),
                monetizability_flag=monetizable_bool,
                impact_score=float(impact),
            )

        record: Dict[str, Any] = {
            "Pain_ID": pain_id,
            "Pain_Name": pain_name,
            "Description": description,
            "Root_Cause": root_cause,
            "Affected_Population": affected_population,
            "Frequency": frequency,
            "Severity": int(severity),
            "Impact_Score": int(impact),
            "Monetizability_Flag": 1 if monetizable_bool else 0,
            "WTP_Estimate": wtp_estimate,
            "Evidence": evidence,
            "Pain_Score": float(pain_score),
            "Linked_Idea_IDs": linked_idea_ids,
            "Phase_Created": phase_created,
            "Date_Identified": date_identified,
            "Status": status,
            "Validated_By": validated_by,
            "Validation_Date": validation_date,
            "Notes": notes,
            "Created_By": created_by,
            "Last_Updated": last_updated,
        }

        cols = list(record.keys())
        placeholders = ", ".join(["?"] * len(cols))
        col_sql = ", ".join([f'"{cname}"' for cname in cols])
        sql = f'INSERT INTO "Pain_Point_Register" ({col_sql}) VALUES ({placeholders});'
        params = tuple(record[cname] for cname in cols)

        if execute_query is not None:
            execute_query(c, sql, params)  # type: ignore[misc]
        else:
            c.execute(sql, params)
            c.commit()

        return pain_id

    finally:
        if should_close:
            _safe_close(c)


def load_pain_record(conn: ConnLike, pain_id: str) -> Dict[str, Any]:
    """Load a single Pain_Point_Register record by Pain_ID.

    Args:
        conn: sqlite3.Connection, or DB path (str/Path), or None.
        pain_id: Pain_ID string (e.g., "PAIN-YYYYMMDD-NNN").

    Returns:
        dict: The record as a dict. Returns an empty dict if not found.

    Raises:
        TypeError/ValueError: On invalid inputs.
        sqlite3.Error: On database failure.
    """
    pid = _as_non_empty_str(pain_id, name="pain_id", min_len=5)
    c, should_close = _coerce_connection(conn)
    try:
        cur = c.execute('SELECT * FROM "Pain_Point_Register" WHERE "Pain_ID" = ? LIMIT 1;', (pid,))
        row = _fetchone_dict(cur)
        return row or {}
    finally:
        if should_close:
            _safe_close(c)


def list_pain_records(conn: ConnLike, limit: int = 50) -> List[Dict[str, Any]]:
    """List the most recent pain records.

    Ordering
    --------
    The Blueprint schema does not include a `created_at` column; it uses
    `Date_Identified` + `Last_Updated`. This function follows the requirement
    "order by created_at" by:
      1) Ordering by `created_at` if that column exists (future-proof), else
      2) Ordering by `Date_Identified` DESC (creation proxy).

    Args:
        conn: sqlite3.Connection, or DB path (str/Path), or None.
        limit: Max number of records to return (default 50).

    Returns:
        list[dict]: Records as dicts.

    Raises:
        TypeError/ValueError: On invalid inputs.
        sqlite3.Error: On database failure.
    """
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise TypeError("limit must be an int")
    if limit <= 0:
        return []
    c, should_close = _coerce_connection(conn)
    try:
        # Detect preferred ordering column.
        cols = [r[1] for r in c.execute('PRAGMA table_info("Pain_Point_Register");').fetchall()]
        order_col = "created_at" if "created_at" in cols else "Date_Identified"
        cur = c.execute(
            f'SELECT * FROM "Pain_Point_Register" ORDER BY "{order_col}" DESC LIMIT ?;',
            (int(limit),),
        )
        return _fetch_dicts(cur)
    finally:
        if should_close:
            _safe_close(c)


def update_pain_status(conn: ConnLike, pain_id: str, status: str) -> bool:
    """Update a pain record's Status (and Last_Updated).

    Args:
        conn: sqlite3.Connection, or DB path (str/Path), or None.
        pain_id: Pain_ID of the record to update.
        status: New status value (CT_Pain_Status).

    Returns:
        bool: True if a row was updated, False if no matching record.

    Raises:
        TypeError/ValueError: On invalid inputs.
        sqlite3.Error: On database failure.
    """
    pid = _as_non_empty_str(pain_id, name="pain_id", min_len=5)
    new_status = _normalize_code(status, allowed=_PAIN_STATUS_VALUES, name="status")
    ts = _now_iso_utc()
    c, should_close = _coerce_connection(conn)
    try:
        sql = 'UPDATE "Pain_Point_Register" SET "Status" = ?, "Last_Updated" = ? WHERE "Pain_ID" = ?;'
        params = (new_status, ts, pid)
        if execute_query is not None:
            cur = execute_query(c, sql, params)  # type: ignore[misc]
        else:
            cur = c.execute(sql, params)
            c.commit()
        return int(getattr(cur, "rowcount", 0) or 0) > 0
    finally:
        if should_close:
            _safe_close(c)
