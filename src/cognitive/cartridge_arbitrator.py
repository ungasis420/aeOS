"""
CartridgeArbitrator — resolves conflicts when two cartridges give contradictory recommendations.
Runs in AeOSCore._run_pipeline() AFTER cartridges fire, BEFORE synthesis.
Wire-in point: step 3.8 (new step after cartridge selection).

Arbitration priority order (from appendix):
1. Master Law compliance (Law wins over cartridge)
2. Domain specificity (more specific domain wins)
3. Confidence score (higher confidence wins)
4. Recency of validation (more recently validated wins)
5. Escalate to Sovereign (Law 31) if unresolvable
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Domain specificity hierarchy — more specific = higher rank
DOMAIN_SPECIFICITY = {
    "personal-finance": 10,
    "tax-optimization": 10,
    "offer-design": 9,
    "negotiation": 9,
    "negotiation-advanced": 10,
    "market-timing": 9,
    "cash-flow": 9,
    "leverage-systems": 8,
    "agency-preservation": 8,
    "decision-architecture": 8,
    "first-principles": 7,
    "systems-thinking": 7,
    "mental-models": 6,
    "stoic": 5,
    "leadership": 5,
}


@dataclass
class Conflict:
    cartridge_a: str
    cartridge_b: str
    conflicting_on: str
    recommendation_a: str
    recommendation_b: str
    severity: str  # "low" | "medium" | "high"
    detected_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ArbitrationResult:
    conflict: Conflict
    winner: str  # cartridge_id of winner, or "sovereign" if escalated
    loser: str
    reasoning: str
    priority_rule_used: int  # 1-5
    escalated_to_sovereign: bool
    final_recommendation: str
    arbitrated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "winner": self.winner,
            "loser": self.loser,
            "reasoning": self.reasoning,
            "priority_rule": self.priority_rule_used,
            "escalated": self.escalated_to_sovereign,
            "final_recommendation": self.final_recommendation,
        }


class CartridgeArbitrator:
    """
    Detects and resolves conflicts between cartridge recommendations.
    Phase 4B: implement detect_conflicts() with semantic similarity.
    Currently: returns no conflicts (safe default until implemented).
    """

    VERSION = "1.0.0"

    def __init__(self, contradiction_detector=None):
        self._contradiction_detector = contradiction_detector
        self._arbitration_log: list = []

    def detect_conflicts(self, fired_cartridges: list, recommendations: list) -> list:
        """
        Compare recommendations pairwise for contradictions.
        Phase 4B: implement semantic conflict detection.
        Returns empty list (no false positives) until implemented.
        """
        # Stub: Phase 4B implements pairwise semantic comparison
        return []

    def arbitrate(self, conflict: Conflict) -> ArbitrationResult:
        """
        Apply 5-priority arbitration rules to resolve conflict.
        """
        # Rule 1: Law compliance check
        if self._contradiction_detector:
            violations_a = self._contradiction_detector.check_against_laws(conflict.recommendation_a)
            violations_b = self._contradiction_detector.check_against_laws(conflict.recommendation_b)
            if violations_a and not violations_b:
                return self._make_result(conflict, conflict.cartridge_b, conflict.cartridge_a,
                                         "Cartridge A violates Master Law(s)", 1, conflict.recommendation_b)
            if violations_b and not violations_a:
                return self._make_result(conflict, conflict.cartridge_a, conflict.cartridge_b,
                                         "Cartridge B violates Master Law(s)", 1, conflict.recommendation_a)

        # Rule 2: Domain specificity
        spec_a = DOMAIN_SPECIFICITY.get(conflict.cartridge_a.replace("CART-", "").lower(), 5)
        spec_b = DOMAIN_SPECIFICITY.get(conflict.cartridge_b.replace("CART-", "").lower(), 5)
        if spec_a != spec_b:
            winner = conflict.cartridge_a if spec_a > spec_b else conflict.cartridge_b
            loser = conflict.cartridge_b if spec_a > spec_b else conflict.cartridge_a
            rec = conflict.recommendation_a if spec_a > spec_b else conflict.recommendation_b
            return self._make_result(conflict, winner, loser, f"Domain specificity: {spec_a} vs {spec_b}", 2, rec)

        # Rules 3-4: Phase 4B implements confidence + recency
        # Rule 5: Escalate to Sovereign
        return self._make_result(
            conflict, "sovereign", "both",
            "Conflict unresolvable by automated rules — Sovereign decision required (Law 31)",
            5, f"[ESCALATED] Both options presented: A={conflict.recommendation_a[:100]} | B={conflict.recommendation_b[:100]}",
            escalated=True,
        )

    def arbitrate_all(self, fired_cartridges: list, recommendations: list) -> tuple:
        """
        Run full detect + arbitrate cycle. Returns (resolved_recommendations, arbitration_log).
        """
        conflicts = self.detect_conflicts(fired_cartridges, recommendations)
        results = []
        for conflict in conflicts:
            result = self.arbitrate(conflict)
            results.append(result)
            self._arbitration_log.append(result)
        # If no conflicts, return recommendations unchanged
        return recommendations, results

    def _make_result(self, conflict, winner, loser, reasoning, rule, final_rec, escalated=False) -> ArbitrationResult:
        return ArbitrationResult(
            conflict=conflict,
            winner=winner,
            loser=loser,
            reasoning=reasoning,
            priority_rule_used=rule,
            escalated_to_sovereign=escalated,
            final_recommendation=final_rec,
        )

    def get_arbitration_log(self, limit: int = 20) -> list:
        return [r.to_dict() for r in self._arbitration_log[-limit:]]

    def get_status(self) -> dict:
        return {
            "version": self.VERSION,
            "arbitrations_run": len(self._arbitration_log),
            "escalated_to_sovereign": sum(1 for r in self._arbitration_log if r.escalated_to_sovereign),
        }
