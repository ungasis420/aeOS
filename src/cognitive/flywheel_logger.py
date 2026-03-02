"""FlywheelLogger — Compound intelligence data collection for aeOS.

Logs every decision cycle (context, cartridges fired, reasoning, confidence)
to build the compound intelligence flywheel. Each logged decision can later
receive outcome feedback to close the learning loop.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional


class FlywheelLogger:
    """Logs decision events for compound intelligence accumulation.

    Stores decision records in memory. In production, these write to
    Compound_Intelligence_Log via PERSIST.
    """

    def __init__(self) -> None:
        self._decisions: Dict[str, dict] = {}

    def log_decision(
        self,
        context: str,
        cartridges_fired: List[str],
        reasoning_summary: str,
        confidence: float,
        domain: str = "general",
    ) -> str:
        """Log a decision event.

        Args:
            context: User query or decision context.
            cartridges_fired: List of cartridge IDs that contributed.
            reasoning_summary: Synthesis output text.
            confidence: Confidence score (0.0–1.0).
            domain: Domain tag.

        Returns:
            decision_id (str) for later feedback linkage.
        """
        if not isinstance(context, str) or not context.strip():
            raise ValueError("context must be a non-empty string")
        if not isinstance(cartridges_fired, list):
            raise ValueError("cartridges_fired must be a list")
        conf = float(confidence)
        if conf < 0.0 or conf > 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")

        decision_id = str(uuid.uuid4())
        record = {
            "decision_id": decision_id,
            "context": context.strip(),
            "cartridges_fired": list(cartridges_fired),
            "reasoning_summary": str(reasoning_summary),
            "confidence": conf,
            "domain": str(domain),
            "outcome": None,
            "feedback_score": None,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        self._decisions[decision_id] = record
        return decision_id

    def record_outcome(
        self,
        decision_id: str,
        outcome: str,
        feedback_score: Optional[float] = None,
    ) -> bool:
        """Record outcome feedback for a prior decision.

        Args:
            decision_id: ID from log_decision().
            outcome: Outcome description (e.g. 'accepted', 'failed').
            feedback_score: Optional numeric score (0.0–1.0).

        Returns:
            True if decision found and updated.
        """
        if decision_id not in self._decisions:
            return False
        record = self._decisions[decision_id]
        record["outcome"] = str(outcome)
        if feedback_score is not None:
            fs = float(feedback_score)
            if fs < 0.0 or fs > 1.0:
                raise ValueError("feedback_score must be between 0.0 and 1.0")
            record["feedback_score"] = fs
        record["updated_at"] = time.time()
        return True

    def get_decision(self, decision_id: str) -> Optional[dict]:
        """Retrieve a single decision record."""
        return self._decisions.get(decision_id)

    def get_recent_decisions(self, limit: int = 20) -> List[dict]:
        """Return most recent decisions, newest first."""
        all_records = sorted(
            self._decisions.values(),
            key=lambda r: r["created_at"],
            reverse=True,
        )
        return all_records[:limit]

    def get_domain_stats(self, domain: str) -> dict:
        """Aggregate stats for a specific domain.

        Returns:
            {domain, total_decisions, avg_confidence,
             outcomes_recorded, avg_feedback_score}
        """
        records = [
            r for r in self._decisions.values() if r["domain"] == domain
        ]
        if not records:
            return {
                "domain": domain,
                "total_decisions": 0,
                "avg_confidence": 0.0,
                "outcomes_recorded": 0,
                "avg_feedback_score": 0.0,
            }
        confidences = [r["confidence"] for r in records]
        feedback_scores = [
            r["feedback_score"]
            for r in records
            if r["feedback_score"] is not None
        ]
        return {
            "domain": domain,
            "total_decisions": len(records),
            "avg_confidence": sum(confidences) / len(confidences),
            "outcomes_recorded": len(
                [r for r in records if r["outcome"] is not None]
            ),
            "avg_feedback_score": (
                sum(feedback_scores) / len(feedback_scores)
                if feedback_scores
                else 0.0
            ),
        }

    def get_all_decisions_count(self) -> int:
        """Return total number of logged decisions."""
        return len(self._decisions)
