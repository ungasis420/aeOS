"""
output_composer.py — Formats a validated SynthesisResult into ComposedOutput.

Produces the final response dict delivered to the caller.  If validation
failed, composes a degraded output explaining which gate failed.

Stamp: S✅ T✅ L✅ A✅
"""
from __future__ import annotations

import logging
from typing import List

from src.cognitive.reasoning_substrate import SynthesisResult
from src.orchestration.models import ComposedOutput, ValidationResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_summary(result: SynthesisResult) -> str:
    """Build a one-liner summary from the synthesis result."""
    primary = result.primary_insight
    if not primary:
        return "No actionable insight could be derived."
    name = primary.get("name", "Insight")
    conf = result.overall_confidence
    n_supporting = len(result.supporting_insights)
    return (
        f"{name} (confidence {conf:.0%}) with "
        f"{n_supporting} supporting insight(s)."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class OutputComposer:
    """Formats SynthesisResult + ValidationResult into a ComposedOutput."""

    def compose(
        self,
        result: SynthesisResult,
        validation: ValidationResult,
    ) -> ComposedOutput:
        """Produce a ComposedOutput.

        If *validation.passed* is ``False``, the output is degraded: the
        summary explains which gate failed and the primary insight is
        replaced with a safe fallback.
        """
        if not validation.passed:
            return self._compose_degraded(result, validation)

        primary_text = ""
        if result.primary_insight:
            primary_text = result.primary_insight.get("insight", "")

        supporting: List[str] = [
            si.get("insight", "") for si in result.supporting_insights if si.get("insight")
        ]

        tensions: List[str] = [t.description for t in result.tensions]
        blind: List[str] = [b.description for b in result.blind_spots]

        output = ComposedOutput(
            summary=_build_summary(result),
            primary_insight=primary_text,
            supporting_points=supporting,
            tensions_flagged=tensions,
            blind_spots=blind,
            recommended_action=result.recommended_action,
            needs_served=list(result.needs_served),
            confidence=result.overall_confidence,
            gate_status=dict(validation.gates),
        )

        logger.info("Composed full output: confidence=%.2f", output.confidence)
        return output

    # ------------------------------------------------------------------

    def _compose_degraded(
        self,
        result: SynthesisResult,
        validation: ValidationResult,
    ) -> ComposedOutput:
        """Produce a safe degraded output when validation fails."""
        reason = validation.failure_reason or "Unknown validation failure."
        return ComposedOutput(
            summary=f"Output withheld — {reason}",
            primary_insight="",
            supporting_points=[],
            tensions_flagged=[],
            blind_spots=[],
            recommended_action="Please rephrase or provide more context.",
            needs_served=[],
            confidence=0.0,
            gate_status=dict(validation.gates),
        )
