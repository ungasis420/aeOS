"""
aeOS Phase 4 — Cartridge_Arbitrator (A4)
==========================================
Defined arbitration logic when two or more cartridges give contradictory
recommendations. 45 cartridges WILL conflict. Without arbitration, outputs
are unpredictable.

Priority Chain:
    1) Master Law compliance (Law wins over any cartridge)
    2) Domain specificity (more specific cartridge wins)
    3) Confidence score (higher wins)
    4) Recency of validation (more recently validated wins)
    5) Escalate to Sovereign

Layer: 4 (AI — cartridge layer)
Dependencies: CARTRIDGE_LOADER, SMART_ROUTER, PERSIST

Interface Contract (from Addendum A):
    detectConflicts(fired, recs)     -> list[Conflict]
    arbitrate(conflict)              -> ArbitrationResult
    getArbitrationHistory()          -> list[ArbitrationResult]
    setDomainPriority(domain, prio)  -> None

V9.0: META_CARTRIDGE (F7.1) replaces simple priority chain with learned
      arbitration patterns. Cartridge_Arbitrator becomes the fallback.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CartridgeRecommendation:
    """A recommendation from a single cartridge."""
    cartridge_id: str
    cartridge_name: str
    recommendation: str
    confidence: float  # 0.0 to 1.0
    domain: str = "unknown"
    validated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Conflict:
    """A detected conflict between two or more cartridge recommendations."""
    conflict_id: str
    cartridge_ids: List[str]
    recommendations: List[CartridgeRecommendation]
    conflict_type: str  # recommendation, priority, domain_overlap
    domain: str = "unknown"
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ArbitrationResult:
    """Result of arbitrating a cartridge conflict."""
    conflict_id: str
    winner_cart_id: Optional[str]
    winner_recommendation: str
    resolution_method: str  # priority_chain, confidence, domain_specificity, sovereign_escalation
    domain: str = "unknown"
    escalated: bool = False
    reasoning: str = ""
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# CartridgeArbitrator
# ---------------------------------------------------------------------------

class CartridgeArbitrator:
    """
    Resolves conflicts when multiple cartridges give contradictory
    recommendations.

    Priority chain:
        1. Master Law compliance
        2. Domain specificity
        3. Confidence score
        4. Recency of validation
        5. Escalate to Sovereign

    Usage:
        arb = CartridgeArbitrator()
        conflicts = arb.detect_conflicts(fired_cartridges, recommendations)
        for conflict in conflicts:
            result = arb.arbitrate(conflict)
    """

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

        # Domain priority overrides (Sovereign can set these)
        self._domain_priorities: Dict[str, int] = {}
        self._conflict_counter = 0

    # ------------------------------------------------------------------
    # Public API: detectConflicts
    # ------------------------------------------------------------------

    def detect_conflicts(
        self,
        fired_cartridges: List[str],
        recommendations: List[CartridgeRecommendation],
    ) -> List[Conflict]:
        """
        Detect conflicts between fired cartridge recommendations.

        Compares all pairs of recommendations for contradictory advice.

        Args:
            fired_cartridges: List of cartridge IDs that fired.
            recommendations:  List of CartridgeRecommendation objects.

        Returns:
            List of Conflict objects (empty if no conflicts).
        """
        if len(recommendations) < 2:
            return []

        conflicts: List[Conflict] = []

        # Compare all pairs
        for i in range(len(recommendations)):
            for j in range(i + 1, len(recommendations)):
                rec_a = recommendations[i]
                rec_b = recommendations[j]

                if self._is_conflicting(rec_a, rec_b):
                    self._conflict_counter += 1
                    conflict = Conflict(
                        conflict_id=f"CONF-{self._conflict_counter:04d}",
                        cartridge_ids=[rec_a.cartridge_id, rec_b.cartridge_id],
                        recommendations=[rec_a, rec_b],
                        conflict_type="recommendation",
                        domain=rec_a.domain if rec_a.domain == rec_b.domain else "cross-domain",
                        description=(
                            f"Conflicting recommendations from "
                            f"'{rec_a.cartridge_name}' and '{rec_b.cartridge_name}'"
                        ),
                    )
                    conflicts.append(conflict)

        return conflicts

    # ------------------------------------------------------------------
    # Public API: arbitrate
    # ------------------------------------------------------------------

    def arbitrate(self, conflict: Conflict) -> ArbitrationResult:
        """
        Resolve a cartridge conflict using the priority chain.

        Priority chain:
            1) Master Law compliance (Law wins over any cartridge)
            2) Domain specificity (Sovereign domain priority)
            3) Confidence score (higher wins)
            4) Recency of validation (more recently validated wins)
            5) Escalate to Sovereign

        Args:
            conflict: The Conflict to resolve.

        Returns:
            ArbitrationResult with winner and reasoning.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        recs = conflict.recommendations

        if len(recs) < 2:
            return ArbitrationResult(
                conflict_id=conflict.conflict_id,
                winner_cart_id=recs[0].cartridge_id if recs else None,
                winner_recommendation=recs[0].recommendation if recs else "",
                resolution_method="no_conflict",
                domain=conflict.domain,
                timestamp=now_iso,
            )

        # Step 1: Domain priority (Sovereign-set overrides)
        domain_winner = self._check_domain_priority(recs)
        if domain_winner is not None:
            result = ArbitrationResult(
                conflict_id=conflict.conflict_id,
                winner_cart_id=domain_winner.cartridge_id,
                winner_recommendation=domain_winner.recommendation,
                resolution_method="domain_specificity",
                domain=conflict.domain,
                reasoning=(
                    f"Domain priority favors '{domain_winner.cartridge_name}' "
                    f"(domain: {domain_winner.domain})"
                ),
                timestamp=now_iso,
            )
            self._log_arbitration(result, conflict)
            return result

        # Step 2: Confidence score (higher wins)
        confidence_winner = self._check_confidence(recs)
        if confidence_winner is not None:
            result = ArbitrationResult(
                conflict_id=conflict.conflict_id,
                winner_cart_id=confidence_winner.cartridge_id,
                winner_recommendation=confidence_winner.recommendation,
                resolution_method="confidence",
                domain=conflict.domain,
                reasoning=(
                    f"Higher confidence: '{confidence_winner.cartridge_name}' "
                    f"({confidence_winner.confidence:.2f}) vs others"
                ),
                timestamp=now_iso,
            )
            self._log_arbitration(result, conflict)
            return result

        # Step 3: Recency (more recently validated wins)
        recency_winner = self._check_recency(recs)
        if recency_winner is not None:
            result = ArbitrationResult(
                conflict_id=conflict.conflict_id,
                winner_cart_id=recency_winner.cartridge_id,
                winner_recommendation=recency_winner.recommendation,
                resolution_method="recency",
                domain=conflict.domain,
                reasoning=(
                    f"More recently validated: '{recency_winner.cartridge_name}'"
                ),
                timestamp=now_iso,
            )
            self._log_arbitration(result, conflict)
            return result

        # Step 4: Escalate to Sovereign
        result = ArbitrationResult(
            conflict_id=conflict.conflict_id,
            winner_cart_id=None,
            winner_recommendation=(
                "Conflict could not be resolved automatically. "
                "Sovereign review required."
            ),
            resolution_method="sovereign_escalation",
            domain=conflict.domain,
            escalated=True,
            reasoning="All priority chain steps exhausted. Escalating.",
            timestamp=now_iso,
        )
        self._log_arbitration(result, conflict)
        return result

    # ------------------------------------------------------------------
    # Public API: getArbitrationHistory
    # ------------------------------------------------------------------

    def get_arbitration_history(
        self, limit: int = 100
    ) -> List[ArbitrationResult]:
        """
        Retrieve past arbitration results for pattern analysis.

        Returns:
            List of ArbitrationResult records, newest first.
        """
        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            if "Cartridge_Arbitration_Log" not in tables:
                return []

            rows = conn.execute(
                "SELECT * FROM Cartridge_Arbitration_Log "
                "ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()

            results = []
            for row in rows:
                carts = json.loads(row["conflicting_carts"]) if row["conflicting_carts"] else []
                results.append(ArbitrationResult(
                    conflict_id=f"CONF-{row['id']:04d}",
                    winner_cart_id=row["winner_cart_id"],
                    winner_recommendation="",
                    resolution_method=row["resolution_method"],
                    domain=row["domain"],
                    escalated=bool(row["escalated"]),
                    reasoning=row["notes"] or "",
                    timestamp=row["timestamp"],
                ))
            return results
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: setDomainPriority
    # ------------------------------------------------------------------

    def set_domain_priority(self, domain: str, priority: int) -> None:
        """
        Sovereign override: set priority for a domain's cartridges.

        Lower number = higher priority. Cartridges from higher-priority
        domains win conflicts.

        Args:
            domain:   Domain name (e.g., "business", "health").
            priority: Priority level (1 = highest).
        """
        self._domain_priorities[domain] = priority

    def get_domain_priorities(self) -> Dict[str, int]:
        """Return current domain priority configuration."""
        return dict(self._domain_priorities)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_conflicting(
        self, a: CartridgeRecommendation, b: CartridgeRecommendation
    ) -> bool:
        """Detect if two recommendations conflict."""
        # Negation-based conflict detection
        negation_pairs = [
            ("should", "should not"), ("do", "don't"), ("will", "won't"),
            ("accept", "reject"), ("buy", "sell"), ("keep", "kill"),
            ("pursue", "abandon"), ("invest", "divest"),
            ("increase", "decrease"), ("start", "stop"),
            ("patience", "urgency"), ("wait", "act now"),
            ("conservative", "aggressive"), ("slow", "fast"),
        ]

        a_lower = a.recommendation.lower()
        b_lower = b.recommendation.lower()

        for pos, neg in negation_pairs:
            if (pos in a_lower and neg in b_lower) or \
               (neg in a_lower and pos in b_lower):
                return True

        return False

    def _check_domain_priority(
        self, recs: List[CartridgeRecommendation]
    ) -> Optional[CartridgeRecommendation]:
        """Check if domain priority resolves the conflict."""
        if not self._domain_priorities:
            return None

        best = None
        best_priority = float("inf")

        for rec in recs:
            priority = self._domain_priorities.get(rec.domain, 999)
            if priority < best_priority:
                best_priority = priority
                best = rec

        # Only return if there's a clear winner (not all same priority)
        priorities = [
            self._domain_priorities.get(r.domain, 999) for r in recs
        ]
        if len(set(priorities)) > 1 and best is not None:
            return best

        return None

    def _check_confidence(
        self, recs: List[CartridgeRecommendation]
    ) -> Optional[CartridgeRecommendation]:
        """Check if confidence score resolves the conflict."""
        if not recs:
            return None

        sorted_recs = sorted(recs, key=lambda r: r.confidence, reverse=True)

        # Need clear winner (>= 0.1 gap)
        if len(sorted_recs) >= 2:
            gap = sorted_recs[0].confidence - sorted_recs[1].confidence
            if gap >= 0.1:
                return sorted_recs[0]

        return None

    def _check_recency(
        self, recs: List[CartridgeRecommendation]
    ) -> Optional[CartridgeRecommendation]:
        """Check if validation recency resolves the conflict."""
        dated = [r for r in recs if r.validated_at]
        if len(dated) < 2:
            return None

        sorted_recs = sorted(dated, key=lambda r: r.validated_at or "", reverse=True)
        return sorted_recs[0]

    def _log_arbitration(
        self, result: ArbitrationResult, conflict: Conflict
    ) -> None:
        """Log arbitration to the database."""
        try:
            conn = self._get_connection()
            tables = self._get_existing_tables(conn)
            if "Cartridge_Arbitration_Log" not in tables:
                conn.close()
                return

            conn.execute(
                """INSERT INTO Cartridge_Arbitration_Log
                (timestamp, conflicting_carts, conflict_type, winner_cart_id,
                 resolution_method, domain, escalated, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.timestamp,
                    json.dumps(conflict.cartridge_ids),
                    conflict.conflict_type,
                    result.winner_cart_id,
                    result.resolution_method,
                    result.domain,
                    1 if result.escalated else 0,
                    result.reasoning,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("Failed to log arbitration: %s", e)

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


__all__ = [
    "CartridgeArbitrator",
    "CartridgeRecommendation",
    "Conflict",
    "ArbitrationResult",
]
