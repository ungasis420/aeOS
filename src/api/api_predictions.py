"""
src/api/api_predictions.py
Stamp: S✅ T✅ L✅ A✅
aeOS Phase 3 — API Layer (Predictions)
Purpose
-------
Expose REST endpoints for Prediction operations backed by the Phase 2
persistence layer (`prediction_persist.py`).
Endpoints (by requirement)
--------------------------
- POST  /predictions                     -> create new prediction
- GET   /predictions/{prediction_id}     -> fetch single
- GET   /predictions                     -> list all (limit param)
- PATCH /predictions/{prediction_id}/resolve
                                        -> resolve prediction with actual outcome/value
- GET   /predictions/calibration         -> calibration summary across predictors
- GET   /predictions/open                -> unresolved predictions only
Security
--------
All endpoints require API key validation via auth.py (validate_api_key()).
Response Envelope
-----------------
Every endpoint returns the standard envelope:
  { "success": bool, "data": any, "error": str | null }
Notes
-----
- This module prefers prediction_persist.py if present, but includes a
  best-effort DB fallback (similar to api_solutions.py) to keep the API
  usable across branch states.
- Brier score is computed as (p - y)^2 where p is predicted probability
  in [0,1] and y is actual_value (typically 0/1).
"""
from __future__ import annotations

import importlib
import inspect
import os
import time
from datetime import datetime, timezone
from itertools import count
from math import sqrt
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi import APIRouter, Body, FastAPI, Header, Path, Query
from fastapi.responses import JSONResponse

# --- Internal imports (safe fallbacks) --------------------------------------

try:
    from core.logger import get_logger  # type: ignore
except Exception:  # pragma: no cover
    try:
        from src.core.logger import get_logger  # type: ignore
    except Exception:  # pragma: no cover
        import logging

        def get_logger(name: str = "aeOS") -> "logging.Logger":  # type: ignore
            """Fallback logger (used only if aeOS logger is unavailable)."""
            logging.basicConfig(level=logging.INFO)
            return logging.getLogger(name)


def _lazy_import(paths: Sequence[str]) -> Optional[Any]:
    """Import the first module that exists from `paths`."""
    for p in paths:
        try:
            return importlib.import_module(p)
        except Exception:
            continue
    return None


# auth.py is REQUIRED by spec (stdlib-only).
_auth = _lazy_import(["core.auth", "src.core.auth", "auth"])
if _auth is None:  # pragma: no cover
    raise ImportError("auth.py not found (expected core.auth / src.core.auth / auth).")

_validate_api_key = getattr(_auth, "validate_api_key", None)
_hash_key = getattr(_auth, "hash_key", None)

if not callable(_validate_api_key) or not callable(_hash_key):  # pragma: no cover
    raise ImportError("auth.py must export validate_api_key() and hash_key().")

# db_connect is OPTIONAL (used for DB fallback paths).
_db = _lazy_import(["db.db_connect", "src.db.db_connect", "db_connect"])
_get_connection = getattr(_db, "get_connection", None) if _db else None

# prediction_persist is OPTIONAL (preferred).
_pp = _lazy_import(["db.prediction_persist", "src.db.prediction_persist", "prediction_persist"])

_LOG = None
_START_MONO = time.monotonic()

# Seed counter with ms to reduce collision risk across runs.
_ID_COUNTER = count(start=int(time.time() * 1000) % 1_000_000)

# Cached schema resolution for DB fallback.
_PRED_SCHEMA_CACHE: Optional[Dict[str, Optional[str]]] = None


def _log():
    """Lazy-init logger (supports get_logger(name) and get_logger())."""
    global _LOG
    if _LOG is None:
        try:
            _LOG = get_logger(__name__)  # type: ignore[arg-type]
        except TypeError:  # pragma: no cover
            _LOG = get_logger()  # type: ignore[call-arg]
    return _LOG


def _uptime_seconds() -> int:
    """Process uptime in seconds (useful for debugging)."""
    return int(max(0.0, time.monotonic() - _START_MONO))


def _utc_now_iso() -> str:
    """UTC now as ISO-8601 string (no microseconds)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _envelope(success: bool, data: Any = None, error: Optional[str] = None) -> Dict[str, Any]:
    """Standard response envelope."""
    return {"success": bool(success), "data": data, "error": error}


def _json(
    success: bool,
    data: Any = None,
    error: Optional[str] = None,
    *,
    status_code: int = 200,
) -> JSONResponse:
    """JSONResponse with standard envelope."""
    return JSONResponse(status_code=status_code, content=_envelope(success, data, error))


# ---------------------------------------------------------------------------
# API key validation (auth.py)
# ---------------------------------------------------------------------------

def _resolve_key_hash() -> Optional[str]:
    """Resolve stored API key hash from env (AEOS_API_KEY_HASH or AEOS_API_KEY).

    Returns:
        str|None: A SHA-256 hex digest, or None if not configured.
    """
    h = (os.getenv("AEOS_API_KEY_HASH") or "").strip()
    if h:
        return h
    raw = (os.getenv("AEOS_API_KEY") or "").strip()
    if raw:
        try:
            return str(_hash_key(raw))
        except Exception:
            return None
    return None


_STORED_HASH = _resolve_key_hash()


def _extract_key(x_api_key: Optional[str], authorization: Optional[str]) -> Optional[str]:
    """Get presented key from X-API-Key or Authorization: Bearer."""
    if isinstance(x_api_key, str) and x_api_key.strip():
        return x_api_key.strip()
    if isinstance(authorization, str):
        a = authorization.strip()
        if a.lower().startswith("bearer "):
            token = a.split(" ", 1)[1].strip()
            return token or None
    return None


def _auth_guard(x_api_key: Optional[str], authorization: Optional[str]) -> Optional[JSONResponse]:
    """Return None if authorized; otherwise a JSONResponse (401/503) envelope."""
    if not _STORED_HASH:
        return _json(
            False,
            error="API key validation not configured (set AEOS_API_KEY_HASH or AEOS_API_KEY).",
            status_code=503,
        )
    key = _extract_key(x_api_key, authorization)
    if not key:
        return _json(False, error="Missing API key.", status_code=401)
    try:
        ok = bool(_validate_api_key(key, _STORED_HASH))
    except Exception:
        ok = False
    if not ok:
        return _json(False, error="Invalid API key.", status_code=401)
    return None


# ---------------------------------------------------------------------------
# Persistence adapter (prediction_persist preferred)
# ---------------------------------------------------------------------------

def _call_persist(fn_names: Sequence[str], *args: Any, **kwargs: Any) -> Tuple[bool, Any]:
    """Call the first available persistence function name.

    The persistence layer may evolve across branches. This helper performs
    a few safe retries to maximize compatibility:
    1) Direct call with provided args/kwargs.
    2) If kwargs fail, filter kwargs to the function signature.
    3) If only one kwarg remains and no positional args, retry as positional.
    4) If a single dict payload was passed positionally, retry as **payload.

    Returns:
        (ok, result_or_error)
    """
    if _pp is None:
        return (False, "prediction_persist_unavailable")

    for name in fn_names:
        fn = getattr(_pp, name, None)
        if not callable(fn):
            continue

        # 1) Try direct call (as provided).
        try:
            return (True, fn(*args, **kwargs))
        except TypeError:
            pass
        except Exception as e:
            return (False, str(e))

        # 2) Retry with filtered kwargs (signature-aware).
        if kwargs:
            try:
                sig = inspect.signature(fn)
                accepts_var_kw = any(
                    p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
                )
                if not accepts_var_kw:
                    filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
                else:
                    filtered = dict(kwargs)
                if filtered:
                    try:
                        return (True, fn(*args, **filtered))
                    except TypeError:
                        pass
                    except Exception as e:
                        return (False, str(e))
            except Exception:
                pass

            # 3) If we had only one kwarg, retry as a single positional arg.
            if not args and len(kwargs) == 1:
                try:
                    return (True, fn(next(iter(kwargs.values()))))
                except TypeError:
                    pass
                except Exception as e:
                    return (False, str(e))

        # 4) If a single dict payload was passed positionally, try keyword expansion.
        if len(args) == 1 and isinstance(args[0], dict) and not kwargs:
            payload = args[0]
            try:
                return (True, fn(**payload))
            except TypeError:
                pass
            except Exception as e:
                return (False, str(e))
            try:
                sig = inspect.signature(fn)
                accepts_var_kw = any(
                    p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
                )
                if accepts_var_kw:
                    return (True, fn(**payload))
                filtered = {k: v for k, v in payload.items() if k in sig.parameters}
                return (True, fn(**filtered))
            except Exception as e:
                return (False, str(e))

        continue
    return (False, "prediction_persist_missing_functions")


# ---------------------------------------------------------------------------
# DB fallback helpers (sqlite introspection)
# ---------------------------------------------------------------------------

def _new_id(prefix: str = "PRED") -> str:
    """Create PREFIX-YYYYMMDD-NNN (NNN numeric, width >= 3)."""
    yyyymmdd = datetime.now(timezone.utc).strftime("%Y%m%d")
    seq = next(_ID_COUNTER)
    return f"{prefix}-{yyyymmdd}-{seq:03d}"


def _safe_close(conn: Any) -> None:
    """Best-effort close for DB connections."""
    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass


def _query_rows(
    conn: Any,
    sql: str,
    params: Sequence[Any] = (),
) -> Tuple[List[str], List[Tuple[Any, ...]]]:
    """Run a SELECT query and return (columns, rows)."""
    cur = conn.cursor()
    cur.execute(sql, list(params))
    rows = cur.fetchall() or []
    cols = [d[0] for d in (cur.description or [])]
    return cols, rows


def _rows_to_dicts(cols: List[str], rows: Sequence[Any]) -> List[Dict[str, Any]]:
    """Convert DB rows to dicts using cursor column names."""
    out: List[Dict[str, Any]] = []
    for r in rows:
        if isinstance(r, dict):
            out.append(dict(r))
            continue
        try:
            out.append({cols[i]: r[i] for i in range(min(len(cols), len(r)))})
        except Exception:
            out.append({"value": r})
    return out


def _list_tables(conn: Any) -> List[str]:
    """List user tables in sqlite (best-effort)."""
    try:
        _cols, rows = _query_rows(
            conn,
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
        )
        return [str(r[0]) for r in rows if r and r[0]]
    except Exception:
        return []


def _table_columns(conn: Any, table: str) -> List[str]:
    """Return columns for a table via PRAGMA table_info."""
    try:
        cols, rows = _query_rows(conn, f'PRAGMA table_info("{table}")')
        name_idx = cols.index("name") if "name" in cols else 1
        return [str(r[name_idx]) for r in rows if r and len(r) > name_idx and r[name_idx]]
    except Exception:
        return []


def _pick_first(existing: Sequence[str], candidates: Sequence[str]) -> Optional[str]:
    """Pick the first candidate present in existing (case-insensitive)."""
    lower = {c.lower(): c for c in existing}
    for cand in candidates:
        hit = lower.get(str(cand).lower())
        if hit:
            return hit
    return None


def _resolve_pred_schema() -> Dict[str, Optional[str]]:
    """Resolve prediction table and key columns for DB fallback (cached)."""
    global _PRED_SCHEMA_CACHE
    if _PRED_SCHEMA_CACHE is not None:
        return _PRED_SCHEMA_CACHE

    schema: Dict[str, Optional[str]] = {
        "table": None,
        "id_col": None,
        "predictor_col": None,
        "status_col": None,
        "predicted_col": None,
        "actual_outcome_col": None,
        "actual_value_col": None,
        "brier_col": None,
        "created_col": None,
        "resolved_col": None,
        "updated_col": None,
    }

    if not callable(_get_connection):
        _PRED_SCHEMA_CACHE = schema
        return schema

    conn = None
    try:
        conn = _get_connection()  # type: ignore[misc]
        tables = _list_tables(conn)
        lower = {t.lower(): t for t in tables}

        # Preferred canonical name; otherwise anything that looks like a prediction table.
        table = (
            lower.get("prediction_registry")
            or lower.get("predictions")
            or lower.get("prediction")
            or next((t for t in tables if "predict" in t.lower()), None)
        )
        if not table:
            _PRED_SCHEMA_CACHE = schema
            return schema

        cols = _table_columns(conn, table)

        id_col = _pick_first(cols, ["Prediction_ID", "prediction_id", "id"])
        if id_col is None:
            id_col = next(
                (c for c in cols if c.lower().endswith("_id") and "predict" in c.lower()),
                None,
            )

        predictor_col = _pick_first(
            cols, ["Predictor", "predictor", "Predictor_ID", "predictor_id", "Owner", "owner"]
        )
        status_col = _pick_first(cols, ["Status", "status", "Prediction_Status", "prediction_status", "State", "state"])
        predicted_col = _pick_first(
            cols,
            [
                "Predicted_Prob",
                "predicted_prob",
                "Probability",
                "probability",
                "Predicted_Value",
                "predicted_value",
                "Confidence",
                "confidence",
            ],
        )
        actual_outcome_col = _pick_first(cols, ["Actual_Outcome", "actual_outcome", "Outcome", "outcome"])
        actual_value_col = _pick_first(
            cols,
            ["Actual_Value", "actual_value", "Actual", "actual", "Resolved_Value", "resolved_value"],
        )
        brier_col = _pick_first(cols, ["Brier_Score", "brier_score", "Brier", "brier"])
        created_col = _pick_first(cols, ["Created_At", "created_at", "Created", "created"])
        resolved_col = _pick_first(cols, ["Resolved_At", "resolved_at", "Resolved", "resolved"])
        updated_col = _pick_first(cols, ["Last_Updated", "last_updated", "Updated_At", "updated_at"])

        schema.update(
            {
                "table": table,
                "id_col": id_col,
                "predictor_col": predictor_col,
                "status_col": status_col,
                "predicted_col": predicted_col,
                "actual_outcome_col": actual_outcome_col,
                "actual_value_col": actual_value_col,
                "brier_col": brier_col,
                "created_col": created_col,
                "resolved_col": resolved_col,
                "updated_col": updated_col,
            }
        )
    except Exception as e:
        _log().warning("Failed to resolve prediction schema: %s", e)
    finally:
        _safe_close(conn)

    _PRED_SCHEMA_CACHE = schema
    return schema


def _db_create_prediction(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create a prediction record using best-effort DB introspection."""
    if not callable(_get_connection):
        raise RuntimeError("db_connect.get_connection unavailable")

    schema = _resolve_pred_schema()
    table = schema.get("table")
    id_col = schema.get("id_col")
    if not table or not id_col:
        raise RuntimeError("prediction table not found (expected Prediction_Registry)")

    conn = None
    try:
        conn = _get_connection()  # type: ignore[misc]
        cols = _table_columns(conn, table)
        rec = {k: v for k, v in payload.items() if k in cols}

        # Ensure ID exists.
        if id_col not in rec or not rec.get(id_col):
            rec[id_col] = payload.get("prediction_id") or payload.get("Prediction_ID") or _new_id("PRED")

        # Populate timestamps if columns exist.
        created_col = schema.get("created_col")
        updated_col = schema.get("updated_col")
        now_iso = _utc_now_iso()
        if created_col and created_col in cols and not rec.get(created_col):
            rec[created_col] = now_iso
        if updated_col and updated_col in cols and not rec.get(updated_col):
            rec[updated_col] = now_iso

        if not rec:
            raise ValueError("No valid fields provided for prediction insert.")

        keys = list(rec.keys())
        placeholders = ",".join(["?"] * len(keys))
        col_sql = ",".join([f'"{k}"' for k in keys])
        cur = conn.cursor()
        cur.execute(
            f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})',
            [rec[k] for k in keys],
        )
        conn.commit()
        return _db_get_prediction(str(rec[id_col]))
    finally:
        _safe_close(conn)


def _db_get_prediction(prediction_id: str) -> Dict[str, Any]:
    """Fetch a single prediction record by ID (DB fallback)."""
    if not callable(_get_connection):
        raise RuntimeError("db_connect.get_connection unavailable")

    schema = _resolve_pred_schema()
    table = schema.get("table")
    id_col = schema.get("id_col")
    if not table or not id_col:
        raise RuntimeError("prediction table not found (expected Prediction_Registry)")

    conn = None
    try:
        conn = _get_connection()  # type: ignore[misc]
        sql = f'SELECT * FROM "{table}" WHERE "{id_col}" = ? LIMIT 1'
        cols, rows = _query_rows(conn, sql, (prediction_id,))
        items = _rows_to_dicts(cols, rows)
        if not items:
            raise KeyError("not_found")
        return items[0]
    finally:
        _safe_close(conn)


def _db_list_predictions(limit: int) -> List[Dict[str, Any]]:
    """List predictions (DB fallback)."""
    if not callable(_get_connection):
        raise RuntimeError("db_connect.get_connection unavailable")

    schema = _resolve_pred_schema()
    table = schema.get("table")
    if not table:
        raise RuntimeError("prediction table not found (expected Prediction_Registry)")

    conn = None
    try:
        conn = _get_connection()  # type: ignore[misc]
        # Order by rowid desc as a safe default.
        sql = f'SELECT * FROM "{table}" ORDER BY rowid DESC LIMIT ?'
        cols, rows = _query_rows(conn, sql, (int(limit),))
        return _rows_to_dicts(cols, rows)
    finally:
        _safe_close(conn)


def _db_list_open_predictions(limit: int) -> List[Dict[str, Any]]:
    """Return unresolved predictions (DB fallback).

    We attempt (in order):
      - status column != 'Resolved'/'Closed'
      - resolved_at column is NULL
      - actual_value column is NULL
      - else: return all and let caller filter
    """
    if not callable(_get_connection):
        raise RuntimeError("db_connect.get_connection unavailable")

    schema = _resolve_pred_schema()
    table = schema.get("table")
    status_col = schema.get("status_col")
    resolved_col = schema.get("resolved_col")
    actual_value_col = schema.get("actual_value_col")
    if not table:
        raise RuntimeError("prediction table not found (expected Prediction_Registry)")

    conn = None
    try:
        conn = _get_connection()  # type: ignore[misc]
        cols = _table_columns(conn, table)
        where = ""
        params: List[Any] = []

        if status_col and status_col in cols:
            where = f'WHERE "{status_col}" NOT IN (?, ?)'
            params = ["Resolved", "Closed"]
        elif resolved_col and resolved_col in cols:
            where = f'WHERE "{resolved_col}" IS NULL'
        elif actual_value_col and actual_value_col in cols:
            where = f'WHERE "{actual_value_col}" IS NULL'

        sql = f'SELECT * FROM "{table}" {where} ORDER BY rowid DESC LIMIT ?'
        params.append(int(limit))
        c, rows = _query_rows(conn, sql, params)
        return _rows_to_dicts(c, rows)
    finally:
        _safe_close(conn)


def _db_resolve_prediction(
    prediction_id: str,
    actual_outcome: str,
    actual_value: float,
    brier_score: Optional[float],
) -> Dict[str, Any]:
    """Resolve a prediction record with actual outcome/value (DB fallback)."""
    if not callable(_get_connection):
        raise RuntimeError("db_connect.get_connection unavailable")

    schema = _resolve_pred_schema()
    table = schema.get("table")
    id_col = schema.get("id_col")
    status_col = schema.get("status_col")
    actual_outcome_col = schema.get("actual_outcome_col")
    actual_value_col = schema.get("actual_value_col")
    brier_col = schema.get("brier_col")
    resolved_col = schema.get("resolved_col")
    updated_col = schema.get("updated_col")

    if not table or not id_col:
        raise RuntimeError("prediction table not found (expected Prediction_Registry)")

    conn = None
    try:
        conn = _get_connection()  # type: ignore[misc]
        cols = _table_columns(conn, table)

        set_parts: List[str] = []
        params: List[Any] = []

        if status_col and status_col in cols:
            set_parts.append(f'"{status_col}" = ?')
            params.append("Resolved")
        if actual_outcome_col and actual_outcome_col in cols:
            set_parts.append(f'"{actual_outcome_col}" = ?')
            params.append(str(actual_outcome))
        if actual_value_col and actual_value_col in cols:
            set_parts.append(f'"{actual_value_col}" = ?')
            params.append(float(actual_value))
        if brier_col and brier_col in cols and brier_score is not None:
            set_parts.append(f'"{brier_col}" = ?')
            params.append(float(brier_score))
        now_iso = _utc_now_iso()
        if resolved_col and resolved_col in cols:
            set_parts.append(f'"{resolved_col}" = ?')
            params.append(now_iso)
        if updated_col and updated_col in cols:
            set_parts.append(f'"{updated_col}" = ?')
            params.append(now_iso)

        if not set_parts:
            raise RuntimeError("No resolvable fields found on prediction table.")

        params.append(prediction_id)
        sql = f'UPDATE "{table}" SET {", ".join(set_parts)} WHERE "{id_col}" = ?'
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()

        if cur.rowcount == 0:
            raise KeyError("not_found")

        # Return updated record.
        return _db_get_prediction(prediction_id)
    finally:
        _safe_close(conn)


# ---------------------------------------------------------------------------
# Shared extraction helpers (works for dict-like records)
# ---------------------------------------------------------------------------

def _normalize_list(x: Any) -> List[Any]:
    """Normalize various persistence return shapes into a list."""
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, tuple):
        return list(x)
    if isinstance(x, dict):
        for k in ("records", "items", "rows", "data", "predictions"):
            v = x.get(k)
            if isinstance(v, list):
                return v
    return [x]


def _get_first_float(rec: Any, keys: Sequence[str]) -> Optional[float]:
    """Best-effort: read first numeric value from record for any key in keys."""
    if not isinstance(rec, dict):
        return None
    for k in keys:
        v = rec.get(k)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v.strip():
            try:
                return float(v.strip())
            except Exception:
                continue
    return None


def _get_first_str(rec: Any, keys: Sequence[str]) -> Optional[str]:
    """Best-effort: read first string value from record for any key in keys."""
    if not isinstance(rec, dict):
        return None
    for k in keys:
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _extract_predicted_prob(rec: Any) -> Optional[float]:
    """Extract predicted probability/value from a record."""
    return _get_first_float(
        rec,
        [
            "predicted_prob",
            "Predicted_Prob",
            "probability",
            "Probability",
            "predicted_value",
            "Predicted_Value",
            "confidence",
            "Confidence",
            "p",
            "P",
        ],
    )


def _extract_actual_value(rec: Any) -> Optional[float]:
    """Extract actual_value from a record."""
    return _get_first_float(
        rec,
        ["actual_value", "Actual_Value", "actual", "Actual", "resolved_value", "Resolved_Value"],
    )


def _extract_brier(rec: Any) -> Optional[float]:
    """Extract brier_score from a record."""
    return _get_first_float(rec, ["brier_score", "Brier_Score", "brier", "Brier"])


def _extract_predictor(rec: Any) -> str:
    """Extract predictor identifier (defaults to 'unknown')."""
    s = _get_first_str(rec, ["predictor", "Predictor", "predictor_id", "Predictor_ID", "owner", "Owner"])
    return s or "unknown"


def _extract_status(rec: Any) -> str:
    """Extract prediction status (defaults to '')."""
    return _get_first_str(rec, ["status", "Status", "prediction_status", "Prediction_Status", "state", "State"]) or ""


def _is_resolved(rec: Any) -> bool:
    """Return True if a prediction looks resolved."""
    if not isinstance(rec, dict):
        return False
    status = _extract_status(rec).lower()
    if status in ("resolved", "closed", "complete", "completed"):
        return True
    # If actual_value exists, treat as resolved.
    av = _extract_actual_value(rec)
    if isinstance(av, (int, float)):
        return True
    # If resolved_at exists, treat as resolved.
    for k in ("resolved_at", "Resolved_At", "resolved", "Resolved"):
        v = rec.get(k)
        if v is not None and str(v).strip():
            return True
    return False


def _clamp01(x: float) -> float:
    """Clamp a number into [0, 1]."""
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return float(x)


def _compute_brier(predicted_prob: Optional[float], actual_value: Optional[float]) -> Optional[float]:
    """Compute Brier score (p - y)^2 for binary outcomes.

    Args:
        predicted_prob: Predicted probability in [0,1] (will be clamped).
        actual_value: Realized outcome (typically 0.0 or 1.0).

    Returns:
        float|None: Brier score, or None if inputs are missing/invalid.
    """
    if predicted_prob is None or actual_value is None:
        return None
    try:
        p = _clamp01(float(predicted_prob))
        y = float(actual_value)
    except Exception:
        return None
    return (p - y) ** 2


# ---------------------------------------------------------------------------
# Public operations (prefer persistence layer; fallback to DB)
# ---------------------------------------------------------------------------

def _create_prediction(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create a prediction via persistence layer or DB fallback."""
    ok, res = _call_persist(
        [
            "create_prediction",
            "create_prediction_record",
            "insert_prediction",
            "add_prediction",
            "save_prediction",
            "save_prediction_record",
        ],
        payload,
    )
    if ok:
        return res if isinstance(res, dict) else {"result": res}
    return _db_create_prediction(payload)


def _get_prediction(prediction_id: str) -> Dict[str, Any]:
    """Fetch a prediction via persistence layer or DB fallback."""
    ok, res = _call_persist(
        ["get_prediction", "get_prediction_by_id", "fetch_prediction", "load_prediction", "read_prediction"],
        prediction_id,
    )
    if ok:
        return res if isinstance(res, dict) else {"result": res}
    return _db_get_prediction(prediction_id)


def _list_predictions(limit: int) -> List[Dict[str, Any]]:
    """List predictions via persistence layer or DB fallback."""
    ok, res = _call_persist(
        ["list_predictions", "get_all_predictions", "list_all_predictions", "fetch_predictions"],
        limit=limit,
    )
    if ok:
        out = _normalize_list(res)
        # Some persistence returns dict-like rows; normalize to dicts where possible.
        return [r if isinstance(r, dict) else {"value": r} for r in out][: int(limit)]
    return _db_list_predictions(limit)


def _list_open_predictions(limit: int) -> List[Dict[str, Any]]:
    """List only unresolved predictions."""
    ok, res = _call_persist(
        ["list_open_predictions", "get_open_predictions", "list_unresolved_predictions", "fetch_open_predictions"],
        limit=limit,
    )
    if ok:
        out = _normalize_list(res)
        return [r if isinstance(r, dict) else {"value": r} for r in out][: int(limit)]
    # DB fallback (preferred), else filter list.
    try:
        return _db_list_open_predictions(limit)
    except Exception:
        all_rows = _list_predictions(limit=limit)
        return [r for r in all_rows if not _is_resolved(r)][: int(limit)]


def _resolve_prediction(
    prediction_id: str,
    actual_outcome: str,
    actual_value: float,
) -> Dict[str, Any]:
    """Resolve a prediction and update its Brier score (best-effort).

    Required behavior:
      - Calls resolve_prediction_db() when available.
      - Updates Brier score after resolution (computed from predicted_prob and actual_value).
    """
    # Fetch existing record first (needed to compute Brier).
    existing = _get_prediction(prediction_id)
    predicted_prob = _extract_predicted_prob(existing)
    brier = _compute_brier(predicted_prob, actual_value)

    # 1) Preferred: resolve via persistence layer.
    ok, res = _call_persist(
        ["resolve_prediction_db", "resolve_prediction", "mark_prediction_resolved"],
        prediction_id,
        actual_outcome,
        float(actual_value),
        brier_score=brier,
    )
    if ok:
        # If persistence computed brier itself, keep it. Otherwise, attach ours.
        if isinstance(res, dict):
            if brier is not None and _extract_brier(res) is None:
                res["brier_score"] = brier
            return res
        return {"result": res, "brier_score": brier}

    # 2) Fallback: DB update.
    return _db_resolve_prediction(prediction_id, actual_outcome, float(actual_value), brier)


def _calibration_summary(*, max_records: int = 50_000) -> Dict[str, Any]:
    """Return calibration summary across predictors (best-effort).

    If prediction_persist exposes a calibration helper, we delegate to it.
    Otherwise we compute a lightweight summary from stored predictions.

    Returns:
        dict: A summary payload safe for JSON transport.
    """
    # Delegate if persistence layer supports it.
    ok, res = _call_persist(
        ["get_calibration_summary", "calibration_summary", "compute_calibration_summary"],
        limit=max_records,
    )
    if ok:
        return res if isinstance(res, dict) else {"result": res}

    preds = _list_predictions(limit=int(max_records))
    resolved: List[Dict[str, Any]] = [p for p in preds if _is_resolved(p)]
    open_ = [p for p in preds if not _is_resolved(p)]

    # Aggregate resolved predictions by predictor.
    per: Dict[str, Dict[str, Any]] = {}
    for p in preds:
        key = _extract_predictor(p)
        d = per.setdefault(
            key,
            {
                "predictor": key,
                "n_total": 0,
                "n_resolved": 0,
                "sum_brier": 0.0,
                "sum_pred": 0.0,
                "sum_actual": 0.0,
            },
        )
        d["n_total"] += 1
        if not _is_resolved(p):
            continue
        pred = _extract_predicted_prob(p)
        act = _extract_actual_value(p)
        b = _extract_brier(p) or _compute_brier(pred, act)
        if b is None or pred is None or act is None:
            continue
        d["n_resolved"] += 1
        d["sum_brier"] += float(b)
        d["sum_pred"] += float(_clamp01(float(pred)))
        d["sum_actual"] += float(act)

    predictors: List[Dict[str, Any]] = []
    for k, d in per.items():
        n_r = int(d.get("n_resolved", 0) or 0)
        avg_brier = (float(d["sum_brier"]) / n_r) if n_r > 0 else None
        avg_pred = (float(d["sum_pred"]) / n_r) if n_r > 0 else None
        avg_actual = (float(d["sum_actual"]) / n_r) if n_r > 0 else None
        predictors.append(
            {
                "predictor": k,
                "n_total": int(d.get("n_total", 0) or 0),
                "n_resolved": n_r,
                "avg_brier": round(avg_brier, 6) if isinstance(avg_brier, (int, float)) else None,
                "rmse": round(sqrt(avg_brier), 6) if isinstance(avg_brier, (int, float)) else None,
                "avg_predicted": round(avg_pred, 6) if isinstance(avg_pred, (int, float)) else None,
                "avg_actual": round(avg_actual, 6) if isinstance(avg_actual, (int, float)) else None,
            }
        )
    predictors.sort(key=lambda r: (-(r.get("n_resolved") or 0), str(r.get("predictor") or "")))

    # Overall calibration bins (0.0-1.0 in 10 buckets).
    bins = []
    for i in range(10):
        lo = i / 10.0
        hi = (i + 1) / 10.0
        bins.append(
            {"bin": f"{lo:.1f}-{hi:.1f}", "lo": lo, "hi": hi, "n": 0, "sum_pred": 0.0, "sum_actual": 0.0}
        )

    for p in resolved:
        pred = _extract_predicted_prob(p)
        act = _extract_actual_value(p)
        if pred is None or act is None:
            continue
        pr = _clamp01(float(pred))
        idx = min(9, max(0, int(pr * 10.0)))
        b = bins[idx]
        b["n"] += 1
        b["sum_pred"] += pr
        b["sum_actual"] += float(act)

    for b in bins:
        n = int(b["n"])
        if n > 0:
            b["avg_pred"] = round(float(b["sum_pred"]) / n, 6)
            b["avg_actual"] = round(float(b["sum_actual"]) / n, 6)
        else:
            b["avg_pred"] = None
            b["avg_actual"] = None
        # Drop sums to keep payload small.
        b.pop("sum_pred", None)
        b.pop("sum_actual", None)

    # Overall avg brier.
    briers = []
    for p in resolved:
        pred = _extract_predicted_prob(p)
        act = _extract_actual_value(p)
        b = _extract_brier(p) or _compute_brier(pred, act)
        if b is not None:
            briers.append(float(b))
    avg_brier_all = (sum(briers) / len(briers)) if briers else None

    return {
        "generated_at": _utc_now_iso(),
        "uptime_seconds": _uptime_seconds(),
        "total": len(preds),
        "resolved": len(resolved),
        "open": len(open_),
        "avg_brier": round(avg_brier_all, 6) if isinstance(avg_brier_all, (int, float)) else None,
        "predictors": predictors,
        "bins": bins,
        "notes": {
            "brier_definition": "(p - y)^2, with p clamped to [0,1]",
            "binning": "10 equal-width probability bins across resolved predictions",
        },
    }


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["predictions"])


@router.post("/predictions")
def create_prediction(
    payload: Dict[str, Any] = Body(..., description="Prediction record fields."),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """POST /predictions — create a new prediction."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    if not isinstance(payload, dict):
        return _json(False, error="Invalid JSON body; expected an object.", status_code=400)
    try:
        created = _create_prediction(payload)
        return _json(True, data=created, status_code=201)
    except Exception as e:
        _log().exception("Failed to create prediction: %s", e)
        return _json(False, error=str(e), status_code=500)


@router.get("/predictions/{prediction_id}")
def get_prediction(
    prediction_id: str = Path(..., description="Prediction_ID / prediction_id."),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """GET /predictions/{prediction_id} — fetch a single prediction."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    try:
        rec = _get_prediction(prediction_id)
        return _json(True, data=rec, status_code=200)
    except KeyError:
        return _json(False, error="Prediction not found.", status_code=404)
    except Exception as e:
        _log().exception("Failed to load prediction '%s': %s", prediction_id, e)
        return _json(False, error=str(e), status_code=500)


@router.get("/predictions")
def list_predictions(
    limit: int = Query(default=50, ge=1, le=1000),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """GET /predictions — list all predictions."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    try:
        rows = _list_predictions(limit=int(limit))
        return _json(True, data=rows, status_code=200)
    except Exception as e:
        _log().exception("Failed to list predictions: %s", e)
        return _json(False, error=str(e), status_code=500)


@router.get("/predictions/open")
def list_open_predictions(
    limit: int = Query(default=50, ge=1, le=1000),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """GET /predictions/open — list unresolved predictions only."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    try:
        rows = _list_open_predictions(limit=int(limit))
        return _json(True, data=rows, status_code=200)
    except Exception as e:
        _log().exception("Failed to list open predictions: %s", e)
        return _json(False, error=str(e), status_code=500)


@router.patch("/predictions/{prediction_id}/resolve")
def resolve_prediction(
    prediction_id: str = Path(..., description="Prediction_ID / prediction_id."),
    payload: Dict[str, Any] = Body(..., description="{actual_outcome: str, actual_value: float}"),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """PATCH /predictions/{prediction_id}/resolve — resolve a prediction and update brier score."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    if not isinstance(payload, dict):
        return _json(False, error="Invalid JSON body; expected an object.", status_code=400)

    actual_outcome = str(payload.get("actual_outcome") or "").strip()
    if not actual_outcome:
        return _json(False, error="Missing required field: actual_outcome", status_code=400)

    actual_value_raw = payload.get("actual_value")
    if not isinstance(actual_value_raw, (int, float, str)):
        return _json(False, error="Missing/invalid required field: actual_value", status_code=400)
    try:
        actual_value = float(actual_value_raw)
    except Exception:
        return _json(False, error="Invalid actual_value; expected a number.", status_code=400)

    try:
        updated = _resolve_prediction(prediction_id, actual_outcome, actual_value)
        return _json(True, data=updated, status_code=200)
    except KeyError:
        return _json(False, error="Prediction not found.", status_code=404)
    except Exception as e:
        _log().exception("Failed to resolve prediction '%s': %s", prediction_id, e)
        return _json(False, error=str(e), status_code=500)


@router.get("/predictions/calibration")
def get_calibration(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """GET /predictions/calibration — calibration summary across all predictors."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    try:
        summary = _calibration_summary(max_records=50_000)
        return _json(True, data=summary, status_code=200)
    except Exception as e:
        _log().exception("Failed to compute calibration summary: %s", e)
        return _json(False, error=str(e), status_code=500)


def create_app() -> FastAPI:
    """Standalone FastAPI app factory (optional)."""
    app = FastAPI(title="aeOS Predictions API", version="0.1.0")
    app.include_router(router)
    return app


# Uvicorn entrypoint: uvicorn src.api.api_predictions:app --reload
app = create_app()
