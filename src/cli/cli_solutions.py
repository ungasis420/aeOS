"""
src/cli/cli_solutions.py
Stamp: S✅ T✅ L✅ A✅
aeOS Phase 3 — CLI Layer (Solutions)
Purpose
-------
CLI commands for solution management (Solution_Design records).
Constraints
-----------
- Imports: argparse, sys (stdlib-only).
- Color output: ANSI escape sequences (no third-party deps).
- DB fallback paths use db_connect.get_connection().
"""
import argparse
import sys

# ---------------------------------------------------------------------------
# ANSI color helpers (stdlib-only)
# ---------------------------------------------------------------------------

_ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "cyan": "\033[36m",
}

_COLOR_ENABLED = False  # set at runtime


def _supports_color() -> bool:
    """True when stdout is a TTY (simple/portable check)."""
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def _c(text: str, color: str) -> str:
    """Colorize text if enabled."""
    if not _COLOR_ENABLED:
        return text
    code = _ANSI.get(color, "")
    return f"{code}{text}{_ANSI['reset']}" if code else text


def _println_error(msg: str) -> None:
    """Print an error line."""
    print(f"{_c('ERROR:', 'red')} {msg}")


def _println_success(msg: str) -> None:
    """Print a success line."""
    print(f"{_c('OK:', 'green')} {msg}")


def _println_warn(msg: str) -> None:
    """Print a warning line."""
    print(f"{_c('WARN:', 'yellow')} {msg}")


# ---------------------------------------------------------------------------
# Dynamic imports (no extra stdlib imports)
# ---------------------------------------------------------------------------

def _import_first(module_names):
    """Return the first importable module from module_names, else None."""
    for name in module_names:
        try:
            return __import__(name, fromlist=["*"])
        except Exception:
            continue
    return None


def _load_solution_persist():
    """Load solution_persist with best-effort paths."""
    return _import_first(["db.solution_persist", "src.db.solution_persist", "solution_persist"])


def _load_db_connect():
    """Load db_connect with best-effort paths."""
    return _import_first(["db.db_connect", "src.db.db_connect", "db_connect"])


def _get_connection():
    """Return a SQLite connection via db_connect.get_connection()."""
    dbc = _load_db_connect()
    if dbc is None:
        raise RuntimeError("db_connect not found (expected db.db_connect or src.db.db_connect).")
    fn = getattr(dbc, "get_connection", None)
    if not callable(fn):
        raise RuntimeError("db_connect.get_connection() not found.")
    return fn()


def _safe_close(conn) -> None:
    """Best-effort connection close."""
    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# solution_persist adapters (preferred path)
# ---------------------------------------------------------------------------

def _persist_create_solution(payload: dict):
    """(ok, result) create a solution using solution_persist when available."""
    sp = _load_solution_persist()
    if sp is None:
        return (False, "solution_persist_unavailable")
    for name in (
        "create_solution",
        "create_solution_record",
        "insert_solution",
        "add_solution",
        "save_solution",
        "save_solution_record",
    ):
        fn = getattr(sp, name, None)
        if not callable(fn):
            continue
        # Prefer positional dict payload.
        try:
            return (True, fn(payload))
        except TypeError:
            pass
        except Exception as e:
            return (False, str(e))
        # Common wrapper keyword names.
        for kw in ("record", "solution_record", "payload", "data"):
            try:
                return (True, fn(**{kw: payload}))
            except TypeError:
                continue
            except Exception as e:
                return (False, str(e))
    return (False, "solution_persist_missing_create_function")


def _persist_list_solutions(limit: int):
    """(ok, result) list solutions using solution_persist when available."""
    sp = _load_solution_persist()
    if sp is None:
        return (False, "solution_persist_unavailable")
    for name in ("list_solutions", "get_all_solutions", "list_all_solutions", "fetch_solutions"):
        fn = getattr(sp, name, None)
        if not callable(fn):
            continue
        for call in (
            lambda: fn(limit=limit),
            lambda: fn(limit),
            lambda: fn(),
        ):
            try:
                return (True, call())
            except TypeError:
                continue
            except Exception as e:
                return (False, str(e))
    return (False, "solution_persist_missing_list_function")


def _persist_get_solution(solution_id: str):
    """(ok, result) fetch a solution by id using solution_persist when available."""
    sp = _load_solution_persist()
    if sp is None:
        return (False, "solution_persist_unavailable")
    for name in ("get_solution", "get_solution_by_id", "fetch_solution", "read_solution", "load_solution_record"):
        fn = getattr(sp, name, None)
        if not callable(fn):
            continue
        try:
            return (True, fn(solution_id))
        except TypeError:
            pass
        except Exception as e:
            return (False, str(e))
        for kw in ("solution_id", "id", "record_id"):
            try:
                return (True, fn(**{kw: solution_id}))
            except TypeError:
                continue
            except Exception as e:
                return (False, str(e))
    return (False, "solution_persist_missing_get_function")


def _persist_top_solutions(n: int):
    """(ok, result) fetch top N using solution_persist when available."""
    sp = _load_solution_persist()
    if sp is None:
        return (False, "solution_persist_unavailable")
    for name in ("top_solutions", "get_top_solutions", "list_top_solutions", "best_solutions"):
        fn = getattr(sp, name, None)
        if not callable(fn):
            continue
        for call in (
            lambda: fn(n),
            lambda: fn(limit=n),
        ):
            try:
                return (True, call())
            except TypeError:
                continue
            except Exception as e:
                return (False, str(e))
    return (False, "solution_persist_missing_top_function")


def _persist_link_solution_to_pain(solution_id: str, pain_id: str):
    """(ok, result) link a solution to a pain using solution_persist when available."""
    sp = _load_solution_persist()
    if sp is None:
        return (False, "solution_persist_unavailable")
    for name in (
        "link_solution_to_pain",
        "set_solution_pain",
        "attach_solution_to_pain",
        "update_solution_pain",
        "link_to_pain",
    ):
        fn = getattr(sp, name, None)
        if not callable(fn):
            continue
        try:
            return (True, fn(solution_id, pain_id))
        except TypeError:
            pass
        except Exception as e:
            return (False, str(e))
        for kwargs in (
            {"solution_id": solution_id, "pain_id": pain_id},
            {"Solution_ID": solution_id, "Pain_ID": pain_id},
            {"id": solution_id, "pain_id": pain_id},
            {"solution": solution_id, "pain": pain_id},
        ):
            try:
                return (True, fn(**kwargs))
            except TypeError:
                continue
            except Exception as e:
                return (False, str(e))
    return (False, "solution_persist_missing_link_function")


def _normalize_list(x):
    """Normalize persistence return shapes into a list."""
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


# ---------------------------------------------------------------------------
# DB fallback helpers (no extra imports)
# ---------------------------------------------------------------------------

def _sql_quote(name: str) -> str:
    """Quote a SQLite identifier with double quotes."""
    name = str(name)
    return '"' + name.replace('"', '""') + '"'


def _db_list_tables(conn):
    """List user tables in sqlite."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    rows = cur.fetchall() or []
    return [str(r[0]) for r in rows if r and r[0]]


def _db_table_columns(conn, table: str):
    """Return columns for table via PRAGMA table_info."""
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({_sql_quote(table)})")
    rows = cur.fetchall() or []
    return [str(r[1]) for r in rows if r and len(r) >= 2 and r[1]]


def _pick_first(existing_cols, candidates):
    """Pick the first candidate present in existing_cols (case-insensitive)."""
    lower = {str(c).lower(): c for c in existing_cols}
    for cand in candidates:
        hit = lower.get(str(cand).lower())
        if hit:
            return hit
    return None


def _resolve_solution_table(conn):
    """Resolve the solutions table name (best-effort)."""
    tables = _db_list_tables(conn)
    lower = {t.lower(): t for t in tables}
    return (
        lower.get("solution_design")
        or lower.get("solutions")
        or lower.get("solution")
        or next((t for t in tables if "solution" in t.lower()), None)
    )


def _resolve_solution_schema(conn):
    """Resolve solution table and key columns (best-effort)."""
    schema = {
        "table": None,
        "id_col": None,
        "pain_col": None,
        "title_col": None,
        "desc_col": None,
        "effort_col": None,
        "impact_col": None,
        "score_col": None,
        "status_col": None,
        "created_col": None,
        "updated_col": None,
    }
    table = _resolve_solution_table(conn)
    if not table:
        return schema

    cols = _db_table_columns(conn, table)
    schema["table"] = table
    schema["id_col"] = _pick_first(cols, ["Solution_ID", "solution_id", "id"])
    schema["pain_col"] = _pick_first(cols, ["Pain_ID", "pain_id"])
    schema["title_col"] = _pick_first(cols, ["Title", "title", "Solution_Name", "solution_name", "name"])
    schema["desc_col"] = _pick_first(cols, ["Description", "description", "Details", "details"])
    schema["effort_col"] = _pick_first(cols, ["Effort", "effort", "Complexity", "complexity"])
    schema["impact_col"] = _pick_first(cols, ["Expected_Impact", "expected_impact", "Impact", "impact", "Pain_Fit_Score"])
    schema["score_col"] = _pick_first(cols, ["Score", "score", "Solution_Score", "solution_score", "BestMoves_Score", "bestmoves_score"])
    if schema["score_col"] is None:
        schema["score_col"] = next((c for c in cols if "score" in c.lower()), None)
    schema["status_col"] = _pick_first(cols, ["Status", "status", "Solution_Status", "solution_status", "Stage", "stage", "State", "state"])
    schema["created_col"] = _pick_first(cols, ["Date_Created", "date_created", "Created_At", "created_at", "Entry_Date", "entry_date"])
    schema["updated_col"] = _pick_first(cols, ["Last_Updated", "last_updated", "Updated_At", "updated_at"])
    return schema


def _db_rows_to_dicts(cur, rows):
    """Convert cursor rows into dicts using cursor.description."""
    cols = [d[0] for d in (cur.description or [])]
    out = []
    for r in rows:
        try:
            out.append({cols[i]: r[i] for i in range(min(len(cols), len(r)))})
        except Exception:
            out.append({"value": r})
    return out


def _db_list_solutions(limit: int):
    """List solutions (DB fallback)."""
    conn = None
    try:
        conn = _get_connection()
        schema = _resolve_solution_schema(conn)
        table = schema.get("table")
        if not table:
            raise RuntimeError("solution table not found (expected Solution_Design).")
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM {_sql_quote(table)} ORDER BY rowid DESC LIMIT ?", (int(limit),))
        return _db_rows_to_dicts(cur, cur.fetchall() or [])
    finally:
        _safe_close(conn)


def _db_get_solution(solution_id: str):
    """Fetch a solution by id (DB fallback)."""
    conn = None
    try:
        conn = _get_connection()
        schema = _resolve_solution_schema(conn)
        table, id_col = schema.get("table"), schema.get("id_col")
        if not table or not id_col:
            raise RuntimeError("solution table missing Solution_ID column.")
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM {_sql_quote(table)} WHERE {_sql_quote(id_col)} = ? LIMIT 1",
            (solution_id,),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError("not_found")
        return _db_rows_to_dicts(cur, [row])[0]
    finally:
        _safe_close(conn)


def _db_top_solutions(limit: int):
    """Return top solutions (DB fallback)."""
    conn = None
    try:
        conn = _get_connection()
        schema = _resolve_solution_schema(conn)
        table, score_col = schema.get("table"), schema.get("score_col")
        if not table:
            raise RuntimeError("solution table not found (expected Solution_Design).")
        cur = conn.cursor()
        if score_col:
            cur.execute(
                f"SELECT * FROM {_sql_quote(table)} ORDER BY {_sql_quote(score_col)} DESC LIMIT ?",
                (int(limit),),
            )
        else:
            cur.execute(f"SELECT * FROM {_sql_quote(table)} ORDER BY rowid DESC LIMIT ?", (int(limit),))
        return _db_rows_to_dicts(cur, cur.fetchall() or [])
    finally:
        _safe_close(conn)


def _db_update_solution_pain(solution_id: str, pain_id: str):
    """Update Pain_ID on a solution (DB fallback)."""
    conn = None
    try:
        conn = _get_connection()
        schema = _resolve_solution_schema(conn)
        table = schema.get("table")
        id_col = schema.get("id_col")
        pain_col = schema.get("pain_col")
        if not table or not id_col or not pain_col:
            raise RuntimeError("solution table missing id/pain columns.")
        cur = conn.cursor()
        cur.execute(
            f"UPDATE {_sql_quote(table)} SET {_sql_quote(pain_col)} = ? WHERE {_sql_quote(id_col)} = ?",
            (pain_id, solution_id),
        )
        conn.commit()
        if getattr(cur, "rowcount", 0) == 0:
            raise KeyError("not_found")
        return _db_get_solution(solution_id)
    finally:
        _safe_close(conn)


def _db_now_date(cur):
    """Return YYYY-MM-DD using SQLite date('now')."""
    cur.execute("SELECT date('now')")
    row = cur.fetchone()
    return (row[0] if row else None) or ""


def _db_now_ymd(cur):
    """Return YYYYMMDD using SQLite strftime."""
    cur.execute("SELECT strftime('%Y%m%d','now')")
    row = cur.fetchone()
    return (row[0] if row else None) or ""


def _db_next_sol_id(cur, table: str, id_col: str):
    """Generate next SOL-YYYYMMDD-NNN id using SQLite (no Python datetime)."""
    yyyymmdd = _db_now_ymd(cur) or "00000000"
    prefix = f"SOL-{yyyymmdd}-"
    cur.execute(
        f"""
        SELECT max(CAST(substr({_sql_quote(id_col)}, 14) AS INTEGER))
        FROM {_sql_quote(table)}
        WHERE {_sql_quote(id_col)} LIKE ?
        """,
        (prefix + "%",),
    )
    row = cur.fetchone()
    max_n = int(row[0]) if row and row[0] is not None else 0
    return f"SOL-{yyyymmdd}-{(max_n + 1):03d}"


def _db_insert_solution(payload: dict):
    """Insert a solution record into DB (fallback)."""
    conn = None
    try:
        conn = _get_connection()
        schema = _resolve_solution_schema(conn)
        table = schema.get("table")
        id_col = schema.get("id_col")
        if not table or not id_col:
            raise RuntimeError("solution table not found or missing Solution_ID column.")

        cols = _db_table_columns(conn, table)
        cur = conn.cursor()
        rec = {}  # insert record limited to known columns

        def _set_if(col_name, *payload_keys):
            if not col_name or col_name not in cols or rec.get(col_name):
                return
            for pk in payload_keys:
                if pk in payload and payload[pk] not in (None, ""):
                    rec[col_name] = payload[pk]
                    return

        _set_if(schema.get("title_col"), "title", "Title", "Solution_Name", "solution_name", "name")
        _set_if(schema.get("desc_col"), "description", "Description", "details", "Details")
        _set_if(schema.get("pain_col"), "pain_id", "Pain_ID", "pain", "PainID")
        _set_if(schema.get("effort_col"), "effort", "Effort", "complexity", "Complexity")
        _set_if(schema.get("impact_col"), "expected_impact", "Expected_Impact", "impact", "Impact", "Pain_Fit_Score")

        # Default status.
        status_col = schema.get("status_col")
        if status_col and status_col in cols and not rec.get(status_col):
            rec[status_col] = "Concept"

        # Optional score (if table stores it).
        score_col = schema.get("score_col")
        if score_col and score_col in cols and not rec.get(score_col):
            try:
                eff = int(payload.get("effort"))
                imp = int(payload.get("expected_impact"))
                rec[score_col] = (imp * 10) - eff
            except Exception:
                pass

        # Date fields (if present).
        created_col = schema.get("created_col")
        if created_col and created_col in cols and not rec.get(created_col):
            rec[created_col] = _db_now_date(cur)
        updated_col = schema.get("updated_col")
        if updated_col and updated_col in cols and not rec.get(updated_col):
            rec[updated_col] = _db_now_date(cur)

        # Ensure Solution_ID exists.
        if id_col in cols and not rec.get(id_col):
            rec[id_col] = _db_next_sol_id(cur, table, id_col)

        if not rec:
            raise ValueError("No valid fields provided for insert.")

        keys = list(rec.keys())
        placeholders = ",".join(["?"] * len(keys))
        col_sql = ",".join([_sql_quote(k) for k in keys])
        cur.execute(
            f"INSERT INTO {_sql_quote(table)} ({col_sql}) VALUES ({placeholders})",
            [rec[k] for k in keys],
        )
        conn.commit()
        return _db_get_solution(str(rec[id_col]))
    finally:
        _safe_close(conn)


# ---------------------------------------------------------------------------
# Record normalization + table printing
# ---------------------------------------------------------------------------

def _as_float(x):
    """Best-effort float conversion; returns None if not parseable."""
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str) and x.strip():
        try:
            return float(x.strip())
        except Exception:
            return None
    return None


def _extract_solution_fields(rec):
    """Extract (solution_id, title, score, status) from a record."""
    if not isinstance(rec, dict):
        return ("", "", None, "")

    def _first(keys):
        for k in keys:
            if k in rec and rec[k] not in (None, ""):
                return rec[k]
        return None

    sid = _first(["Solution_ID", "solution_id", "id", "SOL_ID", "Sol_ID"]) or ""
    title = _first(["title", "Title", "Solution_Name", "solution_name", "name"]) or ""
    status = _first(["status", "Status", "Solution_Status", "solution_status", "Stage", "stage", "State", "state"]) or ""
    score = _as_float(_first(["score", "Score", "Solution_Score", "solution_score", "BestMoves_Score", "bestmoves_score"]))
    if score is None:
        eff = _as_float(_first(["effort", "Effort", "Complexity", "complexity"]))
        imp = _as_float(_first(["expected_impact", "Expected_Impact", "impact", "Impact", "Pain_Fit_Score"]))
        if eff is not None and imp is not None:
            score = (imp * 10.0) - eff
    return (str(sid), str(title), score, str(status))


def _print_table(headers, rows):
    """Print a simple fixed-width table."""
    str_rows = [[("" if v is None else str(v)) for v in r] for r in rows]
    widths = [len(h) for h in headers]
    for r in str_rows:
        for i in range(min(len(headers), len(r))):
            widths[i] = max(widths[i], len(r[i]))
    max_w = 60
    widths = [min(w, max_w) for w in widths]

    def _clip(s, w):
        if len(s) <= w:
            return s
        if w <= 1:
            return s[:w]
        return s[: max(0, w - 1)] + "…"

    header_line = "  ".join(_clip(headers[i], widths[i]).ljust(widths[i]) for i in range(len(headers)))
    sep_line = "  ".join(("-" * widths[i]) for i in range(len(headers)))
    print(_c(header_line, "bold"))
    print(_c(sep_line, "dim"))
    for r in str_rows:
        line = "  ".join(_clip(r[i], widths[i]).ljust(widths[i]) for i in range(len(headers)))
        print(line)


def _print_record(rec):
    """Print a record dict as key/value lines."""
    if not isinstance(rec, dict):
        print(rec)
        return
    for k in sorted(rec.keys(), key=lambda x: str(x).lower()):
        print(f"{_c(str(k), 'cyan')}: {rec.get(k)}")


# ---------------------------------------------------------------------------
# Required CLI command functions
# ---------------------------------------------------------------------------

def cmd_add_solution(args) -> None:
    """Interactive add: title, description, effort(1-10), expected_impact(1-10), pain_id."""
    try:
        title = input("Title: ").strip()
        while not title:
            _println_warn("Title is required.")
            title = input("Title: ").strip()

        description = input("Description: ").strip()
        while len(description) < 3:
            _println_warn("Description is required (min 3 chars).")
            description = input("Description: ").strip()

        def _read_int(prompt, lo, hi):
            while True:
                raw = input(prompt).strip()
                try:
                    v = int(raw)
                except Exception:
                    _println_warn(f"Enter a whole number {lo}-{hi}.")
                    continue
                if v < lo or v > hi:
                    _println_warn(f"Value must be {lo}-{hi}.")
                    continue
                return v

        effort = _read_int("Effort (1-10): ", 1, 10)
        impact = _read_int("Expected impact (1-10): ", 1, 10)
        pain_id = input("Pain ID to link (optional): ").strip()
    except EOFError:
        _println_error("Input cancelled (EOF).")
        return
    except KeyboardInterrupt:
        _println_error("Input cancelled.")
        return

    payload = {"title": title, "description": description, "effort": effort, "expected_impact": impact}
    if pain_id:
        payload["pain_id"] = pain_id

    ok, res = _persist_create_solution(payload)
    if ok:
        rec = res if isinstance(res, dict) else {"result": res}
        sid, _, _, _ = _extract_solution_fields(rec)
        _println_success(f"Solution created {_c(sid or '(id unknown)', 'cyan')}.")
        if isinstance(res, dict):
            _print_record(res)
        return

    try:
        created = _db_insert_solution(payload)
        sid, _, _, _ = _extract_solution_fields(created)
        _println_success(f"Solution created {_c(sid or '(id unknown)', 'cyan')} (DB fallback).")
        _print_record(created)
    except Exception as e:
        _println_error(f"Failed to create solution. ({res})")
        _println_error(str(e))


def cmd_list_solutions(args) -> None:
    """List solutions in a 4-column table."""
    limit = int(getattr(args, "limit", 50) or 50)

    ok, res = _persist_list_solutions(limit)
    if ok:
        items = _normalize_list(res)
    else:
        try:
            items = _db_list_solutions(limit)
        except Exception as e:
            _println_error(f"Failed to list solutions. ({res})")
            _println_error(str(e))
            return

    rows = []
    for rec in items:
        sid, title, score, status = _extract_solution_fields(rec if isinstance(rec, dict) else {})
        score_s = "" if score is None else f"{score:.2f}".rstrip("0").rstrip(".")
        rows.append([sid, title, score_s, status])

    if not rows:
        _println_warn("No solutions found.")
        return

    _print_table(["solution_id", "title", "score", "status"], rows)


def cmd_top_solutions(args) -> None:
    """Show top N (default 5) solutions by score."""
    n = int(getattr(args, "n", 5) or 5)
    if n <= 0:
        _println_warn("n must be > 0.")
        return

    ok, res = _persist_top_solutions(n)
    if ok:
        items = _normalize_list(res)
    else:
        try:
            items = _db_top_solutions(n)
        except Exception:
            ok2, res2 = _persist_list_solutions(1000)
            if ok2:
                items = _normalize_list(res2)
            else:
                try:
                    items = _db_list_solutions(1000)
                except Exception as e:
                    _println_error(f"Failed to compute top solutions. ({res})")
                    _println_error(str(e))
                    return

    scored = []
    for rec in items:
        sid, title, score, status = _extract_solution_fields(rec if isinstance(rec, dict) else {})
        s = -1e18 if score is None else float(score)
        scored.append((s, sid, title, status))

    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)

    rows = []
    for s, sid, title, status in scored[:n]:
        score_s = "" if s <= -1e17 else f"{s:.2f}".rstrip("0").rstrip(".")
        rows.append([sid, title, score_s, status])

    if not rows:
        _println_warn("No solutions found.")
        return

    _print_table(["solution_id", "title", "score", "status"], rows)


def cmd_view_solution(args) -> None:
    """View a full record by --id."""
    solution_id = str(getattr(args, "id", "") or "").strip()
    if not solution_id:
        _println_error("Missing required flag: --id")
        return

    ok, res = _persist_get_solution(solution_id)
    if ok:
        rec = res
    else:
        try:
            rec = _db_get_solution(solution_id)
        except KeyError:
            _println_error("Solution not found.")
            return
        except Exception as e:
            _println_error(f"Failed to fetch solution. ({res})")
            _println_error(str(e))
            return

    _print_record(rec)


def cmd_link_to_pain(args) -> None:
    """Link solution to pain using --solution-id and --pain-id."""
    solution_id = str(getattr(args, "solution_id", "") or "").strip()
    pain_id = str(getattr(args, "pain_id", "") or "").strip()
    if not solution_id or not pain_id:
        _println_error("Both --solution-id and --pain-id are required.")
        return

    ok, res = _persist_link_solution_to_pain(solution_id, pain_id)
    if ok:
        _println_success(f"Linked {_c(solution_id, 'cyan')} → {_c(pain_id, 'cyan')}.")
        if isinstance(res, dict):
            _print_record(res)
        return

    try:
        updated = _db_update_solution_pain(solution_id, pain_id)
        _println_success(f"Linked {_c(solution_id, 'cyan')} → {_c(pain_id, 'cyan')} (DB fallback).")
        _print_record(updated)
    except KeyError:
        _println_error("Solution not found.")
    except Exception as e:
        _println_error(f"Failed to link solution to pain. ({res})")
        _println_error(str(e))


# ---------------------------------------------------------------------------
# Argument parsing + entrypoint
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """Create the `aeos solutions` subcommand parser."""
    parser = argparse.ArgumentParser(
        prog="aeos solutions",
        description="aeOS Solutions CLI (Phase 3).",
        epilog="Example: python -m src.cli.cli_main solutions list --limit 50",
    )
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output.")
    sub = parser.add_subparsers(dest="command")

    p_add = sub.add_parser("add", help="Add a solution (interactive).")
    p_add.set_defaults(handler=cmd_add_solution)

    p_list = sub.add_parser("list", help="List solutions.")
    p_list.add_argument("--limit", type=int, default=50, help="Max rows (default: 50).")
    p_list.set_defaults(handler=cmd_list_solutions)

    p_top = sub.add_parser("top", help="Show top solutions by score.")
    p_top.add_argument("--n", type=int, default=5, help="Rows to show (default: 5).")
    p_top.set_defaults(handler=cmd_top_solutions)

    p_view = sub.add_parser("view", help="View a solution record.")
    p_view.add_argument("--id", required=True, help="Solution ID (e.g., SOL-YYYYMMDD-NNN).")
    p_view.set_defaults(handler=cmd_view_solution)

    p_link = sub.add_parser("link", help="Link a solution to a pain.")
    p_link.add_argument("--solution-id", dest="solution_id", required=True, help="Solution ID.")
    p_link.add_argument("--pain-id", dest="pain_id", required=True, help="Pain ID.")
    p_link.set_defaults(handler=cmd_link_to_pain)

    return parser


def main(argv=None) -> int:
    """Entrypoint called by cli_main dispatcher; returns an exit code."""
    global _COLOR_ENABLED
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = _build_parser()
    args = parser.parse_args(argv)
    _COLOR_ENABLED = bool(_supports_color() and not bool(getattr(args, "no_color", False)))

    handler = getattr(args, "handler", None)
    if not callable(handler):
        parser.print_help()
        return 2

    try:
        handler(args)
        return 0
    except KeyboardInterrupt:
        _println_error("Cancelled.")
        return 130
    except Exception as e:
        _println_error(str(e))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
