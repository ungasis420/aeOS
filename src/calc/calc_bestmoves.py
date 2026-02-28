"""
aeOS — qBestMoves Scoring (Pure Calculation Module)
This module implements the scoring formulas from Blueprint Module 9:
qBestMoves_v70 = (Demand_Score × 0.35) +
                 (Viability_Score × 0.35) +
                 (Interest_Score × 0.30)
qBestMoves_v75 = qBestMoves_v70 × PainM × BiasM × FreshM
Design goals (per build spec):
- Pure functions (no database, no I/O)
- No external dependencies
- Safe defaults for missing multipliers (default to 1.00) while logging
  data-quality flags for later cleanup
Tip:
- Base scores (Demand/Viability/Interest) are treated as required and validated
  to be within 0–100, because missing base scores usually indicates an upstream
  scoring issue, not a "multiplier missing" case.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Union
Number = Union[int, float]
logger = logging.getLogger(__name__)
# Library-style module: don't configure global logging; just avoid "No handler" warnings.
logger.addHandler(logging.NullHandler())
def get_pain_multiplier(pain_score: Optional[Number], has_linkage: Optional[bool]) -> float:
    """Return the Pain Alignment Multiplier (PainM).
    Rules (Blueprint Module 9):
    - No linkage → 0.75
    - pain_score >= 70 → 1.35
    - 50 <= pain_score < 70 → 1.15
    - pain_score < 50 → 1.00
    Missing-data behavior:
    - If has_linkage is unknown (None) OR pain_score is missing while linked,
      default multiplier = 1.00 and emit a data-quality flag via logging.
    Args:
        pain_score: Pain score in the 0–100 range, or None if unavailable.
        has_linkage: True if the idea is linked to a Pain record, False if not,
            or None if unknown.
    Returns:
        PainM multiplier as float.
    """
    # Key decision:
    # "No linkage" is a *real* state (not missing data) and must penalize to 0.75.
    if has_linkage is False:
        return 0.75
    # Key decision:
    # Unknown linkage is treated as missing multiplier input → default 1.00 + log.
    if has_linkage is None:
        logger.warning("PainM defaulted to 1.00: has_linkage is missing/unknown.")
        return 1.00
    # has_linkage is True
    if pain_score is None:
        logger.warning("PainM defaulted to 1.00: pain_score is missing despite linkage.")
        return 1.00
    ps = _to_float("pain_score", pain_score)
    _require_range("pain_score", ps, 0.0, 100.0)
    if ps >= 70.0:
        return 1.35
    if ps >= 50.0:
        return 1.15
    return 1.00
def get_bias_multiplier(bias_score: Optional[Number]) -> float:
    """Return the Bias Correction Multiplier (BiasM).
    Rules:
    - 0–19 → 1.00
    - 20–39 → 0.95
    - 40–59 → 0.85
    - 60–79 → 0.70
    - 80–100 → 0.50
    Missing-data behavior:
    - If bias_score is None, default multiplier = 1.00 and emit a data-quality flag.
    Args:
        bias_score: Bias score in the 0–100 range, or None if unavailable.
    Returns:
        BiasM multiplier as float.
    """
    if bias_score is None:
        logger.warning("BiasM defaulted to 1.00: bias_score is missing.")
        return 1.00
    bs = _to_float("bias_score", bias_score)
    _require_range("bias_score", bs, 0.0, 100.0)
    if bs <= 19.0:
        return 1.00
    if bs <= 39.0:
        return 0.95
    if bs <= 59.0:
        return 0.85
    if bs <= 79.0:
        return 0.70
    return 0.50
def get_fresh_multiplier(days_since_scored: Optional[int]) -> float:
    """Return the Freshness Multiplier (FreshM).
    Rules:
    - 0–30 days → 1.00
    - 31–60 → 0.95
    - 61–90 → 0.88
    - 91–180 → 0.75
    - 181–365 → 0.60
    - 366+ → 0.40  (to avoid overlap with the 181–365 bucket)
    Missing-data behavior:
    - If days_since_scored is None, default multiplier = 1.00 and emit a data-quality flag.
    Args:
        days_since_scored: Non-negative integer days since the record was scored,
            or None if unavailable.
    Returns:
        FreshM multiplier as float.
    """
    if days_since_scored is None:
        logger.warning("FreshM defaulted to 1.00: days_since_scored is missing.")
        return 1.00
    if not isinstance(days_since_scored, int):
        raise TypeError(f"days_since_scored must be int or None, got {type(days_since_scored).__name__}")
    if days_since_scored < 0:
        raise ValueError("days_since_scored must be >= 0")
    d = days_since_scored
    if d <= 30:
        return 1.00
    if d <= 60:
        return 0.95
    if d <= 90:
        return 0.88
    if d <= 180:
        return 0.75
    if d <= 365:
        return 0.60
    return 0.40
def calculate_v70(demand_score: Number, viability_score: Number, interest_score: Number) -> float:
    """Compute qBestMoves v7.0 base score (qBestMoves_v70).
    Formula:
        (Demand_Score × 0.35) + (Viability_Score × 0.35) + (Interest_Score × 0.30)
    Args:
        demand_score: 0–100 demand score.
        viability_score: 0–100 viability score.
        interest_score: 0–100 interest score.
    Returns:
        The v7.0 base score as float.
    """
    d = _to_float("demand_score", demand_score)
    v = _to_float("viability_score", viability_score)
    i = _to_float("interest_score", interest_score)
    _require_range("demand_score", d, 0.0, 100.0)
    _require_range("viability_score", v, 0.0, 100.0)
    _require_range("interest_score", i, 0.0, 100.0)
    return (d * 0.35) + (v * 0.35) + (i * 0.30)
def calculate_v75(
    demand_score: Number,
    viability_score: Number,
    interest_score: Number,
    pain_score: Optional[Number],
    has_pain_linkage: Optional[bool],
    bias_score: Optional[Number],
    days_since_scored: Optional[int],
) -> Dict[str, Any]:
    """Compute qBestMoves v7.5 score (qBestMoves_v75) and return full breakdown.
    Formula:
        qBestMoves_v75 = qBestMoves_v70 × PainM × BiasM × FreshM
    Defaults:
        - Missing PainM/BiasM/FreshM inputs default multiplier to 1.00 (no penalty),
          and the absence is logged + returned in `data_quality_flags`.
    Args:
        demand_score: 0–100 demand score.
        viability_score: 0–100 viability score.
        interest_score: 0–100 interest score.
        pain_score: 0–100 pain score, or None if unavailable.
        has_pain_linkage: True/False if linkage is known, or None if unknown.
        bias_score: 0–100 bias score, or None if unavailable.
        days_since_scored: Non-negative int days since scored, or None if unavailable.
    Returns:
        Dict with all components and the final qBestMoves_v75 score:
        - qBestMoves_v70
        - PainM / BiasM / FreshM
        - qBestMoves_v75
        - data_quality_flags (list of strings)
        - echoed inputs (normalized where appropriate)
    """
    flags: List[str] = []
    v70 = calculate_v70(demand_score, viability_score, interest_score)
    # Pain multiplier + flags
    if has_pain_linkage is False:
        flags.append("NO_PAIN_LINKAGE")
    elif has_pain_linkage is None:
        flags.append("MISSING_PAIN_LINKAGE")
    elif pain_score is None:
        flags.append("MISSING_PAIN_SCORE")
    pain_m = get_pain_multiplier(pain_score=pain_score, has_linkage=has_pain_linkage)
    # Bias multiplier + flags
    if bias_score is None:
        flags.append("MISSING_BIAS_SCORE")
    bias_m = get_bias_multiplier(bias_score=bias_score)
    # Fresh multiplier + flags
    if days_since_scored is None:
        flags.append("MISSING_DAYS_SINCE_SCORED")
    fresh_m = get_fresh_multiplier(days_since_scored=days_since_scored)
    v75 = v70 * pain_m * bias_m * fresh_m
    # Key decision:
    # Echo inputs in a way that doesn't break scoring when a field is irrelevant.
    # Example: pain_score is irrelevant when has_pain_linkage is False, so we avoid
    # raising just because an upstream pipeline sent a non-numeric pain_score.
    echoed_pain_score: Any
    if pain_score is None:
        echoed_pain_score = None
    elif has_pain_linkage is True:
        # Linked → pain_score matters → validate/normalize strictly.
        echoed_pain_score = _to_float("pain_score", pain_score)
    else:
        # Not linked / unknown linkage → best-effort echo only.
        if isinstance(pain_score, bool):
            echoed_pain_score = pain_score
            flags.append("NON_NUMERIC_PAIN_SCORE_ECHO")
        elif isinstance(pain_score, (int, float)):
            echoed_pain_score = float(pain_score)
        else:
            echoed_pain_score = pain_score
            flags.append("NON_NUMERIC_PAIN_SCORE_ECHO")
    # Key decision:
    # Return a fully inspectable breakdown to make the ranking auditable/debuggable.
    return {
        "demand_score": _to_float("demand_score", demand_score),
        "viability_score": _to_float("viability_score", viability_score),
        "interest_score": _to_float("interest_score", interest_score),
        "pain_score": echoed_pain_score,
        "has_pain_linkage": has_pain_linkage,
        "bias_score": None if bias_score is None else _to_float("bias_score", bias_score),
        "days_since_scored": days_since_scored,
        "qBestMoves_v70": v70,
        "PainM": pain_m,
        "BiasM": bias_m,
        "FreshM": fresh_m,
        "qBestMoves_v75": v75,
        "data_quality_flags": flags,
    }
def _to_float(name: str, value: Number) -> float:
    """Convert a numeric input to float with clear error messages."""
    if isinstance(value, bool):
        # bool is a subclass of int; reject to prevent accidental True/False scoring.
        raise TypeError(f"{name} must be a number (int/float), not bool")
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number (int/float), got {type(value).__name__}")
    return float(value)
def _require_range(name: str, value: float, minimum: float, maximum: float) -> None:
    """Raise ValueError if value is outside [minimum, maximum]."""
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum} (inclusive); got {value}")
