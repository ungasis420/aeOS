"""
tests/test_reasoning_substrate.py

Pytest unit tests for `src.cognitive.reasoning_substrate`.

Tests cover convergence detection, tension detection, blind-spot detection,
the full synthesise() pipeline, edge cases, and integration with the real
stoic cartridge via cartridge_loader.

Stamp: S✅ T✅ L✅ A✅
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Ensure repo root is importable when running `pytest` from different CWDs.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.cognitive.reasoning_substrate import (
    UNIVERSAL_DIMENSIONS,
    BlindSpot,
    Convergence,
    SynthesisResult,
    Tension,
    _compute_overall_confidence,
    _detect_blind_spots,
    _detect_convergences,
    _detect_tensions,
    _pick_primary,
    synthesise,
)
from src.cognitive.cartridge_loader import (
    load_cartridge,
    load_schema,
    run_rules,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_CARTRIDGES_DIR = Path(_REPO_ROOT) / "src" / "cartridges"
_SCHEMA_PATH = _CARTRIDGES_DIR / "cartridge_schema.json"
_STOIC_PATH = _CARTRIDGES_DIR / "stoic.json"


# ---------------------------------------------------------------------------
# Fixtures — synthetic insights
# ---------------------------------------------------------------------------

def _make_insight(
    rule_id: str,
    name: str = "Rule",
    principle: str = "A principle",
    confidence: float = 0.5,
    tags: list | None = None,
    sovereign_need_served: str = "clarity",
    insight: str = "An insight.",
    connects_to: list | None = None,
    matched_triggers: list | None = None,
) -> dict:
    return {
        "rule_id": rule_id,
        "name": name,
        "principle": principle,
        "matched_triggers": matched_triggers or ["trigger"],
        "insight": insight,
        "confidence": confidence,
        "sovereign_need_served": sovereign_need_served,
        "connects_to": connects_to or [],
        "tags": tags or [],
    }


@pytest.fixture()
def converging_insights():
    """Two insights sharing the 'resilience' tag → convergence."""
    return [
        _make_insight("r1", name="Alpha", tags=["resilience", "growth"], confidence=0.8,
                       sovereign_need_served="resilience"),
        _make_insight("r2", name="Beta", tags=["resilience", "discipline"], confidence=0.7,
                       sovereign_need_served="resilience"),
    ]


@pytest.fixture()
def conflicting_insights():
    """Two insights with opposing tags → tension."""
    return [
        _make_insight("c1", name="Accept", tags=["acceptance", "calm"], confidence=0.85,
                       principle="Accept what you cannot change.",
                       sovereign_need_served="resilience"),
        _make_insight("c2", name="Discipline", tags=["discipline", "effort"], confidence=0.80,
                       principle="Push through hardship.",
                       sovereign_need_served="resilience"),
    ]


@pytest.fixture()
def narrow_insights():
    """Insights that only serve 'autonomy' — leaving many blind spots."""
    return [
        _make_insight("n1", tags=["control"], sovereign_need_served="autonomy", confidence=0.9),
        _make_insight("n2", tags=["agency"], sovereign_need_served="autonomy", confidence=0.85),
    ]


@pytest.fixture()
def schema():
    return load_schema(_SCHEMA_PATH)


@pytest.fixture()
def stoic(schema):
    return load_cartridge(_STOIC_PATH, schema)


# ---------------------------------------------------------------------------
# Convergence detection
# ---------------------------------------------------------------------------

class TestDetectConvergences:
    def test_shared_tag_yields_convergence(self, converging_insights):
        convs = _detect_convergences(converging_insights)
        assert len(convs) >= 1
        resilience_conv = [c for c in convs if c.theme == "resilience"]
        assert len(resilience_conv) == 1
        assert set(resilience_conv[0].supporting_rule_ids) == {"r1", "r2"}

    def test_mean_confidence(self, converging_insights):
        convs = _detect_convergences(converging_insights)
        resilience_conv = [c for c in convs if c.theme == "resilience"][0]
        assert resilience_conv.mean_confidence == pytest.approx(0.75, abs=0.01)

    def test_no_convergence_with_single_insight(self):
        single = [_make_insight("x1", tags=["alpha"])]
        assert _detect_convergences(single) == []

    def test_no_convergence_with_disjoint_tags(self):
        disjoint = [
            _make_insight("d1", tags=["alpha"]),
            _make_insight("d2", tags=["beta"]),
        ]
        assert _detect_convergences(disjoint) == []

    def test_convergence_summary_is_readable(self, converging_insights):
        convs = _detect_convergences(converging_insights)
        for c in convs:
            assert isinstance(c.summary, str)
            assert len(c.summary) > 10

    def test_shared_tags_computed_correctly(self, converging_insights):
        convs = _detect_convergences(converging_insights)
        resilience_conv = [c for c in convs if c.theme == "resilience"][0]
        # Both share 'resilience' but differ on growth/discipline.
        assert "resilience" in resilience_conv.shared_tags


# ---------------------------------------------------------------------------
# Tension detection
# ---------------------------------------------------------------------------

class TestDetectTensions:
    def test_opposing_tags_yield_tension(self, conflicting_insights):
        tens = _detect_tensions(conflicting_insights)
        assert len(tens) >= 1
        ids = {tens[0].rule_id_a, tens[0].rule_id_b}
        assert ids == {"c1", "c2"}

    def test_no_tension_with_single_insight(self):
        assert _detect_tensions([_make_insight("x")]) == []

    def test_no_tension_with_non_opposing_tags(self):
        pair = [
            _make_insight("a", tags=["alpha"]),
            _make_insight("b", tags=["beta"]),
        ]
        assert _detect_tensions(pair) == []

    def test_tension_description_is_readable(self, conflicting_insights):
        tens = _detect_tensions(conflicting_insights)
        assert "tension" in tens[0].description.lower() or "resolve" in tens[0].description.lower()

    def test_tension_captures_principles(self, conflicting_insights):
        tens = _detect_tensions(conflicting_insights)
        assert tens[0].principle_a != ""
        assert tens[0].principle_b != ""

    def test_one_tension_per_pair(self):
        """Even if multiple opposing-tag combos exist, only one tension per pair."""
        pair = [
            _make_insight("a", tags=["acceptance", "presence"]),
            _make_insight("b", tags=["discipline", "preparation"]),
        ]
        tens = _detect_tensions(pair)
        assert len(tens) == 1


# ---------------------------------------------------------------------------
# Blind-spot detection
# ---------------------------------------------------------------------------

class TestDetectBlindSpots:
    def test_narrow_insights_leave_blind_spots(self, narrow_insights):
        spots = _detect_blind_spots(narrow_insights)
        spot_dims = {s.dimension for s in spots}
        # Only 'autonomy' served → everything else is a blind spot.
        assert "security" in spot_dims
        assert "purpose" in spot_dims
        assert "belonging" in spot_dims
        assert "autonomy" not in spot_dims

    def test_full_coverage_no_blind_spots(self):
        insights = [
            _make_insight(f"d{i}", sovereign_need_served=dim)
            for i, dim in enumerate(UNIVERSAL_DIMENSIONS)
        ]
        spots = _detect_blind_spots(insights)
        assert spots == []

    def test_empty_insights_all_blind_spots(self):
        spots = _detect_blind_spots([])
        assert len(spots) == len(UNIVERSAL_DIMENSIONS)

    def test_tags_can_cover_dimensions(self):
        ins = [_make_insight("t1", sovereign_need_served="autonomy", tags=["security"])]
        spots = _detect_blind_spots(ins)
        spot_dims = {s.dimension for s in spots}
        assert "autonomy" not in spot_dims
        assert "security" not in spot_dims

    def test_custom_dimensions(self):
        custom = {"alpha", "beta"}
        ins = [_make_insight("c1", sovereign_need_served="alpha")]
        spots = _detect_blind_spots(ins, dimensions=custom)
        assert len(spots) == 1
        assert spots[0].dimension == "beta"

    def test_blind_spot_description(self, narrow_insights):
        spots = _detect_blind_spots(narrow_insights)
        for s in spots:
            assert s.dimension in s.description


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_pick_primary_highest_confidence(self):
        ins = [
            _make_insight("lo", confidence=0.3),
            _make_insight("hi", confidence=0.9),
            _make_insight("mid", confidence=0.6),
        ]
        primary = _pick_primary(ins)
        assert primary["rule_id"] == "hi"

    def test_compute_overall_confidence(self):
        ins = [
            _make_insight("a", confidence=0.8),
            _make_insight("b", confidence=0.6),
        ]
        assert _compute_overall_confidence(ins) == pytest.approx(0.7, abs=0.01)

    def test_compute_overall_confidence_empty(self):
        assert _compute_overall_confidence([]) == 0.0


# ---------------------------------------------------------------------------
# Full synthesis pipeline
# ---------------------------------------------------------------------------

class TestSynthesise:
    def test_empty_input(self):
        result = synthesise([])
        assert isinstance(result, SynthesisResult)
        assert result.primary_insight == {}
        assert result.supporting_insights == []
        assert result.overall_confidence == 0.0
        assert result.needs_served == []
        assert len(result.blind_spots) == len(UNIVERSAL_DIMENSIONS)
        assert "No insights" in result.recommended_action

    def test_single_insight(self):
        ins = [_make_insight("solo", confidence=0.77, sovereign_need_served="purpose",
                             insight="Stay focused.")]
        result = synthesise(ins)
        assert result.primary_insight["rule_id"] == "solo"
        assert result.supporting_insights == []
        assert result.overall_confidence == pytest.approx(0.77, abs=0.01)
        assert "purpose" in result.needs_served

    def test_convergences_appear(self, converging_insights):
        result = synthesise(converging_insights)
        assert len(result.convergences) >= 1
        themes = [c.theme for c in result.convergences]
        assert "resilience" in themes

    def test_tensions_appear(self, conflicting_insights):
        result = synthesise(conflicting_insights)
        assert len(result.tensions) >= 1

    def test_blind_spots_appear(self, narrow_insights):
        result = synthesise(narrow_insights)
        assert len(result.blind_spots) > 0

    def test_needs_served_list(self, converging_insights):
        result = synthesise(converging_insights)
        assert "resilience" in result.needs_served

    def test_recommended_action_non_empty(self, converging_insights):
        result = synthesise(converging_insights)
        assert isinstance(result.recommended_action, str)
        assert len(result.recommended_action) > 10

    def test_primary_is_highest_confidence(self):
        ins = [
            _make_insight("lo", confidence=0.3),
            _make_insight("hi", confidence=0.95),
            _make_insight("mid", confidence=0.6),
        ]
        result = synthesise(ins)
        assert result.primary_insight["rule_id"] == "hi"

    def test_supporting_excludes_primary(self):
        ins = [
            _make_insight("a", confidence=0.9),
            _make_insight("b", confidence=0.5),
        ]
        result = synthesise(ins)
        sup_ids = [s["rule_id"] for s in result.supporting_insights]
        assert result.primary_insight["rule_id"] not in sup_ids

    def test_recommended_action_mentions_tensions(self, conflicting_insights):
        result = synthesise(conflicting_insights)
        assert "tension" in result.recommended_action.lower()

    def test_recommended_action_mentions_blind_spots(self, narrow_insights):
        result = synthesise(narrow_insights)
        assert "dimension" in result.recommended_action.lower() or "unexplored" in result.recommended_action.lower()

    def test_custom_dimensions_propagate(self):
        custom = {"alpha", "beta"}
        ins = [_make_insight("x", sovereign_need_served="alpha")]
        result = synthesise(ins, dimensions=custom)
        spot_dims = {s.dimension for s in result.blind_spots}
        assert "beta" in spot_dims
        assert "alpha" not in spot_dims

    def test_convergences_and_tensions_coexist(self):
        """A rich context can produce both convergences and tensions."""
        ins = [
            _make_insight("a", tags=["resilience", "acceptance"], confidence=0.8,
                           sovereign_need_served="resilience"),
            _make_insight("b", tags=["resilience", "discipline"], confidence=0.7,
                           sovereign_need_served="resilience"),
            _make_insight("c", tags=["growth"], confidence=0.6,
                           sovereign_need_served="growth"),
        ]
        result = synthesise(ins)
        assert len(result.convergences) >= 1
        assert len(result.tensions) >= 1


# ---------------------------------------------------------------------------
# Integration: stoic cartridge → reasoning substrate
# ---------------------------------------------------------------------------

class TestStoicIntegration:
    def test_overwhelmed_context(self, stoic):
        context = {
            "situation": "a failing startup",
            "mood": "overwhelmed, anxious, frustrated, isolated",
        }
        insights = run_rules(stoic, context)
        assert len(insights) >= 3  # sanity: multiple rules should fire

        result = synthesise(insights)
        assert isinstance(result, SynthesisResult)
        assert result.primary_insight != {}
        assert result.overall_confidence > 0.0
        assert len(result.needs_served) >= 2

    def test_stoic_convergences_detected(self, stoic):
        context = {
            "situation": "career uncertainty",
            "mood": "anxious, worried, overwhelmed, catastrophizing",
        }
        insights = run_rules(stoic, context)
        result = synthesise(insights)
        # Multiple stoic rules share tags like 'equanimity'.
        assert len(result.convergences) >= 1

    def test_stoic_tensions_detected(self, stoic):
        # Trigger Amor Fati (acceptance tag) via "suffering"/"setback" AND
        # Voluntary Discomfort (discipline tag) via "comfort zone"/"afraid".
        context = {
            "situation": "a painful career change",
            "mood": "suffering, setback, afraid, comfort zone",
        }
        insights = run_rules(stoic, context)
        result = synthesise(insights)
        # Acceptance vs discipline tension should surface.
        assert len(result.tensions) >= 1

    def test_stoic_blind_spots_detected(self, stoic):
        # Narrow context → not all universal dimensions served.
        context = {"situation": "a minor annoyance", "mood": "frustrated"}
        insights = run_rules(stoic, context)
        result = synthesise(insights)
        assert len(result.blind_spots) >= 1

    def test_stoic_recommended_action_is_meaningful(self, stoic):
        context = {
            "situation": "a broken relationship",
            "mood": "hurt, isolated, overwhelmed, regret",
        }
        insights = run_rules(stoic, context)
        result = synthesise(insights)
        assert len(result.recommended_action) > 20
        # Should mention the situation from the template rendering.
        assert "broken relationship" in result.recommended_action.lower()

    def test_stoic_full_pipeline_structure(self, stoic):
        context = {
            "situation": "being criticized publicly",
            "mood": "attacked, hurt, reactive, overwhelmed, status",
        }
        insights = run_rules(stoic, context)
        result = synthesise(insights)

        # Structural contract.
        assert isinstance(result.primary_insight, dict)
        assert isinstance(result.supporting_insights, list)
        assert isinstance(result.convergences, list)
        assert isinstance(result.tensions, list)
        assert isinstance(result.blind_spots, list)
        assert isinstance(result.recommended_action, str)
        assert isinstance(result.overall_confidence, float)
        assert isinstance(result.needs_served, list)
        assert 0.0 < result.overall_confidence <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
