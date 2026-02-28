"""calc_brier.py
Pure calculation utilities for prediction calibration.
This module implements the Brier Score and related helpers, intended for
binary outcomes and probabilistic forecasts:
- predicted_value: probability in the unit interval [0.0, 1.0]
- actual_value: observed outcome in [0.0, 1.0] (typically 0.0 or 1.0)
Brier Score definition:
    Brier_Score = (predicted_value - actual_value) ** 2
Lower is better. With inputs constrained to [0, 1], the score ranges
from 0.0 (perfect) to 1.0 (worst).
No external dependencies. No database imports.
"""
from __future__ import annotations
from numbers import Real
from typing import Iterable, List
def _as_unit_interval(value: Real, *, name: str) -> float:
    """Convert a numeric input to float and validate it is within [0, 1].
    Key decision:
        We validate *all* public inputs to prevent silent bad calibration math.
        (Example: passing 75 instead of 0.75 should fail fast.)
    Args:
        value: A numeric value (int/float/bool) expected to be in [0, 1].
        name: Field name used for error messages.
    Returns:
        The value converted to float.
    Raises:
        TypeError: If value is not a real number.
        ValueError: If value is outside [0, 1].
    """
    if not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number, got {type(value).__name__}")
    # bool is a valid Real, but we normalize it explicitly to avoid surprises.
    v = 1.0 if value is True else 0.0 if value is False else float(value)
    if v < 0.0 or v > 1.0:
        raise ValueError(f"{name} must be within [0.0, 1.0], got {v}")
    return v
def calculate_brier_score(predicted_value: Real, actual_value: Real) -> float:
    """Compute the Brier Score for a single prediction.
    Brier Score is the squared error between predicted probability and actual outcome:
        brier = (predicted_value - actual_value) ** 2
    Args:
        predicted_value: Predicted probability in [0, 1].
        actual_value: Actual outcome in [0, 1] (often 0 or 1).
    Returns:
        Brier score as a float in [0.0, 1.0].
    Raises:
        TypeError: If inputs are not real numbers.
        ValueError: If inputs are outside [0, 1].
    """
    # Reuse calculate_delta() for consistent validation and a single "source of truth".
    d = calculate_delta(predicted_value, actual_value)
    return d * d
def calculate_delta(predicted_value: Real, actual_value: Real) -> float:
    """Compute the signed prediction error (delta).
    Delta is defined as:
        delta = predicted_value - actual_value
    Args:
        predicted_value: Predicted probability in [0, 1].
        actual_value: Actual outcome in [0, 1] (often 0 or 1).
    Returns:
        Signed error as a float in [-1.0, 1.0].
    Raises:
        TypeError: If inputs are not real numbers.
        ValueError: If inputs are outside [0, 1].
    """
    p = _as_unit_interval(predicted_value, name="predicted_value")
    a = _as_unit_interval(actual_value, name="actual_value")
    return p - a
def calculate_running_brier(scores_list: Iterable[Real]) -> float:
    """Compute the running (mean) Brier Score over a list/stream of scores.
    Running Brier Score is the arithmetic mean of individual Brier scores:
        running = sum(scores) / len(scores)
    Args:
        scores_list: Iterable of individual Brier scores, each expected in [0, 1].
    Returns:
        Mean Brier score as a float in [0.0, 1.0].
    Raises:
        ValueError: If the iterable is empty or contains out-of-range values.
        TypeError: If any item is not a real number.
    """
    # Convert to list so we can validate and count without consuming a generator twice.
    scores: List[float] = []
    for i, s in enumerate(scores_list):
        scores.append(_as_unit_interval(s, name=f"scores_list[{i}]"))
    if not scores:
        raise ValueError("scores_list must contain at least one Brier score")
    return sum(scores) / float(len(scores))
def get_calibration_quality(running_brier: Real) -> str:
    """Map a running Brier score to a human-readable calibration label.
    Thresholds (per spec):
        - "Excellent" : running_brier < 0.1
        - "Good"      : 0.1 <= running_brier < 0.2
        - "Fair"      : 0.2 <= running_brier <= 0.3
        - "Poor"      : running_brier > 0.3
    Args:
        running_brier: Mean Brier score in [0, 1].
    Returns:
        One of: "Excellent", "Good", "Fair", "Poor".
    Raises:
        TypeError: If running_brier is not a real number.
        ValueError: If running_brier is outside [0, 1].
    """
    rb = _as_unit_interval(running_brier, name="running_brier")
    # Keep boundaries explicit to match the spec wording precisely.
    if rb < 0.1:
        return "Excellent"
    if rb < 0.2:
        return "Good"
    if rb <= 0.3:
        return "Fair"
    return "Poor"
__all__ = [
    "calculate_brier_score",
    "calculate_delta",
    "calculate_running_brier",
    "get_calibration_quality",
]
