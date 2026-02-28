"""src/api/api_pain.py
Stamp: S✅ T✅ L✅ A✅
aeOS Phase 3 — API Layer (Pain)
Purpose
-------
Expose REST endpoints for Pain Point operations backed by the Phase 2
persistence layer (`pain_persist.py`).
Endpoints (by requirement)
--------------------------
- POST   /pain                  -> create new pain point (save_pain_record)
- GET    /pain/{pain_id}        -> fetch single record (load_pain_record)
- GET    /pain                  -> list all (list_pain_records) [limit param, default 50]
- PATCH  /pain/{pain_id}/status -> update status (update_pain_status)
- GET    /pain/critical         -> pain points with score > 70
Security
--------
All endpoints require API key validation via `auth.py` (validate_api_key()).
The API validates the caller-provided key against a stored hash resolved from:
- AEOS_API_KEY_HASH (preferred; SHA-256 hex digest)
- AEOS_API_KEY      (raw key; hashed at startup using auth.hash_key())
Response Envelope
-----------------
Every endpoint returns the standard envelope:
  { "success": bool, "data": any, "error": str | null }
"""
from __future__ import annotations

import importlib
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, FastAPI, Header, Query
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
            """Fallback logger if aeOS logger.py is unavailable."""
            logging.basicConfig(level=logging.INFO)
            return logging.getLogger(name)


def _lazy_import(paths: List[str]) -> Optional[Any]:
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

# pain_persist is REQUIRED by spec.
_persist = _lazy_import(["db.pain_persist", "src.db.pain_persist", "pain_persist"])
if _persist is None:  # pragma: no cover
    raise ImportError(
        "pain_persist.py not found (expected db.pain_persist / src.db.pain_persist / pain_persist)."
    )
_save_pain_record = getattr(_persist, "save_pain_record", None)
_load_pain_record = getattr(_persist, "load_pain_record", None)
_list_pain_records = getattr(_persist, "list_pain_records", None)
_update_pain_status = getattr(_persist, "update_pain_status", None)
_missing = [
    name
    for name, fn in [
        ("save_pain_record", _save_pain_record),
        ("load_pain_record", _load_pain_record),
        ("list_pain_records", _list_pain_records),
        ("update_pain_status", _update_pain_status),
    ]
    if not callable(fn)
]
if _missing:  # pragma: no cover
    raise ImportError(f"pain_persist.py missing required callables: {', '.join(_missing)}")

# --- Process globals --------------------------------------------------------

_LOG = None


def _log():
    """Lazy-init logger (supports get_logger(name) and get_logger())."""
    global _LOG
    if _LOG is None:
        try:
            _LOG = get_logger(__name__)  # type: ignore[arg-type]
        except TypeError:  # pragma: no cover
            _LOG = get_logger()  # type: ignore[call-arg]
    return _LOG


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


# --- Persistence call wrappers ---------------------------------------------

def _call_save_pain(record: Dict[str, Any]) -> Any:
    """Call save_pain_record() with flexible signature support."""
    fn = _save_pain_record  # type: ignore[assignment]
    # Most common: save_pain_record(record_dict)
    try:
        return fn(record)  # type: ignore[misc]
    except TypeError:
        pass
    # Common keyword names.
    for kw in ("record", "pain_record", "payload", "data"):
        try:
            return fn(**{kw: record})  # type: ignore[misc]
        except TypeError:
            continue
    # Last resort: treat record keys as kwargs.
    return fn(**record)  # type: ignore[misc]


def _call_load_pain(pain_id: str) -> Any:
    """Call load_pain_record() with flexible signature support."""
    fn = _load_pain_record  # type: ignore[assignment]
    try:
        return fn(pain_id)  # type: ignore[misc]
    except TypeError:
        pass
    for kw in ("pain_id", "id", "record_id"):
        try:
            return fn(**{kw: pain_id})  # type: ignore[misc]
        except TypeError:
            continue
    return fn(pain_id=pain_id)  # type: ignore[misc]


def _call_list_pains(limit: Optional[int]) -> Any:
    """Call list_pain_records() with flexible signature support."""
    fn = _list_pain_records  # type: ignore[assignment]
    if limit is None:
        try:
            return fn()  # type: ignore[misc]
        except TypeError:
            return fn(limit=50)  # type: ignore[misc]
    try:
        return fn(limit=limit)  # type: ignore[misc]
    except TypeError:
        # Some implementations use positional args (limit).
        return fn(limit)  # type: ignore[misc]


def _call_update_status(pain_id: str, status: str) -> Any:
    """Call update_pain_status() with flexible signature support."""
    fn = _update_pain_status  # type: ignore[assignment]
    try:
        return fn(pain_id, status)  # type: ignore[misc]
    except TypeError:
        pass
    for kw1 in ("pain_id", "id", "record_id"):
        for kw2 in ("status", "new_status"):
            try:
                return fn(**{kw1: pain_id, kw2: status})  # type: ignore[misc]
            except TypeError:
                continue
    return fn(pain_id=pain_id, status=status)  # type: ignore[misc]


# --- Helpers ----------------------------------------------------------------

def _extract_pain_score(rec: Any) -> Optional[float]:
    """Best-effort extraction of a numeric pain score from a record."""
    if not isinstance(rec, dict):
        return None
    for k in ("pain_score", "Pain_Score", "painScore", "score", "PainScore", "PainScorePct"):
        v = rec.get(k)
        if isinstance(v, (int, float)):
            return float(v)
        # Some stores may persist numeric strings.
        if isinstance(v, str) and v.strip():
            try:
                return float(v.strip())
            except Exception:
                continue
    return None


def _critical_only(records: List[Any], threshold: float = 70.0) -> List[Any]:
    """Filter records to those with pain_score > threshold."""
    out: List[Any] = []
    for r in records:
        s = _extract_pain_score(r)
        if isinstance(s, (int, float)) and float(s) > float(threshold):
            out.append(r)
    return out


def _normalize_list(x: Any) -> List[Any]:
    """Normalize various persistence return shapes into a list."""
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, tuple):
        return list(x)
    # Some persistence layers return {"records": [...]} / {"items": [...]}.
    if isinstance(x, dict):
        for k in ("records", "items", "rows", "data"):
            v = x.get(k)
            if isinstance(v, list):
                return v
    return [x]


# --- FastAPI router ---------------------------------------------------------

router = APIRouter(tags=["pain"])


@router.get("/pain/critical")
def list_critical_pains(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """GET /pain/critical — return only pain points with score > 70."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    try:
        # Fetch "enough" records to make the critical filter meaningful.
        pains = _normalize_list(_call_list_pains(limit=10_000))
        critical = _critical_only(pains, threshold=70.0)
        return _json(True, data=critical, status_code=200)
    except Exception as e:
        _log().exception("Failed to list critical pains: %s", e)
        return _json(False, error=str(e), status_code=500)


@router.post("/pain")
def create_pain(
    payload: Dict[str, Any] = Body(..., description="Pain record fields."),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """POST /pain — create a new pain point via save_pain_record()."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    if not isinstance(payload, dict):
        return _json(False, error="Invalid JSON body; expected an object.", status_code=400)
    try:
        created = _call_save_pain(payload)
        return _json(True, data=created, status_code=201)
    except Exception as e:
        _log().exception("Failed to create pain: %s", e)
        return _json(False, error=str(e), status_code=500)


@router.get("/pain")
def list_pains(
    limit: int = Query(default=50, ge=1, le=1000),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """GET /pain — list pain points via list_pain_records()."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    try:
        rows = _call_list_pains(limit=int(limit))
        return _json(True, data=_normalize_list(rows), status_code=200)
    except Exception as e:
        _log().exception("Failed to list pains: %s", e)
        return _json(False, error=str(e), status_code=500)


@router.patch("/pain/{pain_id}/status")
def patch_pain_status(
    pain_id: str,
    payload: Dict[str, Any] = Body(..., description="{'status': '<new_status>'}"),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """PATCH /pain/{pain_id}/status — update status via update_pain_status()."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    status = ""
    if isinstance(payload, dict):
        status = str(payload.get("status") or "").strip()
    if not status:
        return _json(False, error="Missing required field: status", status_code=400)
    try:
        res = _call_update_status(pain_id, status)
        if res is None or res is False:
            return _json(False, error="Pain record not found.", status_code=404)
        return _json(True, data=res, status_code=200)
    except Exception as e:
        _log().exception("Failed to update pain status: %s", e)
        return _json(False, error=str(e), status_code=500)


@router.get("/pain/{pain_id}")
def get_pain(
    pain_id: str,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """GET /pain/{pain_id} — fetch a single pain point via load_pain_record()."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    try:
        rec = _call_load_pain(pain_id)
        if rec is None:
            return _json(False, error="Pain record not found.", status_code=404)
        return _json(True, data=rec, status_code=200)
    except Exception as e:
        _log().exception("Failed to load pain '%s': %s", pain_id, e)
        return _json(False, error=str(e), status_code=500)


def create_app() -> FastAPI:
    """Standalone FastAPI app factory (optional)."""
    app = FastAPI(title="aeOS Pain API", version="0.1.0")
    app.include_router(router)
    return app


# Uvicorn entrypoint: uvicorn src.api.api_pain:app --reload
app = create_app()
