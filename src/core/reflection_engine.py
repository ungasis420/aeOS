"""
aeOS Phase 5 — Reflection_Engine (A7)
======================================
Scheduled backward-looking intelligence loops. aeOS reasons forward
but never systematically reviews what compounded, what failed, what
patterns emerged.

Highest ROI feature for long-term sovereign intelligence.
Feeds COGNITIVE_TWIN and COMPOUND_FLYWHEEL.

Layer: 9 (Century-Gap bridge) + Cross-cutting
Dependencies: PERSIST, DB, Compound_Intelligence_Log (FlywheelLogger),
              Decision_Tree_Log, Cartridge_Performance_Log, Audit_Log.

Interface Contract (from Addendum A):
    weeklyReflection()          -> ReflectionReport
    monthlyReflection()         -> ReflectionReport
    patternSummary(days)        -> PatternSummary
    whatCompounded()            -> list[CompoundItem]
    whatFailed()                -> list[FailureItem]
    generateInsight()           -> str

DB Table: Reflection_Log
Trigger: weekly Sunday 9AM, monthly 1st 9AM, manual: aeos reflect
"""
from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CompoundItem:
    """An action/decision that generated compound returns."""
    decision_id: str
    context: str
    domain: str
    confidence: float
    outcome_valence: int  # -1, 0, +1
    outcome_magnitude: float
    cartridges_fired: List[str] = field(default_factory=list)
    compound_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FailureItem:
    """An outcome that underperformed predictions."""
    decision_id: str
    context: str
    domain: str
    confidence_at_decision: float
    outcome_valence: int
    outcome_magnitude: float
    failure_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PatternSummary:
    """Ad-hoc period summary of patterns."""
    days: int
    period_start: str
    period_end: str
    total_decisions: int
    domains_active: Dict[str, int]
    avg_confidence: float
    positive_rate: float
    negative_rate: float
    top_cartridges: List[str]
    recurring_themes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReflectionReport:
    """Full reflection report — weekly or monthly."""
    period: str  # 'weekly' | 'monthly' | 'adhoc'
    period_start: str
    period_end: str
    generated_at: str
    decisions_reviewed: int
    compound_score: float
    top_patterns: List[str]
    compounded: List[CompoundItem]
    failed: List[FailureItem]
    cartridges_most_fired: List[str]
    recommended_focus: str
    insight: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# ReflectionEngine
# ---------------------------------------------------------------------------

class ReflectionEngine:
    """
    Scheduled backward-looking intelligence loops.

    Reviews past decisions, outcomes, cartridge usage, and patterns to
    surface what compounded, what failed, and where focus should shift.

    Usage:
        engine = ReflectionEngine(db_path="/path/to/aeOS.db")

        # Scheduled reflections
        weekly = engine.weekly_reflection()
        monthly = engine.monthly_reflection()

        # Ad-hoc analysis
        patterns = engine.pattern_summary(days=14)
        winners = engine.what_compounded()
        losers = engine.what_failed()

        # Claude-generated insight (returns static analysis without API)
        insight = engine.generate_insight()
    """

    # Tables this engine reads from (not all may exist yet)
    _DECISION_TABLES = (
        "Compound_Intelligence_Log",
        "Decision_Tree_Log",
    )

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
    # Public API: weeklyReflection
    # ------------------------------------------------------------------

    def weekly_reflection(self) -> ReflectionReport:
        """
        Generate a weekly reflection report covering the past 7 days.
        Scheduled trigger: Sunday 9 AM.

        Returns:
            ReflectionReport with decisions reviewed, patterns, compounds,
            failures, and recommended focus.
        """
        return self._generate_reflection("weekly", days=7)

    # ------------------------------------------------------------------
    # Public API: monthlyReflection
    # ------------------------------------------------------------------

    def monthly_reflection(self) -> ReflectionReport:
        """
        Generate a monthly reflection report covering the past 30 days.
        Scheduled trigger: 1st of month, 9 AM.

        Returns:
            ReflectionReport with comprehensive monthly analysis.
        """
        return self._generate_reflection("monthly", days=30)

    # ------------------------------------------------------------------
    # Public API: patternSummary
    # ------------------------------------------------------------------

    def pattern_summary(self, days: int = 30) -> PatternSummary:
        """
        Generate an ad-hoc pattern summary for the given number of days.

        Args:
            days: Number of days to analyze (default 30).

        Returns:
            PatternSummary with domain activity, confidence stats,
            top cartridges, and recurring themes.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()

        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            decisions = self._query_decisions(conn, tables, cutoff_iso)

            domains: Dict[str, int] = Counter()
            confidences: List[float] = []
            outcomes: List[int] = []
            cartridge_counts: Counter = Counter()
            themes: Counter = Counter()

            for d in decisions:
                domain = d.get("domain", "unknown")
                domains[domain] += 1

                conf = d.get("confidence", d.get("Confidence_Pct"))
                if conf is not None:
                    # Normalize: Decision_Tree_Log uses 0-100, CIL uses 0-1
                    if isinstance(conf, (int, float)):
                        confidences.append(
                            conf / 100.0 if conf > 1.0 else float(conf)
                        )

                valence = d.get("outcome_valence")
                if valence is not None:
                    outcomes.append(int(valence))

                carts = d.get("cartridges_fired", [])
                if isinstance(carts, str):
                    try:
                        carts = json.loads(carts)
                    except (json.JSONDecodeError, TypeError):
                        carts = []
                for c in carts:
                    cartridge_counts[c] += 1

                # Extract themes from context or reasoning
                context = d.get("context", d.get("Rationale", ""))
                if context:
                    for word in str(context).lower().split():
                        if len(word) > 5:
                            themes[word] += 1

            avg_conf = (
                round(sum(confidences) / len(confidences), 4)
                if confidences else 0.0
            )
            pos_count = sum(1 for o in outcomes if o > 0)
            neg_count = sum(1 for o in outcomes if o < 0)
            total_with_outcomes = len(outcomes) if outcomes else 1

            return PatternSummary(
                days=days,
                period_start=cutoff_iso,
                period_end=now.isoformat(),
                total_decisions=len(decisions),
                domains_active=dict(domains),
                avg_confidence=avg_conf,
                positive_rate=round(pos_count / total_with_outcomes, 4),
                negative_rate=round(neg_count / total_with_outcomes, 4),
                top_cartridges=[c for c, _ in cartridge_counts.most_common(5)],
                recurring_themes=[
                    t for t, count in themes.most_common(10) if count >= 2
                ],
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: whatCompounded
    # ------------------------------------------------------------------

    def what_compounded(self, days: int = 90) -> List[CompoundItem]:
        """
        Identify actions that generated compound returns.

        Looks for decisions with positive outcomes (valence=+1) and
        high outcome magnitude (>= 0.5), indicating compounding value.

        Args:
            days: Lookback period in days (default 90).

        Returns:
            List of CompoundItem objects sorted by magnitude descending.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            items: List[CompoundItem] = []

            if "Compound_Intelligence_Log" in tables:
                rows = conn.execute(
                    """SELECT decision_id, context, domain, confidence,
                              outcome_valence, outcome_magnitude,
                              cartridges_fired
                       FROM Compound_Intelligence_Log
                       WHERE outcome_recorded = 1
                         AND outcome_valence = 1
                         AND outcome_magnitude >= 0.5
                         AND timestamp >= ?
                       ORDER BY outcome_magnitude DESC""",
                    (cutoff,),
                ).fetchall()

                for row in rows:
                    carts = []
                    try:
                        carts = json.loads(row["cartridges_fired"]) if row["cartridges_fired"] else []
                    except (json.JSONDecodeError, TypeError):
                        pass

                    items.append(CompoundItem(
                        decision_id=row["decision_id"] or "",
                        context=row["context"] or "",
                        domain=row["domain"] or "unknown",
                        confidence=float(row["confidence"] or 0),
                        outcome_valence=int(row["outcome_valence"]),
                        outcome_magnitude=float(row["outcome_magnitude"]),
                        cartridges_fired=carts,
                        compound_reason=(
                            f"Positive outcome (magnitude {row['outcome_magnitude']:.1f}) "
                            f"in {row['domain']} domain"
                        ),
                    ))

            return items
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: whatFailed
    # ------------------------------------------------------------------

    def what_failed(self, days: int = 90) -> List[FailureItem]:
        """
        Identify outcomes that underperformed predictions.

        Looks for decisions where outcome_valence=-1 (bad outcome)
        OR where confidence was high but outcome was neutral/negative.

        Args:
            days: Lookback period in days (default 90).

        Returns:
            List of FailureItem objects sorted by magnitude descending.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            items: List[FailureItem] = []

            if "Compound_Intelligence_Log" in tables:
                rows = conn.execute(
                    """SELECT decision_id, context, domain, confidence,
                              outcome_valence, outcome_magnitude
                       FROM Compound_Intelligence_Log
                       WHERE outcome_recorded = 1
                         AND (outcome_valence = -1
                              OR (confidence >= 0.7 AND outcome_valence <= 0))
                         AND timestamp >= ?
                       ORDER BY outcome_magnitude DESC""",
                    (cutoff,),
                ).fetchall()

                for row in rows:
                    valence = int(row["outcome_valence"])
                    conf = float(row["confidence"] or 0)

                    if valence == -1:
                        reason = "Negative outcome"
                    else:
                        reason = (
                            f"High confidence ({conf:.0%}) but "
                            f"{'neutral' if valence == 0 else 'negative'} outcome"
                        )

                    items.append(FailureItem(
                        decision_id=row["decision_id"] or "",
                        context=row["context"] or "",
                        domain=row["domain"] or "unknown",
                        confidence_at_decision=conf,
                        outcome_valence=valence,
                        outcome_magnitude=float(row["outcome_magnitude"] or 0),
                        failure_reason=reason,
                    ))

            return items
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: generateInsight
    # ------------------------------------------------------------------

    def generate_insight(self, days: int = 30) -> str:
        """
        Generate a strategic insight from reflection data.

        In production, this would call Claude API via SMART_ROUTER.
        Currently generates a rule-based insight from available data.

        Args:
            days: Lookback period for insight generation.

        Returns:
            Human-readable strategic insight string.
        """
        summary = self.pattern_summary(days=days)
        compounds = self.what_compounded(days=days)
        failures = self.what_failed(days=days)

        parts: List[str] = []

        if summary.total_decisions == 0:
            return "No decisions recorded yet. Start making decisions to build reflection data."

        parts.append(
            f"Over the past {days} days, {summary.total_decisions} decisions "
            f"were reviewed across {len(summary.domains_active)} domains."
        )

        if summary.avg_confidence > 0:
            parts.append(
                f"Average decision confidence: {summary.avg_confidence:.0%}."
            )

        if compounds:
            top = compounds[0]
            parts.append(
                f"Strongest compound: '{top.context[:60]}' "
                f"in {top.domain} (magnitude {top.outcome_magnitude:.1f})."
            )

        if failures:
            parts.append(
                f"{len(failures)} decision(s) underperformed. "
                f"Review these for pattern correction."
            )

        if summary.top_cartridges:
            parts.append(
                f"Most active cartridges: {', '.join(summary.top_cartridges[:3])}."
            )

        # Focus recommendation
        if summary.negative_rate > 0.3:
            parts.append(
                "RECOMMENDED FOCUS: High failure rate detected. "
                "Review decision frameworks and cartridge calibration."
            )
        elif len(summary.domains_active) <= 1 and summary.total_decisions >= 5:
            parts.append(
                "RECOMMENDED FOCUS: Decisions concentrated in single domain. "
                "Consider cross-domain diversification."
            )
        elif summary.avg_confidence < 0.5:
            parts.append(
                "RECOMMENDED FOCUS: Low average confidence. "
                "Strengthen evidence gathering before deciding."
            )
        else:
            parts.append(
                "RECOMMENDED FOCUS: Maintain current decision quality. "
                "Continue logging outcomes for compound data."
            )

        return " ".join(parts)

    # ------------------------------------------------------------------
    # Internal: generate full reflection
    # ------------------------------------------------------------------

    def _generate_reflection(
        self, period: str, days: int
    ) -> ReflectionReport:
        """Build a complete ReflectionReport for the given period."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()
        now_iso = now.isoformat()

        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            decisions = self._query_decisions(conn, tables, cutoff_iso)

            # Compound score (simplified — would use FlywheelLogger in prod)
            compound_score = self._compute_compound_score(conn, tables)

            # Patterns: domain frequency + cartridge frequency
            domain_counts: Counter = Counter()
            cartridge_counts: Counter = Counter()
            pattern_phrases: Counter = Counter()

            for d in decisions:
                domain_counts[d.get("domain", "unknown")] += 1

                carts = d.get("cartridges_fired", [])
                if isinstance(carts, str):
                    try:
                        carts = json.loads(carts)
                    except (json.JSONDecodeError, TypeError):
                        carts = []
                for c in carts:
                    cartridge_counts[c] += 1

                context = d.get("context", d.get("Rationale", ""))
                if context:
                    words = str(context).lower().split()
                    for w in words:
                        if len(w) > 5:
                            pattern_phrases[w] += 1

            top_patterns = [p for p, c in pattern_phrases.most_common(5) if c >= 2]
            cartridges_most_fired = [
                c for c, _ in cartridge_counts.most_common(5)
            ]

            # Compounded and failed
            compounds = self.what_compounded(days=days)
            failures = self.what_failed(days=days)

            # Recommended focus
            focus = self._determine_focus(
                decisions, compounds, failures, domain_counts
            )

            # Generate insight
            insight = self.generate_insight(days=days)

            report = ReflectionReport(
                period=period,
                period_start=cutoff_iso,
                period_end=now_iso,
                generated_at=now_iso,
                decisions_reviewed=len(decisions),
                compound_score=compound_score,
                top_patterns=top_patterns,
                compounded=compounds,
                failed=failures,
                cartridges_most_fired=cartridges_most_fired,
                recommended_focus=focus,
                insight=insight,
            )

            # Persist to Reflection_Log
            self._persist_reflection(conn, tables, report)

            return report
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

    def _query_decisions(
        self,
        conn: sqlite3.Connection,
        tables: set,
        cutoff_iso: str,
    ) -> List[Dict[str, Any]]:
        """Query decisions from all available decision tables."""
        decisions: List[Dict[str, Any]] = []

        # Compound_Intelligence_Log (FlywheelLogger)
        if "Compound_Intelligence_Log" in tables:
            try:
                rows = conn.execute(
                    """SELECT decision_id, context, domain, confidence,
                              cartridges_fired, outcome_recorded,
                              outcome_valence, outcome_magnitude, timestamp
                       FROM Compound_Intelligence_Log
                       WHERE timestamp >= ?
                       ORDER BY timestamp DESC""",
                    (cutoff_iso,),
                ).fetchall()
                for row in rows:
                    decisions.append(dict(row))
            except sqlite3.Error as e:
                logger.warning("Error querying Compound_Intelligence_Log: %s", e)

        # Decision_Tree_Log (legacy/v8 decisions)
        if "Decision_Tree_Log" in tables:
            try:
                rows = conn.execute(
                    """SELECT Decision_ID as decision_id,
                              Rationale as context,
                              'unknown' as domain,
                              Confidence_Pct as confidence,
                              Outcome as outcome_description,
                              Decision_Date as timestamp
                       FROM Decision_Tree_Log
                       WHERE Decision_Date >= ?
                       ORDER BY Decision_Date DESC""",
                    (cutoff_iso,),
                ).fetchall()
                for row in rows:
                    decisions.append(dict(row))
            except sqlite3.Error as e:
                logger.warning("Error querying Decision_Tree_Log: %s", e)

        return decisions

    def _compute_compound_score(
        self, conn: sqlite3.Connection, tables: set
    ) -> float:
        """Compute simplified compound score from decision data."""
        if "Compound_Intelligence_Log" not in tables:
            return 0.0

        try:
            row = conn.execute(
                """SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome_recorded = 1 THEN 1 ELSE 0 END) as with_outcomes,
                    AVG(confidence) as avg_conf,
                    SUM(CASE WHEN outcome_valence = 1 THEN 1 ELSE 0 END) as positive
                FROM Compound_Intelligence_Log"""
            ).fetchone()

            if not row or row["total"] == 0:
                return 0.0

            total = row["total"]
            with_outcomes = row["with_outcomes"] or 0
            avg_conf = float(row["avg_conf"] or 0)
            positive = row["positive"] or 0

            completeness = with_outcomes / total if total > 0 else 0.0
            pos_rate = positive / max(with_outcomes, 1)

            score = (
                min(total / 100, 1.0) * 30
                + completeness * 25
                + pos_rate * 25
                + avg_conf * 20
            )
            return round(score, 2)
        except sqlite3.Error:
            return 0.0

    def _determine_focus(
        self,
        decisions: List[Dict],
        compounds: List[CompoundItem],
        failures: List[FailureItem],
        domain_counts: Counter,
    ) -> str:
        """Determine recommended focus area from reflection data."""
        if not decisions:
            return "Start logging decisions to build reflection data."

        if len(failures) > len(compounds):
            return (
                "High failure-to-success ratio. Review decision frameworks "
                "and strengthen evidence gathering."
            )

        if len(domain_counts) <= 1 and len(decisions) >= 5:
            return (
                "Decisions concentrated in single domain. "
                "Consider cross-domain exploration."
            )

        # Find domains with no positive outcomes
        domains_with_positives = set()
        for c in compounds:
            domains_with_positives.add(c.domain)

        weak_domains = [
            d for d in domain_counts
            if d not in domains_with_positives and d != "unknown"
        ]
        if weak_domains:
            return (
                f"Domains with no positive outcomes: {', '.join(weak_domains)}. "
                f"Consider improving cartridge coverage or decision quality there."
            )

        return "Maintain current trajectory. Continue logging outcomes."

    def _persist_reflection(
        self,
        conn: sqlite3.Connection,
        tables: set,
        report: ReflectionReport,
    ) -> None:
        """Save reflection report to Reflection_Log table."""
        if "Reflection_Log" not in tables:
            return

        try:
            conn.execute(
                """INSERT INTO Reflection_Log
                (period, report_json, compound_score_at_time, decisions_reviewed,
                 top_patterns, failed_outcomes, cartridges_most_fired,
                 recommended_focus, generated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    report.period,
                    json.dumps(report.to_dict(), default=str),
                    report.compound_score,
                    report.decisions_reviewed,
                    json.dumps(report.top_patterns),
                    json.dumps(
                        [f.to_dict() for f in report.failed], default=str
                    ),
                    json.dumps(report.cartridges_most_fired),
                    report.recommended_focus,
                    report.generated_at,
                ),
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.warning("Failed to persist reflection: %s", e)


__all__ = [
    "ReflectionEngine",
    "ReflectionReport",
    "PatternSummary",
    "CompoundItem",
    "FailureItem",
]
