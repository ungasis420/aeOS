"""tests/test_api_health.py
Stamp: S✅ T✅ L✅ A✅
aeOS Phase 3 — Tests
Unit tests for the Health API endpoints implemented in src/api/api_health.py.
Requirements covered:
- FastAPI TestClient usage
- Auth: valid key → 200, invalid/missing key → 401
- Endpoint contracts:
  - GET /health              -> 200 + envelope
  - GET /health/portfolio     -> data is dict
  - GET /health/summary       -> data is string
  - GET /health/trend         -> data is list
  - GET /health/system        -> data is dict with expected keys
Notes:
- api_health.py resolves the stored API key hash at import time from env vars.
  These tests set AEOS_API_KEY before importing/reloading the module.
- Tests avoid DB/KB dependencies by monkeypatching optional integrations to None.
"""
from __future__ import annotations

import importlib
import os
import sys
import unittest
from typing import Any, Dict, Optional

from fastapi.testclient import TestClient


def _project_root() -> str:
    """Return repo root inferred from this file location."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def _ensure_sys_path() -> None:
    """Ensure repo root and ./src are on sys.path for imports."""
    root = _project_root()
    src = os.path.join(root, "src")
    for p in (root, src):
        if p not in sys.path:
            sys.path.insert(0, p)


def _import_first(module_names) -> Any:
    """Import and return the first importable module from a list of names."""
    last_err: Optional[Exception] = None
    for name in module_names:
        try:
            return importlib.import_module(name)
        except Exception as e:  # pragma: no cover - best-effort import probing
            last_err = e
            continue
    raise ImportError(f"Could not import any module from: {module_names}. Last error: {last_err}")


def _load_api_health_module() -> Any:
    """Import api_health with best-effort paths across possible layouts."""
    _ensure_sys_path()
    return _import_first(["src.api.api_health", "api.api_health", "api_health"])


class TestAPIHealth(unittest.TestCase):
    """Unit tests for aeOS Health API endpoints."""

    TEST_API_KEY = "unit-test-api-key"

    @classmethod
    def setUpClass(cls) -> None:
        # Preserve original env to avoid polluting the caller's environment.
        cls._orig_env = {
            "AEOS_API_KEY": os.environ.get("AEOS_API_KEY"),
            "AEOS_API_KEY_HASH": os.environ.get("AEOS_API_KEY_HASH"),
        }

        # Configure the API to accept TEST_API_KEY.
        os.environ["AEOS_API_KEY"] = cls.TEST_API_KEY
        os.environ.pop("AEOS_API_KEY_HASH", None)

        # Import + reload so api_health.py re-resolves _STORED_HASH from env.
        mod = _load_api_health_module()
        cls.api_health = importlib.reload(mod)

        # Make tests deterministic by disabling optional integrations.
        # - DB introspection becomes a harmless default (counts=0, db_status.ok=False).
        # - Portfolio health view falls back to {} / fixed-score trend generation.
        setattr(cls.api_health, "_get_connection", None)
        setattr(cls.api_health, "_ph", None)

        # Create an app instance for TestClient.
        app_factory = getattr(cls.api_health, "create_app", None)
        if callable(app_factory):
            cls.app = cls.api_health.create_app()
        else:
            cls.app = getattr(cls.api_health, "app")

        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls) -> None:
        # Restore original env vars.
        for k, v in cls._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------

    def _auth_headers(self, *, key: Optional[str] = None) -> Dict[str, str]:
        """Return headers using X-API-Key."""
        return {"X-API-Key": (key or self.TEST_API_KEY)}

    # ---------------------------------------------------------------------
    # Required tests
    # ---------------------------------------------------------------------

    def test_health_check_returns_200(self) -> None:
        r = self.client.get("/health", headers=self._auth_headers())
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body.get("success"))
        self.assertIsInstance(body.get("data"), dict)
        self.assertTrue(body["data"].get("alive"))

    def test_portfolio_health_returns_dict(self) -> None:
        r = self.client.get("/health/portfolio", headers=self._auth_headers())
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body.get("success"))
        self.assertIsInstance(body.get("data"), dict)

    def test_health_summary_returns_string(self) -> None:
        r = self.client.get("/health/summary", headers=self._auth_headers())
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body.get("success"))
        self.assertIsInstance(body.get("data"), str)
        self.assertGreater(len(body.get("data") or ""), 0)

    def test_invalid_api_key_returns_401(self) -> None:
        r = self.client.get("/health", headers=self._auth_headers(key="wrong-key"))
        self.assertEqual(r.status_code, 401)
        body = r.json()
        self.assertFalse(body.get("success"))
        self.assertIsInstance(body.get("error"), str)

    def test_missing_api_key_returns_401(self) -> None:
        r = self.client.get("/health")  # no X-API-Key and no Authorization header
        self.assertEqual(r.status_code, 401)
        body = r.json()
        self.assertFalse(body.get("success"))
        self.assertIsInstance(body.get("error"), str)

    def test_health_trend_returns_list(self) -> None:
        r = self.client.get("/health/trend?days=7", headers=self._auth_headers())
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body.get("success"))
        data = body.get("data")
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 7)
        # Each entry should be a dict containing at least date + score (fallback shape).
        for row in data:
            self.assertIsInstance(row, dict)
            self.assertIn("date", row)
            self.assertIn("score", row)

    # ---------------------------------------------------------------------
    # Additional tests (to reach >= 8 cases + improve coverage)
    # ---------------------------------------------------------------------

    def test_health_system_returns_dict(self) -> None:
        r = self.client.get("/health/system", headers=self._auth_headers())
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body.get("success"))
        data = body.get("data")
        self.assertIsInstance(data, dict)
        # Contract keys (per api_health.py)
        for k in ("db_status", "kb_status", "total_pain_points", "total_solutions", "uptime_seconds"):
            self.assertIn(k, data)
        self.assertIsInstance(data.get("db_status"), dict)
        self.assertIsInstance(data.get("kb_status"), dict)
        self.assertIsInstance(data.get("total_pain_points"), int)
        self.assertIsInstance(data.get("total_solutions"), int)
        self.assertIsInstance(data.get("uptime_seconds"), int)

    def test_authorization_bearer_header_works(self) -> None:
        r = self.client.get("/health", headers={"Authorization": f"Bearer {self.TEST_API_KEY}"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body.get("success"))

    def test_response_envelope_has_expected_keys(self) -> None:
        r = self.client.get("/health", headers=self._auth_headers())
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for k in ("success", "data", "error"):
            self.assertIn(k, body)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
