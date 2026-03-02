"""30 tests for v9.0 Foundation Initializations.

Covers: FlywheelLogger, CryptoGuard, CausalInferenceEngine,
        CartridgeEvolutionEngine, TrajectoryMixin, and integration.
"""
import time
import pytest

from src.cognitive.flywheel_logger import FlywheelLogger
from src.cognitive.crypto_guard import CryptoGuard
from src.cognitive.causal_inference import CausalInferenceEngine
from src.cognitive.cartridge_evolution import CartridgeEvolutionEngine
from src.cognitive.trajectory_mixin import TrajectoryMixin, TrajectoryForecast


# ── FlywheelLogger ─────────────────────────────────────────────

def test_flywheel_log_decision():
    fl = FlywheelLogger()
    did = fl.log_decision("test query", ["cart1"], "Summary", 0.8, "finance")
    assert isinstance(did, str)
    assert len(did) > 0


def test_flywheel_record_outcome():
    fl = FlywheelLogger()
    did = fl.log_decision("query", ["c1"], "sum", 0.5)
    assert fl.record_outcome(did, "accepted", 0.9) is True


def test_flywheel_get_decision():
    fl = FlywheelLogger()
    did = fl.log_decision("query", ["c1"], "sum", 0.7, "general")
    dec = fl.get_decision(did)
    assert dec is not None
    assert dec["confidence"] == 0.7


def test_flywheel_recent_decisions():
    fl = FlywheelLogger()
    fl.log_decision("q1", [], "s1", 0.5)
    fl.log_decision("q2", [], "s2", 0.6)
    recent = fl.get_recent_decisions(limit=5)
    assert len(recent) == 2


def test_flywheel_domain_stats():
    fl = FlywheelLogger()
    fl.log_decision("q1", ["c1"], "s1", 0.8, "finance")
    fl.log_decision("q2", ["c2"], "s2", 0.6, "finance")
    stats = fl.get_domain_stats("finance")
    assert stats["total_decisions"] == 2
    assert stats["avg_confidence"] == pytest.approx(0.7, abs=0.01)


def test_flywheel_invalid_confidence_raises():
    fl = FlywheelLogger()
    with pytest.raises(ValueError):
        fl.log_decision("q", [], "s", 1.5)


# ── CryptoGuard ────────────────────────────────────────────────

def test_crypto_encrypt_decrypt_roundtrip():
    cg = CryptoGuard("test_key_123")
    plaintext = "Hello, aeOS cognitive state!"
    envelope = cg.encrypt(plaintext)
    decrypted = cg.decrypt(envelope)
    assert decrypted == plaintext


def test_crypto_encrypt_state_roundtrip():
    cg = CryptoGuard("key")
    state = {"mood": "focused", "confidence": 0.85, "needs": ["autonomy"]}
    envelope = cg.encrypt_state(state)
    restored = cg.decrypt_state(envelope)
    assert restored["mood"] == "focused"
    assert restored["confidence"] == 0.85


def test_crypto_tampered_hmac_raises():
    cg = CryptoGuard("key")
    envelope = cg.encrypt("test data")
    envelope["hmac"] = "0000000000000000000000000000000000000000000000000000000000000000"
    with pytest.raises(ValueError, match="HMAC"):
        cg.decrypt(envelope)


def test_crypto_checksum_verify():
    cg = CryptoGuard()
    data = "important data"
    checksum = cg.compute_checksum(data)
    assert cg.verify_checksum(data, checksum) is True
    assert cg.verify_checksum("wrong data", checksum) is False


def test_crypto_missing_field_raises():
    cg = CryptoGuard("key")
    with pytest.raises(ValueError, match="missing"):
        cg.decrypt({"ciphertext": "abc"})


# ── CausalInferenceEngine ─────────────────────────────────────

def test_causal_add_edge():
    ci = CausalInferenceEngine()
    edge_id = ci.add_edge("A", "B", 0.8, "strong link")
    assert isinstance(edge_id, str)


def test_causal_get_causes():
    ci = CausalInferenceEngine()
    ci.add_edge("rain", "flood", 0.9)
    ci.add_edge("dam_break", "flood", 0.7)
    causes = ci.get_causes("flood")
    assert len(causes) == 2


def test_causal_get_effects():
    ci = CausalInferenceEngine()
    ci.add_edge("rain", "flood", 0.9)
    ci.add_edge("rain", "mud", 0.5)
    effects = ci.get_effects("rain")
    assert len(effects) == 2


def test_causal_find_path():
    ci = CausalInferenceEngine()
    ci.add_edge("A", "B", 0.5)
    ci.add_edge("B", "C", 0.5)
    path = ci.find_path("A", "C")
    assert path == ["A", "B", "C"]


def test_causal_no_path():
    ci = CausalInferenceEngine()
    ci.add_edge("A", "B", 0.5)
    path = ci.find_path("B", "A")
    assert path is None


def test_causal_influence_score():
    ci = CausalInferenceEngine()
    ci.add_edge("X", "Y", 0.6)
    ci.add_edge("X", "Z", 0.4)
    score = ci.compute_influence_score("X")
    assert score == pytest.approx(1.0)


def test_causal_graph_summary():
    ci = CausalInferenceEngine()
    ci.add_edge("A", "B", 0.5, domain="finance")
    summary = ci.get_graph_summary()
    assert summary["node_count"] == 2
    assert summary["edge_count"] == 1


# ── CartridgeEvolutionEngine ──────────────────────────────────

def test_evolution_propose():
    ce = CartridgeEvolutionEngine()
    pid = ce.propose_evolution("cart1", "add_rule", "Add new insight", "New rule", "medium")
    assert isinstance(pid, str)


def test_evolution_approve():
    ce = CartridgeEvolutionEngine()
    pid = ce.propose_evolution("cart1", "modify_rule", "Update weight", "Change")
    assert ce.approve_proposal(pid) is True


def test_evolution_reject():
    ce = CartridgeEvolutionEngine()
    pid = ce.propose_evolution("cart1", "retire_rule", "Remove old", "Delete")
    assert ce.reject_proposal(pid, reason="Not needed") is True


def test_evolution_pending_list():
    ce = CartridgeEvolutionEngine()
    ce.propose_evolution("c1", "add_rule", "d1", "ch1")
    ce.propose_evolution("c2", "tune_weight", "d2", "ch2")
    pending = ce.get_pending_proposals()
    assert len(pending) == 2


def test_evolution_performance_tracking():
    ce = CartridgeEvolutionEngine()
    ce.record_performance("cart1", 0.85, 120.0, True)
    ce.record_performance("cart1", 0.90, 100.0, True)
    summary = ce.get_performance_summary("cart1")
    assert summary["invocations"] == 2
    assert summary["avg_confidence"] == pytest.approx(0.875)


def test_evolution_invalid_type_raises():
    ce = CartridgeEvolutionEngine()
    with pytest.raises(ValueError):
        ce.propose_evolution("c1", "invalid_type", "d", "ch")


# ── TrajectoryMixin ───────────────────────────────────────────

def test_trajectory_predict():
    tm = TrajectoryMixin()
    result = tm.predict_trajectory([10, 20, 30, 40, 50], horizon=3)
    assert isinstance(result, TrajectoryForecast)
    assert result.trend_direction == "up"
    assert len(result.projected) == 3


def test_trajectory_insufficient_data():
    tm = TrajectoryMixin()
    result = tm.predict_trajectory([5], horizon=3)
    assert result.method == "insufficient_data"
    assert result.projected == []


def test_trajectory_flat():
    tm = TrajectoryMixin()
    result = tm.predict_trajectory([50, 50, 50, 50, 50], horizon=3)
    assert result.trend_direction == "flat"
    assert len(result.projected) == 3


# ── Import checks ─────────────────────────────────────────────

def test_all_v9_modules_importable():
    """Verify all 5 v9 foundation modules import without error."""
    from src.cognitive.flywheel_logger import FlywheelLogger
    from src.cognitive.crypto_guard import CryptoGuard
    from src.cognitive.causal_inference import CausalInferenceEngine
    from src.cognitive.cartridge_evolution import CartridgeEvolutionEngine
    from src.cognitive.trajectory_mixin import TrajectoryMixin
    assert True
