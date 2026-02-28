"""
tests/test_ai_connect.py

Pytest unit tests for `src.ai.ai_connect`.

These tests mock all HTTP calls so they run without Ollama.
Stamp: S✅ T✅ L✅ A✅
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
import requests

# Ensure repo root is importable when running `pytest` from different CWDs.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.ai import ai_connect


def _mk_resp(status_code: int = 200, json_data=None):
    """Small helper to create a mock `requests.Response`-like object."""
    resp = MagicMock()
    resp.status_code = int(status_code)
    resp.json.return_value = json_data if json_data is not None else {}
    return resp


def test_ollama_ping_returns_dict():
    """`get_ai_connection()` should return the stable status dict contract."""
    # Reset the module-level singleton to avoid cross-test leakage.
    ai_connect._CONNECTION = None  # type: ignore[attr-defined]

    def fake_request(self, method, url, json=None, timeout=None, **kwargs):  # noqa: ANN001
        # Provide happy-path responses for all endpoints used by connect().
        if url.endswith("/api/version"):
            return _mk_resp(200, {"version": "0.0.0"})
        if url.endswith("/api/show"):
            # Model exists.
            return _mk_resp(200, {})
        if url.endswith("/api/tags"):
            return _mk_resp(200, {"models": [{"name": str(ai_connect.OLLAMA_MODEL)}]})
        return _mk_resp(404, {})

    # Patch the Session.request used by `_safe_request_json()` across all sessions.
    with patch("src.ai.ai_connect.requests.Session.request", new=fake_request):
        status = ai_connect.get_ai_connection()

    assert isinstance(status, dict)
    for k in ("host", "model", "status", "latency_ms"):
        assert k in status

    # With model available + version OK, connection should be ready.
    assert status["status"] == "ready"
    assert isinstance(status["model"], str) and status["model"].strip()
    assert status["latency_ms"] is None or isinstance(status["latency_ms"], int)


def test_connection_fails_gracefully_when_offline():
    """All helpers should fail gracefully (no exceptions) when Ollama is offline."""
    ai_connect._CONNECTION = None  # type: ignore[attr-defined]

    def raise_conn_err(self, method, url, json=None, timeout=None, **kwargs):  # noqa: ANN001
        raise requests.exceptions.ConnectionError("offline")  # Simulate Ollama not running.

    with patch("src.ai.ai_connect.requests.Session.request", new=raise_conn_err):
        assert ai_connect.ping_ollama() is False
        assert ai_connect.list_available_models() == []
        assert ai_connect.check_model_available("deepseek-r1:8b") is False

        status = ai_connect.get_ai_connection()
        assert isinstance(status, dict)
        assert status.get("status") == "down"


def test_list_models_returns_list():
    """`list_available_models()` should return a stable, de-duped, sorted list."""
    def fake_request(self, method, url, json=None, timeout=None, **kwargs):  # noqa: ANN001
        if url.endswith("/api/tags"):
            return _mk_resp(200, {"models": [{"name": "m1"}, {"name": "m2"}, {"name": "m1"}]})
        return _mk_resp(404, {})

    with patch("src.ai.ai_connect.requests.Session.request", new=fake_request):
        models = ai_connect.list_available_models()

    assert isinstance(models, list)
    assert models == ["m1", "m2"]
