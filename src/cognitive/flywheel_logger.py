"""
aeOS v9.0 — Compound Intelligence Flywheel Logger (F3.6)
=========================================================
FUNCTIONAL — this one actually runs from Day 1.
Every decision → outcome → cartridge performance is logged here.
Without this data accumulating from the start, there's nothing to compound.
This is the most critical initialization: every day we delay = data permanently lost.
Architecture:
  - Append-only log (never mutate past records)
  - Three event types: DECISION_MADE, OUTCOME_RECORDED, CARTRIDGE_FIRED
  - Links decisions to cartridges to outcomes for causal chain reconstruction
  - Feeds: Causal Inference Engine (F1.6), Cognitive Twin (F2.5), Autonomous Cartridge Gen (F3.7)
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional
from src.db.connect import get_db_connection
class FlywheelLogger:
    """
    Compound Intelligence Flywheel Logger.
    Records the full reasoning chain: decision → cartridges fired → outcome.
    This append-only log is the raw material for:
      - Causal inference (which cartridges correlate with good outcomes)
      - Cognitive twin training (your reasoning patterns over time)
      - Autonomous cartridge generation (gap detection)
      - Predictive life engine (trajectory from past patterns)
    Usage:
        logger = FlywheelLogger()
        # When a decision is made:
        decision_id = logger.log_decision(
            context="Should I take this client project?",
            cartridges_fired=["negotiation", "systems_thinking", "energy_management"],
            reasoning_summary="High revenue but low leverage. Decided to negotiate scope.",
            confidence=0.72,
            domain="business"
        )
        # When outcome is known (days/weeks later):
        logger.log_outcome(
            decision_id=decision_id,
            outcome_description="Negotiated 40% scope reduction. Project delivered profitably.",
            outcome_valence=1,   # -1 (bad), 0 (neutral), +1 (good)
            outcome_magnitude=0.8  # 0.0 to 1.0 — how significant was this?
        )
    """
    VALID_DOMAINS = {
        "business", "finance", "health", "relationships",
        "career", "creative", "learning", "personal", "unknown"
    }
    def __init__(self):
        self._db = get_db_connection()
    # ------------------------------------------------------------------
    # Core logging methods
    # ------------------------------------------------------------------
    def log_decision(
        self,
        context: str,
        cartridges_fired: list[str],
        reasoning_summary: str,
        confidence: float,
        domain: str = "unknown",
        session_id: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> str:
        """
        Log a decision event. Returns decision_id for future outcome linkage.
        Args:
            context:           The question or situation being decided on.
            cartridges_fired:  List of cartridge IDs that contributed reasoning.
            reasoning_summary: Brief human-readable summary of the reasoning chain.
            confidence:        Confidence level at decision time (0.0 to 1.0).
            domain:            Life domain (business, finance, health, etc.)
            session_id:        Optional session identifier for grouping.
            metadata:          Any additional structured data to preserve.
        Returns:
            decision_id: UUID string — store this to log the outcome later.
        """
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"confidence must be 0.0–1.0, got {confidence}")
        if domain not in self.VALID_DOMAINS:
            domain = "unknown"
        decision_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "decision_id": decision_id,
            "event_type": "DECISION_MADE",
            "timestamp": now,
            "context": context[:2000],  # cap for storage
            "cartridges_fired": cartridges_fired,
            "cartridge_count": len(cartridges_fired),
            "reasoning_summary": reasoning_summary[:1000],
            "confidence": round(confidence, 4),
            "domain": domain,
            "session_id": session_id,
            "outcome_recorded": False,
            "outcome_valence": None,
            "outcome_magnitude": None,
            "outcome_description": None,
            "outcome_timestamp": None,
            "metadata": metadata or {}
        }
        self._persist(record)
        return decision_id
    def log_outcome(
        self,
        decision_id: str,
        outcome_description: str,
        outcome_valence: int,
        outcome_magnitude: float = 0.5,
        metadata: Optional[dict] = None
    ) -> bool:
        """
        Record the outcome of a previously logged decision.
        Args:
            decision_id:          UUID from log_decision().
            outcome_description:  What actually happened.
            outcome_valence:      -1 (bad), 0 (neutral), +1 (good).
            outcome_magnitude:    How significant? 0.0 (trivial) to 1.0 (life-changing).
            metadata:             Any additional structured data.
        Returns:
            True if outcome was successfully linked to decision, False otherwise.
        """
        if outcome_valence not in (-1, 0, 1):
            raise ValueError("outcome_valence must be -1, 0, or 1")
        if not 0.0 <= outcome_magnitude <= 1.0:
            raise ValueError("outcome_magnitude must be 0.0–1.0")
        now = datetime.now(timezone.utc).isoformat()
        return self._update_outcome(
            decision_id=decision_id,
            outcome_description=outcome_description[:1000],
            outcome_valence=outcome_valence,
            outcome_magnitude=round(outcome_magnitude, 4),
            outcome_timestamp=now,
            metadata=metadata or {}
        )
    def log_cartridge_performance(
        self,
        cartridge_id: str,
        decision_id: str,
        relevance_score: float,
        was_accepted: bool,
        domain: str = "unknown"
    ) -> None:
        """
        Log how a specific cartridge performed in a specific decision.
        Used by Autonomous Cartridge Generation (F3.7) to detect gaps and
        by the Compound Flywheel to weight cartridge contributions.
        Args:
            cartridge_id:    ID of the cartridge (e.g. "negotiation_law25").
            decision_id:     Links to the parent decision.
            relevance_score: How relevant was this cartridge? (0.0 to 1.0)
            was_accepted:    Did the user accept the cartridge's recommendation?
            domain:          Life domain context.
        """
        if domain not in self.VALID_DOMAINS:
            domain = "unknown"
        record = {
            "event_type": "CARTRIDGE_PERFORMANCE",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cartridge_id": cartridge_id,
            "decision_id": decision_id,
            "relevance_score": round(relevance_score, 4),
            "was_accepted": was_accepted,
            "domain": domain
        }
        self._persist_cartridge_event(record)
    # ------------------------------------------------------------------
    # Query methods (feeds downstream engines)
    # ------------------------------------------------------------------
    def get_decision_history(
        self,
        domain: Optional[str] = None,
        limit: int = 100,
        with_outcomes_only: bool = False
    ) -> list[dict]:
        """
        Retrieve decision history for analysis.
        Args:
            domain:            Filter by domain (None = all domains).
            limit:             Max records to return.
            with_outcomes_only: If True, only return decisions with recorded outcomes.
        Returns:
            List of decision records, newest first.
        """
        return self._query_decisions(domain, limit, with_outcomes_only)
    def get_cartridge_effectiveness(
        self,
        cartridge_id: Optional[str] = None,
        domain: Optional[str] = None,
        min_samples: int = 5
    ) -> list[dict]:
        """
        Return effectiveness metrics per cartridge.
        Used by Autonomous Cartridge Generation to detect underperforming areas.
        Returns list of:
            {cartridge_id, total_uses, acceptance_rate, avg_outcome_valence,
             avg_outcome_magnitude, domains_used, last_used}
        """
        return self._compute_cartridge_stats(cartridge_id, domain, min_samples)
    def get_compound_score(self) -> dict:
        """
        Compute the current compound intelligence score.
        Higher = more data = better predictions = more value.
        Returns:
            {
              total_decisions: int,
              decisions_with_outcomes: int,
              outcome_completeness: float,  # % of decisions with outcomes
              avg_confidence: float,
              positive_outcome_rate: float,
              domains_covered: list[str],
              compound_score: float,        # 0.0 to 100.0
              score_interpretation: str
            }
        """
        return self._compute_compound_score()
    def get_domain_intelligence(self, domain: str) -> dict:
        """
        Return intelligence summary for a specific life domain.
        Used by Predictive Life Engine (F1.1) for trajectory analysis.
        """
        if domain not in self.VALID_DOMAINS:
            raise ValueError(f"Unknown domain: {domain}")
        return self._query_domain_stats(domain)
    # ------------------------------------------------------------------
    # Internal persistence (swappable storage backend)
    # ------------------------------------------------------------------
    def _persist(self, record: dict) -> None:
        """Write decision record to Compound_Intelligence_Log table."""
        try:
            with self._db.cursor() as cur:
                cur.execute("""
                    INSERT INTO Compound_Intelligence_Log (
                        decision_id, event_type, timestamp, context,
                        cartridges_fired, cartridge_count, reasoning_summary,
                        confidence, domain, session_id, outcome_recorded,
                        outcome_valence, outcome_magnitude, outcome_description,
                        outcome_timestamp, metadata
                    ) VALUES (
                        %(decision_id)s, %(event_type)s, %(timestamp)s, %(context)s,
                        %(cartridges_fired)s, %(cartridge_count)s, %(reasoning_summary)s,
                        %(confidence)s, %(domain)s, %(session_id)s, %(outcome_recorded)s,
                        %(outcome_valence)s, %(outcome_magnitude)s, %(outcome_description)s,
                        %(outcome_timestamp)s, %(metadata)s
                    )
                """, {
                    **record,
                    "cartridges_fired": json.dumps(record["cartridges_fired"]),
                    "metadata": json.dumps(record["metadata"])
                })
                self._db.commit()
        except Exception as e:
            self._db.rollback()
            raise RuntimeError(f"FlywheelLogger._persist failed: {e}") from e
    def _update_outcome(self, decision_id: str, **kwargs) -> bool:
        """Update existing decision record with outcome data."""
        try:
            with self._db.cursor() as cur:
                cur.execute("""
                    UPDATE Compound_Intelligence_Log
                    SET outcome_recorded = TRUE,
                        outcome_description = %(outcome_description)s,
                        outcome_valence = %(outcome_valence)s,
                        outcome_magnitude = %(outcome_magnitude)s,
                        outcome_timestamp = %(outcome_timestamp)s,
                        metadata = metadata || %(metadata)s::jsonb
                    WHERE decision_id = %(decision_id)s
                    AND outcome_recorded = FALSE
                """, {"decision_id": decision_id, **kwargs,
                      "metadata": json.dumps(kwargs.get("metadata", {}))})
                updated = cur.rowcount > 0
                self._db.commit()
                return updated
        except Exception as e:
            self._db.rollback()
            raise RuntimeError(f"FlywheelLogger._update_outcome failed: {e}") from e
    def _persist_cartridge_event(self, record: dict) -> None:
        """Write cartridge performance event to Cartridge_Evolution_Proposals table."""
        try:
            with self._db.cursor() as cur:
                cur.execute("""
                    INSERT INTO Cartridge_Performance_Log (
                        event_type, timestamp, cartridge_id, decision_id,
                        relevance_score, was_accepted, domain
                    ) VALUES (
                        %(event_type)s, %(timestamp)s, %(cartridge_id)s, %(decision_id)s,
                        %(relevance_score)s, %(was_accepted)s, %(domain)s
                    )
                """, record)
                self._db.commit()
        except Exception as e:
            self._db.rollback()
            raise RuntimeError(f"FlywheelLogger._persist_cartridge_event failed: {e}") from e
    def _query_decisions(
        self, domain: Optional[str], limit: int, with_outcomes_only: bool
    ) -> list[dict]:
        """Query decision history from DB."""
        try:
            with self._db.cursor() as cur:
                where_clauses = []
                params: dict = {"limit": limit}
                if domain:
                    where_clauses.append("domain = %(domain)s")
                    params["domain"] = domain
                if with_outcomes_only:
                    where_clauses.append("outcome_recorded = TRUE")
                where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
                cur.execute(f"""
                    SELECT * FROM Compound_Intelligence_Log
                    {where_sql}
                    ORDER BY timestamp DESC
                    LIMIT %(limit)s
                """, params)
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as e:
            raise RuntimeError(f"FlywheelLogger._query_decisions failed: {e}") from e
    def _compute_cartridge_stats(
        self, cartridge_id: Optional[str], domain: Optional[str], min_samples: int
    ) -> list[dict]:
        """Compute per-cartridge effectiveness from performance log."""
        try:
            with self._db.cursor() as cur:
                where_clauses = []
                params: dict = {"min_samples": min_samples}
                if cartridge_id:
                    where_clauses.append("cpl.cartridge_id = %(cartridge_id)s")
                    params["cartridge_id"] = cartridge_id
                if domain:
                    where_clauses.append("cpl.domain = %(domain)s")
                    params["domain"] = domain
                where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
                cur.execute(f"""
                    SELECT
                        cpl.cartridge_id,
                        COUNT(*) as total_uses,
                        AVG(cpl.relevance_score) as avg_relevance,
                        SUM(CASE WHEN cpl.was_accepted THEN 1 ELSE 0 END)::float / COUNT(*) as acceptance_rate,
                        AVG(cil.outcome_valence) as avg_outcome_valence,
                        AVG(cil.outcome_magnitude) as avg_outcome_magnitude,
                        array_agg(DISTINCT cpl.domain) as domains_used,
                        MAX(cpl.timestamp) as last_used
                    FROM Cartridge_Performance_Log cpl
                    LEFT JOIN Compound_Intelligence_Log cil ON cpl.decision_id = cil.decision_id
                    {where_sql}
                    GROUP BY cpl.cartridge_id
                    HAVING COUNT(*) >= %(min_samples)s
                    ORDER BY avg_outcome_valence DESC NULLS LAST
                """, params)
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as e:
            raise RuntimeError(f"FlywheelLogger._compute_cartridge_stats failed: {e}") from e
    def _compute_compound_score(self) -> dict:
        """Compute the compound intelligence score from accumulated data."""
        try:
            with self._db.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN outcome_recorded THEN 1 ELSE 0 END) as with_outcomes,
                        AVG(confidence) as avg_confidence,
                        SUM(CASE WHEN outcome_valence = 1 THEN 1 ELSE 0 END)::float /
                            NULLIF(SUM(CASE WHEN outcome_recorded THEN 1 ELSE 0 END), 0) as pos_rate,
                        array_agg(DISTINCT domain) as domains
                    FROM Compound_Intelligence_Log
                """)
                row = cur.fetchone()
                if not row or row[0] == 0:
                    return {
                        "total_decisions": 0, "decisions_with_outcomes": 0,
                        "outcome_completeness": 0.0, "avg_confidence": 0.0,
                        "positive_outcome_rate": 0.0, "domains_covered": [],
                        "compound_score": 0.0,
                        "score_interpretation": "No data yet — start making decisions."
                    }
                total, with_outcomes, avg_conf, pos_rate, domains = row
                completeness = (with_outcomes / total) if total > 0 else 0.0
                domain_count = len([d for d in (domains or []) if d and d != "unknown"])
                # Compound score: weighted combination
                score = (
                    min(total / 100, 1.0) * 30 +      # volume (max at 100 decisions)
                    completeness * 25 +                  # outcome tracking discipline
                    (pos_rate or 0) * 25 +              # decision quality
                    min(domain_count / 5, 1.0) * 20     # cross-domain coverage
                )
                if score < 20:
                    interpretation = "Early stage — data accumulating."
                elif score < 40:
                    interpretation = "Foundation forming — patterns emerging."
                elif score < 60:
                    interpretation = "Active intelligence — predictions improving."
                elif score < 80:
                    interpretation = "Strong compound base — high-confidence predictions."
                else:
                    interpretation = "Mature cognitive system — compounding at full power."
                return {
                    "total_decisions": total,
                    "decisions_with_outcomes": with_outcomes or 0,
                    "outcome_completeness": round(completeness, 4),
                    "avg_confidence": round(float(avg_conf or 0), 4),
                    "positive_outcome_rate": round(float(pos_rate or 0), 4),
                    "domains_covered": [d for d in (domains or []) if d],
                    "compound_score": round(score, 2),
                    "score_interpretation": interpretation
                }
        except Exception as e:
            raise RuntimeError(f"FlywheelLogger._compute_compound_score failed: {e}") from e
    def _query_domain_stats(self, domain: str) -> dict:
        """Query intelligence stats for a specific domain."""
        try:
            with self._db.cursor() as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) as total,
                        AVG(confidence) as avg_confidence,
                        SUM(CASE WHEN outcome_recorded THEN 1 ELSE 0 END) as with_outcomes,
                        AVG(outcome_valence) as avg_valence,
                        MIN(timestamp) as first_decision,
                        MAX(timestamp) as latest_decision
                    FROM Compound_Intelligence_Log
                    WHERE domain = %(domain)s
                """, {"domain": domain})
                row = cur.fetchone()
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, row)) if row else {}
        except Exception as e:
            raise RuntimeError(f"FlywheelLogger._query_domain_stats failed: {e}") from e
