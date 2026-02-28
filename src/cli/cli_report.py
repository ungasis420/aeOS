"""
src/cli/cli_report.py
Stamp: S✅ T✅ L✅ A✅
aeOS Phase 3 — CLI Layer
Purpose
-------
CLI report generation commands.
Constraints (required):
- stdlib imports only: argparse, sys
- aeOS modules are imported dynamically (best-effort)
Commands (required):
- cmd_health_report(args): print full portfolio health (colorized)
- cmd_export_json(args): export JSON snapshot to --output (save_snapshot_to_file)
- cmd_pain_report(args): pain summary (total/critical/active/resolved)
- cmd_prediction_report(args): calibration grades per predictor
- cmd_full_report(args): run all reports in sequence
"""
import argparse
import sys

# -----------------------------
# ANSI color helpers (stdlib-only)
# -----------------------------

_ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
}


def _supports_color() -> bool:
    """Return True if stdout is a TTY (safe default for ANSI colors)."""
    try:
        return bool(hasattr(sys.stdout, "isatty") and sys.stdout.isatty())
    except Exception:
        return False


def _c(text: str, color: str) -> str:
    """Wrap text in an ANSI color/style code if supported."""
    if not _supports_color():
        return text
    code = _ANSI.get(color, "")
    return f"{code}{text}{_ANSI['reset']}" if code else text


def _section(title: str) -> None:
    """Print a section header."""
    t = (title or "").strip() or "Report"
    line = "-" * 66
    if _supports_color():
        print(_c(t, "bold"))
        print(_c(line, "dim"))
    else:
        print(t)
        print(line)


# -----------------------------
# Dynamic import helpers
# -----------------------------

def _import_first(names):
    """Import and return the first importable module from `names`."""
    for n in names:
        try:
            return __import__(n, fromlist=["*"])
        except Exception:
            continue
    return None


def _get_db_connection_fn():
    """Return db_connect.get_connection() if importable; else None."""
    m = _import_first(["db.db_connect", "src.db.db_connect", "db_connect"])
    fn = getattr(m, "get_connection", None) if m else None
    return fn if callable(fn) else None


# -----------------------------
# Small utilities (no extra imports)
# -----------------------------

def _extract_score(health):
    """Extract portfolio health score from common keys."""
    if not isinstance(health, dict):
        return None
    for k in ("health_score", "portfolio_health_score", "score", "overall_score"):
        v = health.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    m = health.get("metrics")
    if isinstance(m, dict):
        for k in ("health_score", "score", "overall_score"):
            v = m.get(k)
            if isinstance(v, (int, float)):
                return float(v)
    return None


def _score_band(score):
    """Required thresholds: green>70, yellow 40-70, red<40."""
    if not isinstance(score, (int, float)):
        return ("UNKNOWN", "dim")
    s = float(score)
    if s > 70:
        return ("GREEN", "green")
    if s >= 40:
        return ("YELLOW", "yellow")
    return ("RED", "red")


def _safe_float(x):
    """Convert value to float when possible; else None."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str) and x.strip():
        try:
            return float(x.strip())
        except Exception:
            return None
    return None


def _to_prob(conf):
    """Convert confidence 0-1 or 0-100 to probability in [0,1]."""
    v = _safe_float(conf)
    if v is None:
        return None
    p = float(v)
    if p > 1.0:
        p = p / 100.0
    if p < 0.0:
        p = 0.0
    if p > 1.0:
        p = 1.0
    return p


def _to_bool(x):
    """Convert common truthy/falsey values to bool; else None."""
    if x is None:
        return None
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        try:
            return bool(int(x))
        except Exception:
            return None
    if isinstance(x, str):
        s = x.strip().lower()
        if s in ("true", "t", "yes", "y", "1", "correct", "win", "won"):
            return True
        if s in ("false", "f", "no", "n", "0", "incorrect", "lose", "lost"):
            return False
    return None


def _grade_from_brier(brier):
    """Simple Brier→grade buckets (lower is better)."""
    if brier is None:
        return "N/A"
    b = float(brier)
    if b <= 0.05:
        return "A"
    if b <= 0.10:
        return "B"
    if b <= 0.20:
        return "C"
    if b <= 0.25:
        return "D"
    return "F"


def _print_tree(obj, indent: int = 0, depth: int = 6) -> None:
    """Lightweight pretty printer for dict/list structures."""
    pad = "  " * indent
    if depth <= 0:
        print(pad + "…")
        return
    if isinstance(obj, dict):
        keys = list(obj.keys())
        try:
            keys.sort(key=lambda k: str(k))
        except Exception:
            pass
        for k in keys:
            v = obj.get(k)
            if isinstance(v, (dict, list, tuple)):
                print(f"{pad}{k}:")
                _print_tree(v, indent + 1, depth - 1)
            else:
                print(f"{pad}{k}: {v}")
        return
    if isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            if isinstance(v, (dict, list, tuple)):
                print(f"{pad}[{i}]")
                _print_tree(v, indent + 1, depth - 1)
            else:
                print(f"{pad}- {v}")
        return
    print(pad + str(obj))


def _print_table(headers, rows):
    """Print a simple aligned table."""
    headers = [str(h) for h in headers]
    rows = [[("" if c is None else str(c)) for c in r] for r in (rows or [])]
    widths = [len(h) for h in headers]
    for r in rows:
        for i in range(min(len(headers), len(r))):
            widths[i] = max(widths[i], len(r[i]))

    def fmt(r):
        r = list(r) + [""] * (len(headers) - len(r))
        return " | ".join(r[i].ljust(widths[i]) for i in range(len(headers)))

    print(fmt(headers))
    print("-" * len(fmt(["-" * w for w in widths])))
    for r in rows:
        print(fmt(r))


def _list_tables(conn):
    """List sqlite tables (excluding sqlite_ internal)."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    rows = cur.fetchall() or []
    return [str(r[0]) for r in rows if r and r[0]]


def _table_columns(conn, table):
    """Return column names for a table via PRAGMA table_info."""
    cur = conn.cursor()
    cur.execute(f'PRAGMA table_info("{table}")')
    rows = cur.fetchall() or []
    out = []
    for r in rows:
        try:
            out.append(str(r[1]))  # name is index 1
        except Exception:
            pass
    return out


def _pick_ci(existing, candidates):
    """Pick first candidate present in existing (case-insensitive)."""
    m = {str(x).lower(): str(x) for x in (existing or [])}
    for cand in candidates:
        hit = m.get(str(cand).lower())
        if hit:
            return hit
    return None


def _pick_table(tables, preferred, token):
    """Pick by preferred names; else substring match by token."""
    lower = {t.lower(): t for t in (tables or [])}
    for p in preferred:
        hit = lower.get(str(p).lower())
        if hit:
            return hit
    tok = str(token or "").lower()
    for t in tables or []:
        if tok and tok in str(t).lower():
            return t
    return None


# -----------------------------
# Required command handlers
# -----------------------------

def cmd_health_report(_args) -> None:
    """Print full portfolio health to terminal (colorized by score)."""
    _section("Portfolio Health Report")

    ph = _import_first(["db.portfolio_health_view", "src.db.portfolio_health_view", "portfolio_health_view"])
    if ph is None:
        print(_c("ERROR:", "red"), "portfolio_health_view module not found.")
        return

    health = None
    for fn_name in ("get_portfolio_health", "portfolio_health", "get_health"):
        fn = getattr(ph, fn_name, None)
        if not callable(fn):
            continue
        try:
            health = fn()
            break
        except TypeError:
            # Some versions accept a DB connection.
            get_conn = _get_db_connection_fn()
            if callable(get_conn):
                try:
                    conn = get_conn()
                    try:
                        health = fn(conn)
                        break
                    finally:
                        try:
                            conn.close()
                        except Exception:
                            pass
                except Exception:
                    continue
        except Exception:
            continue

    if health is None:
        print(_c("ERROR:", "red"), "Could not compute portfolio health.")
        return

    if not isinstance(health, dict):
        health = {"raw": health}

    score = _extract_score(health)
    band, color = _score_band(score)
    score_str = f"{float(score):.1f}" if isinstance(score, (int, float)) else "unknown"
    print(f"Score: {_c(band, color)} ({score_str})")
    print("-" * 66)
    _print_tree(health, indent=0, depth=8)
    print("")


def cmd_export_json(args) -> None:
    """Export JSON snapshot to --output via save_snapshot_to_file()."""
    out_path = str(getattr(args, "output", "") or "").strip()
    if not out_path:
        print(_c("ERROR:", "red"), "--output flag is required.")
        return

    engine = _import_first(["core.export_engine", "src.core.export_engine", "export_engine"])
    if engine is None:
        print(_c("ERROR:", "red"), "export_engine module not found.")
        return

    fn = getattr(engine, "save_snapshot_to_file", None)
    if not callable(fn):
        print(_c("ERROR:", "red"), "save_snapshot_to_file() not found in export_engine.")
        return

    saved_path = None
    try:
        saved_path = fn(out_path)
    except TypeError:
        # Support common kwarg aliases (signature drift).
        for kw in ("output_path", "filepath", "path", "out_path", "filename"):
            try:
                saved_path = fn(**{kw: out_path})
                break
            except TypeError:
                continue
    except Exception as e:
        print(_c("ERROR:", "red"), f"Export failed: {e}")
        return

    final_path = str(saved_path or out_path)
    # File size without os: seek/tell.
    size_kb = "unknown"
    try:
        with open(final_path, "rb") as f:
            f.seek(0, 2)
            size_kb = int((int(f.tell()) + 1023) // 1024)
    except Exception:
        pass
    print(f"Exported to {final_path} ({size_kb}KB)")


def cmd_pain_report(_args) -> None:
    """Summary table: total, critical, active, resolved."""
    _section("Pain Report")

    items = []
    # Prefer persistence layer if present.
    persist = _import_first(["db.pain_persist", "src.db.pain_persist", "pain_persist"])
    if persist is not None:
        for fn_name in ("list_pain_records", "list_pains", "get_all_pains"):
            fn = getattr(persist, fn_name, None)
            if not callable(fn):
                continue
            try:
                res = fn()
            except TypeError:
                try:
                    res = fn(limit=10_000)
                except Exception:
                    continue
            except Exception:
                continue
            if isinstance(res, list):
                items = res
            elif isinstance(res, dict):
                for k in ("records", "items", "rows", "data"):
                    v = res.get(k)
                    if isinstance(v, list):
                        items = v
                        break
                else:
                    items = [res]
            elif res is not None:
                items = [res]
            break

    # DB fallback
    if not items:
        get_conn = _get_db_connection_fn()
        if not callable(get_conn):
            print(_c("ERROR:", "red"), "No pain data available (db_connect unavailable).")
            return

        conn = None
        try:
            conn = get_conn()
            tables = _list_tables(conn)
            pain_table = _pick_table(
                tables,
                preferred=["Pain_Point_Register", "pain_point_register", "PainPointRegister"],
                token="pain",
            )
            if not pain_table:
                print(_c("ERROR:", "red"), "Pain table not found in DB.")
                return

            cols = _table_columns(conn, pain_table)
            score_col = _pick_ci(cols, ["Pain_Score", "pain_score", "Score", "score"])
            status_col = _pick_ci(cols, ["Status", "status", "Pain_Status", "pain_status", "State", "state"])

            cur = conn.cursor()
            if score_col and status_col:
                cur.execute(f'SELECT "{score_col}", "{status_col}" FROM "{pain_table}"')
                rows = cur.fetchall() or []
                items = [{"pain_score": r[0], "status": r[1]} for r in rows]
            elif score_col:
                cur.execute(f'SELECT "{score_col}" FROM "{pain_table}"')
                rows = cur.fetchall() or []
                items = [{"pain_score": r[0]} for r in rows]
            elif status_col:
                cur.execute(f'SELECT "{status_col}" FROM "{pain_table}"')
                rows = cur.fetchall() or []
                items = [{"status": r[0]} for r in rows]
            else:
                cur.execute(f'SELECT COUNT(*) FROM "{pain_table}"')
                row = cur.fetchone()
                total = int(row[0]) if row and row[0] is not None else 0
                _print_table(["metric", "count"], [["total", total], ["critical", 0], ["active", total], ["resolved", 0]])
                print("")
                return
        finally:
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass

    def pain_score(rec):
        if not isinstance(rec, dict):
            return None
        for k in ("Pain_Score", "pain_score", "painScore", "score", "PainScorePct"):
            if k in rec:
                return _safe_float(rec.get(k))
        return None

    def pain_status(rec):
        if not isinstance(rec, dict):
            return ""
        for k in ("Status", "status", "Pain_Status", "pain_status", "State", "state"):
            if k in rec:
                v = rec.get(k)
                return str(v).strip() if v is not None else ""
        return ""

    total = len(items)
    critical = 0
    active = 0
    resolved = 0
    for rec in items:
        s = pain_score(rec)
        if isinstance(s, (int, float)) and float(s) > 70.0:
            critical += 1
        st = pain_status(rec).lower()
        if not st:
            active += 1
        elif ("resolv" in st) or (st in ("resolved", "closed", "done", "complete", "completed")):
            resolved += 1
        else:
            active += 1

    _print_table(
        ["metric", "count"],
        [["total", total], ["critical", critical], ["active", active], ["resolved", resolved]],
    )
    print("")


def cmd_prediction_report(_args) -> None:
    """Shows calibration grades per predictor."""
    _section("Prediction Calibration Report")

    # If a calibration module exists, try it first (but always support DB fallback).
    calib = _import_first(["calc.calc_calibration", "src.calc.calc_calibration", "calc_calibration"])
    if calib is not None:
        for fn_name in ("get_calibration_grades", "compute_calibration_grades", "calibration_grades", "predictor_grades"):
            fn = getattr(calib, fn_name, None)
            if not callable(fn):
                continue
            try:
                res = fn()
                if isinstance(res, list) and res and isinstance(res[0], dict):
                    rows = []
                    for r in res:
                        predictor = r.get("predictor") or r.get("Predictor") or r.get("name") or "unknown"
                        n = r.get("n") or r.get("count") or r.get("N") or ""
                        brier = r.get("brier") or r.get("Brier") or r.get("brier_score") or ""
                        grade = r.get("grade") or r.get("Grade") or r.get("calibration_grade") or ""
                        rows.append([predictor, n, brier, grade])
                    _print_table(["predictor", "n", "brier", "grade"], rows)
                    print("")
                    return
                if isinstance(res, dict) and res:
                    rows = [[k, "", "", res.get(k)] for k in sorted(res.keys(), key=lambda x: str(x))]
                    _print_table(["predictor", "n", "brier", "grade"], rows)
                    print("")
                    return
            except Exception:
                break  # fall back below

    get_conn = _get_db_connection_fn()
    if not callable(get_conn):
        print(_c("ERROR:", "red"), "db_connect unavailable; cannot compute calibration grades.")
        return

    conn = None
    try:
        conn = get_conn()
        tables = _list_tables(conn)
        pred_table = _pick_table(
            tables,
            preferred=["Prediction_Registry", "prediction_registry", "Predictions", "predictions"],
            token="prediction",
        )
        if not pred_table:
            print(_c("ERROR:", "red"), "Prediction table not found in DB.")
            return

        cols = _table_columns(conn, pred_table)
        predictor_col = _pick_ci(cols, ["Predictor", "Predicted_By", "Author", "Model", "Source"])
        conf_col = _pick_ci(cols, ["Confidence_Pct", "Predicted_Confidence", "Confidence"])
        outcome_col = _pick_ci(cols, ["Outcome", "Actual_Outcome", "Correct", "Is_Correct"])

        if not conf_col or not outcome_col:
            print(_c("ERROR:", "red"), "Prediction table missing confidence/outcome columns.")
            return

        p_col_sql = f'"{predictor_col}"' if predictor_col else "'unknown'"
        sql = (
            f'SELECT {p_col_sql} AS predictor, "{conf_col}" AS conf, "{outcome_col}" AS outcome '
            f'FROM "{pred_table}" '
            f'WHERE "{outcome_col}" IS NOT NULL AND TRIM(CAST("{outcome_col}" AS TEXT)) <> ""'
        )
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall() or []
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass

    buckets = {}  # predictor -> {"n": int, "sum": float}
    for r in rows:
        predictor = str(r[0]) if r and r[0] is not None else "unknown"
        p = _to_prob(r[1] if len(r) > 1 else None)
        outcome = _to_bool(r[2] if len(r) > 2 else None)
        if p is None or outcome is None:
            continue
        brier = (float(p) - (1.0 if outcome else 0.0)) ** 2
        b = buckets.get(predictor)
        if b is None:
            buckets[predictor] = {"n": 1, "sum": float(brier)}
        else:
            b["n"] = int(b.get("n", 0)) + 1
            b["sum"] = float(b.get("sum", 0.0)) + float(brier)

    if not buckets:
        print("No resolved predictions found (nothing to grade).")
        return

    out = []
    for predictor in sorted(buckets.keys(), key=lambda x: str(x).lower()):
        n = int(buckets[predictor]["n"])
        mean_brier = float(buckets[predictor]["sum"]) / float(max(1, n))
        out.append([predictor, n, f"{mean_brier:.3f}", _grade_from_brier(mean_brier)])

    _print_table(["predictor", "n", "brier", "grade"], out)
    print("")


def cmd_full_report(args) -> None:
    """Runs all reports in sequence (daily briefing printout)."""
    _section("aeOS — Full Report")
    for title, fn in (
        ("Portfolio Health", cmd_health_report),
        ("Pain Summary", cmd_pain_report),
        ("Prediction Calibration", cmd_prediction_report),
    ):
        try:
            fn(args)
        except Exception as e:
            print(_c("ERROR:", "red"), f"{title} failed: {e}")
            print("")

    # Optional export if user provided --output
    if str(getattr(args, "output", "") or "").strip():
        cmd_export_json(args)
        print("")


# -----------------------------
# CLI entry point
# -----------------------------

def _build_parser():
    """Argparse router for report commands."""
    p = argparse.ArgumentParser(
        prog="aeos-report",
        description="aeOS report commands (Phase 3).",
        epilog="Example: python -m src.cli.cli_report full",
    )
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("health", help="Print portfolio health report.")
    sp.set_defaults(handler=cmd_health_report)

    sp = sub.add_parser("pain", help="Print pain summary report.")
    sp.set_defaults(handler=cmd_pain_report)

    sp = sub.add_parser("predictions", help="Print prediction calibration report.")
    sp.set_defaults(handler=cmd_prediction_report)

    sp = sub.add_parser("export-json", help="Export JSON snapshot to a file.")
    sp.add_argument("--output", required=True, help="Output filepath for JSON snapshot.")
    sp.set_defaults(handler=cmd_export_json)

    sp = sub.add_parser("full", help="Run all reports in sequence.")
    sp.add_argument("--output", default="", help="Optional output filepath for JSON snapshot.")
    sp.set_defaults(handler=cmd_full_report)

    return p


def main(argv=None) -> int:
    """Entry point for cli_main delegation or direct execution."""
    argv = sys.argv[1:] if argv is None else argv
    parser = _build_parser()
    args = parser.parse_args(argv)

    handler = getattr(args, "handler", None)
    if not callable(handler):
        parser.print_help()
        return 2

    try:
        handler(args)
        return 0
    except KeyboardInterrupt:
        print(_c("Interrupted.", "yellow"))
        return 130
    except Exception as e:
        print(_c("ERROR:", "red"), str(e))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
