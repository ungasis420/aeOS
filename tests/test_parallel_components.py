"""
tests/test_parallel_components.py
Tests for EventBus, AeOSCore skeleton, KBBridge, UnifiedRouter, CLI, CartridgeValidator.
All tests run without external dependencies.
"""
import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# EventBus tests
# ---------------------------------------------------------------------------
class TestEventBus:
    def setup_method(self):
        from src.core.event_bus import EventBus
        self.bus = EventBus()

    def test_subscribe_and_publish(self):
        received = []
        self.bus.subscribe("test.topic", lambda e: received.append(e.payload), "test")
        self.bus.emit("test.topic", {"msg": "hello"}, source="pytest")
        assert len(received) == 1
        assert received[0]["msg"] == "hello"

    def test_wildcard_subscription(self):
        received = []
        self.bus.subscribe("decision.*", lambda e: received.append(e.topic), "test")
        self.bus.emit("decision.created", {}, source="pytest")
        self.bus.emit("decision.updated", {}, source="pytest")
        self.bus.emit("cartridge.loaded", {}, source="pytest")  # should NOT match
        assert len(received) == 2
        assert "decision.created" in received
        assert "decision.updated" in received

    def test_unsubscribe(self):
        received = []
        sid = self.bus.subscribe("test.topic", lambda e: received.append(1), "test")
        self.bus.emit("test.topic", {})
        self.bus.unsubscribe(sid)
        self.bus.emit("test.topic", {})
        assert len(received) == 1

    def test_unsubscribe_all(self):
        self.bus.subscribe("topic.a", lambda e: None, "subscriber_x")
        self.bus.subscribe("topic.b", lambda e: None, "subscriber_x")
        removed = self.bus.unsubscribe_all("subscriber_x")
        assert removed == 2

    def test_handler_error_isolated(self):
        """Error in one handler must not prevent others from receiving."""
        results = []

        def bad_handler(e):
            raise ValueError("intentional error")

        def good_handler(e):
            results.append("ok")

        self.bus.subscribe("test.topic", bad_handler, "bad")
        self.bus.subscribe("test.topic", good_handler, "good")
        count = self.bus.emit("test.topic", {})
        assert count == 1  # bad handler failed, good handler succeeded
        assert results == ["ok"]

    def test_stats(self):
        self.bus.subscribe("t", lambda e: None, "x")
        self.bus.emit("t", {})
        stats = self.bus.get_stats()
        assert stats["published"] == 1
        assert stats["delivered"] == 1
        assert stats["subscriptions_created"] == 1

    def test_get_recent_events(self):
        self.bus.emit("topic.a", {"x": 1}, source="src1")
        self.bus.emit("topic.b", {"x": 2}, source="src2")
        events = self.bus.get_recent_events(limit=10)
        assert len(events) == 2
        filtered = self.bus.get_recent_events(topic_filter="topic.a")
        assert len(filtered) == 1

    def test_singleton(self):
        from src.core.event_bus import get_event_bus, reset_event_bus
        reset_event_bus()
        b1 = get_event_bus()
        b2 = get_event_bus()
        assert b1 is b2
        reset_event_bus()

    def test_event_create(self):
        from src.core.event_bus import Event
        e = Event.create("my.topic", {"key": "val"}, source="test", extra="meta")
        assert e.topic == "my.topic"
        assert e.source == "test"
        assert e.metadata["extra"] == "meta"
        assert len(e.event_id) > 8


# ---------------------------------------------------------------------------
# AeOSCore skeleton tests
# ---------------------------------------------------------------------------
class TestAeOSCore:
    def _make_core(self):
        from src.cognitive.aeos_core import AeOSCore
        core = AeOSCore()
        return core

    def test_instantiation(self):
        core = self._make_core()
        assert core.VERSION == "9.0.0"
        assert not core._initialized

    def test_query_before_init(self):
        core = self._make_core()
        resp = core.query("test query")
        assert not resp.success
        assert "not initialized" in resp.error.lower()

    def test_health_check_before_init(self):
        core = self._make_core()
        health = core.health_check()
        assert "initialized" in health
        assert health["initialized"] is False

    def test_get_status_before_init(self):
        core = self._make_core()
        status = core.get_status()
        assert status.initialized is False
        assert status.health_score == 0.0

    def test_four_gate_result(self):
        from src.cognitive.aeos_core import FourGateResult, GateStatus
        fg = FourGateResult(
            gate_1_safe=GateStatus.PASS,
            gate_2_true=GateStatus.PASS,
            gate_3_leverage=GateStatus.PASS,
            gate_4_aligned=GateStatus.PASS,
        )
        assert fg.all_pass is True
        d = fg.to_dict()
        assert d["all_pass"] is True

    def test_four_gate_fail(self):
        from src.cognitive.aeos_core import FourGateResult, GateStatus
        fg = FourGateResult(gate_1_safe=GateStatus.FAIL)
        assert fg.all_pass is False

    def test_query_response_serialization(self):
        from src.cognitive.aeos_core import QueryResponse, QueryMode
        resp = QueryResponse(
            query_id="test-123",
            query="hello",
            mode=QueryMode.BALANCED,
            synthesis="answer",
        )
        d = resp.to_dict()
        assert d["query_id"] == "test-123"
        assert d["mode"] == "balanced"
        assert "timestamp" in d

    def test_query_mode_values(self):
        from src.cognitive.aeos_core import QueryMode
        assert QueryMode.FAST.value == "fast"
        assert QueryMode.MAXIMUM.value == "maximum"

    def test_initialize_partial(self):
        """Core should initialize even if some modules missing."""
        core = self._make_core()
        # initialize() will fail to import modules but should still set _initialized=True
        try:
            core.initialize()
        except Exception:
            pass
        # Core marks itself initialized regardless of module failures
        assert core._initialized is True

    def test_core_status_health_score(self):
        from src.cognitive.aeos_core import CoreStatus
        status = CoreStatus(
            initialized=True,
            cartridges_loaded=45,
            cartridges_target=45,
            modules_wired=["EventBus", "CartridgeLoader", "FlywheelLogger"],
            modules_missing=[],
            flywheel_decisions=35,
            causal_ready=True,
            twin_ready=False,
            four_gate_active=True,
            event_bus_active=True,
            last_query_at=None,
            uptime_seconds=100.0,
            total_queries=10,
            errors_total=0,
        )
        assert status.health_score > 0.7


# ---------------------------------------------------------------------------
# KBCognitiveBridge skeleton tests
# ---------------------------------------------------------------------------
class TestKBCognitiveBridge:
    def _make_bridge(self):
        from src.kb.cognitive_bridge import KBCognitiveBridge
        return KBCognitiveBridge()

    def test_instantiation(self):
        bridge = self._make_bridge()
        assert bridge.VERSION == "1.0.0"
        assert not bridge._initialized

    def test_initialize(self):
        bridge = self._make_bridge()
        result = bridge.initialize()
        assert result is True
        assert bridge._initialized is True

    def test_analyze_pain_register_stub(self):
        bridge = self._make_bridge()
        bridge.initialize()
        result = bridge.analyze_pain_register()
        assert isinstance(result.errors, list)
        assert result.entries_processed == 0

    def test_get_status(self):
        bridge = self._make_bridge()
        s = bridge.get_status()
        assert "initialized" in s
        assert "version" in s


# ---------------------------------------------------------------------------
# UnifiedRouter skeleton tests
# ---------------------------------------------------------------------------
class TestUnifiedRouter:
    def _make_router(self):
        from src.api.unified_router import UnifiedRouter
        return UnifiedRouter(aeos_core=None)

    def test_instantiation(self):
        router = self._make_router()
        assert router is not None

    def test_handle_health_no_core(self):
        router = self._make_router()
        result = router.handle_health()
        assert result["success"] is True
        assert result["data"]["initialized"] is False

    def test_handle_query_no_core(self):
        router = self._make_router()
        from src.api.unified_router import QueryRequest
        req = QueryRequest(text="test")
        result = router.handle_query(req)
        assert result["success"] is False
        assert "not initialized" in result["error"].lower()

    def test_get_route_map(self):
        router = self._make_router()
        routes = router.get_route_map()
        assert routes["total"] == 19
        assert len(routes["routes"]) == 19
        paths = [r["path"] for r in routes["routes"]]
        assert "/api/v1/query" in paths
        assert "/api/v1/status" in paths
        assert "/api/v1/cartridges" in paths
        # Phase 4B endpoints
        assert "/api/v1/audit" in paths
        assert "/api/v1/backup" in paths
        assert "/api/v1/restore" in paths
        assert "/api/v1/verify" in paths

    def test_api_response_structure(self):
        from src.api.unified_router import APIResponse
        resp = APIResponse(success=True, data={"key": "value"})
        d = resp.to_dict()
        assert d["success"] is True
        assert d["data"]["key"] == "value"
        assert "timestamp" in d
        assert d["version"] == "9.0.0"


# ---------------------------------------------------------------------------
# CartridgeValidator tests
# ---------------------------------------------------------------------------
class TestCartridgeValidator:
    def _make_valid_cartridge(self, cartridge_id="CART-TEST", domain="test", rule_count=10):
        return {
            "cartridge_id": cartridge_id,
            "domain": domain,
            "version": "1.0",
            "rule_count": rule_count,
            "rules": [
                {"rule_id": f"R{i:03d}", "text": f"Rule {i} text"} for i in range(rule_count)
            ]
        }

    def _write_json(self, tmp_dir, filename, data):
        path = Path(tmp_dir) / filename
        path.write_text(json.dumps(data))
        return path

    def test_valid_cartridge(self):
        from scripts.validate_cartridges import CartridgeValidator
        validator = CartridgeValidator()
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_json(tmp, "cart-test.json", self._make_valid_cartridge())
            report = validator.validate_file(path)
            assert report.valid is True
            assert report.rule_count_actual == 10

    def test_missing_field(self):
        from scripts.validate_cartridges import CartridgeValidator
        validator = CartridgeValidator()
        with tempfile.TemporaryDirectory() as tmp:
            data = self._make_valid_cartridge()
            del data["rules"]
            path = self._write_json(tmp, "bad.json", data)
            report = validator.validate_file(path)
            assert report.valid is False
            fields = [e.field for e in report.errors]
            assert "rules" in fields

    def test_rule_count_mismatch(self):
        from scripts.validate_cartridges import CartridgeValidator
        validator = CartridgeValidator()
        with tempfile.TemporaryDirectory() as tmp:
            data = self._make_valid_cartridge()
            data["rule_count"] = 99  # mismatch
            path = self._write_json(tmp, "cart-test.json", data)
            report = validator.validate_file(path)
            assert report.valid is False

    def test_wrong_id_prefix(self):
        from scripts.validate_cartridges import CartridgeValidator
        validator = CartridgeValidator()
        with tempfile.TemporaryDirectory() as tmp:
            data = self._make_valid_cartridge(cartridge_id="BAD-PREFIX")
            path = self._write_json(tmp, "bad-prefix.json", data)
            report = validator.validate_file(path)
            assert report.valid is False

    def test_duplicate_rule_ids(self):
        from scripts.validate_cartridges import CartridgeValidator
        validator = CartridgeValidator()
        with tempfile.TemporaryDirectory() as tmp:
            data = self._make_valid_cartridge()
            data["rules"][1]["rule_id"] = data["rules"][0]["rule_id"]  # duplicate
            path = self._write_json(tmp, "cart-test.json", data)
            report = validator.validate_file(path)
            assert report.valid is False

    def test_invalid_json(self):
        from scripts.validate_cartridges import CartridgeValidator
        validator = CartridgeValidator()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{ not valid json")
            report = validator.validate_file(path)
            assert report.valid is False

    def test_run_validation_empty_dir(self):
        from scripts.validate_cartridges import run_validation
        with tempfile.TemporaryDirectory() as tmp:
            result = run_validation(tmp)
            assert result == 0  # no files = pass

    def test_run_validation_all_valid(self):
        from scripts.validate_cartridges import run_validation
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(3):
                data = self._make_valid_cartridge(f"CART-DOMAIN{i}", f"domain{i}")
                (Path(tmp) / f"cart-domain{i}.json").write_text(json.dumps(data))
            result = run_validation(tmp)
            assert result == 0

    def test_run_validation_with_errors(self):
        from scripts.validate_cartridges import run_validation
        with tempfile.TemporaryDirectory() as tmp:
            good = self._make_valid_cartridge("CART-GOOD", "good")
            bad = {"cartridge_id": "BAD", "domain": "x"}  # missing fields
            (Path(tmp) / "cart-good.json").write_text(json.dumps(good))
            (Path(tmp) / "bad.json").write_text(json.dumps(bad))
            result = run_validation(tmp)
            assert result == 1


# ---------------------------------------------------------------------------
# Integration: EventBus + AeOSCore wiring
# ---------------------------------------------------------------------------
class TestEventBusIntegration:
    def test_error_events_on_bad_handler(self):
        from src.core.event_bus import EventBus, EventBus as EB
        bus = EventBus()
        system_errors = []
        bus.subscribe(EB.TOPIC_SYSTEM_ERROR, lambda e: system_errors.append(e), "monitor")

        def bad(e):
            raise RuntimeError("crash")

        bus.subscribe("test.crash", bad, "crasher")
        bus.emit("test.crash", {}, source="test")
        # system.error event should have been logged internally
        recent = bus.get_recent_events(topic_filter=EB.TOPIC_SYSTEM_ERROR)
        assert len(recent) >= 1

    def test_topic_constants(self):
        from src.core.event_bus import EventBus
        # All standard topics should be defined
        expected = [
            "TOPIC_DECISION_CREATED", "TOPIC_QUERY_COMPLETED",
            "TOPIC_FLYWHEEL_TICK", "TOPIC_SYSTEM_ERROR",
            "TOPIC_CARTRIDGE_LOADED", "TOPIC_PATTERN_DETECTED",
        ]
        for attr in expected:
            assert hasattr(EventBus, attr), f"Missing constant: {attr}"
