"""
aeOS CLI — commands routing through AeOSCore.
Phase 4 fills implementations.
Usage:
    python -m aeos.cli query "Should I take this consulting deal?"
    python -m aeos.cli status
    python -m aeos.cli cartridges list
    python -m aeos.cli cartridges reload
    python -m aeos.cli decisions log
    python -m aeos.cli decisions list
    python -m aeos.cli decisions patterns
    python -m aeos.cli pain-scan "I hate my job"
    python -m aeos.cli causal-inference "What drives my best decisions?"
    python -m aeos.cli flywheel metrics
    python -m aeos.cli evolution proposals
    python -m aeos.cli evolution approve <id>
    python -m aeos.cli events recent
    python -m aeos.cli validate-cartridges
    python -m aeos.cli audit [--days 30]
    python -m aeos.cli backup
    python -m aeos.cli restore <path>
    python -m aeos.cli verify
"""
from __future__ import annotations
import argparse
import json
import sys
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core bootstrap
# ---------------------------------------------------------------------------
_core = None


def _get_core():
    global _core
    if _core is None:
        from src.cognitive.aeos_core import AeOSCore
        _core = AeOSCore()
        _core.initialize()
    return _core


def _print(data: Any, pretty: bool = True) -> None:
    if isinstance(data, dict):
        print(json.dumps(data, indent=2 if pretty else None, default=str))
    else:
        print(data)


def _error(msg: str, exit_code: int = 1) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return exit_code


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------
def cmd_query(args) -> int:
    """POST /api/v1/query"""
    core = _get_core()
    from src.cognitive.aeos_core import QueryMode
    mode = QueryMode(args.mode) if args.mode else QueryMode.BALANCED
    resp = core.query(text=args.text, mode=mode)
    if args.raw:
        _print(resp.to_dict())
    else:
        print(f"\n{'='*60}")
        print(f"Query  : {resp.query[:80]}")
        print(f"Mode   : {resp.mode.value}")
        print(f"Gates  : {resp.four_gate.to_dict()}")
        print(f"Pain   : {resp.pain_score}")
        print(f"Carts  : {', '.join(resp.cartridges_used) or 'none'}")
        print(f"\nSYNTHESIS:\n{resp.synthesis}")
        print(f"\nDuration: {resp.duration_ms:.0f}ms  |  Flywheel: {'✓' if resp.flywheel_logged else '✗'}")
        if resp.error:
            print(f"ERROR: {resp.error}")
    return 0 if resp.success else 1


def cmd_status(args) -> int:
    """GET /api/v1/status"""
    core = _get_core()
    status = core.get_status()
    health = core.health_check()
    if args.raw:
        _print(health)
    else:
        print(f"\naeOS v{core.VERSION} — {health['status'].upper()}")
        print(f"  Health      : {status.health_score:.0%}")
        print(f"  Cartridges  : {status.cartridges_loaded}/{status.cartridges_target}")
        print(f"  Flywheel    : {status.flywheel_decisions} decisions")
        print(f"  Causal      : {'ready' if status.causal_ready else f'needs {30 - status.flywheel_decisions} more decisions'}")
        print(f"  Twin        : {'ready' if status.twin_ready else 'not yet'}")
        print(f"  Queries     : {status.total_queries}")
        print(f"  Modules OK  : {', '.join(status.modules_wired)}")
        if status.modules_missing:
            print(f"  Modules ✗   : {', '.join(status.modules_missing)}")
    return 0


def cmd_cartridges_list(args) -> int:
    """GET /api/v1/cartridges"""
    core = _get_core()
    loader = core._cartridge_loader
    if not loader:
        return _error("CartridgeLoader not available")
    carts = loader.get_all()
    if args.domain:
        carts = [c for c in carts if c.get("domain") == args.domain]
    if args.raw:
        _print({"cartridges": carts, "count": len(carts)})
    else:
        print(f"\n{'ID':<35} {'Domain':<25} Rules")
        print("-" * 70)
        for c in sorted(carts, key=lambda x: x.get("cartridge_id", "")):
            print(f"{c.get('cartridge_id',''):<35} {c.get('domain',''):<25} {len(c.get('rules', []))}")
        print(f"\nTotal: {len(carts)}")
    return 0


def cmd_cartridges_reload(args) -> int:
    """POST /api/v1/cartridges/reload"""
    core = _get_core()
    loader = core._cartridge_loader
    if not loader:
        return _error("CartridgeLoader not available")
    count = loader.load_all()
    print(f"✓ Reloaded {count} cartridges")
    return 0


def cmd_decisions_log(args) -> int:
    """POST /api/v1/decisions — interactive if no args"""
    core = _get_core()
    fl = core._flywheel_logger
    if not fl:
        return _error("FlywheelLogger not available")
    # Phase 4: implement interactive or --description flag
    print("Phase 4: interactive decision logging not yet implemented")
    print("Use: python scripts/import_founding_decisions.py for bulk import")
    return 0


def cmd_decisions_list(args) -> int:
    """GET /api/v1/decisions"""
    core = _get_core()
    fl = core._flywheel_logger
    if not fl:
        return _error("FlywheelLogger not available")
    # Phase 4: fl.get_recent(args.limit)
    print(f"Flywheel decisions: {fl.count()} logged")
    print("Phase 4: list command not yet implemented")
    return 0


def cmd_decisions_patterns(args) -> int:
    """GET /api/v1/decisions/patterns"""
    core = _get_core()
    pe = core._pattern_engine
    if not pe:
        return _error("PatternEngine not available")
    # Phase 4: pe.get_decision_patterns()
    print("Phase 4: pattern analysis not yet implemented")
    return 0


def cmd_pain_scan(args) -> int:
    """POST /api/v1/pain-scan"""
    core = _get_core()
    de = core._decision_engine
    if not de:
        return _error("DecisionEngine not available")
    score = de.compute_pain_score(args.text, {})
    print(f"\nPain Score: {score}")
    print(f"Text      : {args.text[:100]}")
    return 0


def cmd_causal_inference(args) -> int:
    """POST /api/v1/causal-inference"""
    core = _get_core()
    status = core.get_status()
    if not status.causal_ready:
        print(f"CausalEngine needs 30+ decisions. Current: {status.flywheel_decisions}")
        return 1
    ce = core._causal_engine
    if not ce:
        return _error("CausalInferenceEngine not available")
    result = ce.infer(args.text, {})
    _print(result)
    return 0


def cmd_flywheel_metrics(args) -> int:
    """GET /api/v1/flywheel/metrics"""
    core = _get_core()
    fl = core._flywheel_logger
    if not fl:
        return _error("FlywheelLogger not available")
    # Phase 4: fl.get_metrics()
    print(f"Flywheel decisions logged: {fl.count()}")
    print("Phase 4: full metrics not yet implemented")
    return 0


def cmd_evolution_proposals(args) -> int:
    """GET /api/v1/evolution/proposals"""
    core = _get_core()
    ee = core._evolution_engine
    if not ee:
        print("EvolutionEngine not yet wired (Month 3 feature)")
        return 0
    # Phase 4: ee.get_pending_proposals()
    print("Phase 4: evolution proposals not yet implemented")
    return 0


def cmd_evolution_approve(args) -> int:
    """POST /api/v1/evolution/approve"""
    print(f"Phase 4: proposal approval not yet implemented (id={args.proposal_id})")
    return 0


def cmd_events_recent(args) -> int:
    """GET /api/v1/events/recent"""
    core = _get_core()
    eb = core._event_bus
    if not eb:
        return _error("EventBus not available")
    events = eb.get_recent_events(limit=args.limit, topic_filter=args.topic)
    if args.raw:
        _print({"events": events})
    else:
        print(f"\nRecent Events (last {len(events)})")
        print(f"{'Topic':<35} {'Source':<20} Timestamp")
        print("-" * 75)
        for e in events:
            print(f"{e['topic']:<35} {e['source']:<20} {e['timestamp']}")
    return 0


def cmd_validate_cartridges(args) -> int:
    """Validate all cartridge files."""
    from scripts.validate_cartridges import run_validation
    return run_validation(args.dir, strict=args.strict)


# Phase 4B CLI commands

def cmd_audit(args) -> int:
    """GET /api/v1/audit"""
    core = _get_core()
    at = core._audit_trail
    if not at:
        return _error("AuditTrail not available")
    report = at.generate_report(period_days=args.days)
    if args.raw:
        _print(report.to_dict())
    else:
        print(report.to_markdown())
    return 0


def cmd_backup(args) -> int:
    """POST /api/v1/backup"""
    core = _get_core()
    icp = core._identity_continuity
    if not icp:
        return _error("IdentityContinuityProtocol not available")
    manifest = icp.create_sovereign_backup()
    if args.raw:
        _print(manifest.to_dict())
    else:
        print(f"✓ Backup created: {manifest.backup_path}")
        print(f"  ID       : {manifest.backup_id}")
        print(f"  Tables   : {len(manifest.tables_included)}")
        print(f"  Decisions: {manifest.decision_count}")
        print(f"  Size     : {manifest.size_bytes} bytes")
        print(f"  Checksum : {manifest.checksum}")
        print(f"  Encrypted: {manifest.encrypted}")
    return 0


def cmd_restore(args) -> int:
    """POST /api/v1/restore"""
    core = _get_core()
    icp = core._identity_continuity
    if not icp:
        return _error("IdentityContinuityProtocol not available")
    result = icp.restore_from_backup(args.path)
    if result.success:
        print(f"✓ Restored backup: {result.backup_id}")
        print(f"  Tables   : {', '.join(result.tables_restored)}")
        print(f"  Decisions: {result.decisions_restored}")
    else:
        print(f"✗ Restore failed")
        for err in result.errors:
            print(f"  ERROR: {err}")
    return 0 if result.success else 1


def cmd_verify(args) -> int:
    """GET /api/v1/verify"""
    core = _get_core()
    icp = core._identity_continuity
    if not icp:
        return _error("IdentityContinuityProtocol not available")
    report = icp.verify_integrity()
    if args.raw:
        _print(report.to_dict())
    else:
        status = "✓ HEALTHY" if report.healthy else "✗ ISSUES FOUND"
        print(f"\nIntegrity: {status}")
        print(f"  Tables intact       : {report.all_tables_intact}")
        print(f"  Decision chain valid: {report.decision_chain_valid}")
        print(f"  Cartridges loadable : {report.cartridges_loadable}")
        print(f"  Score reproducible  : {report.compound_score_reproducible}")
        if report.issues_found:
            print(f"\n  Issues:")
            for issue in report.issues_found:
                print(f"    - {issue}")
    return 0 if report.healthy else 1


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aeos", description="aeOS Intelligence CLI")
    p.add_argument("--raw", action="store_true", help="Output raw JSON")
    p.add_argument("--log-level", default="WARNING", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    sub = p.add_subparsers(dest="command", required=True)

    # query
    q = sub.add_parser("query", help="Run a query through AeOSCore")
    q.add_argument("text", help="Query text")
    q.add_argument("--mode", default="balanced", choices=["fast", "balanced", "quality", "maximum"])
    q.set_defaults(func=cmd_query)

    # status
    s = sub.add_parser("status", help="System status and health")
    s.set_defaults(func=cmd_status)

    # cartridges
    cart = sub.add_parser("cartridges", help="Cartridge management")
    cart_sub = cart.add_subparsers(dest="subcommand", required=True)
    cl = cart_sub.add_parser("list", help="List loaded cartridges")
    cl.add_argument("--domain", help="Filter by domain")
    cl.set_defaults(func=cmd_cartridges_list)
    cr = cart_sub.add_parser("reload", help="Hot-reload cartridges from disk")
    cr.set_defaults(func=cmd_cartridges_reload)

    # decisions
    dec = sub.add_parser("decisions", help="Flywheel decision log")
    dec_sub = dec.add_subparsers(dest="subcommand", required=True)
    dec_sub.add_parser("log", help="Log a new decision").set_defaults(func=cmd_decisions_log)
    dl = dec_sub.add_parser("list", help="List decisions")
    dl.add_argument("--limit", type=int, default=20)
    dl.set_defaults(func=cmd_decisions_list)
    dec_sub.add_parser("patterns", help="Pattern analysis").set_defaults(func=cmd_decisions_patterns)

    # pain-scan
    ps = sub.add_parser("pain-scan", help="Compute pain score on text")
    ps.add_argument("text", help="Text to scan")
    ps.set_defaults(func=cmd_pain_scan)

    # causal-inference
    ci = sub.add_parser("causal-inference", help="Causal inference query")
    ci.add_argument("text", help="Query text")
    ci.set_defaults(func=cmd_causal_inference)

    # flywheel
    fw = sub.add_parser("flywheel", help="Flywheel metrics")
    fw_sub = fw.add_subparsers(dest="subcommand", required=True)
    fw_sub.add_parser("metrics").set_defaults(func=cmd_flywheel_metrics)

    # evolution
    ev = sub.add_parser("evolution", help="Cartridge evolution proposals")
    ev_sub = ev.add_subparsers(dest="subcommand", required=True)
    ev_sub.add_parser("proposals").set_defaults(func=cmd_evolution_proposals)
    ea = ev_sub.add_parser("approve")
    ea.add_argument("proposal_id")
    ea.set_defaults(func=cmd_evolution_approve)

    # events
    en = sub.add_parser("events", help="EventBus event log")
    en_sub = en.add_subparsers(dest="subcommand", required=True)
    er = en_sub.add_parser("recent")
    er.add_argument("--limit", type=int, default=50)
    er.add_argument("--topic", help="Filter by topic")
    er.set_defaults(func=cmd_events_recent)

    # validate-cartridges
    vc = sub.add_parser("validate-cartridges", help="Validate cartridge JSON files")
    vc.add_argument("--dir", default="src/cartridges")
    vc.add_argument("--strict", action="store_true")
    vc.set_defaults(func=cmd_validate_cartridges)

    # Phase 4B commands
    # audit
    au = sub.add_parser("audit", help="Generate audit report")
    au.add_argument("--days", type=int, default=30, help="Report period in days")
    au.set_defaults(func=cmd_audit)

    # backup
    bu = sub.add_parser("backup", help="Create sovereign backup")
    bu.set_defaults(func=cmd_backup)

    # restore
    re_ = sub.add_parser("restore", help="Restore from backup")
    re_.add_argument("path", help="Path to backup file")
    re_.set_defaults(func=cmd_restore)

    # verify
    ve = sub.add_parser("verify", help="Verify data integrity")
    ve.set_defaults(func=cmd_verify)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level))
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
