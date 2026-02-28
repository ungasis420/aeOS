"""solution_bridge.py
aeOS — Phase 1 Solution Bridge (Pain → Solution candidates)
Purpose
-------
Bridges Pain_Point_Register output (a Pain_Score plus minimal context) to a short
list of Solution_Design *candidates*.
This is a Phase 1 gate:
- It does NOT write to a database.
- It does NOT decide the "one true solution".
- It simply produces 1–5 plausible Solution_Design candidates, ranked for review.
Inputs
------
- pain_score: float in [0.0, 100.0] (typically output of calc_pain.py)
- action_dict: dict with keys:
    - pain_id (str)
    - severity (int 1–10)
    - urgency (int 1–10)
    - category (str)  e.g., financial/operational/strategic/personal/technical
    - description (str)
Outputs
-------
A ranked list (0–5 items) of candidate dicts. Each candidate includes:
- candidate_id      (str)   format: SOL-YYYYMMDD-NNN
- solution_type     (str)
- effort_score      (float) 1.0–10.0
- expected_impact   (float) 0.0–100.0
- confidence        (float) 0.0–1.0
- rationale         (str)   one sentence
- rank              (int)   1 = best
Ranking
-------
Ranking score (higher is better):
    (pain_score * severity) / effort_score
Gate
----
If pain_score < 20.0 → return [] (not worth solving yet)
Stamp: S✅ T✅ L✅ A✅
"""
from __future__ import annotations
import logging
from datetime import date
from numbers import Real
from typing import Any, Dict, List, Tuple
logger = logging.getLogger(__name__)
# Library-style module: don't configure global logging; avoid "No handler" warnings.
logger.addHandler(logging.NullHandler())
__all__ = ["generate_candidates"]
# -----------------------------------------------------------------------------
# Constants (Phase 1 gate)
# -----------------------------------------------------------------------------
MIN_PAIN_SCORE_TO_SOLVE: float = 20.0  # Spec: < 20.0 => return empty list
MAX_CANDIDATES: int = 5
# -----------------------------------------------------------------------------
# Category → allowed solution_type mappings (minimum 5 categories)
# -----------------------------------------------------------------------------
# Key decision:
# - Keep this mapping explicit and small (canon alignment, easy to audit).
# - We normalize incoming categories (case/spacing/hyphens) before lookup.
CATEGORY_SOLUTION_TYPES: Dict[str, Tuple[str, ...]] = {
    "financial": ("cost_reduction", "revenue_increase"),
    "operational": ("process_improvement", "automation"),
    "strategic": ("pivot", "partnership", "new_market"),
    "personal": ("skill_development", "delegation"),
    "technical": ("build", "buy", "integrate"),
}
# -----------------------------------------------------------------------------
# Candidate templates
# -----------------------------------------------------------------------------
# Key decision:
# - Some categories only list 2–3 solution types in the mapping above.
# - We still want the option to emit up to 5 candidates by generating
#   multiple "variants" under the same solution_type (allowed by spec).
#
# Fields:
# - solution_type: must exist in CATEGORY_SOLUTION_TYPES for that category
# - base_effort: 1.0–10.0 baseline effort estimate
# - impact_bias: small bias added to expected_impact
# - base_confidence: 0.0–1.0 baseline confidence (heuristic)
# - rationale_style: controls one-sentence rationale phrasing
_TEMPLATE_REGISTRY: Dict[str, List[Dict[str, Any]]] = {
    "financial": [
        {"solution_type": "cost_reduction", "base_effort": 3.0, "impact_bias": 2.0, "base_confidence": 0.75, "rationale_style": "quick"},
        {"solution_type": "revenue_increase", "base_effort": 5.0, "impact_bias": 6.0, "base_confidence": 0.62, "rationale_style": "growth"},
        {"solution_type": "cost_reduction", "base_effort": 6.5, "impact_bias": 10.0, "base_confidence": 0.55, "rationale_style": "structural"},
        {"solution_type": "revenue_increase", "base_effort": 7.5, "impact_bias": 12.0, "base_confidence": 0.48, "rationale_style": "expansion"},
        {"solution_type": "revenue_increase", "base_effort": 8.5, "impact_bias": 14.0, "base_confidence": 0.40, "rationale_style": "bet"},
    ],
    "operational": [
        {"solution_type": "process_improvement", "base_effort": 3.5, "impact_bias": 3.0, "base_confidence": 0.72, "rationale_style": "quick"},
        {"solution_type": "automation", "base_effort": 6.5, "impact_bias": 10.0, "base_confidence": 0.55, "rationale_style": "automation"},
        {"solution_type": "process_improvement", "base_effort": 6.0, "impact_bias": 8.0, "base_confidence": 0.60, "rationale_style": "structural"},
        {"solution_type": "automation", "base_effort": 8.5, "impact_bias": 14.0, "base_confidence": 0.45, "rationale_style": "integration"},
        {"solution_type": "process_improvement", "base_effort": 7.5, "impact_bias": 11.0, "base_confidence": 0.50, "rationale_style": "bet"},
    ],
    "strategic": [
        {"solution_type": "partnership", "base_effort": 5.5, "impact_bias": 8.0, "base_confidence": 0.55, "rationale_style": "growth"},
        {"solution_type": "new_market", "base_effort": 7.0, "impact_bias": 12.0, "base_confidence": 0.45, "rationale_style": "expansion"},
        {"solution_type": "pivot", "base_effort": 9.0, "impact_bias": 16.0, "base_confidence": 0.35, "rationale_style": "bet"},
        {"solution_type": "partnership", "base_effort": 6.5, "impact_bias": 10.0, "base_confidence": 0.50, "rationale_style": "structural"},
        {"solution_type": "new_market", "base_effort": 8.5, "impact_bias": 14.0, "base_confidence": 0.40, "rationale_style": "bet"},
    ],
    "personal": [
        {"solution_type": "skill_development", "base_effort": 4.5, "impact_bias": 5.0, "base_confidence": 0.70, "rationale_style": "quick"},
        {"solution_type": "delegation", "base_effort": 5.0, "impact_bias": 7.0, "base_confidence": 0.60, "rationale_style": "growth"},
        {"solution_type": "skill_development", "base_effort": 7.5, "impact_bias": 12.0, "base_confidence": 0.50, "rationale_style": "structural"},
        {"solution_type": "delegation", "base_effort": 8.0, "impact_bias": 14.0, "base_confidence": 0.42, "rationale_style": "expansion"},
        {"solution_type": "delegation", "base_effort": 9.0, "impact_bias": 16.0, "base_confidence": 0.35, "rationale_style": "bet"},
    ],
    "technical": [
        {"solution_type": "buy", "base_effort": 5.0, "impact_bias": 7.0, "base_confidence": 0.62, "rationale_style": "quick"},
        {"solution_type": "integrate", "base_effort": 6.5, "impact_bias": 10.0, "base_confidence": 0.55, "rationale_style": "integration"},
        {"solution_type": "build", "base_effort": 9.0, "impact_bias": 16.0, "base_confidence": 0.40, "rationale_style": "bet"},
        {"solution_type": "buy", "base_effort": 6.0, "impact_bias": 9.0, "base_confidence": 0.58, "rationale_style": "structural"},
        {"solution_type": "integrate", "base_effort": 8.0, "impact_bias": 13.0, "base_confidence": 0.45, "rationale_style": "expansion"},
    ],
}
# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
def generate_candidates(pain_score: float, action_dict: dict) -> list[dict]:
    """Generate ranked Solution_Design candidate dicts for a pain.
    Args:
        pain_score: Pain score in [0.0, 100.0] (output of calc_pain.py).
        action_dict: Dict containing:
            pain_id (str): ID of the pain (e.g., PAIN-YYYYMMDD-NNN).
            severity (int): 1–10 severity.
            urgency (int): 1–10 urgency.
            category (str): financial/operational/strategic/personal/technical.
            description (str): human description of the pain.
    Returns:
        A ranked list of 0–5 candidate dicts. If pain_score < 20.0, returns [].
    Raises:
        TypeError: If pain_score/action_dict types are invalid.
        ValueError: If pain_score or action_dict fields are out of range/missing.
    Notes:
        - Ranking formula is fixed by spec:
              (pain_score * severity) / effort_score
        - expected_impact and confidence are heuristic (simple, deterministic),
          intended to help human selection, not to be treated as ground truth.
    """
    ps = _validate_pain_score(pain_score)
    # Spec gate: if not worth solving, emit nothing.
    if ps < MIN_PAIN_SCORE_TO_SOLVE:
        return []
    pain_id, severity, urgency, category, description = _validate_action_dict(action_dict)
    # Normalize category so callers can send "Financial", "financial ", "FINANCIAL", etc.
    cat = _normalize_category(category)
    # Choose candidate templates:
    # - Use the registry if category is known
    # - Otherwise, fall back to a safe operational set (process improvements),
    #   because it's the least risky "default fix" category.
    templates = _TEMPLATE_REGISTRY.get(cat)
    if templates is None:
        logger.warning("Unknown category %r; defaulting to 'operational' templates.", category)
        cat = "operational"
        templates = _TEMPLATE_REGISTRY[cat]
    # Decide how many to emit (1..5) based on pain intensity.
    max_candidates = _choose_candidate_count(ps, severity, urgency)
    chosen = templates[:max_candidates]
    # Build raw candidates (without rank yet).
    built: List[Dict[str, Any]] = []
    for t in chosen:
        solution_type = str(t["solution_type"])
        if solution_type not in CATEGORY_SOLUTION_TYPES.get(cat, ()):
            # Defensive: registry should always match mapping; if not, skip.
            logger.warning("Template solution_type %r not allowed for category %r; skipping.", solution_type, cat)
            continue
        effort = _compute_effort_score(base_effort=float(t["base_effort"]), urgency=urgency)
        expected_impact = _compute_expected_impact(
            pain_score=ps,
            severity=severity,
            urgency=urgency,
            effort_score=effort,
            impact_bias=float(t.get("impact_bias", 0.0)),
        )
        confidence = _compute_confidence(
            base_confidence=float(t.get("base_confidence", 0.5)),
            urgency=urgency,
            effort_score=effort,
        )
        rationale = _build_rationale(
            style=str(t.get("rationale_style", "quick")),
            solution_type=solution_type,
            description=description,
            category=cat,
        )
        built.append(
            {
                # candidate_id is assigned after ranking so rank 1 gets NNN=001, etc.
                "candidate_id": "",
                "solution_type": solution_type,
                "effort_score": float(effort),
                "expected_impact": float(expected_impact),
                "confidence": float(confidence),
                "rationale": rationale,
                "rank": 0,
                # Keep raw inputs out of the candidate dict to preserve schema simplicity.
                # (If you need traceability, the caller already has pain_id.)
            }
        )
    if not built:
        return []
    # Rank using spec formula.
    ranked = _rank_candidates(pain_score=ps, severity=severity, candidates=built)
    # Assign IDs + rank fields (post-sort).
    today = date.today().strftime("%Y%m%d")
    for idx, cand in enumerate(ranked, start=1):
        cand["rank"] = idx
        cand["candidate_id"] = _format_candidate_id(today, idx)
    return ranked
# -----------------------------------------------------------------------------
# Validation helpers (calc_pain.py style: strict, explicit, non-magical)
# -----------------------------------------------------------------------------
def _is_real_number(value: object) -> bool:
    """True if value is a real number (int/float), excluding booleans."""
    return isinstance(value, Real) and not isinstance(value, bool)
def _validate_pain_score(pain_score: Any) -> float:
    if not _is_real_number(pain_score):
        raise TypeError(f"pain_score must be a real number (int/float), got {type(pain_score).__name__}")
    ps = float(pain_score)
    if ps < 0.0 or ps > 100.0:
        raise ValueError(f"pain_score must be within [0.0, 100.0], got {ps}")
    return ps
def _validate_action_dict(action_dict: Any) -> Tuple[str, int, int, str, str]:
    if not isinstance(action_dict, dict):
        raise TypeError(f"action_dict must be a dict, got {type(action_dict).__name__}")
    required = ("pain_id", "severity", "urgency", "category", "description")
    missing = [k for k in required if k not in action_dict]
    if missing:
        raise ValueError(f"action_dict is missing required keys: {missing}")
    pain_id = action_dict.get("pain_id")
    severity = action_dict.get("severity")
    urgency = action_dict.get("urgency")
    category = action_dict.get("category")
    description = action_dict.get("description")
    if not isinstance(pain_id, str) or not pain_id.strip():
        raise ValueError("action_dict.pain_id must be a non-empty string")
    if not isinstance(severity, int) or isinstance(severity, bool):
        raise ValueError("action_dict.severity must be an int in 1..10")
    if severity < 1 or severity > 10:
        raise ValueError("action_dict.severity must be in the range 1..10")
    if not isinstance(urgency, int) or isinstance(urgency, bool):
        raise ValueError("action_dict.urgency must be an int in 1..10")
    if urgency < 1 or urgency > 10:
        raise ValueError("action_dict.urgency must be in the range 1..10")
    if not isinstance(category, str) or not category.strip():
        raise ValueError("action_dict.category must be a non-empty string")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("action_dict.description must be a non-empty string")
    return pain_id.strip(), int(severity), int(urgency), category.strip(), description.strip()
def _normalize_category(category: str) -> str:
    # Normalize to lookup keys like "financial", "operational", etc.
    c = (category or "").strip().lower()
    c = c.replace("-", "_").replace(" ", "_")
    # Some callers might send plural variants; normalize minimally.
    if c.endswith("s") and c[:-1] in CATEGORY_SOLUTION_TYPES:
        c = c[:-1]
    return c
# -----------------------------------------------------------------------------
# Candidate synthesis helpers
# -----------------------------------------------------------------------------
def _choose_candidate_count(pain_score: float, severity: int, urgency: int) -> int:
    """Return desired candidate count (1..5) based on pain intensity."""
    # Key decision:
    # - Low pain scores should not spawn many options (avoid cognitive overhead).
    # - High pain scores deserve broader exploration (up to MAX_CANDIDATES).
    if pain_score < 40.0:
        # If it's mild AND low urgency, keep it to one option.
        if severity <= 3 and urgency <= 4:
            return 1
        return 2
    if pain_score < 60.0:
        return 3
    if pain_score < 80.0:
        return 4
    return MAX_CANDIDATES
def _clamp(value: float, low: float, high: float) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value
def _compute_effort_score(*, base_effort: float, urgency: int) -> float:
    """Compute effort_score in [1.0, 10.0].
    We bias effort slightly DOWN when urgency is high (favor quick execution),
    and slightly UP when urgency is low (room for deeper work).
    """
    # urgency 1..10 => adjust in roughly [-0.75, +0.60]
    adjust = (5 - float(urgency)) * 0.15
    return _clamp(base_effort + adjust, 1.0, 10.0)
def _compute_expected_impact(
    *,
    pain_score: float,
    severity: int,
    urgency: int,
    effort_score: float,
    impact_bias: float,
) -> float:
    """Heuristic expected impact in [0.0, 100.0]."""
    # Key decision:
    # - impact should mostly track pain_score (it's the system's signal),
    #   but severity + urgency should still matter.
    # - effort is subtracted: high-effort initiatives often lose impact via delay/risk.
    raw = (pain_score * 0.55) + (severity * 4.0) + (urgency * 2.5) - (effort_score * 3.5) + impact_bias
    return _clamp(raw, 0.0, 100.0)
def _compute_confidence(*, base_confidence: float, urgency: int, effort_score: float) -> float:
    """Heuristic confidence in [0.0, 1.0]."""
    # Key decision:
    # - confidence is NOT probability of success; it's "how confident we are this is a good bet".
    # - We nudge confidence up when urgency is high (clear pressure) and down when effort is high.
    raw = base_confidence + ((urgency - 5) * 0.02) - ((effort_score - 5) * 0.015)
    return _clamp(raw, 0.05, 0.95)
def _truncate(text: str, max_len: int) -> str:
    t = (text or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "\u2026"
def _humanize_solution_type(solution_type: str) -> str:
    return (solution_type or "").replace("_", " ").strip()
def _build_rationale(*, style: str, solution_type: str, description: str, category: str) -> str:
    """Return a one-sentence rationale."""
    st = _humanize_solution_type(solution_type)
    desc = _truncate(description, 90)
    # Key decision:
    # - Keep it to ONE sentence for UI compactness and scanability.
    # - Do not embed numeric scores here; scores already exist as fields.
    if style == "quick":
        return f"Use {st} as a quick win to relieve \u201c{desc}\u201d in the {category} area."
    if style == "automation":
        return f"Use {st} to remove repeat manual work driving \u201c{desc}\u201d in the {category} area."
    if style == "integration":
        return f"Use {st} to connect systems and reduce friction behind \u201c{desc}\u201d in the {category} area."
    if style == "growth":
        return f"Use {st} to address \u201c{desc}\u201d by increasing leverage in the {category} area."
    if style == "structural":
        return f"Use {st} to fix root causes behind \u201c{desc}\u201d with a more durable {category} change."
    if style == "expansion":
        return f"Use {st} to expand options that reduce \u201c{desc}\u201d in the {category} area."
    # Default / "bet"
    return f"Use {st} as a higher-upside bet to materially reduce \u201c{desc}\u201d in the {category} area."
def _rank_candidates(*, pain_score: float, severity: int, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort candidates descending by the spec ranking formula."""
    # Spec formula:
    #   (pain_score * severity) / effort_score
    # Key decision:
    # - Use expected_impact/confidence only as tie-breakers (they are heuristic).
    def score(c: Dict[str, Any]) -> float:
        effort = float(c.get("effort_score", 10.0))
        if effort <= 0.0:
            effort = 1.0  # defensive: avoid division by zero
        return (pain_score * float(severity)) / effort
    return sorted(
        candidates,
        key=lambda c: (
            score(c),
            float(c.get("expected_impact", 0.0)),
            float(c.get("confidence", 0.0)),
            -float(c.get("effort_score", 10.0)),  # prefer lower effort if everything else ties
        ),
        reverse=True,
    )
def _format_candidate_id(yyyymmdd: str, n: int) -> str:
    """Format candidate id as SOL-YYYYMMDD-NNN."""
    # Key decision:
    # - Use rank-based numbering to keep IDs stable within the returned list.
    # - NNN is zero-padded to 3 digits (001..999).
    return f"SOL-{yyyymmdd}-{n:03d}"
