"""
src/api/api_health.py
Stamp: S✅ T✅ L✅ A✅
aeOS Phase 3 — API Layer (Health)
- All endpoints require API key validation via auth.py (validate_api_key()).
- Standard response envelope: {success: bool, data: any, error: str|null}
"""
from __future__ import annotations

import importlib
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, FastAPI, Header, Query
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
            """Fallback logger."""
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

# db_connect is OPTIONAL (used for /health/system).
_db = _lazy_import(["db.db_connect", "src.db.db_connect"])
_get_connection = getattr(_db, "get_connection", None) if _db else None

# portfolio_health_view is OPTIONAL (preferred for portfolio endpoints).
_ph = _lazy_import(
    ["db.portfolio_health_view", "src.db.portfolio_health_view", "portfolio_health_view"]
)

_LOG = None
_START_MONO = time.monotonic()


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
    """UTC now as ISO string."""
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


# --- Portfolio health -------------------------------------------------------

def _get_portfolio_health() -> Dict[str, Any]:
    """Return portfolio health dict (calls get_portfolio_health() if available)."""
    if _ph and hasattr(_ph, "get_portfolio_health"):
        try:
            res = _ph.get_portfolio_health()  # type: ignore[attr-defined]
            return res if isinstance(res, dict) else {"raw": res}
        except Exception as e:
            _log().warning("get_portfolio_health failed: %s", e)
            return {"error": "get_portfolio_health_failed", "detail": str(e)}
    return {}


def _extract_score(health: Dict[str, Any]) -> Optional[float]:
    """Best-effort numeric score extraction."""
    if not isinstance(health, dict):
        return None
    for k in ("health_score", "portfolio_health_score", "score", "overall_score"):
        v = health.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    metrics = health.get("metrics")
    if isinstance(metrics, dict):
        for k in ("health_score", "score", "overall_score"):
            v = metrics.get(k)
            if isinstance(v, (int, float)):
                return float(v)
    return None


def _band(score: Optional[float]) -> str:
    """Score → band label."""
    if score is None:
        return "UNKNOWN"
    if score >= 80:
        return "GREEN"
    if score >= 60:
        return "YELLOW"
    return "RED"


def _summary_line(health: Dict[str, Any], pains: int, solutions: int) -> str:
    """One-line summary string."""
    s = _extract_score(health)
    if isinstance(s, (int, float)):
        base = f"{_band(float(s))} — portfolio score {float(s):.1f}"
    else:
        base = "UNKNOWN — portfolio score unknown"
    return f"{base} | pains={pains} | solutions={solutions}"


def _trend(days: int) -> List[Dict[str, Any]]:
    """Daily health scores for last N days (best-effort)."""
    if _ph:
        fn = getattr(_ph, "get_portfolio_health_trend", None)
        if callable(fn):
            # Support both keyword and positional signatures.
            try:
                out = fn(days=days)
                if isinstance(out, list):
                    return out
            except TypeError:
                try:
                    out = fn(days)
                    if isinstance(out, list):
                        return out
                except Exception:
                    pass
            except Exception:
                pass
    score = float(_extract_score(_get_portfolio_health()) or 0.0)
    today = date.today()
    start = today - timedelta(days=max(0, days - 1))
    return [{"date": (start + timedelta(days=i)).isoformat(), "score": score} for i in range(days)]


# --- System status ----------------------------------------------------------

def _db_ping() -> Dict[str, Any]:
    """DB connectivity check (best-effort)."""
    if not callable(_get_connection):
        return {"ok": False, "error": "db_connect.get_connection unavailable"}
    conn = None
    try:
        conn = _get_connection()  # type: ignore[misc]
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _count_table(cur: Any, table: Optional[str]) -> int:
    """Return COUNT(*) for a table name using an existing cursor (0 on failure)."""
    if not table:
        return 0
    try:
        cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


def _counts() -> Tuple[int, int]:
    """(total_pain_points, total_solutions) via sqlite introspection (best-effort)."""
    if not callable(_get_connection):
        return (0, 0)
    conn = None
    try:
        conn = _get_connection()  # type: ignore[misc]
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        names = [str(r[0]) for r in (cur.fetchall() or []) if r and r[0]]
        lower = {n.lower(): n for n in names}
        # Prefer known schema names; otherwise match by substring.
        pain_table = lower.get("pain_point_register") or next(
            (n for n in names if "pain" in n.lower()), None
        )
        sol_table = lower.get("solution_design") or next(
            (n for n in names if "solution" in n.lower()), None
        )
        return (_count_table(cur, pain_table), _count_table(cur, sol_table))
    except Exception:
        return (0, 0)
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _kb_status() -> Dict[str, Any]:
    """KB connectivity check (best-effort)."""
    kb = _lazy_import(["kb.kb_connect", "src.kb.kb_connect", "kb_connect"])
    if not kb:
        return {"ok": False, "error": "KB module unavailable"}
    KBConnection = getattr(kb, "KBConnection", None)
    list_collections = getattr(kb, "list_collections", None)
    if not callable(KBConnection) or not callable(list_collections):
        return {"ok": False, "error": "KB module missing KBConnection/list_collections"}
    try:
        c = KBConnection()  # type: ignore[call-arg]
        c.connect()  # type: ignore[attr-defined]
        cols = list_collections(c)  # type: ignore[misc]
        c.disconnect()  # type: ignore[attr-defined]
        return {"ok": True, "collections": cols}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --- FastAPI router ---------------------------------------------------------

router = APIRouter(tags=["health"])


@router.get("/health")
def health(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """GET /health — alive check."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    return _json(
        True,
        data={"alive": True, "timestamp_utc": _utc_now_iso(), "uptime_seconds": _uptime_seconds()},
        status_code=200,
    )


@router.get("/health/portfolio")
def health_portfolio(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """GET /health/portfolio — portfolio health dict."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    return _json(True, data=_get_portfolio_health(), status_code=200)


@router.get("/health/summary")
def health_summary(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """GET /health/summary — one-line health summary."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    pains, sols = _counts()
    return _json(True, data=_summary_line(_get_portfolio_health(), pains, sols), status_code=200)


@router.get("/health/trend")
def health_trend(
    days: int = Query(default=30, ge=1, le=365),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """GET /health/trend — daily health scores."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    return _json(True, data=_trend(int(days)), status_code=200)


@router.get("/health/system")
def health_system(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """GET /health/system — db/kb status, totals, uptime."""
    guard = _auth_guard(x_api_key, authorization)
    if guard:
        return guard
    pains, sols = _counts()
    payload = {
        "db_status": _db_ping(),
        "kb_status": _kb_status(),
        "total_pain_points": int(pains),
        "total_solutions": int(sols),
        "uptime_seconds": _uptime_seconds(),
    }
    return _json(True, data=payload, status_code=200)


def create_app() -> FastAPI:
    """Standalone app factory (optional)."""
    app = FastAPI(title="aeOS Health API", version="0.1.0")
    app.include_router(router)
    return app


# Uvicorn entrypoint: uvicorn src.api.api_health:app --reload
app = create_app()
