"""
aeOS Phase 4 — Contradiction_Detector (A2)
===========================================
Flags when new decisions or recommendations contradict past decisions
or Master Laws. Wired into AeOSCore.query() BEFORE 4-Gate, AFTER reasoning.

Silent contradictions erode compound intelligence — this module ensures
internal consistency.

Layer: Cross-cutting (pre-4-Gate)
Dependencies: PERSIST, DB, NLP (similarity), DECISIONS

Interface Contract (from Addendum A):
    checkDecision(decision, domain)     -> ContradictionResult
    checkAgainstLaws(recommendation)    -> list[LawViolation]
    getHistory(opts?)                   -> list[ContradictionResult]
    getConsistencyScore(domain?)        -> float (0-100)

Severity Levels:
    LOW:      Minor inconsistency, informational.
    MEDIUM:   Notable conflict, recommend review.
    HIGH:     Direct contradiction, blocks 4-Gate Gate 1 until resolved.
    CRITICAL: Master Law violation, halts response.

Integration Point:
    AeOSCore.query() pipeline: NLQ_Parser -> Reasoning -> Contradiction_Detector -> 4-Gate
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# The 5 Master Laws of Sovereign Intelligence
# ---------------------------------------------------------------------------

MASTER_LAWS = {
    "LAW_1_SCANNER": {
        "id": "LAW_1",
        "name": "Law of the Scanner",
        "principle": "Every conversation is a potential scan. Extract signal from noise.",
        "keywords": ["ignore", "skip scan", "don't extract", "no analysis"],
    },
    "LAW_2_KILL": {
        "id": "LAW_2",
        "name": "Law of the Kill",
        "principle": "Kill ideas ruthlessly. Survival of the fittest. No sentimentality.",
        "keywords": ["keep everything", "never kill", "save all", "no pruning"],
    },
    "LAW_3_PAIN": {
        "id": "LAW_3",
        "name": "Law of the Pain",
        "principle": "Pain is the compass. High-pain problems = high-value solutions.",
        "keywords": ["ignore pain", "pain doesn't matter", "skip pain analysis"],
    },
    "LAW_4_SCORE": {
        "id": "LAW_4",
        "name": "Law of the Score",
        "principle": "If it cannot be scored, it cannot be prioritized. Quantify everything.",
        "keywords": ["don't score", "no metrics", "skip scoring", "feelings only"],
    },
    "LAW_5_EVIDENCE": {
        "id": "LAW_5",
        "name": "Law of the Evidence",
        "principle": "No claim without evidence. No stage advance without data.",
        "keywords": ["no evidence needed", "skip validation", "trust blindly", "no proof"],
    },
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ContradictionResult:
    """Result of checking a decision for contradictions."""
    has_contradiction: bool
    severity: str  # low, medium, high, critical
    new_decision_id: Optional[str]
    conflicting_decision_id: Optional[str]
    explanation: str
    domain: str = "unknown"
    similarity_score: float = 0.0
    recommendation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LawViolation:
    """A violation of one of the 5 Master Laws."""
    law_id: str
    law_name: str
    principle: str
    violation_text: str
    severity: str = "critical"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Contradiction_Detector
# ---------------------------------------------------------------------------

class ContradictionDetector:
    """
    Detects contradictions between new decisions and past decision history,
    and checks recommendations against the 5 Master Laws.

    Wired into the AeOSCore.query() pipeline BEFORE 4-Gate validation.
    HIGH/CRITICAL contradictions block Gate 1 (Safe) until resolved.

    Usage:
        detector = ContradictionDetector(db_path="/path/to/aeOS.db")
        result = detector.check_decision(
            decision={"description": "Keep all ideas regardless of score"},
            domain="business"
        )
        if result.has_contradiction:
            print(f"Contradiction: {result.explanation}")

        violations = detector.check_against_laws("We should skip scoring entirely")
        for v in violations:
            print(f"Law Violation: {v.law_name} - {v.violation_text}")
    """

    # Similarity threshold for detecting contradictions
    SIMILARITY_THRESHOLD = 0.35
    # Minimum similarity for a HIGH severity contradiction
    HIGH_SEVERITY_THRESHOLD = 0.55

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
    ) -> None:
        if db_path is not None:
            self._db_path = Path(db_path).expanduser().resolve()
        else:
            self._db_path = (
                Path(__file__).resolve().parent.parent.parent / "db" / "aeOS.db"
            )

    # ------------------------------------------------------------------
    # Public API: checkDecision
    # ------------------------------------------------------------------

    def check_decision(
        self,
        decision: Dict[str, Any],
        domain: str = "unknown",
    ) -> ContradictionResult:
        """
        Check a new decision against past decision history for contradictions.

        Args:
            decision: Dict with at least 'description' key.
            domain:   Decision domain for scoped comparison.

        Returns:
            ContradictionResult with contradiction details.
        """
        description = decision.get("description", "")
        decision_id = decision.get("id", decision.get("decision_id"))

        if not description:
            return ContradictionResult(
                has_contradiction=False,
                severity="low",
                new_decision_id=decision_id,
                conflicting_decision_id=None,
                explanation="No decision description provided.",
                domain=domain,
            )

        # Check against Master Laws first
        law_violations = self.check_against_laws(description)
        if law_violations:
            violation = law_violations[0]
            result = ContradictionResult(
                has_contradiction=True,
                severity="critical",
                new_decision_id=decision_id,
                conflicting_decision_id=None,
                explanation=f"Master Law violation: {violation.law_name} — {violation.violation_text}",
                domain=domain,
                similarity_score=1.0,
                recommendation=f"Revise decision to comply with {violation.law_name}: {violation.principle}",
            )
            self._log_contradiction(result)
            return result

        # Check against recent decisions
        past_decisions = self._get_past_decisions(domain, limit=100)
        best_match = self._find_contradiction(description, past_decisions)

        if best_match is not None:
            similarity, past_desc, past_id = best_match
            severity = self._classify_severity(similarity)

            result = ContradictionResult(
                has_contradiction=True,
                severity=severity,
                new_decision_id=decision_id,
                conflicting_decision_id=past_id,
                explanation=(
                    f"New decision contradicts past decision "
                    f"(similarity: {similarity:.0%}): '{past_desc[:100]}...'"
                ),
                domain=domain,
                similarity_score=similarity,
                recommendation=(
                    "Review and reconcile with previous decision, "
                    "or explicitly override with rationale."
                ),
            )
            self._log_contradiction(result)
            return result

        return ContradictionResult(
            has_contradiction=False,
            severity="low",
            new_decision_id=decision_id,
            conflicting_decision_id=None,
            explanation="No contradictions detected.",
            domain=domain,
        )

    # ------------------------------------------------------------------
    # Public API: checkAgainstLaws
    # ------------------------------------------------------------------

    def check_against_laws(self, recommendation: str) -> List[LawViolation]:
        """
        Check a recommendation against the 5 Master Laws.

        Args:
            recommendation: Text of the recommendation to check.

        Returns:
            List of LawViolation objects (empty if no violations).
        """
        if not recommendation:
            return []

        violations = []
        text_lower = recommendation.lower()

        for law_key, law in MASTER_LAWS.items():
            for keyword in law["keywords"]:
                if keyword.lower() in text_lower:
                    violations.append(LawViolation(
                        law_id=law["id"],
                        law_name=law["name"],
                        principle=law["principle"],
                        violation_text=(
                            f"Recommendation contains '{keyword}' which "
                            f"violates {law['name']}: {law['principle']}"
                        ),
                        severity="critical",
                    ))
                    break  # One violation per law is enough

        return violations

    # ------------------------------------------------------------------
    # Public API: getHistory
    # ------------------------------------------------------------------

    def get_history(
        self,
        domain: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100,
    ) -> List[ContradictionResult]:
        """
        Retrieve contradiction detection history.

        Args:
            domain:   Filter by domain (None = all).
            severity: Filter by severity (None = all).
            limit:    Maximum records to return.

        Returns:
            List of ContradictionResult records, newest first.
        """
        conn = self._get_connection()
        try:
            if "Contradiction_Log" not in self._get_existing_tables(conn):
                return []

            where_parts = []
            params: List[Any] = []

            if domain:
                where_parts.append("domain = ?")
                params.append(domain)
            if severity:
                where_parts.append("severity = ?")
                params.append(severity)

            where_clause = ""
            if where_parts:
                where_clause = "WHERE " + " AND ".join(where_parts)

            params.append(limit)
            rows = conn.execute(
                f"SELECT * FROM Contradiction_Log {where_clause} "
                f"ORDER BY detected_at DESC LIMIT ?",
                params,
            ).fetchall()

            return [
                ContradictionResult(
                    has_contradiction=True,
                    severity=row["severity"],
                    new_decision_id=row["new_decision_id"],
                    conflicting_decision_id=row["conflicting_decision_id"],
                    explanation=row["explanation"],
                    domain=row["domain"],
                )
                for row in rows
            ]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: getConsistencyScore
    # ------------------------------------------------------------------

    def get_consistency_score(self, domain: Optional[str] = None) -> float:
        """
        Compute overall consistency score for the decision history.

        Score 0-100 where 100 = perfectly consistent, 0 = highly contradictory.

        Args:
            domain: Optional domain filter.

        Returns:
            Consistency score (0-100).
        """
        conn = self._get_connection()
        try:
            if "Contradiction_Log" not in self._get_existing_tables(conn):
                return 100.0  # No contradictions = perfect consistency

            params: List[Any] = []
            domain_filter = ""
            if domain:
                domain_filter = "WHERE domain = ?"
                params.append(domain)

            row = conn.execute(
                f"SELECT COUNT(*) FROM Contradiction_Log {domain_filter}",
                params,
            ).fetchone()
            total_contradictions = row[0] if row else 0

            # Weighted by severity
            severity_weights = {"low": 1, "medium": 3, "high": 7, "critical": 15}
            weighted_sum = 0

            for sev, weight in severity_weights.items():
                sev_params = [sev] + (params[:] if params else [])
                sev_filter = f"WHERE severity = ?"
                if domain:
                    sev_filter += " AND domain = ?"
                row = conn.execute(
                    f"SELECT COUNT(*) FROM Contradiction_Log {sev_filter}",
                    sev_params,
                ).fetchone()
                count = row[0] if row else 0
                weighted_sum += count * weight

            # Score: 100 - penalty. Penalty grows with contradictions.
            # Max penalty capped at 100.
            penalty = min(weighted_sum * 2, 100)
            return max(100.0 - penalty, 0.0)

        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _get_existing_tables(self, conn: sqlite3.Connection) -> set:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {row[0] for row in rows}

    def _get_past_decisions(
        self, domain: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Retrieve past decisions from Decision_Tree_Log."""
        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)

            decisions = []

            # Check Decision_Tree_Log
            if "Decision_Tree_Log" in tables:
                rows = conn.execute(
                    "SELECT Decision_ID, Decision_Description, Decision_Type "
                    "FROM Decision_Tree_Log "
                    "ORDER BY Decision_Date DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                for row in rows:
                    decisions.append({
                        "id": row["Decision_ID"],
                        "description": row["Decision_Description"] or "",
                        "type": row["Decision_Type"],
                    })

            # Also check Contradiction_Log for past detected contradictions
            if "Contradiction_Log" in tables:
                rows = conn.execute(
                    "SELECT new_decision_id, explanation "
                    "FROM Contradiction_Log "
                    "WHERE resolution = 'overridden' "
                    "ORDER BY detected_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                for row in rows:
                    decisions.append({
                        "id": row["new_decision_id"],
                        "description": row["explanation"] or "",
                        "type": "overridden",
                    })

            return decisions

        finally:
            conn.close()

    def _find_contradiction(
        self,
        new_description: str,
        past_decisions: List[Dict[str, Any]],
    ) -> Optional[tuple]:
        """
        Find the most contradictory past decision using text similarity.

        Uses negation detection + semantic similarity.
        Returns (similarity_score, past_description, past_id) or None.
        """
        if not past_decisions:
            return None

        # Negation indicators that suggest contradiction
        negation_pairs = [
            ("should", "should not"), ("do", "don't"), ("will", "won't"),
            ("accept", "reject"), ("start", "stop"), ("buy", "sell"),
            ("keep", "kill"), ("pursue", "abandon"), ("invest", "divest"),
            ("grow", "shrink"), ("expand", "contract"), ("hire", "fire"),
            ("yes", "no"), ("approve", "deny"), ("increase", "decrease"),
        ]

        new_lower = new_description.lower()
        best_score = 0.0
        best_match = None

        for past in past_decisions:
            past_desc = past.get("description", "")
            if not past_desc:
                continue

            past_lower = past_desc.lower()

            # Base similarity
            similarity = SequenceMatcher(
                None, new_lower, past_lower
            ).ratio()

            # Boost if negation detected
            negation_boost = 0.0
            for pos, neg in negation_pairs:
                if (pos in new_lower and neg in past_lower) or \
                   (neg in new_lower and pos in past_lower):
                    negation_boost = max(negation_boost, 0.3)

            # Combined score
            combined = min(similarity + negation_boost, 1.0)

            if combined > best_score and combined >= self.SIMILARITY_THRESHOLD:
                best_score = combined
                best_match = (combined, past_desc, past.get("id"))

        return best_match

    def _classify_severity(self, similarity: float) -> str:
        """Classify contradiction severity based on similarity score."""
        if similarity >= 0.8:
            return "high"
        elif similarity >= self.HIGH_SEVERITY_THRESHOLD:
            return "medium"
        else:
            return "low"

    def _log_contradiction(self, result: ContradictionResult) -> None:
        """Log a detected contradiction to the database."""
        conn = self._get_connection()
        try:
            if "Contradiction_Log" not in self._get_existing_tables(conn):
                return

            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT INTO Contradiction_Log
                (detected_at, new_decision_id, conflicting_decision_id,
                 severity, explanation, domain)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    now_iso,
                    result.new_decision_id,
                    result.conflicting_decision_id,
                    result.severity,
                    result.explanation,
                    result.domain,
                ),
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.warning("Failed to log contradiction: %s", e)
        finally:
            conn.close()


__all__ = [
    "ContradictionDetector",
    "ContradictionResult",
    "LawViolation",
    "MASTER_LAWS",
]
