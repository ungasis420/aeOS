"""
tests/test_persist_solutions.py
Stamp: S✅ T✅ L✅ A✅
Unit tests for aeOS persistence layer: solution_persist.py
Constraints:
- Imports limited to: unittest, tempfile, os
- setUp builds a temp SQLite DB with the full schema
- tearDown deletes the temp DB
- Minimum 8 test cases
"""
import os
import tempfile
import unittest


def _import_first(names):
    """Return the first importable module from `names`, else None."""
    for n in names:
        try:
            return __import__(n, fromlist=["*"])
        except Exception:
            continue
    return None


def _repo_root():
    """Repo root path (tests/..)."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def _set_env_db_path(db_path):
    """Set common env vars used to resolve aeOS DB path."""
    p = os.path.abspath(os.path.expanduser(str(db_path)))
    for k in ("AEOS_DB_PATH", "DB_PATH", "SQLITE_DB_PATH", "AEOS_SQLITE_DB_PATH", "AEOS_DB", "AEOS_SQLITE_DB"):
        os.environ[k] = p


def _patch_db_path(db_path):
    """Best-effort patch config/db_connect modules to point at db_path."""
    p = os.path.abspath(os.path.expanduser(str(db_path)))
    for mod in (_import_first(["core.config"]), _import_first(["src.core.config"]), _import_first(["config"])):
        if mod is None:
            continue
        for attr in ("DB_PATH", "SQLITE_DB_PATH", "AEOS_DB_PATH", "DB_FILE", "DB"):
            try:
                setattr(mod, attr, p)
            except Exception:
                pass
    dbc = _import_first(["db.db_connect", "src.db.db_connect", "db_connect"])
    if dbc is None:
        raise ImportError("db_connect.py not found (expected db.db_connect / src.db.db_connect / db_connect).")
    for attr in ("DB_PATH", "SQLITE_DB_PATH", "AEOS_DB_PATH", "DB_FILE", "DB"):
        if hasattr(dbc, attr):
            try:
                setattr(dbc, attr, p)
            except Exception:
                pass
    for fn_name in ("set_db_path", "configure", "set_path", "set_database_path"):
        fn = getattr(dbc, fn_name, None)
        if callable(fn):
            try:
                fn(p)
            except Exception:
                pass
    return dbc


def _get_connection(dbc, db_path):
    """Open a sqlite connection via dbc.get_connection() (signature-flexible)."""
    fn = getattr(dbc, "get_connection", None)
    if not callable(fn):
        raise ImportError("db_connect.get_connection() not found.")
    try:
        return fn()
    except TypeError:
        pass
    for call in (lambda: fn(db_path), lambda: fn(path=db_path), lambda: fn(db_path=db_path), lambda: fn(database=db_path)):
        try:
            return call()
        except TypeError:
            continue
    raise TypeError("db_connect.get_connection() signature not supported by tests.")


def _ensure_schema(conn, db_path):
    """Initialize full schema using db_init; fall back to executing schema SQL."""
    dbi = _import_first(["db.db_init", "src.db.db_init", "db_init"])
    if dbi is not None:
        for fn_name in ("init_db", "initialize_db", "init_database", "create_schema", "ensure_schema", "bootstrap_db", "init"):
            fn = getattr(dbi, fn_name, None)
            if not callable(fn):
                continue
            for call in (lambda: fn(db_path), lambda: fn(path=db_path), lambda: fn(db_path=db_path), lambda: fn(database_path=db_path), lambda: fn()):
                try:
                    call()
                    conn.commit()
                    return
                except TypeError:
                    continue
                except Exception:
                    break  # fall back to raw SQL
    root = _repo_root()
    candidates = (
        os.path.join(root, "db", "aeOS_PERSIST_v1.0.sql"),
        os.path.join(root, "db", "aeOS_PERSIST.sql"),
        os.path.join(root, "db", "schema.sql"),
    )
    sql_path = next((p for p in candidates if os.path.isfile(p)), "")
    if not sql_path:
        raise FileNotFoundError("Schema SQL not found (expected db/aeOS_PERSIST_v1.0.sql).")
    with open(sql_path, "r", encoding="utf-8", errors="replace") as f:
        sql = f.read()
    if hasattr(conn, "executescript"):
        conn.executescript(sql)
    else:
        cur = conn.cursor()
        for stmt in sql.split(";"):
            s = stmt.strip()
            if s:
                cur.execute(s)
    conn.commit()


def _list_tables(conn):
    """List user tables in sqlite."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return [str(r[0]) for r in (cur.fetchall() or []) if r and r[0]]


def _table_columns(conn, table):
    """List column names for `table`."""
    cur = conn.cursor()
    cur.execute(f'PRAGMA table_info("{table}")')
    return [str(r[1]) for r in (cur.fetchall() or []) if r and len(r) > 1 and r[1]]


def _pick_ci(existing, candidates):
    """Pick first candidate present in existing (case-insensitive)."""
    m = {str(x).lower(): str(x) for x in (existing or [])}
    for cand in candidates:
        hit = m.get(str(cand).lower())
        if hit:
            return hit
    return None


def _pick_table(tables, preferred, token):
    """Pick table by preferred names; else substring match."""
    lower = {str(t).lower(): str(t) for t in (tables or [])}
    for p in preferred:
        hit = lower.get(str(p).lower())
        if hit:
            return hit
    tok = str(token or "").lower()
    for t in (tables or []):
        if tok and tok in str(t).lower():
            return str(t)
    return ""


def _normalize_list(x):
    """Normalize common persistence return shapes into a list."""
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, tuple):
        return list(x)
    if isinstance(x, dict):
        for k in ("items", "records", "rows", "data"):
            v = x.get(k)
            if isinstance(v, list):
                return v
    return [x]


def _extract_str(d, keys):
    """Extract first non-empty string from dict d for any key in keys."""
    if not isinstance(d, dict):
        return ""
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _extract_num(d, keys):
    """Extract first numeric value from dict d for any key in keys; else None."""
    if not isinstance(d, dict):
        return None
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v.strip():
            try:
                return float(v.strip())
            except Exception:
                continue
    return None


def _extract_solution_id(obj):
    """Extract solution_id from common shapes."""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj.strip()
    if isinstance(obj, dict):
        return _extract_str(obj, ("solution_id", "Solution_ID", "id", "ID"))
    if isinstance(obj, (list, tuple)):
        for it in obj:
            sid = _extract_solution_id(it)
            if sid:
                return sid
    return ""


def _solution_persist():
    """Load solution_persist module."""
    sp = _import_first(["db.solution_persist", "src.db.solution_persist", "solution_persist"])
    if sp is None:
        raise ImportError("solution_persist.py not found.")
    return sp


def _call_create_solution(sp, payload):
    """Call solution create/save entrypoint with signature fallbacks."""
    for name in ("create_solution", "create_solution_record", "insert_solution", "add_solution", "save_solution", "save_solution_record"):
        fn = getattr(sp, name, None)
        if not callable(fn):
            continue
        try:
            return fn(payload)
        except TypeError:
            pass
        for kw in ("record", "solution_record", "payload", "data"):
            try:
                return fn(**{kw: payload})
            except TypeError:
                continue
        return fn(**payload)
    raise AttributeError("No create/save function found in solution_persist.")


def _call_get_solution(sp, solution_id):
    """Call solution read/load entrypoint with signature fallbacks."""
    for name in ("get_solution", "get_solution_by_id", "fetch_solution", "read_solution", "load_solution_record"):
        fn = getattr(sp, name, None)
        if not callable(fn):
            continue
        try:
            return fn(solution_id)
        except TypeError:
            pass
        for kw in ("solution_id", "id", "record_id"):
            try:
                return fn(**{kw: solution_id})
            except TypeError:
                continue
        return fn(solution_id=solution_id)
    raise AttributeError("No get/load function found in solution_persist.")


def _call_list_solutions(sp, limit):
    """Call solution list entrypoint with signature fallbacks."""
    for name in ("list_solutions", "get_all_solutions", "list_all_solutions", "fetch_solutions"):
        fn = getattr(sp, name, None)
        if not callable(fn):
            continue
        for call in (lambda: fn(limit=limit), lambda: fn(limit), lambda: fn()):
            try:
                return call()
            except TypeError:
                continue
        raise TypeError("list_solutions signature not supported by tests.")
    raise AttributeError("No list function found in solution_persist.")


def _call_top_solutions(sp, n):
    """Call top solutions entrypoint with signature fallbacks."""
    for name in ("top_solutions", "get_top_solutions", "list_top_solutions", "best_solutions"):
        fn = getattr(sp, name, None)
        if not callable(fn):
            continue
        for call in (lambda: fn(n), lambda: fn(limit=n)):
            try:
                return call()
            except TypeError:
                continue
        raise TypeError("get_top_solutions signature not supported by tests.")
    raise AttributeError("No top_solutions function found in solution_persist.")


def _call_link_solution_to_pain(sp, solution_id, pain_id):
    """Call link_solution_to_pain entrypoint with signature fallbacks."""
    for name in ("link_solution_to_pain", "set_solution_pain", "attach_solution_to_pain", "update_solution_pain", "link_to_pain"):
        fn = getattr(sp, name, None)
        if not callable(fn):
            continue
        try:
            return fn(solution_id, pain_id)
        except TypeError:
            pass
        for kwargs in ({"solution_id": solution_id, "pain_id": pain_id}, {"Solution_ID": solution_id, "Pain_ID": pain_id}, {"id": solution_id, "pain_id": pain_id}):
            try:
                return fn(**kwargs)
            except TypeError:
                continue
        raise TypeError("link_solution_to_pain signature not supported by tests.")
    raise AttributeError("No link_solution_to_pain function found in solution_persist.")


class TestSolutionPersist(unittest.TestCase):
    """Unit tests for solution_persist operations."""

    def setUp(self):
        """Create temp DB and init schema."""
        self._old_cwd = os.getcwd()
        os.chdir(_repo_root())
        tmp = tempfile.NamedTemporaryFile(prefix="aeos_test_", suffix=".db", delete=False)
        tmp.close()
        self.db_path = tmp.name
        _set_env_db_path(self.db_path)
        self.dbc = _patch_db_path(self.db_path)
        self.conn = _get_connection(self.dbc, self.db_path)
        _ensure_schema(self.conn, self.db_path)
        tables = _list_tables(self.conn)
        self.solution_table = _pick_table(tables, ["Solution_Design", "solution_design", "solutions"], "solution")
        self.pain_table = _pick_table(tables, ["Pain_Point_Register", "pain_point_register", "pains"], "pain")
        if not self.solution_table:
            raise AssertionError("Solution table not found after schema init.")
        if not self.pain_table:
            raise AssertionError("Pain table not found after schema init.")
        self.sp = _solution_persist()
        self._seq = 0

    def tearDown(self):
        """Close and delete temp DB."""
        try:
            try:
                self.conn.close()
            except Exception:
                pass
        finally:
            try:
                os.chdir(self._old_cwd)
            except Exception:
                pass
        for suffix in ("", "-wal", "-shm", "-journal"):
            p = self.db_path + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    # --------
    # Helpers
    # --------

    def _next(self):
        """Increment and return per-test counter."""
        self._seq += 1
        return self._seq

    def _fk_value(self, ref_table, ref_col):
        """Get first value from referenced table/col (or '')."""
        try:
            cur = self.conn.cursor()
            cur.execute(f'SELECT "{ref_col}" FROM "{ref_table}" LIMIT 1')
            row = cur.fetchone()
            return "" if not row else row[0]
        except Exception:
            return ""

    def _ensure_pain(self):
        """Insert a pain record (SQL best-effort) and return pain_id."""
        cols = _table_columns(self.conn, self.pain_table)
        id_col = _pick_ci(cols, ("Pain_ID", "pain_id", "id", "ID")) or (cols[0] if cols else "Pain_ID")
        cur = self.conn.cursor()
        cur.execute("SELECT strftime('%Y%m%d','now')")
        yyyymmdd = (cur.fetchone() or ["00000000"])[0] or "00000000"
        pain_id = f"PAIN-{yyyymmdd}-{self._next():03d}"
        insert = {id_col: pain_id}
        # Map foreign keys: from_col -> (ref_table, ref_col)
        fk_map = {}
        try:
            cur.execute(f'PRAGMA foreign_key_list("{self.pain_table}")')
            for r in (cur.fetchall() or []):
                # row: (id, seq, table, from, to, on_update, on_delete, match)
                if len(r) >= 5:
                    fk_map[str(r[3])] = (str(r[2]), str(r[4]))
        except Exception:
            fk_map = {}
        cur.execute(f'PRAGMA table_info("{self.pain_table}")')
        for r in (cur.fetchall() or []):
            # row: cid, name, type, notnull, dflt_value, pk
            try:
                name = str(r[1])
                notnull = int(r[3] or 0)
                dflt = r[4]
                pk = int(r[5] or 0)
            except Exception:
                continue
            if pk == 1 or name in insert:
                continue
            if notnull == 1 and dflt is None:
                # Prefer FK-safe values when possible.
                if name in fk_map:
                    ref_table, ref_col = fk_map[name]
                    v = self._fk_value(ref_table, ref_col)
                    if v not in ("", None):
                        insert[name] = v
                        continue
                lname = name.lower()
                if "status" in lname:
                    insert[name] = "Active"
                elif "score" in lname or "severity" in lname or "urgency" in lname or "frequency" in lname:
                    insert[name] = 1
                elif "date" in lname or "created" in lname or "updated" in lname:
                    insert[name] = "2000-01-01"
                else:
                    insert[name] = "Test"
        keys = list(insert.keys())
        cols_sql = ",".join([f'"{k}"' for k in keys])
        placeholders = ",".join(["?"] * len(keys))
        cur.execute(f'INSERT INTO "{self.pain_table}" ({cols_sql}) VALUES ({placeholders})', [insert[k] for k in keys])
        self.conn.commit()
        return pain_id

    def _solution_payloads(self, pain_id, score=None):
        """Build payload variants to handle schema drift."""
        n = self._next()
        title = f"Test Solution {n}"
        desc = "A unit-test solution description long enough for basic validation."
        payloads = [
            {"title": title, "description": desc, "pain_id": pain_id, "effort": 3, "expected_impact": 8, "score": score, "status": "Concept"},
            {"Solution_Name": title, "Description": desc, "Pain_ID": pain_id, "Effort": 3, "Expected_Impact": 8, "Score": score, "Status": "Concept"},
        ]
        return [{k: v for k, v in p.items() if v is not None} for p in payloads]

    def _create_solution(self, pain_id, score=None):
        """Create a solution and return (solution_id, created_obj)."""
        last_err = None
        for payload in self._solution_payloads(pain_id, score=score):
            try:
                created = _call_create_solution(self.sp, payload)
                sid = _extract_solution_id(created) or _extract_solution_id(payload)
                if sid:
                    return sid, created
            except Exception as e:
                last_err = e
        raise RuntimeError(f"Failed to create solution. Last error: {last_err}")

    # ----------------
    # Required tests
    # ----------------

    def test_save_solution_returns_id(self):
        """Saving a solution returns a non-empty solution_id."""
        pid = self._ensure_pain()
        sid, _ = self._create_solution(pid, score=50)
        self.assertTrue(isinstance(sid, str) and sid.strip())

    def test_load_solution_returns_dict(self):
        """Loading an existing solution returns a dict record."""
        pid = self._ensure_pain()
        sid, _ = self._create_solution(pid, score=40)
        rec = _call_get_solution(self.sp, sid)
        self.assertIsInstance(rec, dict)
        self.assertEqual(_extract_solution_id(rec), sid)

    def test_list_solutions_returns_list(self):
        """Listing solutions returns a list."""
        pid = self._ensure_pain()
        self._create_solution(pid, score=10)
        items = _normalize_list(_call_list_solutions(self.sp, limit=50))
        self.assertIsInstance(items, list)
        self.assertGreaterEqual(len(items), 1)

    def test_get_top_solutions_returns_ranked_list(self):
        """Top solutions returns list ranked by score when scores exist."""
        pid = self._ensure_pain()
        self._create_solution(pid, score=10)
        self._create_solution(pid, score=90)
        self._create_solution(pid, score=50)
        top = _normalize_list(_call_top_solutions(self.sp, n=5))
        self.assertIsInstance(top, list)
        self.assertGreaterEqual(len(top), 1)
        scores = []
        for r in top:
            s = _extract_num(r, ("Score", "score", "Solution_Score", "solution_score", "BestMoves_Score"))
            if isinstance(s, (int, float)):
                scores.append(float(s))
        if len(scores) >= 2:
            for i in range(len(scores) - 1):
                self.assertGreaterEqual(scores[i], scores[i + 1])

    def test_save_invalid_solution_raises_error(self):
        """Saving an invalid payload raises an exception."""
        with self.assertRaises(Exception):
            _call_create_solution(self.sp, {})

    def test_load_nonexistent_id_returns_none(self):
        """Loading a missing id returns None (not exception)."""
        rec = _call_get_solution(self.sp, "SOL-00000000-999")
        self.assertIsNone(rec)

    def test_link_solution_to_pain(self):
        """Linking a solution to a pain updates the pain reference."""
        pain_a = self._ensure_pain()
        pain_b = self._ensure_pain()
        sid, _ = self._create_solution(pain_a, score=30)
        _call_link_solution_to_pain(self.sp, sid, pain_b)
        rec = _call_get_solution(self.sp, sid)
        self.assertIsInstance(rec, dict)
        linked = _extract_str(rec, ("pain_id", "Pain_ID", "PainId", "pain"))
        self.assertTrue(linked)
        self.assertEqual(linked, pain_b)

    # ----------------
    # Extra tests (>=8)
    # ----------------

    def test_list_solutions_limit_respected(self):
        """list_solutions(limit=N) returns <= N."""
        pid = self._ensure_pain()
        self._create_solution(pid, score=1)
        self._create_solution(pid, score=2)
        self._create_solution(pid, score=3)
        items = _normalize_list(_call_list_solutions(self.sp, limit=1))
        self.assertLessEqual(len(items), 1)


if __name__ == "__main__":
    unittest.main()
