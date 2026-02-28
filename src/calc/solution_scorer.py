"""
solution_scorer.py
aeOS — Solution Scorer (Phase 1.5)
Purpose
-------
Takes Solution_Design candidate dicts produced by `solution_bridge.generate_candidates()`
and scores them against an investor profile (from `InvestorProfile.to_dict()`).
This module is intentionally "pure" and stdlib-only:
- No database access
- No network calls
- No external dependencies
Public API
----------
- score_solutions(candidates: list[dict], profile: dict) -> list[dict]
Scoring
-------
For each candidate, compute:
- profile_fit_score (0.0–1.0)  : fit to investor risk tolerance + mode
- final_score                  : expected_impact * confidence * profile_fit_score
- adjusted_rank (1..N)         : rank after sorting by final_score desc
- fit_rationale (one sentence) : why the fit score was assigned
Risk tolerance mapping (spec)
-----------------------------
- conservative: penalize high effort_score (> 7.0) by 0.5x
- moderate    : no penalty
- aggressive  : bonus on high expected_impact (> 70.0) by 1.2x
Stamp: S✅ T✅ L✅ A✅
"""
from __future__ import annotations
import logging
from numbers import Real
from typing import Any, Dict, List, Tuple
logger = logging.getLogger(__name__)
# Library-style module: don't configure global logging; avoid "No handler" warnings.
logger.addHandler(logging.NullHandler())
__all__ = ["score_solutions"]
# -----------------------------------------------------------------------------
# Profile enums (InvestorProfile.validate() enforces these; we re-check defensively)
# -----------------------------------------------------------------------------
_ALLOWED_MODES = {"personal", "professional"}
_ALLOWED_RISK = {"conservative", "moderate", "aggressive"}
# -----------------------------------------------------------------------------
# Mode preference heuristics (small, auditable, deterministic)
# -----------------------------------------------------------------------------
# Key decision:
# We keep this intentionally light-weight: risk tolerance is the "hard" constraint,
# mode is a softer preference signal.
_PERSONAL_PREFERRED = {"skill_development", "delegation", "process_improvement", "cost_reduction"}
_PROFESSIONAL_PREFERRED = {"revenue_increase", "automation", "build", "integrate", "partnership", "new_market", "pivot"}
def score_solutions(candidates: List[Dict[str, Any]], profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Score and re-rank solution candidates against an investor profile.
    Args:
        candidates: List of candidate dicts produced by solution_bridge.generate_candidates().
            Each candidate is expected to include:
              - candidate_id (str)
              - solution_type (str)
              - effort_score (float 1.0–10.0)
              - expected_impact (float 0.0–100.0)
              - confidence (float 0.0–1.0)
              - rationale (str)
              - rank (int)  # original rank from solution_bridge (kept as-is)
        profile: Dict produced by InvestorProfile.to_dict(), expected keys include:
            - mode: "personal" | "professional"
            - risk_tolerance: "conservative" | "moderate" | "aggressive"
    Returns:
        New list of candidate dicts, each augmented with:
          - profile_fit_score (float 0.0–1.0)
          - final_score (float)  # used for adjusted ranking
          - adjusted_rank (int)
          - fit_rationale (str)
        The list is sorted by final_score descending.
    Raises:
        TypeError: If candidates/profile have wrong types.
        ValueError: If candidate fields or profile fields are missing/out of range.
    """
    _validate_inputs(candidates, profile)
    if not candidates:
        return []
    mode = str(profile.get("mode", "")).strip()
    risk = str(profile.get("risk_tolerance", "")).strip()
    scored: List[Dict[str, Any]] = []
    for cand in candidates:
        c = dict(cand)  # shallow copy (don't mutate caller list)
        solution_type = str(c.get("solution_type", "")).strip()
        effort = float(c["effort_score"])
        impact = float(c["expected_impact"])
        confidence = float(c["confidence"])
        fit_score, fit_rationale = _compute_profile_fit(
            mode=mode,
            risk_tolerance=risk,
            solution_type=solution_type,
            effort_score=effort,
            expected_impact=impact,
        )
        final_score = impact * confidence * fit_score
        c["profile_fit_score"] = float(fit_score)
        c["final_score"] = float(final_score)
        c["fit_rationale"] = str(fit_rationale)
        # adjusted_rank assigned after sorting
        c["adjusted_rank"] = 0
        scored.append(c)
    # Sort by final_score desc; tie-break by original rank (ascending) for stability.
    scored.sort(key=lambda x: (-float(x["final_score"]), int(x.get("rank", 999999))))
    for idx, c in enumerate(scored, start=1):
        c["adjusted_rank"] = idx
    return scored
# -----------------------------------------------------------------------------
# Fit scoring (deterministic heuristics)
# -----------------------------------------------------------------------------
def _compute_profile_fit(
    *,
    mode: str,
    risk_tolerance: str,
    solution_type: str,
    effort_score: float,
    expected_impact: float,
) -> Tuple[float, str]:
    """Compute (profile_fit_score, fit_rationale) for one candidate.
    The fit score is a bounded number in [0.0, 1.0]. It is computed as:
        fit_pre = base + mode_adjustment + effort_adjustment
        fit = clamp(fit_pre * risk_factor, 0.0, 1.0)
    Where `risk_factor` follows the spec's risk tolerance mapping.
    Returns:
        (fit_score, rationale_sentence)
    """
    base = 0.80  # neutral fit baseline (chosen so 1.2x aggressive bonus still fits under 1.0 often)
    mode_adj, mode_note = _mode_adjustment(mode=mode, solution_type=solution_type)
    effort_adj, effort_note = _effort_adjustment(effort_score=effort_score)
    fit_pre = _clamp(base + mode_adj + effort_adj, 0.0, 1.0)
    risk_factor, risk_note = _risk_factor(
        risk_tolerance=risk_tolerance,
        effort_score=effort_score,
        expected_impact=expected_impact,
    )
    fit = _clamp(fit_pre * risk_factor, 0.0, 1.0)
    # One sentence, semicolon-separated clauses (still one sentence).
    rationale = (
        f"{mode.capitalize()} / {risk_tolerance} profile: {mode_note}{effort_note}; {risk_note}."
    )
    return float(fit), rationale
def _mode_adjustment(*, mode: str, solution_type: str) -> Tuple[float, str]:
    """Return (adjustment, human note) for mode preference."""
    st = (solution_type or "").strip()
    if mode == "personal":
        if st in _PERSONAL_PREFERRED:
            return 0.10, "matches personal low-overhead preference"
        if st in _PROFESSIONAL_PREFERRED:
            return -0.05, "leans more professional/scale-oriented than personal"
        return 0.0, "neutral for personal mode"
    # professional
    if st in _PROFESSIONAL_PREFERRED:
        return 0.10, "matches professional scale/ROI preference"
    if st in _PERSONAL_PREFERRED:
        return -0.02, "useful but less directly tied to professional ROI"
    return 0.0, "neutral for professional mode"
def _effort_adjustment(*, effort_score: float) -> Tuple[float, str]:
    """Return (adjustment, short clause) based on effort.
    Note:
      Risk tolerance handles the "big" penalty/bonus. This adjustment just adds
      a gentle preference for lower effort options.
    """
    if effort_score <= 3.0:
        return 0.05, ", very low effort"
    if effort_score >= 9.0:
        return -0.05, ", very high effort"
    return 0.0, ""
def _risk_factor(*, risk_tolerance: str, effort_score: float, expected_impact: float) -> Tuple[float, str]:
    """Return (multiplier, note) based on risk tolerance mapping (spec)."""
    if risk_tolerance == "conservative":
        if effort_score > 7.0:
            return 0.5, f"conservative penalty applied (effort {effort_score:.1f} > 7.0)"
        return 1.0, "no conservative penalty triggered"
    if risk_tolerance == "aggressive":
        if expected_impact > 70.0:
            return 1.2, f"aggressive bonus applied (impact {expected_impact:.1f} > 70.0)"
        return 1.0, "no aggressive bonus triggered"
    # moderate
    return 1.0, "moderate risk: no adjustment"
def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp a float into [lo, hi]."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value
# -----------------------------------------------------------------------------
# Validation helpers (calc_pain.py style: strict, explicit, non-magical)
# -----------------------------------------------------------------------------
def _is_real_number(value: object) -> bool:
    """True if value is a real number (int/float), excluding booleans."""
    return isinstance(value, Real) and not isinstance(value, bool)
def _validate_inputs(candidates: Any, profile: Any) -> None:
    """Validate top-level inputs."""
    if not isinstance(candidates, list):
        raise TypeError(f"candidates must be a list of dicts, got {type(candidates).__name__}")
    if not isinstance(profile, dict):
        raise TypeError(f"profile must be a dict, got {type(profile).__name__}")
    mode = str(profile.get("mode", "")).strip()
    risk = str(profile.get("risk_tolerance", "")).strip()
    if mode not in _ALLOWED_MODES:
        raise ValueError(f"profile.mode must be one of {_ALLOWED_MODES}, got {mode!r}")
    if risk not in _ALLOWED_RISK:
        raise ValueError(f"profile.risk_tolerance must be one of {_ALLOWED_RISK}, got {risk!r}")
    for i, cand in enumerate(candidates):
        if not isinstance(cand, dict):
            raise TypeError(f"candidates[{i}] must be a dict, got {type(cand).__name__}")
        _require_key(cand, "solution_type", i)
        _require_key(cand, "effort_score", i)
        _require_key(cand, "expected_impact", i)
        _require_key(cand, "confidence", i)
        st = cand.get("solution_type")
        if not isinstance(st, str) or not st.strip():
            raise ValueError(f"candidates[{i}].solution_type must be a non-empty string")
        effort = cand.get("effort_score")
        impact = cand.get("expected_impact")
        conf = cand.get("confidence")
        if not _is_real_number(effort):
            raise TypeError(f"candidates[{i}].effort_score must be a number, got {type(effort).__name__}")
        if not _is_real_number(impact):
            raise TypeError(f"candidates[{i}].expected_impact must be a number, got {type(impact).__name__}")
        if not _is_real_number(conf):
            raise TypeError(f"candidates[{i}].confidence must be a number, got {type(conf).__name__}")
        eff_f = float(effort)
        imp_f = float(impact)
        conf_f = float(conf)
        if eff_f < 1.0 or eff_f > 10.0:
            raise ValueError(f"candidates[{i}].effort_score must be within [1.0, 10.0], got {eff_f}")
        if imp_f < 0.0 or imp_f > 100.0:
            raise ValueError(f"candidates[{i}].expected_impact must be within [0.0, 100.0], got {imp_f}")
        if conf_f < 0.0 or conf_f > 1.0:
            raise ValueError(f"candidates[{i}].confidence must be within [0.0, 1.0], got {conf_f}")
def _require_key(d: Dict[str, Any], key: str, idx: int) -> None:
    """Raise if dict is missing a required key."""
    if key not in d:
        raise ValueError(f"candidates[{idx}] is missing required key: {key!r}")
