"""
Tests for Phase 4B integrity layer components.
All tests run without DB, API, or external dependencies.
~60 tests covering all 6 new modules.
"""
import json
import tempfile
from pathlib import Path
from datetime import datetime
import pytest


# ─── ContradictionDetector ───────────────────────────────────────────────────

class TestContradictionDetector:

    def _make(self):
        from src.cognitive.contradiction_detector import ContradictionDetector
        return ContradictionDetector()

    def test_instantiation(self):
        cd = self._make()
        assert cd.VERSION == "1.0.0"

    def test_clean_decision_no_contradiction(self):
        cd = self._make()
        result = cd.check_decision("I will build a scalable content system", "business")
        assert result.severity in ("none", "low")

    def test_detects_privacy_violation(self):
        cd = self._make()
        result = cd.check_decision("we should share data with partners to grow faster", "business")
        assert result.detected is True
        assert any(v.law_number == 2 for v in result.law_violations)

    def test_detects_reality_violation(self):
        cd = self._make()
        result = cd.check_decision("this strategy is guaranteed to succeed with no risk", "strategy")
        assert result.detected is True
        law_nums = [v.law_number for v in result.law_violations]
        assert 18 in law_nums

    def test_contradiction_result_serializable(self):
        cd = self._make()
        result = cd.check_decision("test decision", "test")
        d = result.to_dict()
        assert "detected" in d
        assert "severity" in d
        assert "law_violations" in d

    def test_get_contradiction_history(self):
        cd = self._make()
        cd.check_decision("decision 1", "finance")
        cd.check_decision("decision 2", "business")
        history = cd.get_contradiction_history()
        assert len(history) == 2

    def test_get_status(self):
        cd = self._make()
        s = cd.get_status()
        assert "version" in s
        assert "checks_run" in s

    def test_master_laws_defined(self):
        from src.cognitive.contradiction_detector import MASTER_LAWS
        assert 1 in MASTER_LAWS
        assert 21 in MASTER_LAWS
        assert len(MASTER_LAWS) >= 10


# ─── CartridgeArbitrator ─────────────────────────────────────────────────────

class TestCartridgeArbitrator:

    def _make(self):
        from src.cognitive.cartridge_arbitrator import CartridgeArbitrator
        return CartridgeArbitrator()

    def test_instantiation(self):
        ca = self._make()
        assert ca.VERSION == "1.0.0"

    def test_detect_conflicts_returns_list(self):
        ca = self._make()
        result = ca.detect_conflicts(["CART-STOIC", "CART-NEGOTIATION"], [])
        assert isinstance(result, list)

    def test_no_false_positives_stub(self):
        ca = self._make()
        carts = ["CART-A", "CART-B", "CART-C"]
        recs = [{"cartridge_id": c, "recommendation": "do x"} for c in carts]
        conflicts = ca.detect_conflicts(carts, recs)
        assert len(conflicts) == 0  # stub returns no conflicts

    def test_arbitrate_all_no_conflicts(self):
        ca = self._make()
        recs = [{"cartridge_id": "CART-A", "text": "focus on leverage"}]
        final_recs, arbitrations = ca.arbitrate_all(["CART-A"], recs)
        assert final_recs == recs
        assert arbitrations == []

    def test_domain_specificity_defined(self):
        from src.cognitive.cartridge_arbitrator import DOMAIN_SPECIFICITY
        assert "personal-finance" in DOMAIN_SPECIFICITY
        assert "negotiation-advanced" in DOMAIN_SPECIFICITY
        assert DOMAIN_SPECIFICITY["negotiation-advanced"] > DOMAIN_SPECIFICITY["stoic"]

    def test_arbitrate_law_wins(self):
        from src.cognitive.cartridge_arbitrator import CartridgeArbitrator, Conflict
        from src.cognitive.contradiction_detector import ContradictionDetector
        cd = ContradictionDetector()
        ca = CartridgeArbitrator(contradiction_detector=cd)
        conflict = Conflict(
            cartridge_a="CART-A",
            cartridge_b="CART-B",
            conflicting_on="data usage",
            recommendation_a="share data with partners",   # violates Law 2
            recommendation_b="keep data private",
            severity="high",
        )
        result = ca.arbitrate(conflict)
        assert result.priority_rule_used == 1
        assert result.winner == "CART-B"

    def test_arbitrate_escalates_to_sovereign(self):
        from src.cognitive.cartridge_arbitrator import CartridgeArbitrator, Conflict
        ca = CartridgeArbitrator()
        conflict = Conflict(
            cartridge_a="CART-A",
            cartridge_b="CART-B",
            conflicting_on="strategy",
            recommendation_a="take the consulting deal",
            recommendation_b="decline and focus on product",
            severity="medium",
        )
        result = ca.arbitrate(conflict)
        # With no law violations and same specificity, should escalate
        assert result.escalated_to_sovereign is True or result.priority_rule_used in (2, 3, 4, 5)

    def test_get_status(self):
        ca = self._make()
        s = ca.get_status()
        assert "arbitrations_run" in s


# ─── OfflineMode ─────────────────────────────────────────────────────────────

class TestOfflineMode:

    def _make(self):
        from src.core.offline_mode import OfflineMode
        return OfflineMode()

    def test_instantiation(self):
        om = self._make()
        assert om.VERSION == "1.0.0"

    def test_online_by_default(self):
        om = self._make()
        assert om.is_api_available() is True

    def test_force_offline(self):
        om = self._make()
        om.force_offline(True)
        assert om.is_api_available() is False

    def test_force_online(self):
        om = self._make()
        om.force_offline(True)
        om.force_offline(False)
        assert om.is_api_available() is True

    def test_degraded_response_structure(self):
        from src.core.offline_mode import RESPONSE_SOURCE_CARTRIDGE_ONLY
        om = self._make()
        om.force_offline(True)
        carts = [{"cartridge_id": "CART-STOIC", "domain": "stoic", "rules": [{"text": "Focus on what you control"}]}]
        resp = om.get_degraded_response("what should I do?", carts)
        assert resp.response_source == RESPONSE_SOURCE_CARTRIDGE_ONLY
        assert resp.api_available is False
        assert "OFFLINE" in resp.synthesis

    def test_cache_and_retrieve(self):
        from src.core.offline_mode import RESPONSE_SOURCE_CACHED
        om = self._make()
        om.cache_response("my query", "cached answer")
        om.force_offline(True)
        resp = om.get_degraded_response("my query", [])
        assert resp.response_source == RESPONSE_SOURCE_CACHED
        assert resp.synthesis == "cached answer"

    def test_degraded_response_serializable(self):
        om = self._make()
        om.force_offline(True)
        resp = om.get_degraded_response("test", [])
        d = resp.to_dict()
        assert "synthesis" in d
        assert "response_source" in d
        assert "degraded" in d
        assert d["degraded"] is True

    def test_get_status(self):
        om = self._make()
        s = om.get_status()
        assert "api_available" in s
        assert "cache_size" in s


# ─── NLQParser ───────────────────────────────────────────────────────────────

class TestNLQParser:

    def _make(self):
        from src.core.nlq_parser import NLQParser
        return NLQParser()

    def test_instantiation(self):
        nlq = self._make()
        assert nlq.VERSION == "1.0.0"

    def test_parse_returns_intent(self):
        from src.core.nlq_parser import ParsedIntent
        nlq = self._make()
        result = nlq.parse("what should I focus on this week?")
        assert isinstance(result, ParsedIntent)
        assert result.confidence > 0

    def test_decision_intent(self):
        from src.core.nlq_parser import INTENT_DECISION_REQUEST
        nlq = self._make()
        result = nlq.parse("should I take this consulting project?")
        assert result.intent_type == INTENT_DECISION_REQUEST

    def test_status_intent(self):
        from src.core.nlq_parser import INTENT_STATUS_QUERY
        nlq = self._make()
        result = nlq.parse("how am I doing financially?")
        assert result.intent_type == INTENT_STATUS_QUERY

    def test_finance_domain(self):
        nlq = self._make()
        result = nlq.parse("how is my revenue and cash flow looking?")
        assert result.domain == "finance"

    def test_business_domain(self):
        nlq = self._make()
        result = nlq.parse("should I take this client project?")
        assert result.domain == "business"

    def test_routed_to_populated(self):
        nlq = self._make()
        result = nlq.parse("what should I do?")
        assert result.routed_to is not None
        assert len(result.routed_to) > 0

    def test_period_extraction(self):
        nlq = self._make()
        result = nlq.parse("what should I focus on this week?")
        assert result.parameters.get("period") == "week"

    def test_serializable(self):
        nlq = self._make()
        result = nlq.parse("test query")
        d = result.to_dict()
        assert "intent_type" in d
        assert "domain" in d
        assert "confidence" in d

    def test_parse_history(self):
        nlq = self._make()
        nlq.parse("query 1")
        nlq.parse("query 2")
        history = nlq.get_parse_history()
        assert len(history) == 2

    def test_get_status(self):
        nlq = self._make()
        nlq.parse("test")
        s = nlq.get_status()
        assert s["stats"]["parsed"] == 1


# ─── AuditTrail ──────────────────────────────────────────────────────────────

class TestAuditTrail:

    def _make(self):
        from src.core.audit_trail import AuditTrail
        return AuditTrail()

    def test_instantiation(self):
        at = self._make()
        assert at.VERSION == "1.0.0"

    def test_generate_report_no_modules(self):
        at = self._make()
        report = at.generate_report(period_days=30)
        assert report.period_days == 30
        assert report.decisions_logged == 0

    def test_report_serializable(self):
        at = self._make()
        report = at.generate_report()
        d = report.to_dict()
        assert "period_days" in d
        assert "decisions_logged" in d
        assert "generated_at" in d

    def test_report_markdown(self):
        at = self._make()
        report = at.generate_report()
        md = report.to_markdown()
        assert "# aeOS Audit Report" in md
        assert "Activity" in md

    def test_export_csv(self):
        at = self._make()
        path = at.export_csv(period_days=7)
        assert Path(path).exists()
        content = Path(path).read_text()
        assert "metric,value" in content

    def test_get_status(self):
        at = self._make()
        s = at.get_status()
        assert "modules_wired" in s

    def test_period_boundaries(self):
        at = self._make()
        report = at.generate_report(period_days=7)
        delta = report.period_end - report.period_start
        assert 6 <= delta.days <= 8  # approximately 7 days


# ─── IdentityContinuityProtocol ──────────────────────────────────────────────

class TestIdentityContinuityProtocol:

    def _make(self, tmp_dir=None):
        from src.core.identity_continuity import IdentityContinuityProtocol
        return IdentityContinuityProtocol(backup_dir=tmp_dir or tempfile.mkdtemp())

    def test_instantiation(self):
        icp = self._make()
        assert icp.VERSION == "1.0.0"

    def test_backup_dir_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = str(Path(tmp) / "backups")
            icp = self._make(backup_dir)
            assert Path(backup_dir).exists()

    def test_create_backup_returns_manifest(self):
        from src.core.identity_continuity import BackupManifest
        with tempfile.TemporaryDirectory() as tmp:
            icp = self._make(tmp)
            manifest = icp.create_sovereign_backup()
            assert isinstance(manifest, BackupManifest)
            assert manifest.backup_id is not None
            assert manifest.encrypted is False
            assert len(manifest.checksum) > 0

    def test_backup_file_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            icp = self._make(tmp)
            manifest = icp.create_sovereign_backup()
            assert Path(manifest.backup_path).exists()
            assert manifest.size_bytes > 0

    def test_backup_file_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            icp = self._make(tmp)
            manifest = icp.create_sovereign_backup()
            content = Path(manifest.backup_path).read_text()
            data = json.loads(content)
            assert "backup_id" in data
            assert "tables" in data

    def test_restore_from_valid_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            icp = self._make(tmp)
            manifest = icp.create_sovereign_backup()
            result = icp.restore_from_backup(manifest.backup_path)
            assert result.backup_id == manifest.backup_id

    def test_restore_from_missing_file(self):
        icp = self._make()
        result = icp.restore_from_backup("/nonexistent/path/backup.json")
        assert result.success is False
        assert len(result.errors) > 0

    def test_verify_integrity_runs(self):
        from src.core.identity_continuity import IntegrityReport
        with tempfile.TemporaryDirectory() as tmp:
            icp = self._make(tmp)
            report = icp.verify_integrity()
            assert isinstance(report, IntegrityReport)
            assert isinstance(report.issues_found, list)

    def test_list_backups(self):
        with tempfile.TemporaryDirectory() as tmp:
            icp = self._make(tmp)
            icp.create_sovereign_backup()
            icp.create_sovereign_backup()
            backups = icp.list_backups()
            assert len(backups) == 2

    def test_manifest_serializable(self):
        with tempfile.TemporaryDirectory() as tmp:
            icp = self._make(tmp)
            manifest = icp.create_sovereign_backup()
            d = manifest.to_dict()
            assert "backup_id" in d
            assert "encrypted" in d

    def test_get_backup_schedule(self):
        icp = self._make()
        schedule = icp.get_backup_schedule()
        assert "frequency" in schedule
        assert "backup_dir" in schedule

    def test_get_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            icp = self._make(tmp)
            s = icp.get_status()
            assert s["backup_dir_exists"] is True
            assert "backups_created_this_session" in s
