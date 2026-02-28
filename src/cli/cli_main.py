"""src/cli/cli_main.py
Stamp: S✅ T✅ L✅ A✅
aeOS Phase 3 — CLI Layer
Purpose
-------
Main CLI entry point and command router for the aeOS terminal interface.
Entry point
-----------
    python -m src.cli.cli_main <command> [args]
Commands
--------
- pain         : Pain management commands (delegates to src.cli.cli_pain when available)
- solutions    : Solution commands (delegates to src.cli.cli_solutions when available)
- predictions  : Prediction commands (delegates to src.cli.cli_predictions when available)
- health       : Quick system health (config + DB + KB paths)
- export       : Export data (delegates to core.export_engine when available)
- version      : Print aeOS version line
Constraints
-----------
- This file intentionally imports only: argparse, sys, os (stdlib-only as required).
- Color output uses ANSI escape sequences (no third-party deps).
"""
import argparse
import os
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
    """Return True if ANSI colors should be used for stdout."""
    if os.getenv("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    # Most modern terminals (including Windows Terminal) support ANSI.
    return True


def _c(text: str, color: str) -> str:
    """Colorize `text` with a named ANSI style if supported."""
    if not _supports_color():
        return text
    code = _ANSI.get(color, "")
    reset = _ANSI["reset"]
    return f"{code}{text}{reset}" if code else text


def _badge(ok: bool) -> str:
    """Return a colored status badge."""
    return _c("OK", "green") if ok else _c("FAIL", "red")


def _project_root() -> str:
    """Best-effort project root (repo root) derived from this file location."""
    here = os.path.dirname(os.path.abspath(__file__))
    # src/cli -> src -> repo root
    return os.path.abspath(os.path.join(here, os.pardir, os.pardir))


def _import_first(module_names):
    """Import and return the first importable module from a list of module names."""
    for name in module_names:
        try:
            return __import__(name, fromlist=["*"])
        except Exception:
            continue
    return None


def _load_config():
    """Load core.config with safe fallbacks.

    Returns:
        module|None: The imported config module, or None if not found.
    """
    return _import_first(["core.config", "src.core.config", "config"])


def _resolve_db_path(cfg) -> str:
    """Resolve aeOS SQLite DB path from config when available, else fall back to db/aeOS.db."""
    root = _project_root()
    fallback = os.path.join(root, "db", "aeOS.db")
    if cfg is None:
        return fallback
    for attr in (
        "DB_PATH",
        "SQLITE_DB_PATH",
        "AEOS_DB_PATH",
        "DB_FILE",
        "DB",
        "DB_FILENAME",
    ):
        val = getattr(cfg, attr, None)
        if isinstance(val, str) and val.strip():
            return os.path.abspath(os.path.expanduser(val.strip()))
    return fallback


def _resolve_kb_path(cfg) -> str:
    """Resolve KB persistence path from config when available, else fall back to ./kb."""
    root = _project_root()
    fallback = os.path.join(root, "kb")
    if cfg is None:
        return fallback
    for attr in ("KB_PATH", "KB_DIR", "KB_DIRECTORY"):
        val = getattr(cfg, attr, None)
        if isinstance(val, str) and val.strip():
            return os.path.abspath(os.path.expanduser(val.strip()))
    return fallback


def validate_environment() -> bool:
    """Validate core environment prerequisites for aeOS CLI.

    Checks (required):
    - DB exists (SQLite file)
    - KB path exists (directory)
    - config module loads successfully

    Returns:
        bool: True if all checks pass; otherwise False.
    """
    cfg = _load_config()
    config_loaded = cfg is not None
    db_path = _resolve_db_path(cfg)
    kb_path = _resolve_kb_path(cfg)
    db_ok = os.path.isfile(db_path)
    kb_ok = os.path.isdir(kb_path)
    return bool(config_loaded and db_ok and kb_ok)


def _today_string() -> str:
    """Return today's date as YYYY-MM-DD without importing datetime/time.

    We prefer:
    - env AEOS_DATE / AEOS_BUILD_DATE
    - POSIX `date` command
    - Windows PowerShell `Get-Date`
    Falls back to "unknown-date" if all methods fail.
    """
    env_date = (os.getenv("AEOS_DATE") or os.getenv("AEOS_BUILD_DATE") or "").strip()
    if env_date:
        return env_date

    # POSIX environments (Linux/macOS)
    try:
        out = os.popen("date +%Y-%m-%d").read().strip()
        if out:
            return out
    except Exception:
        pass

    # Windows PowerShell (best-effort)
    try:
        out = os.popen(
            'powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"'
        ).read().strip()
        if out:
            return out
    except Exception:
        pass

    return "unknown-date"


def _get_version() -> str:
    """Resolve aeOS version string from config or environment."""
    env_v = (os.getenv("AEOS_VERSION") or "").strip()
    if env_v:
        return env_v
    cfg = _load_config()
    if cfg is not None:
        for attr in ("AEOS_VERSION", "VERSION", "__version__", "APP_VERSION"):
            val = getattr(cfg, attr, None)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, (int, float)):
                return str(val)
    return "0.0"


def show_version() -> None:
    """Print aeOS version line: 'aeOS vX.X | Phase 3 | [date]'."""
    v = _get_version()
    d = _today_string()
    print(f"aeOS v{v} | Phase 3 | {d}")


def show_status() -> None:
    """Print quick system health (terminal friendly)."""
    cfg = _load_config()
    config_loaded = cfg is not None
    db_path = _resolve_db_path(cfg)
    kb_path = _resolve_kb_path(cfg)
    db_ok = os.path.isfile(db_path)
    kb_ok = os.path.isdir(kb_path)

    # Header
    title = _c("aeOS — System Status", "bold") if _supports_color() else "aeOS — System Status"
    print(title)
    print(_c("--------------------------------------------------", "dim"))

    # Status lines
    print(f"Config loaded : {_badge(config_loaded)}")
    print(f"DB path       : {_badge(db_ok)}  {db_path}")
    print(f"KB path       : {_badge(kb_ok)}  {kb_path}")

    # Summary
    all_ok = bool(config_loaded and db_ok and kb_ok)
    summary = _c("READY", "green") if all_ok else _c("NOT READY", "red")
    print(_c("--------------------------------------------------", "dim"))
    print(f"Overall       : {summary}")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _dispatch_to_module(module_candidates, argv_tail) -> int:
    """Delegate execution to another CLI module if present.

    This keeps cli_main.py small and stable while allowing each command to
    evolve independently.

    Args:
        module_candidates (list[str]): Import paths to try in order.
        argv_tail (list[str]): Remaining argv tokens for the delegated module.

    Returns:
        int: Exit code (0=success, non-zero=error).
    """
    mod = _import_first(module_candidates)
    if mod is None:
        print(_c("ERROR:", "red"), "Command module not found.")
        print("Tried:", ", ".join(module_candidates))
        return 2

    fn = getattr(mod, "main", None)
    if not callable(fn):
        print(_c("ERROR:", "red"), f"Module '{mod.__name__}' has no callable main().")
        return 2

    # Prefer main(argv:list[str]) if supported; fall back to main() if not.
    try:
        rc = fn(argv_tail)
        return int(rc) if rc is not None else 0
    except TypeError:
        try:
            rc = fn()
            return int(rc) if rc is not None else 0
        except Exception as e:
            print(_c("ERROR:", "red"), f"Command failed: {e}")
            return 1
    except Exception as e:
        print(_c("ERROR:", "red"), f"Command failed: {e}")
        return 1


def _cmd_health(_args, _rest) -> int:
    """health command handler."""
    show_status()
    return 0 if validate_environment() else 1


def _cmd_version(_args, _rest) -> int:
    """version command handler."""
    show_version()
    return 0


def _cmd_pain(_args, rest) -> int:
    """pain command handler (delegates to cli_pain if available)."""
    return _dispatch_to_module(
        ["src.cli.cli_pain", "cli.cli_pain", "cli_pain"],
        rest,
    )


def _cmd_solutions(_args, rest) -> int:
    """solutions command handler (delegates to cli_solutions if available)."""
    return _dispatch_to_module(
        ["src.cli.cli_solutions", "cli.cli_solutions", "cli_solutions"],
        rest,
    )


def _cmd_predictions(_args, rest) -> int:
    """predictions command handler (delegates to cli_predictions if available)."""
    return _dispatch_to_module(
        ["src.cli.cli_predictions", "cli.cli_predictions", "cli_predictions"],
        rest,
    )


def _cmd_export(args, _rest) -> int:
    """export command handler.

    Attempts to call core.export_engine (preferred) to export data. If unavailable,
    prints a helpful error.
    """
    out_dir = str(getattr(args, "out", "") or "").strip() or "exports"
    if not os.path.isabs(out_dir):
        out_dir = os.path.abspath(os.path.join(_project_root(), out_dir))

    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception as e:
        print(_c("ERROR:", "red"), f"Could not create export dir '{out_dir}': {e}")
        return 2

    engine = _import_first(["core.export_engine", "src.core.export_engine", "export_engine"])
    if engine is None:
        print(_c("ERROR:", "red"), "Export engine not found.")
        print("Expected: core.export_engine (or src.core.export_engine).")
        print(f"Export dir: {out_dir}")
        return 2

    # Try common export entrypoints (best-effort).
    for fn_name in ("export_all", "export_all_json", "export", "run", "main"):
        fn = getattr(engine, fn_name, None)
        if not callable(fn):
            continue
        try:
            res = fn(out_dir)
            # If the engine returns a filename/path, surface it; otherwise show dir.
            if isinstance(res, str) and res.strip():
                print(_c("Export complete:", "green"), res.strip())
            else:
                print(_c("Export complete:", "green"), out_dir)
            return 0
        except TypeError:
            # Some implementations take no args.
            try:
                res = fn()
                if isinstance(res, str) and res.strip():
                    print(_c("Export complete:", "green"), res.strip())
                else:
                    print(_c("Export complete:", "green"), out_dir)
                return 0
            except Exception as e:
                print(_c("ERROR:", "red"), f"Export failed: {e}")
                return 1
        except Exception as e:
            print(_c("ERROR:", "red"), f"Export failed: {e}")
            return 1

    print(_c("ERROR:", "red"), "No usable export function found in export_engine.")
    print("Looked for:", "export_all, export_all_json, export, run, main")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    """Create the top-level argparse parser and subcommand routers."""
    parser = argparse.ArgumentParser(
        prog="aeos",
        description="aeOS terminal interface (Phase 3).",
        epilog="Example: python -m src.cli.cli_main health",
    )
    sub = parser.add_subparsers(dest="command")

    # pain
    p_pain = sub.add_parser(
        "pain",
        help="Pain management commands (Phase 0/1).",
        description="Manage pain points (delegates to cli_pain).",
    )
    p_pain.set_defaults(handler=_cmd_pain)

    # solutions
    p_sol = sub.add_parser(
        "solutions",
        help="Solution commands (Phase 1).",
        description="Manage solutions (delegates to cli_solutions).",
    )
    p_sol.set_defaults(handler=_cmd_solutions)

    # predictions
    p_pred = sub.add_parser(
        "predictions",
        help="Prediction commands (Phase 2+).",
        description="Manage predictions (delegates to cli_predictions).",
    )
    p_pred.set_defaults(handler=_cmd_predictions)

    # health
    p_health = sub.add_parser(
        "health",
        help="Quick system health (config + DB + KB paths).",
        description="Show quick environment health for aeOS.",
    )
    p_health.set_defaults(handler=_cmd_health)

    # export
    p_export = sub.add_parser(
        "export",
        help="Export aeOS data (JSON snapshots).",
        description="Export aeOS data to disk using core.export_engine (if available).",
    )
    p_export.add_argument(
        "--out",
        default="exports",
        help="Output directory for exported files (default: ./exports).",
    )
    p_export.set_defaults(handler=_cmd_export)

    # version
    p_ver = sub.add_parser(
        "version",
        help="Show aeOS version string.",
        description="Print 'aeOS vX.X | Phase 3 | [date]'.",
    )
    p_ver.set_defaults(handler=_cmd_version)

    return parser


def main() -> None:
    """CLI entry point (argparse router)."""
    parser = _build_parser()

    # Use parse_known_args so delegated commands can own their argument parsing.
    args, rest = parser.parse_known_args(sys.argv[1:])

    # If no command provided, show help.
    cmd = getattr(args, "command", None)
    handler = getattr(args, "handler", None)

    if not cmd or not callable(handler):
        parser.print_help()
        sys.exit(2)

    rc = handler(args, rest)
    try:
        sys.exit(int(rc) if rc is not None else 0)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
