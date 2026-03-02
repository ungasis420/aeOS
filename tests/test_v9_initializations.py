"""
aeOS v9.0 — Tests for all 6 Critical Initializations
=====================================================
Run: pytest tests/test_v9_initializations.py -v
Expected: 30 tests passing
"""
import json
import pytest
from unittest.mock import MagicMock, patch, call
# ===========================================================================
# INIT 1: FlywheelLogger
# ===========================================================================
class TestFlywheelLogger:
    """Tests for Compound Intelligence Flywheel Logger (F3.6)."""
    def _make_logger(self, mock_cursor=None):
        """Create FlywheelLogger with mocked DB."""
        with patch("src.cognitive.flywheel_logger.get_db_connection") as mock_conn:
            from src.cognitive.flywheel_logger import FlywheelLogger
            logger = FlywheelLogger.__new__(FlywheelLogger)
            logger._db = MagicMock()
            if mock_cursor:
                logger._db.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
                logger._db.cursor.return_value.__exit__ = MagicMock(return_value=False)
            return logger
    def test_log_decision_returns_uuid(self):
        """log_decision should return a valid UUID string."""
        logger = self._make_logger()
        logger._persist = MagicMock()
        decision_id = logger.log_decision(
            context="Should I take this project?",
            cartridges_fired=["negotiation", "energy_management"],
            reasoning_summary="High revenue, low leverage. Negotiated scope.",
            confidence=0.75,
            domain="business"
        )
        assert isinstance(decision_id, str)
        assert len(decision_id) == 36  # UUID format
        assert decision_id.count("-") == 4
    def test_log_decision_rejects_invalid_confidence(self):
        """Confidence outside 0.0–1.0 should raise ValueError."""
        logger = self._make_logger()
        with pytest.raises(ValueError, match="confidence"):
            logger.log_decision(
                context="test",
                cartridges_fired=[],
                reasoning_summary="test",
                confidence=1.5  # invalid
            )
    def test_log_decision_normalizes_unknown_domain(self):
        """Unknown domains should be stored as 'unknown'."""
        logger = self._make_logger()
        persisted = {}
        logger._persist = lambda r: persisted.update(r)
        logger.log_decision(
            context="test",
            cartridges_fired=[],
            reasoning_summary="test",
            confidence=0.5,
            domain="space_exploration"  # not in VALID_DOMAINS
        )
        assert persisted["domain"] == "unknown"
    def test_log_outcome_rejects_invalid_valence(self):
        """outcome_valence must be -1, 0, or 1."""
        logger = self._make_logger()
        with pytest.raises(ValueError, match="valence"):
            logger.log_outcome(
                decision_id="some-uuid",
                outcome_description="test",
                outcome_valence=2  # invalid
            )
    def test_log_outcome_rejects_invalid_magnitude(self):
        """outcome_magnitude must be 0.0–1.0."""
        logger = self._make_logger()
        with pytest.raises(ValueError, match="magnitude"):
            logger.log_outcome(
                decision_id="some-uuid",
                outcome_description="test",
                outcome_valence=1,
                outcome_magnitude=1.5  # invalid
            )
    def test_get_compound_score_empty_db(self):
        """Compound score with no data should return zero score."""
        logger = self._make_logger()
        logger._compute_compound_score = MagicMock(return_value={
            "total_decisions": 0,
            "compound_score": 0.0,
            "score_interpretation": "No data yet — start making decisions."
        })
        result = logger.get_compound_score()
        assert result["compound_score"] == 0.0
        assert result["total_decisions"] == 0
    def test_valid_domains_constant(self):
        """VALID_DOMAINS should contain all expected life domains."""
        from src.cognitive.flywheel_logger import FlywheelLogger
        expected = {"business", "finance", "health", "relationships",
                    "career", "creative", "learning", "personal", "unknown"}
        assert FlywheelLogger.VALID_DOMAINS == expected
    def test_log_cartridge_performance_structure(self):
        """log_cartridge_performance should persist correct record structure."""
        logger = self._make_logger()
        persisted = {}
        logger._persist_cartridge_event = lambda r: persisted.update(r)
        logger.log_cartridge_performance(
            cartridge_id="negotiation_law25",
            decision_id="test-decision-id",
            relevance_score=0.85,
            was_accepted=True,
            domain="business"
        )
        assert persisted["event_type"] == "CARTRIDGE_PERFORMANCE"
        assert persisted["cartridge_id"] == "negotiation_law25"
        assert persisted["was_accepted"] is True
        assert persisted["relevance_score"] == 0.85
# ===========================================================================
# INIT 2: CausalInferenceEngine
# ===========================================================================
class TestCausalInferenceEngine:
    """Tests for Causal Inference Engine stub (F1.6)."""
    @pytest.fixture
    def engine(self):
        from src.cognitive.causal_inference import CausalInferenceEngine
        return CausalInferenceEngine()
    def test_build_causal_graph_returns_empty_when_no_data(self, engine):
        """Stub should return empty graph with guidance."""
        result = engine.build_causal_graph()
        assert result["edges"] == []
        assert result["confidence"] == 0.0
        assert "insufficient" in result["data_sufficiency"].lower()
    def test_do_calculus_returns_stub_recommendation(self, engine):
        """do_calculus stub should return recommendation with 0 confidence."""
        from src.cognitive.causal_inference import InterventionRecommendation
        result = engine.do_calculus(
            intervention_variable="sleep_hours",
            intervention_value="8",
            target_outcome="decision_quality"
        )
        assert isinstance(result, InterventionRecommendation)
        assert result.confidence == 0.0
        assert result.effect_magnitude == 0.0
    def test_counterfactual_returns_stub_result(self, engine):
        """counterfactual stub should return result with 0 confidence."""
        from src.cognitive.causal_inference import CounterfactualResult
        result = engine.counterfactual(
            decision_id="some-uuid",
            alternative_action="Negotiated harder on price"
        )
        assert isinstance(result, CounterfactualResult)
        assert result.confidence == 0.0
    def test_get_data_readiness_no_logger(self, engine):
        """get_data_readiness without logger should return zero state."""
        result = engine.get_data_readiness()
        assert result["total_decisions"] == 0
        assert result["ready_for_inference"] is False
        assert result["shortfall"] == 30  # min_samples_for_inference
    def test_identify_leverage_points_returns_guidance(self, engine):
        """leverage points stub should return data accumulation guidance."""
        result = engine.identify_leverage_points("decision_quality")
        assert len(result) >= 1
        assert "data_accumulation" in result[0]["variable"] or "variable" in result[0]
    def test_causal_strength_enum_values(self):
        """CausalStrength enum should have expected values."""
        from src.cognitive.causal_inference import CausalStrength
        assert CausalStrength.STRONG.value == "strong"
        assert CausalStrength.UNKNOWN.value == "unknown"
# ===========================================================================
# INIT 3: CartridgeEvolutionEngine
# ===========================================================================
class TestCartridgeEvolutionEngine:
    """Tests for Autonomous Cartridge Generation stub (F3.7)."""
    @pytest.fixture
    def engine(self):
        from src.cognitive.cartridge_evolution import CartridgeEvolutionEngine
        return CartridgeEvolutionEngine()
    def test_detect_coverage_gaps_returns_empty_stub(self, engine):
        """Stub detect_coverage_gaps should return empty list."""
        gaps = engine.detect_coverage_gaps()
        assert gaps == []
    def test_get_evolution_status_structure(self, engine):
        """get_evolution_status should return expected keys."""
        status = engine.get_evolution_status()
        expected_keys = {"gaps_detected", "cartridges_drafted", "cartridges_deployed",
                         "evolution_score", "next_gap_priority"}
        assert expected_keys.issubset(status.keys())
        assert status["evolution_score"] == 0.0
        assert status["gaps_detected"] == 0
    def test_list_proposals_empty_initially(self, engine):
        """No proposals on fresh engine."""
        proposals = engine.list_proposals()
        assert proposals == []
    def test_cartridge_status_enum(self):
        """CartridgeStatus should have all expected values."""
        from src.cognitive.cartridge_evolution import CartridgeStatus
        assert CartridgeStatus.DRAFT.value == "draft"
        assert CartridgeStatus.DEPLOYED.value == "deployed"
        assert CartridgeStatus.REJECTED.value == "rejected"
    def test_validate_via_4gate_stub_fails(self, engine):
        """4-Gate validation stub should return all False (not implemented)."""
        from src.cognitive.cartridge_evolution import CartridgeDraft, CartridgeStatus, CoverageGap
        gap = CoverageGap(
            domain="business", subdomain="pricing",
            gap_description="No cartridge for value-based pricing",
            frequency_of_encounter=12, estimated_impact=0.7
        )
        draft = engine.draft_cartridge(gap)
        result = engine.validate_via_4gate(draft)
        assert result["overall_pass"] is False
        assert result["gate_1_safe"] is False
# ===========================================================================
# INIT 4: CryptoGuard
# ===========================================================================
class TestCryptoGuard:
    """Tests for Cryptographic Cognitive State (F0.3)."""
    @pytest.fixture
    def guard(self):
        from src.cognitive.crypto_guard import CryptoGuard
        g = CryptoGuard()
        with patch.object(g, "_get_machine_id", return_value="test-machine-id-12345"):
            g.initialize_crypto("test-passphrase-sovereign")
        return g
    def test_initialize_crypto_sets_initialized_flag(self, guard):
        """After initialization, _initialized should be True."""
        assert guard._initialized is True
        assert guard._key is not None
    def test_encrypt_decrypt_roundtrip(self, guard):
        """Encrypted data should decrypt back to original."""
        original = {
            "decision_id": "test-123",
            "context": "Should I take this project?",
            "cartridges_fired": ["negotiation", "energy"],
            "confidence": 0.75
        }
        encrypted = guard.encrypt_cognitive_state(original)
        assert isinstance(encrypted, str)
        assert encrypted != json.dumps(original)  # definitely not plaintext
        decrypted = guard.decrypt_cognitive_state(encrypted)
        assert decrypted == original
    def test_encrypt_produces_different_ciphertext_each_time(self, guard):
        """Same input should produce different ciphertext (nonce randomization)."""
        data = {"test": "same input"}
        ct1 = guard.encrypt_cognitive_state(data)
        ct2 = guard.encrypt_cognitive_state(data)
        assert ct1 != ct2  # different nonces → different ciphertext
    def test_hmac_verify_passes_for_valid_data(self, guard):
        """HMAC should verify correctly for unmodified data."""
        data = {"decision": "test", "outcome": 1}
        mac = guard.generate_hmac(data)
        assert guard.verify_hmac(data, mac) is True
    def test_hmac_verify_fails_for_tampered_data(self, guard):
        """HMAC should fail for tampered data."""
        data = {"decision": "test", "outcome": 1}
        mac = guard.generate_hmac(data)
        tampered = {"decision": "test", "outcome": -1}  # outcome changed
        assert guard.verify_hmac(tampered, mac) is False
    def test_get_crypto_status_reveals_no_key(self, guard):
        """Status should confirm init without exposing key material."""
        status = guard.get_crypto_status()
        assert status["initialized"] is True
        # Verify no raw key bytes are exposed (key_derivation_iterations is safe metadata)
        assert guard._key is not None
        key_hex = guard._key.hex()
        assert key_hex not in str(status)
        assert status["algorithm"] == "AES-256-GCM + PBKDF2-HMAC-SHA256"
    def test_should_encrypt_known_tables(self, guard):
        """Protected tables should return True."""
        assert guard.should_encrypt("Compound_Intelligence_Log") is True
        assert guard.should_encrypt("Cognitive_Twin_State") is True
        assert guard.should_encrypt("Causal_Graph_Log") is True
    def test_should_not_encrypt_non_cognitive_tables(self, guard):
        """Non-cognitive tables should return False."""
        assert guard.should_encrypt("Users") is False
        assert guard.should_encrypt("Projects") is False
    def test_requires_initialization_before_encrypt(self):
        """Calling encrypt before init should raise RuntimeError."""
        from src.cognitive.crypto_guard import CryptoGuard
        guard = CryptoGuard()  # not initialized
        with pytest.raises(RuntimeError, match="not initialized"):
            guard.encrypt_cognitive_state({"test": "data"})
    def test_different_machines_produce_different_keys(self):
        """Same passphrase on different machine IDs → different keys."""
        from src.cognitive.crypto_guard import CryptoGuard
        g1, g2 = CryptoGuard(), CryptoGuard()
        with patch.object(g1, "_get_machine_id", return_value="machine-A"):
            g1.initialize_crypto("same-passphrase")
        with patch.object(g2, "_get_machine_id", return_value="machine-B"):
            g2.initialize_crypto("same-passphrase")
        assert g1._key != g2._key  # hardware binding works
