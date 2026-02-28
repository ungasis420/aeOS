"""calc_pain.py
Pure calculation helpers for aeOS Phase 0 (Pain Scan).
Implements the canonical Pain_Score calculation and threshold routing
per Blueprint Module 6.2 (Pain Engine).
Canonical formula:
    Pain_Score = (Severity × 40) + (Frequency_num × 30)
                 + (Monetizability_Flag × 20) + (Impact_Score × 10)
Thresholds:
- Pain_Score >= 60 → proceed to Solution Bridge (Phase 1)
- Pain_Score >= 60 AND Monetizability_Flag is True → spawn MoneyScan (Phase 2)
Input scale
-----------
The formula weights assume unit-normalized numeric inputs (0–1) so the
score lands in a 0–100 range. In practice, UI capture often uses 1–10
sliders for Severity / Frequency / Impact.
This module supports either:
- Normalized inputs: 0.0–1.0 (preferred for computation), OR
- Slider inputs: 1–10 (common for capture; internally divided by 10)
All three numeric inputs (severity, frequency_num, impact_score) must use
the *same* scale. Mixed scales (e.g., 0.7 and 7) are rejected.
No external dependencies (stdlib only). No database imports.
"""
from __future__ import annotations
from numbers import Real
from typing import List, Tuple, TypedDict
__all__ = [
    "SOLUTION_BRIDGE_THRESHOLD",
    "ThresholdAction",
    "validate_pain_inputs",
    "calculate_pain_score",
    "get_pain_threshold_action",
]
# --- Phase thresholds (Blueprint Module 6.2) ---------------------------------
SOLUTION_BRIDGE_THRESHOLD: float = 60.0
# --- Public types ------------------------------------------------------------
class ThresholdAction(TypedDict):
    """Return type for `get_pain_threshold_action`."""
    recommended_action: str
    next_phase: str
# --- Internal helpers --------------------------------------------------------
def _is_real_number(value: object) -> bool:
    """True if `value` is a real number (int/float), excluding booleans."""
    return isinstance(value, Real) and not isinstance(value, bool)
def _is_int_like(value: float) -> bool:
    """True if the value has no fractional part (e.g., 1 or 1.0)."""
    # Note: bool is excluded by _is_real_number; still guard for safety.
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and value.is_integer()
def _infer_scale(severity: float, frequency_num: float, impact_score: float) -> str:
    """Infer whether inputs are normalized (0–1) or slider-style (1–10).
    Heuristic:
    - If all three values are <= 1:
        - If they *all* look integer-like (0/1/1.0), treat as slider-style
          (ambiguity-resolving).
        - Otherwise treat as normalized.
    - Otherwise:
        - If any value is < 1 while another is > 1, treat as mixed.
        - Else treat as slider-style.
    """
    values = [severity, frequency_num, impact_score]
    all_leq_1 = all(v <= 1.0 for v in values)
    all_int_like = all(_is_int_like(v) for v in values)
    if all_leq_1:
        return "slider" if all_int_like else "normalized"
    if any(v < 1.0 for v in values) and any(v > 1.0 for v in values):
        return "mixed"
    return "slider"
def _to_unit_interval(value: float, scale: str) -> float:
    """Convert `value` to a 0–1 scale based on inferred scale."""
    return value / 10.0 if scale == "slider" else value
# --- Public API --------------------------------------------------------------
def validate_pain_inputs(
    severity: Real,
    frequency_num: Real,
    monetizability_flag: bool,
    impact_score: Real,
) -> Tuple[bool, List[str]]:
    """Validate inputs for Pain Score computation.
    Parameters
    ----------
    severity
        Severity on either a 0–1 scale or a 1–10 scale.
    frequency_num
        Numeric frequency on either a 0–1 scale or a 1–10 scale.
    monetizability_flag
        Whether the pain is plausibly monetizable.
    impact_score
        Impact on either a 0–1 scale or a 1–10 scale.
    Returns
    -------
    (is_valid, errors)
        - is_valid: True if all inputs are acceptable.
        - errors: list of human-readable error messages.
    """
    errors: List[str] = []
    # Type checks (bool is a subclass of int, so exclude it explicitly).
    if not _is_real_number(severity):
        errors.append("severity must be a real number (int/float), not bool/str.")
    if not _is_real_number(frequency_num):
        errors.append("frequency_num must be a real number (int/float), not bool/str.")
    if not isinstance(monetizability_flag, bool):
        errors.append("monetizability_flag must be a boolean (True/False).")
    if not _is_real_number(impact_score):
        errors.append("impact_score must be a real number (int/float), not bool/str.")
    if errors:
        return False, errors
    sev = float(severity)
    freq = float(frequency_num)
    imp = float(impact_score)
    # Range checks: allow up to 10 for slider-style capture.
    for name, v in (("severity", sev), ("frequency_num", freq), ("impact_score", imp)):
        if v < 0.0:
            errors.append(f"{name} must be >= 0.")
        if v > 10.0:
            errors.append(f"{name} must be <= 10 (or <= 1 for normalized inputs).")
    if errors:
        return False, errors
    # Mixed scale detection: reject obvious mixtures like 0.7 + 7.
    if (sev < 1.0 or freq < 1.0 or imp < 1.0) and (sev > 1.0 or freq > 1.0 or imp > 1.0):
        errors.append(
            "Inputs appear to mix normalized (0–1) and slider-style (1–10) scales. "
            "Use a consistent scale for severity, frequency_num, and impact_score."
        )
    return len(errors) == 0, errors
def calculate_pain_score(
    severity: Real,
    frequency_num: Real,
    monetizability_flag: bool,
    impact_score: Real,
) -> float:
    """Compute Pain_Score using the Blueprint Module 6.2 formula.
    Returns
    -------
    float
        Pain_Score in the 0–100 range when inputs use a consistent scale.
    Raises
    ------
    ValueError
        If any input is invalid. Use `validate_pain_inputs` if you prefer
        non-throwing validation.
    Examples
    --------
    # Slider-style inputs (1–10)
    >>> calculate_pain_score(8, 7, True, 8)
    81.0
    # Normalized inputs (0–1)
    >>> calculate_pain_score(0.8, 0.7, True, 0.8)
    81.0
    """
    is_valid, errors = validate_pain_inputs(severity, frequency_num, monetizability_flag, impact_score)
    if not is_valid:
        raise ValueError("Invalid pain inputs: " + "; ".join(errors))
    sev = float(severity)
    freq = float(frequency_num)
    imp = float(impact_score)
    scale = _infer_scale(sev, freq, imp)
    if scale == "mixed":
        # Defensive: should be blocked by validate_pain_inputs.
        raise ValueError("Mixed input scales detected; cannot compute Pain_Score.")
    sev_u = _to_unit_interval(sev, scale)
    freq_u = _to_unit_interval(freq, scale)
    imp_u = _to_unit_interval(imp, scale)
    monetizable = 1.0 if monetizability_flag else 0.0
    pain_score = (sev_u * 40.0) + (freq_u * 30.0) + (monetizable * 20.0) + (imp_u * 10.0)
    # Guard against tiny float drift beyond bounds.
    if pain_score < 0.0:
        pain_score = 0.0
    elif pain_score > 100.0:
        pain_score = 100.0
    return float(pain_score)
def get_pain_threshold_action(pain_score: Real, monetizability_flag: bool) -> ThresholdAction:
    """Return the recommended next step based on Pain_Score and monetizability.
    Parameters
    ----------
    pain_score
        The computed Pain_Score (expected 0–100).
    monetizability_flag
        Whether the pain is plausibly monetizable.
    Returns
    -------
    ThresholdAction
        Dict with:
        - recommended_action: human-readable instruction
        - next_phase: "Phase_0" | "Phase_1" | "Phase_2"
    Raises
    ------
    ValueError
        If inputs are invalid.
    """
    if not _is_real_number(pain_score):
        raise ValueError("pain_score must be a real number (int/float), not bool/str.")
    if not isinstance(monetizability_flag, bool):
        raise ValueError("monetizability_flag must be a boolean (True/False).")
    score = float(pain_score)
    if score >= SOLUTION_BRIDGE_THRESHOLD and monetizability_flag:
        return {
            "recommended_action": "Proceed to Solution Bridge (Phase 1) and spawn MoneyScan (Phase 2).",
            "next_phase": "Phase_2",
        }
    if score >= SOLUTION_BRIDGE_THRESHOLD:
        return {
            "recommended_action": "Proceed to Solution Bridge (Phase 1).",
            "next_phase": "Phase_1",
        }
    return {
        "recommended_action": (
            "Remain in Pain Scan (Phase 0) — refine inputs / gather evidence until Pain_Score >= 60."
        ),
        "next_phase": "Phase_0",
    }
