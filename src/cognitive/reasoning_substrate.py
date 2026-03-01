"""
reasoning_substrate.py — COGNITIVE_CORE reasoning substrate for aeOS.

Takes insights from multiple cartridges and synthesises them into a single
SynthesisResult that surfaces convergences, conflicts, blind spots, and a
recommended action.

Stamp: S✅ T✅ L✅ A✅
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Universal coverage dimensions — used for blind-spot detection
# ---------------------------------------------------------------------------

UNIVERSAL_DIMENSIONS: Set[str] = {
    "autonomy",
    "security",
    "purpose",
    "resilience",
    "clarity",
    "belonging",
    "integrity",
    "growth",
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Convergence:
    """Multiple insights pointing toward the same conclusion."""

    theme: str
    supporting_rule_ids: List[str]
    shared_tags: List[str]
    mean_confidence: float
    summary: str


@dataclass
class Tension:
    """Two insights that pull in opposing directions."""

    rule_id_a: str
    principle_a: str
    rule_id_b: str
    principle_b: str
    description: str


@dataclass
class BlindSpot:
    """A sovereign need that no triggered insight addresses."""

    dimension: str
    description: str


@dataclass
class SynthesisResult:
    """Final output of the reasoning substrate."""

    primary_insight: Dict[str, Any]
    supporting_insights: List[Dict[str, Any]]
    convergences: List[Convergence]
    tensions: List[Tension]
    blind_spots: List[BlindSpot]
    recommended_action: str
    overall_confidence: float
    needs_served: List[str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_OPPOSING_PAIRS: List[Tuple[str, str]] = [
    ("acceptance", "discipline"),
    ("presence", "preparation"),
    ("mindfulness", "visualization"),
    ("community", "self-mastery"),
    ("control", "acceptance"),
]


def _tag_set(insight: Dict[str, Any]) -> Set[str]:
    return set(insight.get("tags", []))


def _detect_convergences(insights: List[Dict[str, Any]]) -> List[Convergence]:
    """Find groups of insights that share tags — a signal they converge."""
    if len(insights) < 2:
        return []

    # Build an inverted index: tag -> list of insights
    tag_to_insights: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for ins in insights:
        for tag in ins.get("tags", []):
            tag_to_insights[tag].append(ins)

    seen_groups: Set[frozenset] = set()
    convergences: List[Convergence] = []

    for tag, group in sorted(tag_to_insights.items(), key=lambda t: -len(t[1])):
        if len(group) < 2:
            continue
        group_key = frozenset(i["rule_id"] for i in group)
        if group_key in seen_groups:
            continue
        seen_groups.add(group_key)

        rule_ids = [i["rule_id"] for i in group]
        confidences = [i["confidence"] for i in group]
        mean_conf = round(sum(confidences) / len(confidences), 4)

        # Shared tags across the whole group.
        shared = _tag_set(group[0])
        for i in group[1:]:
            shared &= _tag_set(i)

        names = [i["name"] for i in group]
        summary = (
            f"Rules {', '.join(names)} converge on theme '{tag}' "
            f"with mean confidence {mean_conf:.2f}."
        )

        convergences.append(
            Convergence(
                theme=tag,
                supporting_rule_ids=rule_ids,
                shared_tags=sorted(shared),
                mean_confidence=mean_conf,
                summary=summary,
            )
        )

    return convergences


def _detect_tensions(insights: List[Dict[str, Any]]) -> List[Tension]:
    """Surface pairs of insights whose tags are in known opposing pairs."""
    if len(insights) < 2:
        return []

    tensions: List[Tension] = []
    seen: Set[frozenset] = set()

    for i, a in enumerate(insights):
        tags_a = _tag_set(a)
        for b in insights[i + 1 :]:
            pair_key = frozenset((a["rule_id"], b["rule_id"]))
            if pair_key in seen:
                continue
            tags_b = _tag_set(b)
            for left, right in _OPPOSING_PAIRS:
                if (left in tags_a and right in tags_b) or (
                    right in tags_a and left in tags_b
                ):
                    seen.add(pair_key)
                    tensions.append(
                        Tension(
                            rule_id_a=a["rule_id"],
                            principle_a=a["principle"],
                            rule_id_b=b["rule_id"],
                            principle_b=b["principle"],
                            description=(
                                f"'{a['name']}' ({left if left in tags_a else right}) "
                                f"may tension with '{b['name']}' "
                                f"({right if right in tags_b else left}). "
                                f"Surface this for the user to resolve."
                            ),
                        )
                    )
                    break  # one tension per pair is enough

    return tensions


def _detect_blind_spots(
    insights: List[Dict[str, Any]],
    dimensions: Set[str] | None = None,
) -> List[BlindSpot]:
    """Identify sovereign-need dimensions not served by any insight."""
    dims = dimensions if dimensions is not None else UNIVERSAL_DIMENSIONS
    served: Set[str] = set()
    for ins in insights:
        need = ins.get("sovereign_need_served", "")
        if need:
            served.add(need.lower())
        # Tags can also cover a dimension.
        for tag in ins.get("tags", []):
            if tag.lower() in dims:
                served.add(tag.lower())

    missing = sorted(dims - served)
    return [
        BlindSpot(
            dimension=d,
            description=f"No triggered insight addresses the '{d}' dimension.",
        )
        for d in missing
    ]


def _pick_primary(insights: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Select the highest-confidence insight as the primary."""
    return max(insights, key=lambda i: i.get("confidence", 0.0))


def _compute_overall_confidence(insights: List[Dict[str, Any]]) -> float:
    """Weighted-average confidence across all insights."""
    if not insights:
        return 0.0
    total_w = sum(i.get("confidence", 0.0) for i in insights)
    return round(total_w / len(insights), 4)


def _build_recommended_action(
    primary: Dict[str, Any],
    convergences: List[Convergence],
    tensions: List[Tension],
    blind_spots: List[BlindSpot],
) -> str:
    """Generate a short recommended-action string from synthesis signals."""
    parts: List[str] = []

    parts.append(primary.get("insight", "Reflect on the situation."))

    if convergences:
        themes = ", ".join(c.theme for c in convergences[:3])
        parts.append(f"Multiple perspectives converge on: {themes}.")

    if tensions:
        parts.append(
            f"Note {len(tensions)} tension(s) to resolve before acting."
        )

    if blind_spots:
        dims = ", ".join(b.dimension for b in blind_spots[:3])
        parts.append(f"Consider unexplored dimensions: {dims}.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def synthesise(
    all_insights: List[Dict[str, Any]],
    dimensions: Set[str] | None = None,
) -> SynthesisResult:
    """Run the full reasoning substrate over a flat list of triggered insights.

    Parameters
    ----------
    all_insights:
        Combined output of ``cartridge_loader.run_rules()`` across one or
        more cartridges.
    dimensions:
        Optional override for the universal coverage dimensions used in
        blind-spot detection.  Defaults to ``UNIVERSAL_DIMENSIONS``.

    Returns
    -------
    SynthesisResult with primary insight, supporting insights, convergences,
    tensions, blind spots, recommended action, overall confidence, and the
    list of sovereign needs served.
    """
    if not all_insights:
        return SynthesisResult(
            primary_insight={},
            supporting_insights=[],
            convergences=[],
            tensions=[],
            blind_spots=list(
                _detect_blind_spots([], dimensions)
            ),
            recommended_action="No insights were triggered. Provide more context.",
            overall_confidence=0.0,
            needs_served=[],
        )

    # Sort descending by confidence for deterministic selection.
    ranked = sorted(all_insights, key=lambda i: i.get("confidence", 0.0), reverse=True)

    primary = ranked[0]
    supporting = ranked[1:]

    convergences = _detect_convergences(ranked)
    tensions = _detect_tensions(ranked)
    blind_spots = _detect_blind_spots(ranked, dimensions)

    overall_conf = _compute_overall_confidence(ranked)

    needs_counter: Counter = Counter()
    for ins in ranked:
        need = ins.get("sovereign_need_served", "")
        if need:
            needs_counter[need] += 1
    needs_served = [n for n, _ in needs_counter.most_common()]

    recommended = _build_recommended_action(primary, convergences, tensions, blind_spots)

    result = SynthesisResult(
        primary_insight=primary,
        supporting_insights=supporting,
        convergences=convergences,
        tensions=tensions,
        blind_spots=blind_spots,
        recommended_action=recommended,
        overall_confidence=overall_conf,
        needs_served=needs_served,
    )

    logger.info(
        "Synthesis complete: %d insights, %d convergences, %d tensions, %d blind spots, confidence=%.2f",
        len(ranked),
        len(convergences),
        len(tensions),
        len(blind_spots),
        overall_conf,
    )
    return result
