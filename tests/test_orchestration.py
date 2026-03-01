"""
tests/test_orchestration.py

Pytest unit tests for the aeOS orchestration layer (Phase 2).

Covers all five components: Dispatcher, CartridgeConductor,
ReasoningSynthesizer, OutputValidator, OutputComposer, plus full pipeline
integration.  50+ tests, stdlib-only, no filesystem side-effects.

Stamp: S✅ T✅ L✅ A✅
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure repo root is importable.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.orchestration.models import (
    CartridgeInsight,
    ComposedOutput,
    IntentClassification,
    OrchestratorRequest,
    ValidationResult,
)
from src.orchestration.dispatcher import Dispatcher, _score_text, _DOMAIN_KEYWORDS
from src.orchestration.cartridge_conductor import (
    CartridgeConductor,
    _domain_matches,
    _extract_context,
)
from src.orchestration.reasoning_synthesizer import ReasoningSynthesizer
from src.orchestration.output_validator import (
    OutputValidator,
    _gate_safe,
    _gate_true,
    _gate_high_leverage,
    _gate_aligned,
)
from src.orchestration.output_composer import OutputComposer
from src.cognitive.reasoning_substrate import (
    BlindSpot,
    Convergence,
    SynthesisResult,
    Tension,
)
from src.cognitive.cartridge_loader import load_cartridge, load_schema

# ---------------------------------------------------------------------------
# Paths to real repo assets
# ---------------------------------------------------------------------------
_CARTRIDGES_DIR = Path(_REPO_ROOT) / "src" / "cartridges"
_SCHEMA_PATH = _CARTRIDGES_DIR / "cartridge_schema.json"
_STOIC_PATH = _CARTRIDGES_DIR / "stoic.json"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def dispatcher():
    return Dispatcher()


@pytest.fixture()
def stoic_cartridge():
    schema = load_schema(_SCHEMA_PATH)
    return load_cartridge(_STOIC_PATH, schema)


@pytest.fixture()
def conductor(stoic_cartridge):
    return CartridgeConductor(cartridges=[stoic_cartridge])


@pytest.fixture()
def synthesizer():
    return ReasoningSynthesizer()


@pytest.fixture()
def validator():
    return OutputValidator()


@pytest.fixture()
def composer():
    return OutputComposer()


def _make_synthesis(
    primary_insight=None,
    supporting=None,
    convergences=None,
    tensions=None,
    blind_spots=None,
    recommended_action="Do the thing.",
    confidence=0.75,
    needs_served=None,
):
    """Helper to build a SynthesisResult with sensible defaults."""
    return SynthesisResult(
        primary_insight={"insight": "Primary insight text.", "name": "Rule", "principle": "P"} if primary_insight is None else primary_insight,
        supporting_insights=[] if supporting is None else supporting,
        convergences=[] if convergences is None else convergences,
        tensions=[] if tensions is None else tensions,
        blind_spots=[] if blind_spots is None else blind_spots,
        recommended_action=recommended_action,
        overall_confidence=confidence,
        needs_served=["clarity"] if needs_served is None else needs_served,
    )


def _make_cartridge_insight(
    rule_id="r1",
    cartridge_id="test",
    insight_text="Insight.",
    confidence=0.7,
    sovereign_need="clarity",
    tags=None,
):
    return CartridgeInsight(
        rule_id=rule_id,
        cartridge_id=cartridge_id,
        insight_text=insight_text,
        confidence=confidence,
        sovereign_need=sovereign_need,
        tags=tags or ["test"],
    )


# ===================================================================
# 1. MODEL TESTS
# ===================================================================

class TestModels:
    def test_intent_classification_fields(self):
        ic = IntentClassification(domains=["philosophy.stoicism"], complexity="low")
        assert ic.domains == ["philosophy.stoicism"]
        assert ic.complexity == "low"
        assert ic.sovereign_need_hint is None

    def test_orchestrator_request_fields(self):
        ic = IntentClassification(domains=["d"], complexity="medium", sovereign_need_hint="clarity")
        req = OrchestratorRequest(raw_text="hello", intent=ic, timestamp="2026-01-01T00:00:00Z")
        assert req.raw_text == "hello"
        assert req.intent.sovereign_need_hint == "clarity"

    def test_cartridge_insight_defaults(self):
        ci = CartridgeInsight(rule_id="r", cartridge_id="c", insight_text="t", confidence=0.5, sovereign_need="s")
        assert ci.tags == []

    def test_validation_result_defaults(self):
        vr = ValidationResult(passed=True)
        assert vr.gates == {}
        assert vr.failure_reason is None

    def test_composed_output_defaults(self):
        co = ComposedOutput(summary="s", primary_insight="p")
        assert co.supporting_points == []
        assert co.confidence == 0.0


# ===================================================================
# 2. DISPATCHER TESTS
# ===================================================================

class TestDispatcher:
    def test_classify_returns_intent(self, dispatcher):
        intent = dispatcher.classify_intent("I feel frustrated and stuck")
        assert isinstance(intent, IntentClassification)
        assert isinstance(intent.domains, list)
        assert intent.complexity in ("low", "medium", "high")

    def test_stoic_keywords_route_to_philosophy(self, dispatcher):
        intent = dispatcher.classify_intent("I need stoic discipline and virtue to endure")
        assert any("philosophy.stoicism" in d for d in intent.domains)

    def test_anxiety_routes_to_mental_health(self, dispatcher):
        intent = dispatcher.classify_intent("I have severe anxiety and depression, I need therapy")
        domains = intent.domains
        assert any("mental_health" in d or "emotional_regulation" in d for d in domains)

    def test_money_routes_to_finance(self, dispatcher):
        intent = dispatcher.classify_intent("I need to budget my money and reduce debt and expenses")
        assert any("finance" in d for d in intent.domains)

    def test_career_keywords(self, dispatcher):
        intent = dispatcher.classify_intent("I want a promotion and career advancement at my job")
        assert any("career" in d for d in intent.domains)

    def test_relationship_keywords(self, dispatcher):
        intent = dispatcher.classify_intent("I keep having arguments and conflict with my partner, we need to compromise")
        assert any("relationships" in d for d in intent.domains)

    def test_productivity_keywords(self, dispatcher):
        intent = dispatcher.classify_intent("I need deep work and focus, too many distractions")
        assert any("productivity" in d for d in intent.domains)

    def test_complexity_low_for_short_text(self, dispatcher):
        intent = dispatcher.classify_intent("I feel stuck")
        assert intent.complexity == "low"

    def test_complexity_high_for_long_text(self, dispatcher):
        long_text = " ".join(["I feel stressed and overwhelmed"] * 10)
        intent = dispatcher.classify_intent(long_text)
        assert intent.complexity in ("medium", "high")

    def test_sovereign_need_detected(self, dispatcher):
        intent = dispatcher.classify_intent("I need freedom and control over my own life")
        assert intent.sovereign_need_hint is not None
        assert intent.sovereign_need_hint == "autonomy"

    def test_dispatch_returns_request(self, dispatcher):
        req = dispatcher.dispatch("I feel lost")
        assert isinstance(req, OrchestratorRequest)
        assert req.raw_text == "I feel lost"

    def test_dispatch_timestamp_populated(self, dispatcher):
        req = dispatcher.dispatch("hello world")
        assert len(req.timestamp) > 0

    def test_all_45_domains_reachable(self, dispatcher):
        """Every domain must be reachable via its own keywords."""
        for domain, keywords in _DOMAIN_KEYWORDS.items():
            text = " ".join(keywords[:4])
            intent = dispatcher.classify_intent(text)
            assert domain in intent.domains, f"Domain {domain} not reachable with keywords: {text}"

    def test_fallback_when_no_keywords_match(self, dispatcher):
        intent = dispatcher.classify_intent("xyzzy plugh")
        assert len(intent.domains) > 0  # falls back to default


# ===================================================================
# 3. CONDUCTOR TESTS
# ===================================================================

class TestConductor:
    def test_conduct_with_stoic_cartridge(self, conductor):
        req = OrchestratorRequest(
            raw_text="I feel frustrated and overwhelmed",
            intent=IntentClassification(domains=["philosophy.stoicism"], complexity="low"),
        )
        insights = conductor.conduct(req)
        assert len(insights) > 0
        assert all(isinstance(i, CartridgeInsight) for i in insights)

    def test_conduct_returns_cartridge_id(self, conductor):
        req = OrchestratorRequest(
            raw_text="I feel anxious and worried",
            intent=IntentClassification(domains=["philosophy"], complexity="low"),
        )
        insights = conductor.conduct(req)
        assert all(i.cartridge_id == "stoic" for i in insights)

    def test_conduct_ranks_by_confidence(self, conductor):
        req = OrchestratorRequest(
            raw_text="overwhelmed, anxious, frustrated, hurt, isolated",
            intent=IntentClassification(domains=["philosophy.stoicism"], complexity="high"),
        )
        insights = conductor.conduct(req)
        confidences = [i.confidence for i in insights]
        assert confidences == sorted(confidences, reverse=True)

    def test_conduct_max_20_insights(self, stoic_cartridge):
        # Create a fake cartridge with >20 rules to test cap.
        fat = dict(stoic_cartridge)
        fat["rules"] = fat["rules"] * 5  # 50 rules
        cond = CartridgeConductor(cartridges=[fat])
        req = OrchestratorRequest(
            raw_text="frustrated helpless overwhelmed anxious hurt alone",
            intent=IntentClassification(domains=["philosophy"], complexity="high"),
        )
        assert len(cond.conduct(req)) <= 20

    def test_conduct_no_matching_domain(self, conductor):
        req = OrchestratorRequest(
            raw_text="frustrated",
            intent=IntentClassification(domains=["zzz.nonexistent"], complexity="low"),
        )
        assert conductor.conduct(req) == []

    def test_conduct_empty_text_no_crash(self, conductor):
        req = OrchestratorRequest(
            raw_text="",
            intent=IntentClassification(domains=["philosophy.stoicism"], complexity="low"),
        )
        result = conductor.conduct(req)
        assert isinstance(result, list)

    def test_conduct_insight_structure(self, conductor):
        req = OrchestratorRequest(
            raw_text="I feel frustrated and helpless",
            intent=IntentClassification(domains=["philosophy.stoicism"], complexity="low"),
        )
        insights = conductor.conduct(req)
        for ins in insights:
            assert ins.rule_id
            assert ins.cartridge_id
            assert isinstance(ins.confidence, float)
            assert isinstance(ins.tags, list)

    def test_conduct_prefix_domain_match(self, conductor):
        """'philosophy' should match the stoic cartridge domain 'philosophy.stoicism'."""
        req = OrchestratorRequest(
            raw_text="I feel frustrated",
            intent=IntentClassification(domains=["philosophy"], complexity="low"),
        )
        assert len(conductor.conduct(req)) > 0


# ===================================================================
# 4. DOMAIN-MATCH HELPER TESTS
# ===================================================================

class TestDomainMatch:
    def test_exact_match(self):
        assert _domain_matches("philosophy.stoicism", ["philosophy.stoicism"]) is True

    def test_prefix_match(self):
        assert _domain_matches("philosophy.stoicism", ["philosophy"]) is True

    def test_reverse_prefix(self):
        assert _domain_matches("philosophy", ["philosophy.stoicism"]) is True

    def test_no_match(self):
        assert _domain_matches("finance.investing", ["philosophy"]) is False


# ===================================================================
# 5. SYNTHESIZER TESTS
# ===================================================================

class TestReasoningSynthesizer:
    def test_synthesize_empty_insights(self, synthesizer):
        result = synthesizer.synthesize([])
        assert isinstance(result, SynthesisResult)
        assert result.primary_insight == {}
        assert result.overall_confidence == 0.0
        assert "No insights" in result.recommended_action

    def test_synthesize_with_insights(self, synthesizer):
        insights = [
            _make_cartridge_insight("r1", confidence=0.8, tags=["resilience"]),
            _make_cartridge_insight("r2", confidence=0.6, tags=["clarity"]),
        ]
        result = synthesizer.synthesize(insights)
        assert isinstance(result, SynthesisResult)
        assert result.overall_confidence > 0.0

    def test_synthesize_returns_synthesis_result(self, synthesizer):
        result = synthesizer.synthesize([_make_cartridge_insight()])
        assert hasattr(result, "primary_insight")
        assert hasattr(result, "convergences")
        assert hasattr(result, "tensions")
        assert hasattr(result, "blind_spots")

    def test_synthesize_handles_single_insight(self, synthesizer):
        result = synthesizer.synthesize([_make_cartridge_insight(confidence=0.9)])
        assert result.primary_insight != {}
        assert result.overall_confidence == pytest.approx(0.9, abs=0.01)

    def test_synthesize_passes_through_convergences(self, synthesizer):
        insights = [
            _make_cartridge_insight("a", tags=["resilience"], confidence=0.8, sovereign_need="resilience"),
            _make_cartridge_insight("b", tags=["resilience"], confidence=0.7, sovereign_need="resilience"),
        ]
        result = synthesizer.synthesize(insights)
        themes = [c.theme for c in result.convergences]
        assert "resilience" in themes

    def test_synthesize_needs_served(self, synthesizer):
        insights = [
            _make_cartridge_insight("a", sovereign_need="clarity"),
            _make_cartridge_insight("b", sovereign_need="autonomy"),
        ]
        result = synthesizer.synthesize(insights)
        assert "clarity" in result.needs_served
        assert "autonomy" in result.needs_served


# ===================================================================
# 6. VALIDATOR TESTS — each gate independently
# ===================================================================

class TestOutputValidator:
    def test_all_gates_pass(self, validator):
        sr = _make_synthesis(confidence=0.75, needs_served=["clarity"],
                             convergences=[Convergence("t", ["r1"], [], 0.8, "s")])
        vr = validator.validate(sr, "some text")
        assert vr.passed is True
        assert all(vr.gates.values())

    def test_gate_safe_fails_with_pii_email(self, validator):
        sr = _make_synthesis(primary_insight={"insight": "Contact john@example.com", "name": "R", "principle": "P"})
        vr = validator.validate(sr, "text")
        assert vr.gates["SAFE"] is False
        assert vr.passed is False

    def test_gate_safe_fails_with_pii_phone(self, validator):
        sr = _make_synthesis(primary_insight={"insight": "Call 555-123-4567", "name": "R", "principle": "P"})
        vr = validator.validate(sr, "text")
        assert vr.gates["SAFE"] is False

    def test_gate_safe_fails_with_pii_ssn(self, validator):
        sr = _make_synthesis(primary_insight={"insight": "SSN is 123-45-6789", "name": "R", "principle": "P"})
        vr = validator.validate(sr, "text")
        assert vr.gates["SAFE"] is False

    def test_gate_safe_fails_with_harmful_content(self, validator):
        sr = _make_synthesis(recommended_action="Kill yourself to escape problems")
        vr = validator.validate(sr, "text")
        assert vr.gates["SAFE"] is False

    def test_gate_safe_passes_clean_text(self, validator):
        sr = _make_synthesis()
        assert _gate_safe(sr, "text") is True

    def test_gate_true_fails_low_confidence(self, validator):
        sr = _make_synthesis(confidence=0.2)
        assert _gate_true(sr) is False

    def test_gate_true_fails_no_primary(self, validator):
        sr = _make_synthesis(primary_insight={}, confidence=0.8)
        assert _gate_true(sr) is False

    def test_gate_true_passes(self, validator):
        sr = _make_synthesis(confidence=0.6)
        assert _gate_true(sr) is True

    def test_gate_leverage_fails_no_convergence_low_conf(self, validator):
        sr = _make_synthesis(convergences=[], confidence=0.5)
        assert _gate_high_leverage(sr) is False

    def test_gate_leverage_passes_with_convergence(self, validator):
        sr = _make_synthesis(convergences=[Convergence("t", ["r1"], [], 0.8, "s")])
        assert _gate_high_leverage(sr) is True

    def test_gate_leverage_passes_with_high_conf(self, validator):
        sr = _make_synthesis(confidence=0.8, convergences=[])
        assert _gate_high_leverage(sr) is True

    def test_gate_aligned_fails_no_needs(self, validator):
        sr = _make_synthesis(needs_served=[])
        assert _gate_aligned(sr) is False

    def test_gate_aligned_passes(self, validator):
        sr = _make_synthesis(needs_served=["clarity"])
        assert _gate_aligned(sr) is True

    def test_failure_reason_lists_gates(self, validator):
        sr = _make_synthesis(confidence=0.2, needs_served=[], convergences=[])
        vr = validator.validate(sr, "text")
        assert vr.failure_reason is not None
        assert "TRUE" in vr.failure_reason


# ===================================================================
# 7. COMPOSER TESTS
# ===================================================================

class TestOutputComposer:
    def test_compose_passed_validation(self, composer):
        sr = _make_synthesis()
        vr = ValidationResult(passed=True, gates={"SAFE": True, "TRUE": True, "HIGH-LEVERAGE": True, "ALIGNED": True})
        out = composer.compose(sr, vr)
        assert isinstance(out, ComposedOutput)
        assert out.confidence > 0.0
        assert out.primary_insight != ""

    def test_compose_failed_validation(self, composer):
        sr = _make_synthesis()
        vr = ValidationResult(passed=False, gates={"SAFE": False}, failure_reason="Failed gate(s): SAFE")
        out = composer.compose(sr, vr)
        assert "withheld" in out.summary.lower()
        assert out.confidence == 0.0

    def test_compose_includes_tensions(self, composer):
        t = Tension("a", "pa", "b", "pb", "Tension between A and B.")
        sr = _make_synthesis(tensions=[t])
        vr = ValidationResult(passed=True, gates={"SAFE": True, "TRUE": True, "HIGH-LEVERAGE": True, "ALIGNED": True})
        out = composer.compose(sr, vr)
        assert len(out.tensions_flagged) == 1
        assert "Tension between" in out.tensions_flagged[0]

    def test_compose_includes_blind_spots(self, composer):
        bs = BlindSpot("security", "No insight on security.")
        sr = _make_synthesis(blind_spots=[bs])
        vr = ValidationResult(passed=True, gates={"SAFE": True, "TRUE": True, "HIGH-LEVERAGE": True, "ALIGNED": True})
        out = composer.compose(sr, vr)
        assert len(out.blind_spots) == 1

    def test_compose_summary_format(self, composer):
        sr = _make_synthesis()
        vr = ValidationResult(passed=True, gates={"SAFE": True, "TRUE": True, "HIGH-LEVERAGE": True, "ALIGNED": True})
        out = composer.compose(sr, vr)
        assert "confidence" in out.summary.lower()

    def test_compose_gate_status(self, composer):
        sr = _make_synthesis()
        gates = {"SAFE": True, "TRUE": True, "HIGH-LEVERAGE": False, "ALIGNED": True}
        vr = ValidationResult(passed=False, gates=gates, failure_reason="Failed gate(s): HIGH-LEVERAGE")
        out = composer.compose(sr, vr)
        assert out.gate_status["HIGH-LEVERAGE"] is False

    def test_compose_recommended_action_on_pass(self, composer):
        sr = _make_synthesis(recommended_action="Breathe deeply.")
        vr = ValidationResult(passed=True, gates={"SAFE": True, "TRUE": True, "HIGH-LEVERAGE": True, "ALIGNED": True})
        out = composer.compose(sr, vr)
        assert out.recommended_action == "Breathe deeply."

    def test_compose_recommended_action_on_fail(self, composer):
        sr = _make_synthesis()
        vr = ValidationResult(passed=False, gates={"SAFE": False}, failure_reason="Failed gate(s): SAFE")
        out = composer.compose(sr, vr)
        assert "rephrase" in out.recommended_action.lower()


# ===================================================================
# 8. FULL PIPELINE INTEGRATION
# ===================================================================

class TestFullPipeline:
    """End-to-end: raw text → Dispatcher → Conductor → Synthesizer → Validator → Composer."""

    def _run_pipeline(self, text, conductor, synthesizer, validator, composer):
        dispatcher = Dispatcher()
        req = dispatcher.dispatch(text)
        insights = conductor.conduct(req)
        sr = synthesizer.synthesize(insights)
        vr = validator.validate(sr, text)
        return composer.compose(sr, vr)

    def test_full_pipeline_stoic(self, conductor, synthesizer, validator, composer):
        # Saturate stoic-001 triggers (6/6) for high confidence (0.92 > 0.7).
        out = self._run_pipeline(
            "As a stoic I feel frustrated, helpless, out of control, "
            "stuck, powerless, and I can't change anything with virtue",
            conductor, synthesizer, validator, composer,
        )
        assert isinstance(out, ComposedOutput)
        assert out.primary_insight != ""

    def test_full_pipeline_empty_input(self, conductor, synthesizer, validator, composer):
        out = self._run_pipeline("", conductor, synthesizer, validator, composer)
        assert isinstance(out, ComposedOutput)

    def test_full_pipeline_no_matching_cartridges(self, synthesizer, validator, composer):
        cond = CartridgeConductor(cartridges=[])
        out = self._run_pipeline("anything", cond, synthesizer, validator, composer)
        assert isinstance(out, ComposedOutput)
        # No cartridges → no insights → degraded output.
        assert out.confidence == 0.0

    def test_full_pipeline_structure(self, conductor, synthesizer, validator, composer):
        out = self._run_pipeline(
            "I feel overwhelmed and anxious about everything",
            conductor, synthesizer, validator, composer,
        )
        # Structural contract.
        assert isinstance(out.summary, str)
        assert isinstance(out.primary_insight, str)
        assert isinstance(out.supporting_points, list)
        assert isinstance(out.tensions_flagged, list)
        assert isinstance(out.blind_spots, list)
        assert isinstance(out.recommended_action, str)
        assert isinstance(out.needs_served, list)
        assert isinstance(out.confidence, float)
        assert isinstance(out.gate_status, dict)

    def test_full_pipeline_rich_context(self, conductor, synthesizer, validator, composer):
        # Saturate stoic-009 + stoic-010 (share 'equanimity' tag → convergence)
        # and stoic-001 for broad coverage + high confidence.
        out = self._run_pipeline(
            "As a stoic I must endure with virtue. I feel overwhelmed, "
            "attacked, criticized, emotional, reactive, hurt, frustrated, "
            "helpless, stuck, powerless, catastrophizing, in crisis, "
            "panic, with no perspective",
            conductor, synthesizer, validator, composer,
        )
        # Rich context should trigger multiple rules → convergences.
        assert out.confidence > 0.0
        assert len(out.needs_served) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
