"""
tests/test_persist_pain.py
Stamp: S✅ T✅ L✅ A✅
aeOS Phase 3 — Tests
Unit tests for the pain persistence layer (pain_persist.py).
Requirements covered:
- setUp creates /tmp/test_aeos.db and runs db/aeOS_PERSIST_v1.0.sql
- tearDown removes temp DB
- ≥8 tests (includes required cases)
Constraints:
- stdlib imports ONLY: unittest, tempfile, os
"""
import os
import tempfile
import unittest

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

# Required by prompt (explicit path).
TEST_DB_PATH = "/tmp/test_aeos.db"

# Env vars commonly used to override DB location across aeOS modules.
_ENV_DB_KEYS = (
    "AEOS_DB_PATH",
    "DB_PATH",
    "SQLITE_DB_PATH",
    "AEOS_SQLITE_PATH",
    "AEOS_DB_FILE",
)


# -----------------------------------------------------------------------------
# Helpers (no additional stdlib imports)
# -----------------------------------------------------------------------------


def _project_root() -> str:
    """Repo root derived from this file location: tests/ -> repo root."""
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))


def _schema_sql_path() -> str:
    """Absolute path to db/aeOS_PERSIST_v1.0.sql."""
    return os.path.join(_project_root(), "db", "aeOS_PERSIST_v1.0.sql")


def _import_first(module_names):
    """Return first importable module from a list, else None."""
    for name in module_names:
        try:
            return __import__(name, fromlist=["*"])
        except Exception:
            continue
    return None


def _set_env_db_path(db_path: str) -> dict:
    """Set env overrides to db_path; return previous values for restore."""
    old = {}
    for k in _ENV_DB_KEYS:
        old[k] = os.environ.get(k)
        os.environ[k] = db_path
    return old


def _restore_env(old: dict) -> None:
    """Restore env values previously returned by _set_env_db_path()."""
    for k, v in (old or {}).items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _patch_db_path_attrs(mod, db_path: str) -> None:
    """Best-effort: patch common DB path attributes on a module."""
    if mod is None:
        return
    for attr in ("DB_PATH", "SQLITE_DB_PATH", "AEOS_DB_PATH", "DB_FILE", "DB", "DB_FILENAME"):
        if hasattr(mod, attr):
            try:
                setattr(mod, attr, db_path)
            except Exception:
                pass


def _get_connection(db_connect_mod, db_path: str):
    """Return sqlite connection to db_path via db_connect.get_connection()."""
    if db_connect_mod is None:
        raise RuntimeError("db_connect module not found")
    fn = getattr(db_connect_mod, "get_connection", None)
    if not callable(fn):
        raise RuntimeError("db_connect.get_connection() not found")
    # Try common signatures across branch states.
    for call in (
        lambda: fn(db_path),  # positional
        lambda: fn(db_path=db_path),
        lambda: fn(path=db_path),
        lambda: fn(database=db_path),
        lambda: fn(filepath=db_path),
    ):
        try:
            return call()
        except TypeError:
            continue
    # Fallback: patch attrs + no-arg call.
    _patch_db_path_attrs(db_connect_mod, db_path)
    cfg = _import_first(["core.config", "src.core.config", "config"])
    _patch_db_path_attrs(cfg, db_path)
    return fn()


def _assert_test_db_connection(testcase: unittest.TestCase, conn) -> None:
    """Guardrail: ensure we are connected to the test DB (avoid mutating real DB)."""
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA database_list;")
        rows = cur.fetchall() or []
    except Exception as e:
        testcase.fail(f"Could not inspect sqlite connection (PRAGMA database_list): {e}")
        return

    want_base = os.path.basename(TEST_DB_PATH)
    for r in rows:
        try:
            p = r[2]
        except Exception:
            continue
        if isinstance(p, str) and os.path.basename(p) == want_base:
            return
    testcase.fail("db_connect.get_connection() does not appear to target /tmp/test_aeos.db")


def _run_schema(conn) -> None:
    """Load and execute the full schema SQL against conn."""
    sql_path = _schema_sql_path()
    if not os.path.isfile(sql_path):
        raise FileNotFoundError(sql_path)
    with open(sql_path, "r", encoding="utf-8", errors="replace") as f:
        sql = f.read()
    if not sql.strip():
        raise ValueError("Schema SQL file is empty.")
    # Enable FK constraints (common in aeOS schema).
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
    except Exception:
        pass
    if hasattr(conn, "executescript"):
        conn.executescript(sql)
    else:  # pragma: no cover
        conn.execute(sql)
    try:
        conn.commit()
    except Exception:
        pass


def _normalize_records(res):
    """Normalize persistence return shapes into a list."""
    if res is None:
        return []
    if isinstance(res, list):
        return res
    if isinstance(res, tuple):
        return list(res)
    if isinstance(res, dict):
        for k in ("records", "items", "rows", "data"):
            v = res.get(k)
            if isinstance(v, list):
                return v
        return [res]
    return [res]


def _extract_pain_id(obj) -> str:
    """Extract pain_id from common return shapes."""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj.strip()
    if isinstance(obj, dict):
        for k in ("Pain_ID", "pain_id", "PainId", "id", "ID"):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    if isinstance(obj, (list, tuple)):
        for item in obj:
            pid = _extract_pain_id(item)
            if pid:
                return pid
    return ""


def _extract_status(rec) -> str:
    """Extract status from record dict (schema-variant tolerant)."""
    if not isinstance(rec, dict):
        return ""
    for k in ("Status", "status", "Pain_Status", "pain_status", "State", "state", "Stage", "stage"):
        v = rec.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def _valid_pain_payload(tag: str = "") -> dict:
    """Payload designed to satisfy strict schema validation (plus common aliases)."""
    desc = "This is a unit test pain description with enough length to pass validation."
    if tag:
        desc = f"{desc} [{tag}]"
    return {
        # Canonical-ish schema keys (Blueprint A.2 style)
        "Pain_Name": f"Unit Test Pain {tag}".strip(),
        "Description": desc,
        "Root_Cause": "Unit test",
        "Affected_Population": "Unit tests",
        "Frequency": "Daily",
        "Severity": 7,
        "Impact_Score": 6,
        "Monetizability_Flag": 0,
        "WTP_Estimate": 0,
        "Evidence": "unit test evidence",
        "Linked_Idea_IDs": "",
        "Phase_Created": "0",
        # Always-valid historic date
        "Date_Identified": "2000-01-01",
        "Status": "Active",
        # Common alternate keys (some branches / CLIs)
        "description": desc,
        "severity": 7,
        "urgency": 6,
        "frequency": 9,
        "category": "Test",
    }


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------


class TestPainPersist(unittest.TestCase):
    """Unit tests for pain_persist.py CRUD behavior."""

    def setUp(self) -> None:
        """Create fresh /tmp/test_aeos.db and load the full schema."""
        self.db_path = TEST_DB_PATH

        # Ensure /tmp exists in portable environments.
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        except Exception:
            pass

        # Reset DB file.
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
        except Exception:
            pass

        # Touch file (some connectors expect it to exist).
        try:
            with open(self.db_path, "a", encoding="utf-8"):
                pass
        except Exception:
            pass

        # Force modules to use test DB.
        self._env_old = _set_env_db_path(self.db_path)

        # Import + patch db_connect/config.
        self.cfg = _import_first(["core.config", "src.core.config", "config"])
        _patch_db_path_attrs(self.cfg, self.db_path)

        self.db_connect = _import_first(["db.db_connect", "src.db.db_connect", "db_connect"])
        if self.db_connect is None:
            raise RuntimeError("db_connect.py not found (expected src.db.db_connect / db.db_connect).")
        _patch_db_path_attrs(self.db_connect, self.db_path)

        # Run schema using a real connection from db_connect.
        conn = _get_connection(self.db_connect, self.db_path)
        _assert_test_db_connection(self, conn)
        _run_schema(conn)
        try:
            conn.close()
        except Exception:
            pass

        # Import pain_persist after schema is present.
        self.pain_persist = _import_first(["db.pain_persist", "src.db.pain_persist", "pain_persist"])
        if self.pain_persist is None:
            raise RuntimeError("pain_persist.py not found (expected src.db.pain_persist / db.pain_persist).")

        # If pain_persist imported get_connection directly, patch it to guarantee test DB usage.
        if hasattr(self.pain_persist, "get_connection"):
            try:
                setattr(
                    self.pain_persist,
                    "get_connection",
                    lambda: _get_connection(self.db_connect, self.db_path),
                )
            except Exception:
                pass

    def tearDown(self) -> None:
        """Remove temp DB and restore environment."""
        _restore_env(getattr(self, "_env_old", {}))
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
        except Exception:
            pass

    # -----------------------------
    # Persistence call adapters
    # -----------------------------

    def _save(self, payload: dict):
        """Call save_pain_record() with flexible signature support."""
        fn = getattr(self.pain_persist, "save_pain_record", None)
        self.assertTrue(callable(fn), "pain_persist.save_pain_record missing")
        try:
            return fn(payload)
        except TypeError:
            pass
        for kw in ("record", "pain_record", "payload", "data"):
            try:
                return fn(**{kw: payload})
            except TypeError:
                continue
        return fn(**payload)

    def _load(self, pain_id: str):
        """Call load_pain_record() with flexible signature support."""
        fn = getattr(self.pain_persist, "load_pain_record", None)
        self.assertTrue(callable(fn), "pain_persist.load_pain_record missing")
        try:
            return fn(pain_id)
        except TypeError:
            pass
        for kw in ("pain_id", "id", "record_id"):
            try:
                return fn(**{kw: pain_id})
            except TypeError:
                continue
        return fn(pain_id=pain_id)

    def _list(self, limit=None):
        """Call list_pain_records() with flexible signature support."""
        fn = getattr(self.pain_persist, "list_pain_records", None)
        self.assertTrue(callable(fn), "pain_persist.list_pain_records missing")
        if limit is None:
            try:
                return fn()
            except TypeError:
                return fn(limit=50)
        try:
            return fn(limit=limit)
        except TypeError:
            pass
        try:
            return fn(limit)
        except TypeError:
            return fn()

    def _update_status(self, pain_id: str, status: str):
        """Call update_pain_status() with flexible signature support."""
        fn = getattr(self.pain_persist, "update_pain_status", None)
        self.assertTrue(callable(fn), "pain_persist.update_pain_status missing")
        try:
            return fn(pain_id, status)
        except TypeError:
            pass
        for kw1 in ("pain_id", "id", "record_id"):
            for kw2 in ("status", "new_status"):
                try:
                    return fn(**{kw1: pain_id, kw2: status})
                except TypeError:
                    continue
        return fn(pain_id=pain_id, status=status)

    # -----------------------------
    # Required tests
    # -----------------------------

    def test_save_pain_record_returns_id(self):
        created = self._save(_valid_pain_payload("save_id"))
        pid = _extract_pain_id(created)
        self.assertIsInstance(pid, str)
        self.assertTrue(pid)

    def test_load_pain_record_returns_dict(self):
        pid = _extract_pain_id(self._save(_valid_pain_payload("load_dict")))
        rec = self._load(pid)
        self.assertIsInstance(rec, dict)

    def test_list_pain_records_returns_list(self):
        pid = _extract_pain_id(self._save(_valid_pain_payload("list")))
        records = _normalize_records(self._list(limit=100))
        self.assertIsInstance(records, list)
        self.assertTrue(any(_extract_pain_id(r) == pid for r in records))

    def test_update_pain_status_succeeds(self):
        pid = _extract_pain_id(self._save(_valid_pain_payload("update")))
        res = self._update_status(pid, "Resolved")
        self.assertNotIn(res, (None, False))
        rec = self._load(pid)
        self.assertIsInstance(rec, dict)
        self.assertIn("resolv", _extract_status(rec).lower())

    def test_save_invalid_record_raises_error(self):
        with self.assertRaises(Exception):
            self._save({})

    def test_load_nonexistent_id_returns_none(self):
        rec = self._load("PAIN-19000101-999")
        self.assertIsNone(rec)

    # -----------------------------
    # Extra tests (min 8 total)
    # -----------------------------

    def test_save_two_records_have_unique_ids(self):
        pid1 = _extract_pain_id(self._save(_valid_pain_payload("uniq1")))
        pid2 = _extract_pain_id(self._save(_valid_pain_payload("uniq2")))
        self.assertTrue(pid1 and pid2)
        self.assertNotEqual(pid1, pid2)

    def test_list_contains_two_saved_records(self):
        pid1 = _extract_pain_id(self._save(_valid_pain_payload("m1")))
        pid2 = _extract_pain_id(self._save(_valid_pain_payload("m2")))
        records = _normalize_records(self._list(limit=200))
        ids = set(_extract_pain_id(r) for r in records if _extract_pain_id(r))
        self.assertIn(pid1, ids)
        self.assertIn(pid2, ids)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
