"""
src/api/api_solutions.py
Stamp: S✅ T✅ L✅ A✅
aeOS Phase 3 — API Layer (Solutions)
Purpose
-------
REST endpoints for solution operations (Solution_Design records).
Security + response contract
----------------------------
- All endpoints require API key validation via auth.py (validate_api_key()).
- Standard response envelope: {success: bool, data: any, error: str|null}
Endpoints (by requirement)
--------------------------
- POST   /solutions                     — create solution record
- GET    /solutions/{solution_id}       — fetch single
- GET    /solutions                     — list all (limit param)
- GET    /solutions/top                 — top 5 by score
- GET    /solutions/by-pain/{pain_id}   — solutions linked to a specific pain
- PATCH  /solutions/{solution_id}/status— update solution status
Implementation notes
--------------------
This API prefers the Phase 2 persistence layer (solution_persist.py) when present.
If the persistence module is unavailable (or lacks required functions), the API
falls back to direct SQLite queries via db_connect.get_connection(), using best-
effort table/column introspection.
This keeps the API usable across branch states while staying within Phase 3
constraints (stdlib + fastapi).
"""
from __future__ import annotations

import importlib
import inspect
import os
import time
from datetime import datetime, timezone
from itertools import count
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

# db_connect is OPTIONAL here (but required for DB fallback paths).
_db = _lazy_import(["db.db_connect", "src.db.db_connect", "db_connect"])
_get_connection = getattr(_db, "get_connection", None) if _db else None

# solution_persist is OPTIONAL (preferred).
_sp = _lazy_import(["db.solution_persist", "src.db.solution_persist", "solution_persist"])

_LOG = None
_START_MONO = time.monotonic()

# Seed counter with ms to reduce collision risk across runs.
_ID_COUNTER = count(start=int(time.time() * 1000) % 1_000_000)

# Cached schema resolution for DB fallback.
_SOLUTION_SCHEMA_CACHE: Optional[Dict[str, Optional[str]]] = None


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
    """Process uptime in seconds."""
    return int(max(0.0, time.monotonic() - _START_MONO))


def _utc_now_iso() -> str:
    """UTC now as ISO string (no microseconds)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _envelope(success: bool, data: Any = None, error: Optional[str] = None) -> Dict[str, Any]:
    """Standard response envelope."""
    return {"success": bool(success), "data": data, "error": error}


def _json(
    success: bool, data: Any = None, error: Optional[str] = None, *, status_code: int = 200
) -> JSONResponse:
    """JSONResponse with standard envelope."""
    return JSONResponse(status_code=status_code, content=_envelope(success, data, error))


def _resolve_key_hash() -> Optional[str]:
    """Resolve stored API key hash from env (AEOS_API_KEY_HASH or AEOS_API_KEY)."""
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
# Persistence adapter (solution_persist preferred)
# ---------------------------------------------------------------------------

def _call_persist(fn_names: Sequence[str], *args: Any, **kwargs: Any) -> Tuple[bool, Any]:
    """Call the first available persistence function name.

    The persistence layer (solution_persist.py) may evolve across branches.
    This helper performs a few safe retries to maximize compatibility:
    1) Direct call with provided args/kwargs.
    2) If kwargs fail, filter kwargs to the function signature.
    3) If a single kwarg remains (e.g., limit=50), retry as a single positional arg.
    4) If a single dict payload was passed positionally, retry as **payload (and filtered).

    Returns:
        (ok, result_or_error)
    """
    if _sp is None:
        return (False, "solution_persist_unavailable")

    for name in fn_names:
        fn = getattr(_sp, name, None)
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
                # Only retry if we actually have something to pass.
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

        # If we get here, try next candidate name.
        continue

    return (False, "solution_persist_missing_functions")


# ---------------------------------------------------------------------------
# DB fallback helpers
# ---------------------------------------------------------------------------

def _new_id(prefix: str) -> str:
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


def _query_rows(conn: Any, sql: str, params: Sequence[Any] = ()) -> Tuple[List[str], List[Tuple[Any, ...]]]:
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
        # rows are tuples like ("table_name",)
        return [str(r[0]) for r in rows if r and r[0]]
    except Exception:
        return []


def _table_columns(conn: Any, table: str) -> List[str]:
    """Return columns for a table via PRAGMA table_info."""
    try:
        cols, rows = _query_rows(conn, f'PRAGMA table_info("{table}")')
        # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
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


def _resolve_solution_schema() -> Dict[str, Optional[str]]:
    """Resolve solution table and key columns for DB fallback (cached)."""
    global _SOLUTION_SCHEMA_CACHE
    if _SOLUTION_SCHEMA_CACHE is not None:
        return _SOLUTION_SCHEMA_CACHE

    schema: Dict[str, Optional[str]] = {
        "table": None,
        "id_col": None,
        "pain_col": None,
        "score_col": None,
        "status_col": None,
        "updated_col": None,
    }

    if not callable(_get_connection):
        _SOLUTION_SCHEMA_CACHE = schema
        return schema

    conn = None
    try:
        conn = _get_connection()  # type: ignore[misc]
        tables = _list_tables(conn)
        lower = {t.lower(): t for t in tables}

        # Preferred canonical name; otherwise anything that looks like a solutions table.
        table = (
            lower.get("solution_design")
            or lower.get("solutions")
            or lower.get("solution")
            or next((t for t in tables if "solution" in t.lower()), None)
        )
        if not table:
            _SOLUTION_SCHEMA_CACHE = schema
            return schema

        cols = _table_columns(conn, table)
        id_col = _pick_first(cols, ["Solution_ID", "solution_id", "id"])
        if id_col is None:
            # Try any column ending in "_id" containing "solution".
            id_col = next(
                (c for c in cols if c.lower().endswith("_id") and "solution" in c.lower()),
                None,
            )

        pain_col = _pick_first(cols, ["Pain_ID", "pain_id"])
        if pain_col is None:
            pain_col = next((c for c in cols if c.lower().endswith("_id") and "pain" in c.lower()), None)

        status_col = _pick_first(
            cols,
            ["Status", "status", "Solution_Status", "solution_status", "Stage", "stage", "State", "state"],
        )

        score_col = _pick_first(cols, ["Score", "score", "Solution_Score", "solution_score", "BestMoves_Score", "bestmoves_score"])
        if score_col is None:
            score_col = next((c for c in cols if "score" in c.lower()), None)

        updated_col = _pick_first(cols, ["Last_Updated", "last_updated", "Updated_At", "updated_at"])

        schema.update(
            {
                "table": table,
                "id_col": id_col,
                "pain_col": pain_col,
                "score_col": score_col,
                "status_col": status_col,
                "updated_col": updated_col,
            }
        )
    except Exception as e:
        _log().warning("Failed to resolve solution schema: %s", e)
    finally:
        _safe_close(conn)

    _SOLUTION_SCHEMA_CACHE = schema
    return schema


def _db_create_solution(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create a solution record using best-effort DB introspection."""
    if not callable(_get_connection):
        raise RuntimeError("db_connect.get_connection unavailable")

    schema = _resolve_solution_schema()
    table = schema.get("table")
    id_col = schema.get("id_col")
    if not table or not id_col:
        raise RuntimeError("solution table not found (expected Solution_Design)")

    # Filter payload to known columns.
    conn = None
    try:
        conn = _get_connection()  # type: ignore[misc]
        cols = _table_columns(conn, table)
        rec = {k: v for k, v in payload.items() if k in cols}

        # Ensure ID exists.
        if id_col not in rec or not rec.get(id_col):
            rec[id_col] = payload.get("solution_id") or payload.get("Solution_ID") or _new_id("SOL")

        # If an updated timestamp column exists, set it (UTC ISO).
        updated_col = schema.get("updated_col")
        if updated_col and updated_col in cols and not rec.get(updated_col):
            rec[updated_col] = _utc_now_iso()

        if not rec:
            raise ValueError("No valid fields provided for solution insert.")

        keys = list(rec.keys())
        placeholders = ",".join(["?"] * len(keys))
        col_sql = ",".join([f'"{k}"' for k in keys])

        cur = conn.cursor()
        cur.execute(
            f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})',
            [rec[k] for k in keys],
        )
        conn.commit()

        # Fetch inserted record by ID (best-effort).
        return _db_get_solution(str(rec[id_col]))
    finally:
        _safe_close(conn)


def _db_get_solution(solution_id: str) -> Dict[str, Any]:
    """Fetch a single solution record by ID (DB fallback)."""
    if not callable(_get_connection):
        raise RuntimeError("db_connect.get_connection unavailable")

    schema = _resolve_solution_schema()
    table = schema.get("table")
    id_col = schema.get("id_col")
    if not table or not id_col:
        raise RuntimeError("solution table not found (expected Solution_Design)")

    conn = None
    try:
        conn = _get_connection()  # type: ignore[misc]
        sql = f'SELECT * FROM "{table}" WHERE "{id_col}" = ? LIMIT 1'
        cols, rows = _query_rows(conn, sql, (solution_id,))
        items = _rows_to_dicts(cols, rows)
        if not items:
            raise KeyError("not_found")
        return items[0]
    finally:
        _safe_close(conn)


def _db_list_solutions(limit: int) -> List[Dict[str, Any]]:
    """List solutions (DB fallback)."""
    if not callable(_get_connection):
        raise RuntimeError("db_connect.get_connection unavailable")

    schema = _resolve_solution_schema()
    table = schema.get("table")
    if not table:
        raise RuntimeError("solution table not found (expected Solution_Design)")

    conn = None
    try:
        conn = _get_connection()  # type: ignore[misc]
        # Order by rowid desc as a safe default (works even without timestamps).
        sql = f'SELECT * FROM "{table}" ORDER BY rowid DESC LIMIT ?'
        cols, rows = _query_rows(conn, sql, (int(limit),))
        return _rows_to_dicts(cols, rows)
    finally:
        _safe_close(conn)


def _db_solutions_by_pain(pain_id: str, limit: int) -> List[Dict[str, Any]]:
    """List solutions linked to a specific pain (DB fallback)."""
    if not callable(_get_connection):
        raise RuntimeError("db_connect.get_connection unavailable")

    schema = _resolve_solution_schema()
    table = schema.get("table")
    pain_col = schema.get("pain_col")
    if not table or not pain_col:
        raise RuntimeError("solution table missing pain_id column")

    score_col = schema.get("score_col")
    conn = None
    try:
        conn = _get_connection()  # type: ignore[misc]
        order = f'ORDER BY "{score_col}" DESC' if score_col else "ORDER BY rowid DESC"
        sql = f'SELECT * FROM "{table}" WHERE "{pain_col}" = ? {order} LIMIT ?'
        cols, rows = _query_rows(conn, sql, (pain_id, int(limit)))
        return _rows_to_dicts(cols, rows)
    finally:
        _safe_close(conn)


def _db_top_solutions(limit: int) -> List[Dict[str, Any]]:
    """Return top solutions by score (DB fallback)."""
    if not callable(_get_connection):
        raise RuntimeError("db_connect.get_connection unavailable")

    schema = _resolve_solution_schema()
    table = schema.get("table")
    score_col = schema.get("score_col")
    if not table:
        raise RuntimeError("solution table not found (expected Solution_Design)")

    conn = None
    try:
        conn = _get_connection()  # type: ignore[misc]
        if score_col:
            sql = f'SELECT * FROM "{table}" ORDER BY "{score_col}" DESC LIMIT ?'
            cols, rows = _query_rows(conn, sql, (int(limit),))
            return _rows_to_dicts(cols, rows)
        # No score column: fall back to most recent.
        return _db_list_solutions(limit)
    finally:
        _safe_close(conn)


def _db_update_solution_status(solution_id: str, status: str) -> Dict[str, Any]:
    """Update solution status (DB fallback)."""
    if not callable(_get_connection):
        raise RuntimeError("db_connect.get_connection unavailable")

    schema = _resolve_solution_schema()
    table = schema.get("table")
    id_col = schema.get("id_col")
    status_col = schema.get("status_col")
    if not table or not id_col or not status_col:
        raise RuntimeError("solution table missing status/id columns")

    conn = None
    try:
        conn = _get_connection()  # type: ignore[misc]
        cols = _table_columns(conn, table)
        updated_col = schema.get("updated_col")

        set_parts = [f'"{status_col}" = ?']
        params: List[Any] = [status]

        if updated_col and updated_col in cols:
            set_parts.append(f'"{updated_col}" = ?')
            params.append(_utc_now_iso())

        params.append(solution_id)
        sql = f'UPDATE "{table}" SET {", ".join(set_parts)} WHERE "{id_col}" = ?'

        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        if cur.rowcount == 0:
            raise KeyError("not_found")
        return _db_get_solution(solution_id)
    finally:
        _safe_close(conn)


# ---------------------------------------------------------------------------
# Public operations (prefer persistence layer; fallback to DB)
# ---------------------------------------------------------------------------

def _create_solution(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create a solution via persistence layer or DB fallback."""
    ok, res = _call_persist(
        ["create_solution", "create_solution_record", "insert_solution", "add_solution", "save_solution"],
        payload,
    )
    if ok:
        return res if isinstance(res, dict) else {"result": res}
    # DB fallback
    return _db_create_solution(payload)


def _get_solution(solution_id: str) -> Dict[str, Any]:
    """Fetch a solution via persistence layer or DB fallback."""
    ok, res = _call_persist(
        ["get_solution", "get_solution_by_id", "fetch_solution", "read_solution"],
        solution_id,
    )
    if ok:
        return res if isinstance(res, dict) else {"result": res}
    return _db_get_solution(solution_id)


def _list_solutions(limit: int) -> List[Dict[str, Any]]:
    """List solutions via persistence layer or DB fallback."""
    ok, res = _call_persist(
        ["list_solutions", "get_all_solutions", "list_all_solutions", "fetch_solutions"],
        limit=limit,
    )
    if ok:
        if isinstance(res, list):
            return res[: int(limit)]
        if isinstance(res, dict) and isinstance(res.get("items"), list):
            return res["items"][: int(limit)]
        return [res]  # type: ignore[list-item]
    return _db_list_solutions(limit)


def _solutions_by_pain(pain_id: str, limit: int) -> List[Dict[str, Any]]:
    """List solutions for a pain_id via persistence layer or DB fallback."""
    ok, res = _call_persist(
        ["list_solutions_by_pain", "get_solutions_by_pain", "solutions_by_pain"],
        pain_id,
        limit=limit,
    )
    if ok:
        if isinstance(res, list):
            return res[: int(limit)]
        if isinstance(res, dict) and isinstance(res.get("items"), list):
            return res["items"][: int(limit)]
        return [res]  # type: ignore[list-item]
    return _db_solutions_by_pain(pain_id, limit)


def _top_solutions(limit: int) -> List[Dict[str, Any]]:
    """Top-N solutions by score via persistence layer or DB fallback."""
    # Prefer a dedicated persistence helper if present.
    ok, res = _call_persist(
        ["top_solutions", "get_top_solutions", "list_top_solutions"],
        limit=limit,
    )
    if ok:
        if isinstance(res, list):
            return res[: int(limit)]
        if isinstance(res, dict) and isinstance(res.get("items"), list):
            return res["items"][: int(limit)]
        return [res]  # type: ignore[list-item]

    # Otherwise, list and sort best-effort, then fallback to DB.
    try:
        items = _list_solutions(max(50, int(limit) * 5))

        def _score(x: Dict[str, Any]) -> float:
            for k in ("score", "Score", "solution_score", "Solution_Score", "bestmoves_score", "BestMoves_Score"):
                v = x.get(k)
                if isinstance(v, (int, float)):
                    return float(v)
            return 0.0

        items.sort(key=_score, reverse=True)
        return items[: int(limit)]
    except Exception:
        return _db_top_solutions(limit)


def _update_solution_status(solution_id: str, status: str) -> Dict[str, Any]:
    """Update solution status via persistence layer or DB fallback."""
    ok, res = _call_persist(
        ["update_solution_status", "set_solution_status", "patch_solution_status"],
        solution_id,
        status,
    )
    if ok:
        return res if isinstance(res, dict) else {"result": res}
    return _db_update_solution_status(solution_id, status)


# ---------------------------------------------------------------------------
# FastAPI router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["solutions"])


@router.post("/solutions")
def create_solution(
    payload: Dict[str, Any] = Body(default_factory=dict),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """POST /solutions — create solution record."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    if not isinstance(payload, dict) or not payload:
        return _json(False, error="Request body must be a non-empty JSON object.", status_code=400)
    try:
        created = _create_solution(payload)
        return _json(True, data=created, status_code=201)
    except Exception as e:
        _log().warning("create_solution failed: %s", e)
        return _json(False, error=str(e), status_code=400)


@router.get("/solutions/{solution_id}")
def get_solution(
    solution_id: str = Path(..., min_length=3),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """GET /solutions/{solution_id} — fetch single solution by ID."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    try:
        sol = _get_solution(solution_id)
        return _json(True, data=sol, status_code=200)
    except KeyError:
        return _json(False, error="Solution not found.", status_code=404)
    except Exception as e:
        _log().warning("get_solution failed: %s", e)
        return _json(False, error=str(e), status_code=400)


@router.get("/solutions")
def list_solutions(
    limit: int = Query(default=50, ge=1, le=1000),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """GET /solutions — list all solutions (limit param)."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    try:
        items = _list_solutions(int(limit))
        return _json(True, data=items, status_code=200)
    except Exception as e:
        _log().warning("list_solutions failed: %s", e)
        return _json(False, error=str(e), status_code=400)


@router.get("/solutions/top")
def top_solutions(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """GET /solutions/top — top 5 solutions by score."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    try:
        items = _top_solutions(5)
        return _json(True, data=items, status_code=200)
    except Exception as e:
        _log().warning("top_solutions failed: %s", e)
        return _json(False, error=str(e), status_code=400)


@router.get("/solutions/by-pain/{pain_id}")
def solutions_by_pain(
    pain_id: str = Path(..., min_length=3),
    limit: int = Query(default=100, ge=1, le=1000),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """GET /solutions/by-pain/{pain_id} — solutions linked to a specific pain."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    try:
        items = _solutions_by_pain(pain_id, int(limit))
        return _json(True, data=items, status_code=200)
    except Exception as e:
        _log().warning("solutions_by_pain failed: %s", e)
        return _json(False, error=str(e), status_code=400)


@router.patch("/solutions/{solution_id}/status")
def patch_solution_status(
    solution_id: str = Path(..., min_length=3),
    payload: Dict[str, Any] = Body(default_factory=dict),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """PATCH /solutions/{solution_id}/status — update a solution's status.

    Expected JSON body:
        { "status": "<new_status>" }

    Compatibility:
        Accepts alternative keys: "solution_status", "Status", "Solution_Status".
    """
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard

    if not isinstance(payload, dict):
        return _json(False, error="Request body must be a JSON object.", status_code=400)

    status = (
        payload.get("status")
        or payload.get("solution_status")
        or payload.get("Status")
        or payload.get("Solution_Status")
    )
    if not isinstance(status, str) or not status.strip():
        return _json(False, error="Missing required field: status.", status_code=400)

    try:
        updated = _update_solution_status(solution_id, status.strip())
        return _json(True, data=updated, status_code=200)
    except KeyError:
        return _json(False, error="Solution not found.", status_code=404)
    except Exception as e:
        _log().warning("patch_solution_status failed: %s", e)
        return _json(False, error=str(e), status_code=400)


def create_app() -> FastAPI:
    """Standalone app factory (optional).

    Note:
        In a larger aeOS API deployment, your main app may include multiple routers:
        - api_pain.router
        - api_solutions.router
        - api_predictions.router
        - api_health.router
    """
    app = FastAPI(title="aeOS Solutions API", version="0.1.0")
    app.include_router(router)
    return app


# Uvicorn entrypoint: uvicorn src.api.api_solutions:app --reload
app = create_app()
