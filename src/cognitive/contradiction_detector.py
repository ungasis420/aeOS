"""
ContradictionDetector — checks new decisions/recommendations against:
1. Past decisions in FlywheelLogger
2. 31 Master Laws (hardcoded ruleset)
Runs in AeOSCore._run_pipeline() AFTER cartridge selection, BEFORE synthesis.
Wire-in point: step 3.5 (new step between cartridge select and Claude call).
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)

MASTER_LAWS = {
    1: "Sovereign's interests come first",
    2: "Privacy is absolute — no data leaks",
    3: "Never reduce future options",
    4: "Harsh truth over comforting lie",
    8: "Attention is finite — do not waste it",
    9: "Time cannot be recovered",
    11: "Always seek disproportionate return (80/20)",
    12: "Only take bets where upside is 10x downside",
    15: "Complexity is laziness — simplify ruthlessly",
    18: "Market and physics do not care about feelings",
    21: "Knowledge without execution is vanity",
    24: "Never start a war you cannot fund",
    28: "If you cannot replicate it, you do not own it",
    29: "Manage energy, not just time",
}


@dataclass
class LawViolation:
    law_number: int
    law_text: str
    explanation: str
    severity: str  # "low" | "medium" | "high" | "critical"


@dataclass
class ContradictionResult:
    detected: bool
    severity: str  # "none" | "low" | "medium" | "high" | "critical"
    conflicting_decision_id: Optional[str]
    conflicting_decision_text: Optional[str]
    explanation: str
    resolution_options: list
    law_violations: list
    checked_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "detected": self.detected,
            "severity": self.severity,
            "conflicting_decision_id": self.conflicting_decision_id,
            "explanation": self.explanation,
            "resolution_options": self.resolution_options,
            "law_violations": [{"law": v.law_number, "severity": v.severity, "explanation": v.explanation} for v in self.law_violations],
            "checked_at": self.checked_at.isoformat(),
        }


class ContradictionDetector:
    """
    Checks new decisions/recommendations for internal contradictions.
    Phase 4B: implement check_decision() and check_against_laws() fully.
    """

    VERSION = "1.0.0"

    def __init__(self, flywheel_logger=None):
        self._flywheel = flywheel_logger
        self._history: list = []

    def check_decision(self, new_decision: str, domain: str, context: dict = None) -> ContradictionResult:
        """
        Compare new_decision against recent FlywheelLogger decisions in same domain.
        Phase 4B: implement semantic similarity + keyword contradiction detection.
        Returns clean result (detected=False) until implemented.
        """
        law_violations = self.check_against_laws(new_decision)
        has_violations = len(law_violations) > 0
        severity = "none"
        if has_violations:
            severities = [v.severity for v in law_violations]
            if "critical" in severities:
                severity = "critical"
            elif "high" in severities:
                severity = "high"
            elif "medium" in severities:
                severity = "medium"
            else:
                severity = "low"

        result = ContradictionResult(
            detected=has_violations,
            severity=severity,
            conflicting_decision_id=None,
            conflicting_decision_text=None,
            explanation="Law violation detected" if has_violations else "No contradiction detected (stub — Phase 4B implements full check)",
            resolution_options=[],
            law_violations=law_violations,
        )
        self._history.append(result)
        return result

    def check_against_laws(self, recommendation: str) -> list:
        """
        Rule-based check against 31 Master Laws.
        Phase 4B: implement full NLP-based law violation detection.
        Returns empty list until implemented (safe default).
        """
        violations = []
        text_lower = recommendation.lower()

        # Basic keyword heuristics — Phase 4B replaces with full NLP
        if any(w in text_lower for w in ["ignore privacy", "share data", "leak"]):
            violations.append(LawViolation(2, MASTER_LAWS[2], "Potential privacy violation detected", "high"))
        if any(w in text_lower for w in ["burn bridges", "irreversible", "no way back"]):
            violations.append(LawViolation(3, MASTER_LAWS[3], "May reduce future options", "medium"))
        if any(w in text_lower for w in ["guaranteed", "no risk", "impossible to fail"]):
            violations.append(LawViolation(18, MASTER_LAWS[18], "Violates reality principle — no guarantees", "medium"))

        return violations

    def get_contradiction_history(self, limit: int = 20) -> list:
        """Return recent contradiction checks."""
        return [r.to_dict() for r in self._history[-limit:]]

    def get_status(self) -> dict:
        return {
            "version": self.VERSION,
            "flywheel_wired": self._flywheel is not None,
            "checks_run": len(self._history),
            "contradictions_found": sum(1 for r in self._history if r.detected),
        }
