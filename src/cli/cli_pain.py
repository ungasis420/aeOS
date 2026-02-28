"""
src/cli/cli_pain.py
Stamp: S✅ T✅ L✅ A✅
aeOS Phase 3 — CLI Layer (Pain)
Purpose
-------
CLI commands for pain point management. This module is designed to be
delegated to from `src/cli/cli_main.py`:
    python -m src.cli.cli_main pain <subcommand> [args]
Constraints
-----------
- This file imports ONLY: argparse, sys  (stdlib-only as required).
- Color output uses ANSI escape sequences (no third-party deps).
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


def _supports_color() -> bool:
    """Return True if ANSI colors should be used for stdout.

    We intentionally keep this minimal to respect the "argparse, sys only"
    constraint (no os.getenv / platform checks). `isatty()` is a good-enough
    heuristic for modern terminals.
    """
    try:
        return bool(getattr(sys.stdout, "isatty", lambda: False)())
    except Exception:
        return False


def _c(text: str, color: str) -> str:
    """Colorize `text` with a named ANSI style if supported."""
    if not _supports_color():
        return text
    code = _ANSI.get(color, "")
    reset = _ANSI["reset"]
    return f"{code}{text}{reset}" if code else text


def _badge(ok: bool) -> str:
    """Return a colored OK/FAIL badge."""
    return _c("OK", "green") if ok else _c("FAIL", "red")


# ---------------------------------------------------------------------------
# Persistence import + call adapters (best-effort across branch states)
# ---------------------------------------------------------------------------

_PERSIST = None


def _import_first(module_names):
    """Import and return the first importable module from `module_names`."""
    for name in module_names:
        try:
            return __import__(name, fromlist=["*"])
        except Exception:
            continue
    return None


def _persist():
    """Lazy import the pain persistence module (pain_persist.py)."""
    global _PERSIST
    if _PERSIST is None:
        _PERSIST = _import_first(
            ["src.db.pain_persist", "db.pain_persist", "pain_persist"]
        )
    return _PERSIST


def _require_persist():
    """Return persistence module or print a helpful error and raise."""
    mod = _persist()
    if mod is None:
        raise ImportError(
            "pain_persist.py not found (expected src.db.pain_persist / db.pain_persist / pain_persist)."
        )
    missing = [
        name
        for name in (
            "save_pain_record",
            "list_pain_records",
            "load_pain_record",
            "update_pain_status",
        )
        if not callable(getattr(mod, name, None))
    ]
    if missing:
        raise ImportError(
            f"pain_persist.py missing required callables: {', '.join(missing)}"
        )
    return mod


def _call_save_pain(record: dict):
    """Call save_pain_record() with flexible signature support."""
    mod = _require_persist()
    fn = getattr(mod, "save_pain_record")

    # Most common: save_pain_record(record_dict)
    try:
        return fn(record)
    except TypeError:
        pass

    # Common keyword names.
    for kw in ("record", "pain_record", "payload", "data"):
        try:
            return fn(**{kw: record})
        except TypeError:
            continue

    # Last resort: treat record keys as kwargs.
    return fn(**record)


def _call_list_pains(limit):
    """Call list_pain_records() with flexible signature support."""
    mod = _require_persist()
    fn = getattr(mod, "list_pain_records")

    # If the caller didn't request a limit, try the simplest call first.
    if limit is None:
        try:
            return fn()
        except TypeError:
            # Some branches require a default limit kwarg.
            return fn(limit=50)

    # Preferred: keyword argument.
    try:
        return fn(limit=int(limit))
    except TypeError:
        pass

    # Fallback: positional argument.
    try:
        return fn(int(limit))
    except TypeError:
        # Last resort: function takes no arguments.
        return fn()


def _call_load_pain(pain_id: str):
    """Call load_pain_record() with flexible signature support."""
    mod = _require_persist()
    fn = getattr(mod, "load_pain_record")
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


def _call_update_status(pain_id: str, status: str):
    """Call update_pain_status() with flexible signature support."""
    mod = _require_persist()
    fn = getattr(mod, "update_pain_status")
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


def _normalize_list(x):
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


# ---------------------------------------------------------------------------
# Record field extraction helpers (to keep CLI compatible with schema variants)
# ---------------------------------------------------------------------------

def _extract_pain_id(rec) -> str:
    """Best-effort extraction of pain_id from a record dict."""
    if not isinstance(rec, dict):
        return ""
    for k in ("pain_id", "Pain_ID", "PainId", "id", "ID"):
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _extract_score(rec):
    """Best-effort extraction of numeric pain score from a record dict."""
    if not isinstance(rec, dict):
        return None
    for k in ("pain_score", "Pain_Score", "PainScore", "score", "Score"):
        v = rec.get(k)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v.strip():
            try:
                return float(v.strip())
            except Exception:
                continue
    return None


def _extract_status(rec) -> str:
    """Best-effort extraction of status from a record dict."""
    if not isinstance(rec, dict):
        return ""
    for k in ("status", "Status", "Pain_Status", "Stage", "State"):
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _extract_date(rec) -> str:
    """Best-effort extraction of a date/timestamp from a record dict."""
    if not isinstance(rec, dict):
        return ""
    for k in (
        "date",
        "Date",
        "Date_Identified",
        "Entry_Date",
        "created_at",
        "Created_At",
        "created",
        "Last_Updated",
        "updated_at",
        "timestamp",
    ):
        v = rec.get(k)
        if v is None:
            continue
        if isinstance(v, str) and v.strip():
            return v.strip()
        # Some SQLite adapters return date/datetime objects; stringify.
        try:
            s = str(v).strip()
            if s:
                return s
        except Exception:
            continue
    return ""


# ---------------------------------------------------------------------------
# Input helpers (interactive add)
# ---------------------------------------------------------------------------

def _prompt_nonempty(label: str, *, min_len: int = 1) -> str:
    """Prompt until user provides a non-empty string (optionally min length)."""
    while True:
        val = input(label).strip()
        if len(val) >= int(min_len):
            return val
        print(_c(f"Please enter at least {min_len} characters.", "yellow"))


def _prompt_int(label: str, *, lo: int, hi: int) -> int:
    """Prompt until user provides an int in [lo, hi]."""
    while True:
        raw = input(label).strip()
        try:
            n = int(raw)
        except Exception:
            print(_c("Please enter a valid integer.", "yellow"))
            continue
        if lo <= n <= hi:
            return n
        print(_c(f"Please enter a number between {lo} and {hi}.", "yellow"))


def _frequency_code_from_rating(rating_1_to_10: int) -> str:
    """Map a 1–10 frequency rating into the Blueprint-style CT_Freq bucket."""
    r = int(rating_1_to_10)
    if r >= 9:
        return "Daily"
    if r >= 7:
        return "Weekly"
    if r >= 4:
        return "Monthly"
    if r >= 2:
        return "Occasional"
    return "Rare"


def _build_save_payloads(
    description: str, severity: int, urgency: int, frequency: int, category: str
):
    """Build multiple payload shapes to maximize compatibility with pain_persist variants."""
    desc = str(description).strip()
    sev = int(severity)
    urg = int(urgency)
    freq = int(frequency)
    cat = str(category).strip()

    # Minimal payload matches the CLI requirement field names.
    minimal = {
        "description": desc,
        "severity": sev,
        "urgency": urg,
        "frequency": freq,
        "category": cat,
    }

    # Expanded payload leans toward Blueprint / DB schema column names.
    # We derive "Pain_Name" from the description for compatibility with schemas that require it.
    name = (desc[:60] + "…") if len(desc) > 60 else desc
    expanded = {
        "Pain_Name": name,
        "Description": desc,
        "Severity": sev,
        "Urgency": urg,  # Some branches track urgency explicitly.
        "Impact_Score": urg,  # Blueprint requires Impact_Score; urgency is a reasonable proxy.
        "Frequency": _frequency_code_from_rating(freq),
        "Frequency_Rating": freq,  # Preserve raw numeric input.
        "Category": cat,
        "Affected_Population": "Self",
        "Monetizability_Flag": 0,
        "Evidence": "user_reported",
        "Status": "Active",
        "Phase_Created": "0",
    }
    return [minimal, expanded]


def _extract_created_id(created) -> str:
    """Extract pain_id from save result (str/dict/tuple/other)."""
    if created is None:
        return ""
    if isinstance(created, str):
        return created.strip()
    if isinstance(created, dict):
        # Common: persistence returns the inserted row.
        pid = _extract_pain_id(created)
        if pid:
            return pid
    # Some layers return (pain_id, record) or similar.
    if isinstance(created, (list, tuple)) and created:
        for item in created:
            pid = _extract_created_id(item)
            if pid:
                return pid
    return ""


# ---------------------------------------------------------------------------
# Command implementations (required by prompt)
# ---------------------------------------------------------------------------

def cmd_add_pain(args) -> None:
    """Interactive add: description, severity, urgency, frequency, category → save_pain_record()."""
    _ = args  # reserved for future non-interactive flags
    print(_c("Add Pain Point", "bold"))
    print(_c("----------------", "dim"))

    description = _prompt_nonempty("Description (min 20 chars): ", min_len=20)
    severity = _prompt_int("Severity (1-10): ", lo=1, hi=10)
    urgency = _prompt_int("Urgency (1-10): ", lo=1, hi=10)
    frequency = _prompt_int("Frequency (1-10): ", lo=1, hi=10)
    category = _prompt_nonempty("Category: ", min_len=1)

    payloads = _build_save_payloads(description, severity, urgency, frequency, category)
    last_err = None
    created = None
    for payload in payloads:
        try:
            created = _call_save_pain(payload)
            break
        except Exception as e:
            last_err = e
            continue

    if created is None:
        print(_c("ERROR:", "red"), f"Failed to save pain record: {last_err}")
        raise SystemExit(1)

    pain_id = _extract_created_id(created) or _extract_pain_id(created) or ""
    if pain_id:
        print(_c("pain_id:", "green"), pain_id)
    else:
        # If persistence doesn't return an ID, print the raw result so it can be inspected.
        print(_c("Saved (no pain_id returned). Raw result:", "yellow"))
        print(created)


def _print_table(rows, headers, get_row):
    """Render a simple left-aligned ASCII table (no external deps)."""
    data = [headers]
    for r in rows:
        data.append(get_row(r))

    # Compute column widths.
    widths = [0] * len(headers)
    for row in data:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt(row):
        return "  ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers)))

    # Header
    print(_c(fmt(headers), "bold"))
    print(_c("  ".join("-" * w for w in widths), "dim"))
    # Body
    for row in data[1:]:
        print(fmt(row))


def cmd_list_pain(args) -> None:
    """List pains. Prints: pain_id, score, status, date (default limit 10)."""
    limit = int(getattr(args, "limit", 10) or 10)

    try:
        rows = _normalize_list(_call_list_pains(limit))
    except Exception as e:
        print(_c("ERROR:", "red"), f"Failed to list pain records: {e}")
        raise SystemExit(1)

    # Most persistence layers return newest-first; we still cap to limit defensively.
    rows = rows[:limit]

    headers = ("pain_id", "score", "status", "date")

    def row_fn(rec):
        pid = _extract_pain_id(rec)
        score = _extract_score(rec)
        status = _extract_status(rec)
        date = _extract_date(rec)
        s = (
            ""
            if score is None
            else (
                f"{score:.1f}" if isinstance(score, (int, float)) else str(score)
            )
        )
        return (pid, s, status, date)

    if not rows:
        print(_c("No pain records found.", "yellow"))
        return

    _print_table(rows, headers, row_fn)


def cmd_view_pain(args) -> None:
    """View a single pain record by --id."""
    pain_id = str(getattr(args, "id", "") or "").strip()
    if not pain_id:
        print(_c("ERROR:", "red"), "--id is required")
        raise SystemExit(2)

    try:
        rec = _call_load_pain(pain_id)
    except Exception as e:
        print(_c("ERROR:", "red"), f"Failed to load pain '{pain_id}': {e}")
        raise SystemExit(1)

    if not rec:
        print(_c("Not found:", "yellow"), pain_id)
        return

    # Print a stable, readable key/value list.
    if isinstance(rec, dict):
        print(_c(f"Pain Record: {pain_id}", "bold"))
        print(_c("-------------------------", "dim"))
        for k in sorted(rec.keys(), key=lambda x: str(x)):
            v = rec.get(k)
            try:
                v_s = str(v)
            except Exception:
                v_s = "<unprintable>"
            print(f"{k}: {v_s}")
        return

    # Non-dict record shape (fallback).
    print(_c(f"Pain Record: {pain_id} (raw)", "bold"))
    print(rec)


def cmd_update_status(args) -> None:
    """Update pain status via --id and --status."""
    pain_id = str(getattr(args, "id", "") or "").strip()
    status = str(getattr(args, "status", "") or "").strip()

    if not pain_id:
        print(_c("ERROR:", "red"), "--id is required")
        raise SystemExit(2)
    if not status:
        print(_c("ERROR:", "red"), "--status is required")
        raise SystemExit(2)

    try:
        res = _call_update_status(pain_id, status)
    except Exception as e:
        print(_c("ERROR:", "red"), f"Failed to update status for '{pain_id}': {e}")
        raise SystemExit(1)

    ok = not (res is None or res is False)
    print(
        _c("Updated:", "green") if ok else _c("Not updated:", "yellow"),
        pain_id,
        "→",
        status,
    )

    if isinstance(res, dict):
        # Surface new score/status briefly if present.
        s = _extract_score(res)
        st = _extract_status(res)
        if s is not None or st:
            extra = []
            if s is not None:
                extra.append(f"score={s:.1f}")
            if st:
                extra.append(f"status={st}")
            print(_c("Result:", "dim"), ", ".join(extra))


def cmd_critical(args) -> None:
    """List only pain points scoring > 70."""
    _ = args
    try:
        # Fetch "enough" records to make filtering meaningful.
        rows = _normalize_list(_call_list_pains(10_000))
    except Exception as e:
        print(_c("ERROR:", "red"), f"Failed to list pain records: {e}")
        raise SystemExit(1)

    critical = []
    for r in rows:
        s = _extract_score(r)
        if isinstance(s, (int, float)) and float(s) > 70.0:
            critical.append(r)

    if not critical:
        print(_c("No critical pain points found (score > 70).", "yellow"))
        return

    headers = ("pain_id", "score", "status", "date")

    def row_fn(rec):
        pid = _extract_pain_id(rec)
        score = _extract_score(rec)
        status = _extract_status(rec)
        date = _extract_date(rec)
        s = "" if score is None else f"{float(score):.1f}"
        return (pid, s, status, date)

    print(_c("Critical pain points (score > 70)", "bold"))
    _print_table(critical, headers, row_fn)


# ---------------------------------------------------------------------------
# Argparse router (for delegation from cli_main.py)
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """Build the pain subcommand parser."""
    p = argparse.ArgumentParser(
        prog="aeos pain",
        description="Pain point management commands (Phase 3).",
    )
    sub = p.add_subparsers(dest="subcommand")

    # add
    p_add = sub.add_parser("add", help="Add a pain point (interactive).")
    p_add.set_defaults(func=cmd_add_pain)

    # list
    p_list = sub.add_parser("list", help="List pain points.")
    p_list.add_argument(
        "--limit", type=int, default=10, help="Max records to show (default: 10)."
    )
    p_list.set_defaults(func=cmd_list_pain)

    # view
    p_view = sub.add_parser("view", help="View a pain point by id.")
    p_view.add_argument("--id", required=True, help="Pain ID (e.g., PAIN-YYYYMMDD-NNN).")
    p_view.set_defaults(func=cmd_view_pain)

    # update-status
    p_upd = sub.add_parser("update-status", help="Update pain status.")
    p_upd.add_argument("--id", required=True, help="Pain ID (e.g., PAIN-YYYYMMDD-NNN).")
    p_upd.add_argument("--status", required=True, help="New status value.")
    p_upd.set_defaults(func=cmd_update_status)

    # critical
    p_crit = sub.add_parser("critical", help="List pain points with score > 70.")
    p_crit.set_defaults(func=cmd_critical)

    return p


def main(argv=None) -> int:
    """Entry point for delegated execution.

    Args:
        argv: Optional list of CLI args (excluding the parent 'pain' token).

    Returns:
        int: process exit code (0 success, non-zero error)
    """
    argv = list(argv) if argv is not None else sys.argv[1:]
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "subcommand", None):
        parser.print_help()
        return 2

    fn = getattr(args, "func", None)
    if not callable(fn):
        parser.print_help()
        return 2

    try:
        fn(args)
        return 0
    except SystemExit as e:
        # Command handlers may raise SystemExit to signal a specific code.
        try:
            return int(getattr(e, "code", 1) or 0)
        except Exception:
            return 1
    except KeyboardInterrupt:
        print()
        print(_c("Interrupted.", "yellow"))
        return 130
    except Exception as e:
        print(_c("ERROR:", "red"), str(e))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
