"""
ai_connect.py
Ollama connection manager for aeOS Phase 4 (Local AI Layer).

This module provides:
- A small connection manager class (AIConnection)
- Helper functions to ping Ollama and inspect locally available models

All network calls are best-effort and fail gracefully when Ollama is not running.

Stamp: S✅ T✅ L✅ A✅
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

import requests


# --- Config + logging ---------------------------------------------------------

# Phase 4 assumes these exist in src/core/config.py, but we keep small fallbacks
# to allow stand-alone execution during early development and tests.

try:
    # Preferred when repo is executed as a package: `python -m src...`
    from src.core.config import OLLAMA_HOST, OLLAMA_MODEL, AI_TIMEOUT  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    try:
        # Alternate when `src/` is added to PYTHONPATH.
        from core.config import OLLAMA_HOST, OLLAMA_MODEL, AI_TIMEOUT  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover
        OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "deepseek-r1:8b")
        AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "30"))

try:
    from src.core.logger import get_logger  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    try:
        from core.logger import get_logger  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover
        import logging

        def get_logger(name: Optional[str] = None) -> "logging.Logger":
            logging.basicConfig(level=logging.INFO)
            return logging.getLogger(name or __name__)


def _init_logger():
    """Initialize aeOS logger while staying compatible with differing signatures."""
    try:
        return get_logger(__name__)
    except TypeError:  # pragma: no cover
        return get_logger()


log = _init_logger()


# --- HTTP helpers -------------------------------------------------------------


def _normalize_host(host: str) -> str:
    """
    Normalize an Ollama host string.

    - strips trailing slashes
    - ensures a scheme exists (defaults to http://)
    """
    host = (host or "").strip()
    if not host:
        return "http://localhost:11434"
    host = host.rstrip("/")
    if "://" not in host:
        host = f"http://{host}"
    return host


def _build_url(host: str, path: str) -> str:
    """Join host + path safely."""
    host = _normalize_host(host)
    path = path if path.startswith("/") else f"/{path}"
    return f"{host}{path}"


def _safe_request_json(
    session: requests.Session,
    method: str,
    url: str,
    timeout_s: float,
    payload: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[requests.Response], Optional[int]]:
    """
    Perform an HTTP request and return (response, latency_ms).

    Returns (None, None) on request errors (e.g., Ollama not running).
    """
    try:
        start = time.monotonic()
        resp = session.request(method=method, url=url, json=payload, timeout=timeout_s)
        latency_ms = int((time.monotonic() - start) * 1000)
        return resp, latency_ms
    except requests.RequestException as e:
        log.debug("Ollama request failed (%s %s): %s", method, url, e)
        return None, None


# --- Public helper functions --------------------------------------------------


def ping_ollama() -> bool:
    """
    Health check: return True if Ollama responds.

    Uses GET /api/version, which is lightweight and stable across versions.
    """
    host = _normalize_host(str(OLLAMA_HOST))
    timeout_s = float(AI_TIMEOUT)
    url = _build_url(host, "/api/version")
    session = requests.Session()
    try:
        resp, _ = _safe_request_json(session=session, method="GET", url=url, timeout_s=timeout_s)
        if resp is None:
            return False
        return 200 <= resp.status_code < 300
    finally:
        try:
            session.close()
        except Exception:  # pragma: no cover
            pass


def list_available_models() -> List[str]:
    """
    Return a list of locally available model names (tags) in Ollama.

    Returns an empty list if Ollama is unreachable or the response is malformed.
    """
    host = _normalize_host(str(OLLAMA_HOST))
    timeout_s = float(AI_TIMEOUT)
    url = _build_url(host, "/api/tags")
    session = requests.Session()
    try:
        resp, _ = _safe_request_json(session=session, method="GET", url=url, timeout_s=timeout_s)
        if resp is None or not (200 <= resp.status_code < 300):
            return []
        try:
            data = resp.json()
        except ValueError:
            return []
        models = data.get("models", [])
        names: List[str] = []
        if isinstance(models, list):
            for m in models:
                if isinstance(m, dict):
                    name = m.get("name")
                    if isinstance(name, str) and name:
                        names.append(name)
        # Stable output, de-duped.
        return sorted(set(names))
    finally:
        try:
            session.close()
        except Exception:  # pragma: no cover
            pass


def check_model_available(model: str) -> bool:
    """
    Return True if the specified model is available (pulled) in Ollama.

    Strategy:
    1) Prefer POST /api/show (more exact), then
    2) Fall back to scanning GET /api/tags.

    Returns False on errors or if Ollama is unreachable.
    """
    host = _normalize_host(str(OLLAMA_HOST))
    timeout_s = float(AI_TIMEOUT)
    model = (model or "").strip()
    if not model:
        return False
    session = requests.Session()
    try:
        # 1) Exact check
        show_url = _build_url(host, "/api/show")
        resp, _ = _safe_request_json(
            session=session,
            method="POST",
            url=show_url,
            timeout_s=timeout_s,
            payload={"name": model},
        )
        if resp is not None and 200 <= resp.status_code < 300:
            return True
        # 2) Fallback: tags listing
        tags_url = _build_url(host, "/api/tags")
        resp, _ = _safe_request_json(session=session, method="GET", url=tags_url, timeout_s=timeout_s)
        if resp is None or not (200 <= resp.status_code < 300):
            return False
        try:
            data = resp.json()
        except ValueError:
            return False
        models = data.get("models", [])
        if not isinstance(models, list):
            return False
        for m in models:
            if isinstance(m, dict) and m.get("name") == model:
                return True
        return False
    finally:
        try:
            session.close()
        except Exception:  # pragma: no cover
            pass


# --- Connection manager -------------------------------------------------------


class AIConnection:
    """
    Lightweight Ollama connection manager.

    This is intentionally simple: it checks if Ollama is reachable and whether
    the configured model is available, while tracking latency for monitoring.

    Status values:
    - "disconnected": no connect attempt made yet OR explicitly disconnected
    - "down": Ollama unreachable
    - "model_missing": Ollama reachable, but model is not available locally
    - "ready": Ollama reachable and model is available
    """

    def __init__(
        self,
        host: Optional[str] = None,
        model: Optional[str] = None,
        timeout_s: Optional[float] = None,
    ) -> None:
        self.host = _normalize_host(host or str(OLLAMA_HOST))
        self.model = (model or str(OLLAMA_MODEL)).strip()
        self.timeout_s = float(timeout_s if timeout_s is not None else AI_TIMEOUT)
        self._session = requests.Session()
        self._status: str = "disconnected"
        self._latency_ms: Optional[int] = None
        self._last_error: Optional[str] = None

    def connect(self) -> bool:
        """
        Attempt to connect to Ollama and validate configured model.

        Returns:
            True if Ollama is reachable AND model is available.
            False otherwise (status will reflect the failure mode).
        """
        ok, latency_ms = self._ping()
        self._latency_ms = latency_ms
        if not ok:
            self._status = "down"
            self._last_error = "Ollama is unreachable"
            return False
        if not self._check_model_available(self.model):
            self._status = "model_missing"
            self._last_error = f"Model not available in Ollama: {self.model}"
            return False
        self._status = "ready"
        self._last_error = None
        return True

    def disconnect(self) -> None:
        """
        Disconnect and release resources.

        Note: Ollama itself remains running; this only closes the local HTTP session.
        """
        try:
            self._session.close()
        finally:
            self._session = requests.Session()
            self._status = "disconnected"
            self._latency_ms = None
            self._last_error = None

    def status(self) -> Dict[str, Any]:
        """
        Return a status dict for external callers.

        Contract keys:
        - host
        - model
        - status
        - latency_ms
        """
        return {
            "host": self.host,
            "model": self.model,
            "status": self._status,
            "latency_ms": self._latency_ms,
        }

    # --- Internal helpers (instance-scoped) ----------------------------------

    def _ping(self) -> Tuple[bool, Optional[int]]:
        """Instance-scoped ping with latency capture."""
        url = _build_url(self.host, "/api/version")
        resp, latency_ms = _safe_request_json(
            session=self._session,
            method="GET",
            url=url,
            timeout_s=self.timeout_s,
        )
        if resp is None:
            return False, latency_ms
        return (200 <= resp.status_code < 300), latency_ms

    def _check_model_available(self, model: str) -> bool:
        """Instance-scoped model availability check using this connection's host/session."""
        model = (model or "").strip()
        if not model:
            return False
        show_url = _build_url(self.host, "/api/show")
        resp, _ = _safe_request_json(
            session=self._session,
            method="POST",
            url=show_url,
            timeout_s=self.timeout_s,
            payload={"name": model},
        )
        if resp is not None and 200 <= resp.status_code < 300:
            return True
        # Fallback to /api/tags using the same host/session.
        tags_url = _build_url(self.host, "/api/tags")
        resp, _ = _safe_request_json(
            session=self._session,
            method="GET",
            url=tags_url,
            timeout_s=self.timeout_s,
        )
        if resp is None or not (200 <= resp.status_code < 300):
            return False
        try:
            data = resp.json()
        except ValueError:
            return False
        models = data.get("models", [])
        if not isinstance(models, list):
            return False
        for m in models:
            if isinstance(m, dict) and m.get("name") == model:
                return True
        return False


# --- Singleton access ---------------------------------------------------------

_CONNECTION: Optional[AIConnection] = None


def get_ai_connection() -> Dict[str, Any]:
    """
    Get (and lazily initialize) the global AIConnection status dict.

    This is the main entry point for most callers: it will attempt to connect
    on first use and return a stable status payload.

    Returns:
        dict: {host, model, status, latency_ms}
    """
    global _CONNECTION
    if _CONNECTION is None:
        _CONNECTION = AIConnection()
    # Always re-check reachability on call; connection status can change at runtime.
    _CONNECTION.connect()
    return _CONNECTION.status()
