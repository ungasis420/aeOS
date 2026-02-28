"""
calc_calibration.py
Pure stdlib-only calibration tracker for aeOS.
Purpose
-------
Maintain a predictor's running Brier score from a stream of
(predicted_probability, actual_outcome) pairs.
Constraints
-----------
- predicted_probability: float in [0.0, 1.0]
- actual_outcome: int in {0, 1}
- stdlib only (no external dependencies)
Brier score for one event:
    (predicted_probability - actual_outcome) ** 2
"""
from __future__ import annotations
import math
from numbers import Real
from typing import Any, Dict, List, Optional, Tuple
Pair = Tuple[float, int]
def _validate_predicted(value: Real) -> float:
    """Validate predicted probability in [0.0, 1.0] and return it as float.
    Args:
        value: A real number representing a probability.
    Returns:
        The validated probability as float.
    Raises:
        TypeError: If value is not a real number or is a boolean.
        ValueError: If value is NaN/inf or outside [0.0, 1.0].
    """
    if not isinstance(value, Real) or isinstance(value, bool):
        raise TypeError(f"predicted must be a real number (int/float), got {type(value).__name__}")
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"predicted must be finite, got {v}")
    if v < 0.0 or v > 1.0:
        raise ValueError(f"predicted must be within [0.0, 1.0], got {v}")
    return v
def _validate_actual(value: int) -> int:
    """Validate actual outcome is exactly 0 or 1 and return it as int.
    Args:
        value: Observed outcome.
    Returns:
        The validated outcome (0 or 1).
    Raises:
        TypeError: If value is not an int or is a boolean.
        ValueError: If value is not 0 or 1.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"actual must be an int (0 or 1), got {type(value).__name__}")
    if value not in (0, 1):
        raise ValueError(f"actual must be 0 or 1, got {value}")
    return int(value)
class CalibrationTracker:
    """Maintain running Brier score for binary probabilistic predictions.
    Stores:
      - Full history of (predicted, actual) pairs
      - Incremental running mean (Brier score)
      - Best/worst individual scores observed
    """
    def __init__(self) -> None:
        """Initialize an empty tracker with zero observations."""
        self._history: List[Pair] = []
        self._count: int = 0
        self._mean_score: float = 0.0
        self._best_score: Optional[float] = None
        self._worst_score: Optional[float] = None
    def update(self, predicted: float, actual: int) -> float:
        """Add one (predicted, actual) pair and update the running Brier score.
        Args:
            predicted: Predicted probability in [0.0, 1.0].
            actual: Observed outcome (0 or 1).
        Returns:
            Updated running (mean) Brier score as float.
        Raises:
            TypeError: If inputs are of the wrong type.
            ValueError: If inputs are out of range.
        """
        p = _validate_predicted(predicted)
        a = _validate_actual(actual)
        score = (p - float(a)) ** 2
        self._history.append((p, a))
        self._count += 1
        # Incremental mean update:
        # mean_new = mean_old + (x - mean_old) / n
        self._mean_score = self._mean_score + (score - self._mean_score) / float(self._count)
        if self._best_score is None or score < self._best_score:
            self._best_score = score
        if self._worst_score is None or score > self._worst_score:
            self._worst_score = score
        return float(self._mean_score)
    def get_score(self) -> float:
        """Return the current running Brier score.
        Returns:
            Current running mean Brier score. If there is no history yet,
            returns 0.0.
        """
        return float(self._mean_score) if self._count > 0 else 0.0
    def get_history(self) -> List[Pair]:
        """Return the full history of prediction/outcome pairs.
        Returns:
            A copy of the internal list of (predicted, actual) tuples.
        """
        return list(self._history)
    def reset(self) -> None:
        """Clear all stored history and reset running statistics."""
        self._history.clear()
        self._count = 0
        self._mean_score = 0.0
        self._best_score = None
        self._worst_score = None
    def to_dict(self) -> Dict[str, Any]:
        """Serialize this tracker to a JSON-safe dict.
        Returns:
            JSON-safe dict representation:
              - schema_version: int
              - history: list of [predicted, actual] pairs
        """
        return {
            "schema_version": 1,
            "history": [[p, a] for (p, a) in self._history],
        }
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalibrationTracker":
        """Reconstruct a CalibrationTracker from a dict produced by to_dict().
        Args:
            data: Dict containing at least a `history` list.
        Returns:
            A reconstructed CalibrationTracker instance.
        Raises:
            TypeError: If `data` (or history) is the wrong type.
            ValueError: If any history entry is malformed or out of range.
        """
        if not isinstance(data, dict):
            raise TypeError(f"data must be a dict, got {type(data).__name__}")
        tracker = cls()
        history = data.get("history", [])
        if history is None:
            return tracker
        if not isinstance(history, list):
            raise TypeError("history must be a list of [predicted, actual] pairs")
        for i, item in enumerate(history):
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise ValueError(f"history[{i}] must be a 2-item list/tuple [predicted, actual]")
            predicted_raw, actual_raw = item[0], item[1]
            tracker.update(predicted=predicted_raw, actual=actual_raw)
        return tracker
    def summary(self) -> Dict[str, Any]:
        """Return summary stats for the tracked calibration performance.
        Returns:
            Dict with:
              - count: int
              - mean_score: float (running mean; 0.0 if empty)
              - best_score: float | None (min individual score; None if empty)
              - worst_score: float | None (max individual score; None if empty)
        """
        return {
            "count": int(self._count),
            "mean_score": float(self.get_score()),
            "best_score": None if self._best_score is None else float(self._best_score),
            "worst_score": None if self._worst_score is None else float(self._worst_score),
        }
__all__ = ["CalibrationTracker"]
