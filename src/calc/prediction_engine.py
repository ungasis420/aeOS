"""prediction_engine.py
aeOS — Prediction Engine (Pure Logic Layer)
Purpose
-------
Create, resolve, and evaluate probabilistic predictions intended for storage in
the `Prediction_Registry` table.
This module is intentionally a *logic-only* layer:
- No database calls
- No file/network I/O
- stdlib-only (no external dependencies)
Public API
----------
- create_prediction(description, probability, category, horizon_days) -> dict
- resolve_prediction(prediction, actual_outcome, notes) -> dict
- evaluate_predictor(predictions) -> dict
Notes
-----
- Brier score is computed for binary outcomes: (p - y)^2, where y ∈ {0, 1}.
- Prediction IDs are generated in-process using a daily counter. In a DB-backed
  environment, uniqueness should still be enforced at the storage layer.
Stamp: S✅ T✅ L✅ A✅
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from numbers import Real
from typing import Any, Dict, List, TypedDict, Union
logger = logging.getLogger(__name__)
# Library-style module: don't configure global logging; avoid "No handler" warnings.
logger.addHandler(logging.NullHandler())
Number = Union[int, float]
# -----------------------------------------------------------------------------
# Optional internal imports (pure modules, stdlib-only)
# -----------------------------------------------------------------------------
# Key decision:
# - Prefer reusing the canonical Brier implementation if available.
# - Fall back to an equivalent local computation if imports fail (keeps the
#   module usable even when copied out of the package).
try:  # package-relative
    from .calc_brier import calculate_brier_score as _brier  # type: ignore
except Exception:  # pragma: no cover
    try:  # flat import
        from calc_brier import calculate_brier_score as _brier  # type: ignore
    except Exception:  # pragma: no cover
        _brier = None  # type: ignore
class PredictionDict(TypedDict, total=False):
    """Canonical in-memory representation for a prediction record.
    Required at creation time:
      - prediction_id
      - description
      - probability
      - category
      - horizon_days
      - status
      - created_at
    Added at resolution time:
      - actual_outcome
      - brier_score
      - notes
      - resolved_at
    """
    prediction_id: str
    description: str
    probability: float
    category: str
    horizon_days: int
    status: str
    created_at: str
    actual_outcome: int
    brier_score: float
    notes: str
    resolved_at: str
# -----------------------------------------------------------------------------
# ID generation (in-process)
# -----------------------------------------------------------------------------
_COUNTER_BY_YYYYMMDD: Dict[str, int] = {}
def _today_yyyymmdd_utc() -> str:
    """Return today's date as YYYYMMDD in UTC."""
    return datetime.now(timezone.utc).strftime("%Y%m%d")
def _now_iso_utc() -> str:
    """Return a timezone-aware ISO-8601 datetime string in UTC."""
    return datetime.now(timezone.utc).isoformat()
def _next_prediction_id() -> str:
    """Generate a new prediction_id in the format PRED-YYYYMMDD-NNN."""
    yyyymmdd = _today_yyyymmdd_utc()
    n = _COUNTER_BY_YYYYMMDD.get(yyyymmdd, 0) + 1
    _COUNTER_BY_YYYYMMDD[yyyymmdd] = n
    return f"PRED-{yyyymmdd}-{n:03d}"
# -----------------------------------------------------------------------------
# Validation helpers (strict, calc_brier/calc_calibration style)
# -----------------------------------------------------------------------------
def _is_real_number(value: object) -> bool:
    """True if value is a real number (int/float), excluding booleans."""
    return isinstance(value, Real) and not isinstance(value, bool)
def _require_non_empty_str(name: str, value: Any, *, min_len: int = 1) -> str:
    """Validate a non-empty string and return it stripped."""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string, got {type(value).__name__}")
    v = value.strip()
    if len(v) < int(min_len):
        raise ValueError(f"{name} must be at least {min_len} characters long")
    return v
def _require_probability(probability: Any) -> float:
    """Validate probability in [0.0, 1.0] and return it as float."""
    if not _is_real_number(probability):
        raise TypeError(
            f"probability must be a real number in [0.0, 1.0], got {type(probability).__name__}"
        )
    p = float(probability)
    if p < 0.0 or p > 1.0:
        raise ValueError(f"probability must be within [0.0, 1.0], got {p}")
    return p
def _require_horizon_days(horizon_days: Any) -> int:
    """Validate horizon_days is a positive integer."""
    if not isinstance(horizon_days, int) or isinstance(horizon_days, bool):
        raise TypeError(f"horizon_days must be an int, got {type(horizon_days).__name__}")
    if horizon_days <= 0:
        raise ValueError(f"horizon_days must be > 0, got {horizon_days}")
    return int(horizon_days)
def _require_actual_outcome(actual_outcome: Any) -> int:
    """Validate actual_outcome is exactly 0 or 1."""
    if not isinstance(actual_outcome, int) or isinstance(actual_outcome, bool):
        raise TypeError(f"actual_outcome must be an int (0 or 1), got {type(actual_outcome).__name__}")
    if actual_outcome not in (0, 1):
        raise ValueError(f"actual_outcome must be 0 or 1, got {actual_outcome}")
    return int(actual_outcome)
def _compute_brier(probability: float, actual_outcome: int) -> float:
    """Compute Brier score for one prediction (binary outcome)."""
    # Prefer the canonical implementation if available.
    if _brier is not None:
        return float(_brier(probability, actual_outcome))
    # Fallback: equivalent implementation.
    return float((float(probability) - float(actual_outcome)) ** 2)
# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
def create_prediction(description: str, probability: float, category: str, horizon_days: int) -> PredictionDict:
    """Create a new prediction dict ready for DB insert.
    Args:
        description: Human-readable prediction statement.
        probability: Predicted probability in [0.0, 1.0].
        category: Category label used for later evaluation (e.g., "market", "ops").
        horizon_days: Integer horizon in days (e.g., 30, 90).
    Returns:
        PredictionDict with:
          - prediction_id: "PRED-YYYYMMDD-NNN"
          - status: "open"
          - created_at: ISO timestamp (UTC)
    Raises:
        TypeError/ValueError on invalid inputs.
    """
    desc = _require_non_empty_str("description", description, min_len=3)
    cat = _require_non_empty_str("category", category, min_len=2)
    p = _require_probability(probability)
    h = _require_horizon_days(horizon_days)
    pred: PredictionDict = {
        "prediction_id": _next_prediction_id(),
        "description": desc,
        "probability": p,
        "category": cat,
        "horizon_days": h,
        "status": "open",
        "created_at": _now_iso_utc(),
    }
    return pred
def resolve_prediction(prediction: Dict[str, Any], actual_outcome: int, notes: str) -> PredictionDict:
    """Resolve a prediction and compute its Brier score.
    Args:
        prediction: A prediction dict created by `create_prediction()`.
        actual_outcome: Observed binary outcome: 0 or 1.
        notes: Human notes about what happened and why.
    Returns:
        Updated prediction dict:
          - status set to "resolved"
          - resolved_at ISO timestamp (UTC)
          - brier_score for this single event
          - actual_outcome recorded
          - notes recorded
    Raises:
        TypeError/ValueError if inputs are invalid or prediction is already resolved.
        KeyError if required fields are missing from `prediction`.
    """
    if not isinstance(prediction, dict):
        raise TypeError(f"prediction must be a dict, got {type(prediction).__name__}")
    pred_id = _require_non_empty_str("prediction['prediction_id']", prediction["prediction_id"])
    prob = _require_probability(prediction["probability"])
    status = str(prediction.get("status", "open")).strip().lower() or "open"
    if status == "resolved":
        raise ValueError(f"Prediction {pred_id} is already resolved")
    actual = _require_actual_outcome(actual_outcome)
    # Notes are stored as-is (trimmed). Empty notes are allowed.
    n = _require_non_empty_str("notes", notes, min_len=0)
    brier_score = _compute_brier(probability=prob, actual_outcome=actual)
    updated: PredictionDict = dict(prediction)  # shallow copy to avoid mutating caller
    updated.update(
        {
            "prediction_id": pred_id,
            "status": "resolved",
            "resolved_at": _now_iso_utc(),
            "actual_outcome": actual,
            "brier_score": float(brier_score),
            "notes": n,
        }
    )
    return updated
def evaluate_predictor(predictions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Evaluate predictor calibration over a list of predictions.
    This function is robust to mixed input lists (open + resolved). The spec
    says callers should pass resolved predictions, but we still compute:
      - total_count
      - resolved_count
    Calibration grades (spec):
      - A = mean_brier < 0.05
      - B = mean_brier < 0.10
      - C = mean_brier < 0.15
      - D = mean_brier < 0.20
      - F = mean_brier >= 0.20
    Args:
        predictions: List of prediction dicts.
    Returns:
        Dict with:
          - total_count: int
          - resolved_count: int
          - mean_brier: float | None
          - calibration_grade: "A"|"B"|"C"|"D"|"F"|"N/A"
          - best_category: str | None (lowest mean brier)
          - worst_category: str | None (highest mean brier)
    Raises:
        TypeError: if predictions is not a list.
    """
    if not isinstance(predictions, list):
        raise TypeError(f"predictions must be a list of dicts, got {type(predictions).__name__}")
    total_count = len(predictions)
    scores: List[float] = []
    by_category: Dict[str, List[float]] = {}
    for i, p in enumerate(predictions):
        if not isinstance(p, dict):
            logger.warning("Skipping predictions[%s]: not a dict", i)
            continue
        status = str(p.get("status", "")).strip().lower()
        has_resolution_fields = ("actual_outcome" in p) and ("probability" in p)
        # If caller passed mixed lists, only score the resolved ones.
        if status != "resolved" and not has_resolution_fields:
            continue
        try:
            prob = _require_probability(p.get("probability"))
            actual = _require_actual_outcome(p.get("actual_outcome"))
            # Prefer stored brier_score if present and valid.
            brier_raw = p.get("brier_score")
            if brier_raw is not None and _is_real_number(brier_raw):
                brier_val = float(brier_raw)
                if brier_val < 0.0 or brier_val > 1.0:
                    raise ValueError("brier_score out of [0,1] range")
                brier_score = brier_val
            else:
                brier_score = _compute_brier(probability=prob, actual_outcome=actual)
            # Category grouping (missing category -> "uncategorized")
            cat_raw = p.get("category")
            cat = str(cat_raw).strip() if isinstance(cat_raw, str) and cat_raw.strip() else "uncategorized"
            scores.append(float(brier_score))
            by_category.setdefault(cat, []).append(float(brier_score))
        except Exception as e:
            logger.warning("Skipping predictions[%s] due to invalid resolved fields: %s", i, e)
            continue
    resolved_count = len(scores)
    if resolved_count == 0:
        return {
            "total_count": int(total_count),
            "resolved_count": 0,
            "mean_brier": None,
            "calibration_grade": "N/A",
            "best_category": None,
            "worst_category": None,
        }
    mean_brier = sum(scores) / float(resolved_count)
    if mean_brier < 0.05:
        grade = "A"
    elif mean_brier < 0.10:
        grade = "B"
    elif mean_brier < 0.15:
        grade = "C"
    elif mean_brier < 0.20:
        grade = "D"
    else:
        grade = "F"
    cat_means: List[tuple[str, float]] = []
    for cat, cat_scores in by_category.items():
        if cat_scores:
            cat_means.append((cat, sum(cat_scores) / float(len(cat_scores))))
    # Stable tie-break: sort by (mean, category name)
    cat_means.sort(key=lambda x: (x[1], x[0]))
    best_category = cat_means[0][0] if cat_means else None
    worst_category = cat_means[-1][0] if cat_means else None
    return {
        "total_count": int(total_count),
        "resolved_count": int(resolved_count),
        "mean_brier": float(mean_brier),
        "calibration_grade": grade,
        "best_category": best_category,
        "worst_category": worst_category,
    }
__all__ = [
    "create_prediction",
    "resolve_prediction",
    "evaluate_predictor",
    "PredictionDict",
]
