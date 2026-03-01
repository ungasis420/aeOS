"""
output_validator.py — 4-Gate validation for SynthesisResult.

Runs the SAFE / TRUE / HIGH-LEVERAGE / ALIGNED gates before a synthesis
result is delivered to the user.

Stamp: S✅ T✅ L✅ A✅
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List

from src.cognitive.reasoning_substrate import SynthesisResult
from src.orchestration.models import ValidationResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PII detection patterns (Gate 1 — SAFE)
# ---------------------------------------------------------------------------

_PII_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),  # email
    re.compile(r"\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b"),                      # SSN
    re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),# phone
    re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),            # credit card
]

_HARMFUL_KEYWORDS: List[str] = [
    "kill yourself", "self harm", "suicide method", "hurt others",
    "illegal", "exploit", "hack password",
]


def _collect_text(result: SynthesisResult) -> str:
    """Flatten all textual fields of a SynthesisResult into one string."""
    parts: List[str] = []
    if result.primary_insight:
        parts.append(result.primary_insight.get("insight", ""))
        parts.append(result.primary_insight.get("principle", ""))
    for si in result.supporting_insights:
        parts.append(si.get("insight", ""))
    parts.append(result.recommended_action)
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Individual gates
# ---------------------------------------------------------------------------


def _gate_safe(result: SynthesisResult, original_text: str) -> bool:
    """Gate 1 — SAFE: no PII in insights, no harmful recommendations."""
    blob = _collect_text(result)
    for pat in _PII_PATTERNS:
        if pat.search(blob):
            return False
    lower = blob.lower()
    for kw in _HARMFUL_KEYWORDS:
        if kw in lower:
            return False
    return True


def _gate_true(result: SynthesisResult) -> bool:
    """Gate 2 — TRUE: confidence > 0.4 and primary insight exists."""
    if result.overall_confidence <= 0.4:
        return False
    if not result.primary_insight:
        return False
    return True


def _gate_high_leverage(result: SynthesisResult) -> bool:
    """Gate 3 — HIGH-LEVERAGE: at least one convergence OR confidence > 0.7."""
    if result.convergences:
        return True
    if result.overall_confidence > 0.7:
        return True
    return False


def _gate_aligned(result: SynthesisResult) -> bool:
    """Gate 4 — ALIGNED: at least one sovereign need served."""
    return len(result.needs_served) > 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class OutputValidator:
    """Runs 4-gate validation on a SynthesisResult."""

    def validate(
        self,
        result: SynthesisResult,
        original_text: str,
    ) -> ValidationResult:
        """Return a ValidationResult indicating whether all gates passed.

        Gates:
        1. SAFE — no PII, no harmful content
        2. TRUE — confidence > 0.4, primary insight present
        3. HIGH-LEVERAGE — convergence exists or confidence > 0.7
        4. ALIGNED — at least one sovereign need served
        """
        gates: Dict[str, bool] = {
            "SAFE": _gate_safe(result, original_text),
            "TRUE": _gate_true(result),
            "HIGH-LEVERAGE": _gate_high_leverage(result),
            "ALIGNED": _gate_aligned(result),
        }

        failed = [name for name, ok in gates.items() if not ok]
        passed = len(failed) == 0
        reason = f"Failed gate(s): {', '.join(failed)}" if failed else None

        if not passed:
            logger.warning("Validation failed: %s", reason)

        return ValidationResult(passed=passed, gates=gates, failure_reason=reason)
