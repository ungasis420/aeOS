"""
reasoning_synthesizer.py — Bridges CartridgeInsight list to ReasoningSubstrate.

Converts the orchestration-layer CartridgeInsight objects into the raw dict
format expected by ``reasoning_substrate.synthesise()`` and returns the
resulting SynthesisResult.

Stamp: S✅ T✅ L✅ A✅
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from src.cognitive.reasoning_substrate import SynthesisResult, synthesise
from src.orchestration.models import CartridgeInsight

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insight_to_dict(ci: CartridgeInsight) -> Dict[str, Any]:
    """Convert a CartridgeInsight dataclass to the dict schema
    expected by ``synthesise()``."""
    return {
        "rule_id": ci.rule_id,
        "name": ci.rule_id,  # rule_id as fallback name
        "principle": "",
        "matched_triggers": [],
        "insight": ci.insight_text,
        "confidence": ci.confidence,
        "sovereign_need_served": ci.sovereign_need,
        "connects_to": [],
        "tags": list(ci.tags),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class ReasoningSynthesizer:
    """Wraps the reasoning substrate for the orchestration pipeline."""

    def synthesize(self, insights: List[CartridgeInsight]) -> SynthesisResult:
        """Run synthesis over a list of CartridgeInsight objects.

        Returns a SynthesisResult.  If *insights* is empty the substrate
        returns a null result with an explanatory recommended_action.
        """
        if not insights:
            logger.info("ReasoningSynthesizer received empty insight list")
            return synthesise([])

        dicts = [_insight_to_dict(ci) for ci in insights]
        result = synthesise(dicts)

        logger.info(
            "Synthesis produced: confidence=%.2f convergences=%d tensions=%d blind_spots=%d",
            result.overall_confidence,
            len(result.convergences),
            len(result.tensions),
            len(result.blind_spots),
        )
        return result
