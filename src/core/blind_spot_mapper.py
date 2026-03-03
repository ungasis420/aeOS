"""
aeOS Phase 5 — Blind_Spot_Mapper (A8)
=======================================
Surfaces what you consistently miss, avoid, or underweight.

COGNITIVE_TWIN finds patterns in what you DO.
Blind_Spot_Mapper finds patterns in what you DON'T —
absences, avoidances, systematic omissions.

Layer: 9 (Century-Gap bridge)
Dependencies: PERSIST, DB, CARTRIDGE_LOADER, Reflection_Engine (A7).
              V9.0: COGNITIVE_TWIN (F2.5).

Analysis Method:
    1) Domain activity distribution vs expected.
    2) Decision type frequency gaps.
    3) Cartridge activation analysis.
    4) Temporal avoidance patterns (things consistently deferred).

Interface Contract (from Addendum A):
    analyze()                   -> BlindSpotReport
    getUnderweightedDomains()   -> list[str]
    getAvoidedDecisionTypes()   -> list[str]
    getCartridgesNeverFired()   -> list[str]
    getSuggestedFocus()         -> list[str]

DB Table: BlindSpot_Log
"""
from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# All known domains in aeOS (from FlywheelLogger.VALID_DOMAINS + cartridge
# domains). Used to detect underweighted areas.
ALL_KNOWN_DOMAINS: Set[str] = {
    "business",
    "finance",
    "health",
    "relationships",
    "career",
    "creative",
    "learning",
    "personal",
}

# All known decision types from Decision_Tree_Log schema
ALL_DECISION_TYPES: Set[str] = {
    "strategic",
    "tactical",
    "operational",
    "financial",
    "personal",
    "creative",
    "technical",
}

# Minimum activity threshold — domains below this fraction of the average
# are considered underweighted
UNDERWEIGHT_THRESHOLD = 0.25


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BlindSpotReport:
    """Full blind spot analysis result."""
    analysis_date: str
    total_decisions_analyzed: int
    underweighted_domains: List[str]
    avoided_patterns: List[str]
    cartridges_never_fired: List[str]
    suggested_focus: List[str]
    domain_distribution: Dict[str, int]
    decision_type_distribution: Dict[str, int]
    coverage_score: float  # 0-100: how evenly spread is decision activity

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# BlindSpotMapper
# ---------------------------------------------------------------------------

class BlindSpotMapper:
    """
    Surfaces what the Sovereign consistently misses, avoids, or
    underweights across decision-making.

    Uses historical decision data to detect:
    - Domains with disproportionately few decisions
    - Decision types consistently deferred
    - Active cartridges that were never used
    - Patterns of avoidance (temporal, domain, type)

    Usage:
        mapper = BlindSpotMapper(db_path="/path/to/aeOS.db")

        report = mapper.analyze()
        weak = mapper.get_underweighted_domains()
        avoided = mapper.get_avoided_decision_types()
        unused = mapper.get_cartridges_never_fired()
        focus = mapper.get_suggested_focus()
    """

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        cartridge_dir: Optional[Union[str, Path]] = None,
        known_domains: Optional[Set[str]] = None,
        known_decision_types: Optional[Set[str]] = None,
    ) -> None:
        if db_path is not None:
            self._db_path = Path(db_path).expanduser().resolve()
        else:
            self._db_path = (
                Path(__file__).resolve().parent.parent.parent / "db" / "aeOS.db"
            )

        if cartridge_dir is not None:
            self._cartridge_dir = Path(cartridge_dir).expanduser().resolve()
        else:
            self._cartridge_dir = (
                Path(__file__).resolve().parent.parent / "cartridges"
            )

        self._known_domains = known_domains or ALL_KNOWN_DOMAINS
        self._known_decision_types = known_decision_types or ALL_DECISION_TYPES

    # ------------------------------------------------------------------
    # Public API: analyze
    # ------------------------------------------------------------------

    def analyze(self, days: int = 90) -> BlindSpotReport:
        """
        Full blind spot analysis.

        Examines decision history across domains, decision types,
        and cartridge usage to surface systematic gaps.

        Args:
            days: Lookback period in days (default 90).

        Returns:
            BlindSpotReport with underweighted domains, avoided patterns,
            unused cartridges, and recommended focus areas.
        """
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=days)).isoformat()

        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            decisions = self._query_all_decisions(conn, tables, cutoff)

            domain_dist = self._compute_domain_distribution(decisions)
            type_dist = self._compute_decision_type_distribution(decisions)
            fired_carts = self._get_fired_cartridges(conn, tables, cutoff)
            all_carts = self._get_all_cartridge_ids()

            underweighted = self._find_underweighted_domains(domain_dist)
            avoided_types = self._find_avoided_decision_types(type_dist)
            never_fired = sorted(all_carts - fired_carts)
            avoided_patterns = self._detect_avoidance_patterns(
                decisions, underweighted, avoided_types
            )
            coverage = self._compute_coverage_score(domain_dist)
            suggestions = self._generate_suggestions(
                underweighted, avoided_types, never_fired, avoided_patterns
            )

            report = BlindSpotReport(
                analysis_date=now.isoformat(),
                total_decisions_analyzed=len(decisions),
                underweighted_domains=underweighted,
                avoided_patterns=avoided_patterns,
                cartridges_never_fired=never_fired,
                suggested_focus=suggestions,
                domain_distribution=dict(domain_dist),
                decision_type_distribution=dict(type_dist),
                coverage_score=coverage,
            )

            # Persist to BlindSpot_Log
            self._persist_analysis(conn, tables, report)

            return report
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: getUnderweightedDomains
    # ------------------------------------------------------------------

    def get_underweighted_domains(self, days: int = 90) -> List[str]:
        """
        Domains with disproportionately few decisions.

        A domain is underweighted if its decision count is below
        UNDERWEIGHT_THRESHOLD (25%) of the average across all active domains.

        Args:
            days: Lookback period in days.

        Returns:
            List of domain name strings.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()

        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            decisions = self._query_all_decisions(conn, tables, cutoff)
            domain_dist = self._compute_domain_distribution(decisions)
            return self._find_underweighted_domains(domain_dist)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: getAvoidedDecisionTypes
    # ------------------------------------------------------------------

    def get_avoided_decision_types(self, days: int = 90) -> List[str]:
        """
        Decision categories consistently deferred.

        Compares actual decision type frequency against known types
        and returns those with zero or near-zero activity.

        Args:
            days: Lookback period in days.

        Returns:
            List of decision type strings.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()

        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            decisions = self._query_all_decisions(conn, tables, cutoff)
            type_dist = self._compute_decision_type_distribution(decisions)
            return self._find_avoided_decision_types(type_dist)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: getCartridgesNeverFired
    # ------------------------------------------------------------------

    def get_cartridges_never_fired(self, days: int = 90) -> List[str]:
        """
        Active cartridges with zero usage in the lookback period.

        Compares loaded cartridge IDs against Cartridge_Performance_Log
        to find cartridges that exist but were never activated.

        Args:
            days: Lookback period in days.

        Returns:
            Sorted list of cartridge ID strings.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()

        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            fired = self._get_fired_cartridges(conn, tables, cutoff)
            all_carts = self._get_all_cartridge_ids()
            return sorted(all_carts - fired)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: getSuggestedFocus
    # ------------------------------------------------------------------

    def get_suggested_focus(self, days: int = 90) -> List[str]:
        """
        Recommended areas to address blind spots.

        Generates actionable suggestions based on the full analysis.

        Args:
            days: Lookback period in days.

        Returns:
            List of suggestion strings.
        """
        report = self.analyze(days=days)
        return report.suggested_focus

    # ------------------------------------------------------------------
    # Internal: query decisions
    # ------------------------------------------------------------------

    def _query_all_decisions(
        self,
        conn: sqlite3.Connection,
        tables: set,
        cutoff_iso: str,
    ) -> List[Dict[str, Any]]:
        """Query decisions from all available decision tables."""
        decisions: List[Dict[str, Any]] = []

        if "Compound_Intelligence_Log" in tables:
            try:
                rows = conn.execute(
                    """SELECT decision_id, context, domain, confidence,
                              cartridges_fired, outcome_valence,
                              outcome_magnitude, timestamp
                       FROM Compound_Intelligence_Log
                       WHERE timestamp >= ?
                       ORDER BY timestamp DESC""",
                    (cutoff_iso,),
                ).fetchall()
                for row in rows:
                    d = dict(row)
                    d["_source"] = "CIL"
                    decisions.append(d)
            except sqlite3.Error as e:
                logger.warning("Error querying CIL: %s", e)

        if "Decision_Tree_Log" in tables:
            try:
                rows = conn.execute(
                    """SELECT Decision_ID as decision_id,
                              Rationale as context,
                              'unknown' as domain,
                              Decision_Type as decision_type,
                              Confidence_Pct as confidence,
                              Outcome as outcome,
                              Decision_Date as timestamp
                       FROM Decision_Tree_Log
                       WHERE Decision_Date >= ?
                       ORDER BY Decision_Date DESC""",
                    (cutoff_iso,),
                ).fetchall()
                for row in rows:
                    d = dict(row)
                    d["_source"] = "DTL"
                    decisions.append(d)
            except sqlite3.Error as e:
                logger.warning("Error querying DTL: %s", e)

        return decisions

    # ------------------------------------------------------------------
    # Internal: distributions
    # ------------------------------------------------------------------

    def _compute_domain_distribution(
        self, decisions: List[Dict[str, Any]]
    ) -> Counter:
        """Count decisions per domain."""
        counts: Counter = Counter()
        for d in decisions:
            domain = d.get("domain", "unknown")
            if domain and domain != "unknown":
                counts[domain] += 1
        return counts

    def _compute_decision_type_distribution(
        self, decisions: List[Dict[str, Any]]
    ) -> Counter:
        """Count decisions per type (from Decision_Tree_Log)."""
        counts: Counter = Counter()
        for d in decisions:
            dtype = d.get("decision_type")
            if dtype:
                counts[dtype.lower()] += 1
        return counts

    # ------------------------------------------------------------------
    # Internal: underweight detection
    # ------------------------------------------------------------------

    def _find_underweighted_domains(self, dist: Counter) -> List[str]:
        """Find domains below UNDERWEIGHT_THRESHOLD of average."""
        if not dist:
            # No decisions at all — all domains are underweighted
            return sorted(self._known_domains)

        avg = sum(dist.values()) / max(len(self._known_domains), 1)
        threshold = avg * UNDERWEIGHT_THRESHOLD

        underweighted = []
        for domain in sorted(self._known_domains):
            if dist.get(domain, 0) < threshold:
                underweighted.append(domain)

        return underweighted

    def _find_avoided_decision_types(self, dist: Counter) -> List[str]:
        """Find decision types with zero activity."""
        avoided = []
        for dtype in sorted(self._known_decision_types):
            if dist.get(dtype, 0) == 0:
                avoided.append(dtype)
        return avoided

    # ------------------------------------------------------------------
    # Internal: cartridge analysis
    # ------------------------------------------------------------------

    def _get_fired_cartridges(
        self,
        conn: sqlite3.Connection,
        tables: set,
        cutoff_iso: str,
    ) -> Set[str]:
        """Get set of cartridge IDs that were fired in the lookback period."""
        fired: Set[str] = set()

        # From Cartridge_Performance_Log
        if "Cartridge_Performance_Log" in tables:
            try:
                rows = conn.execute(
                    """SELECT DISTINCT cartridge_id
                       FROM Cartridge_Performance_Log
                       WHERE timestamp >= ?""",
                    (cutoff_iso,),
                ).fetchall()
                for row in rows:
                    fired.add(row[0])
            except sqlite3.Error:
                pass

        # From Compound_Intelligence_Log (cartridges_fired JSON array)
        if "Compound_Intelligence_Log" in tables:
            try:
                rows = conn.execute(
                    """SELECT cartridges_fired
                       FROM Compound_Intelligence_Log
                       WHERE timestamp >= ?
                         AND cartridges_fired IS NOT NULL""",
                    (cutoff_iso,),
                ).fetchall()
                for row in rows:
                    try:
                        carts = json.loads(row[0]) if row[0] else []
                        for c in carts:
                            fired.add(c)
                    except (json.JSONDecodeError, TypeError):
                        pass
            except sqlite3.Error:
                pass

        # From Cartridge_Arbitration_Log
        if "Cartridge_Arbitration_Log" in tables:
            try:
                rows = conn.execute(
                    """SELECT conflicting_carts
                       FROM Cartridge_Arbitration_Log
                       WHERE timestamp >= ?""",
                    (cutoff_iso,),
                ).fetchall()
                for row in rows:
                    try:
                        carts = json.loads(row[0]) if row[0] else []
                        for c in carts:
                            fired.add(c)
                    except (json.JSONDecodeError, TypeError):
                        pass
            except sqlite3.Error:
                pass

        return fired

    def _get_all_cartridge_ids(self) -> Set[str]:
        """Load all cartridge IDs from the cartridge directory."""
        cart_ids: Set[str] = set()
        if not self._cartridge_dir.exists():
            return cart_ids

        for fp in self._cartridge_dir.glob("*.json"):
            if fp.name == "cartridge_schema.json":
                continue
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                cid = data.get("id", data.get("cartridge_id", ""))
                if cid:
                    cart_ids.add(cid)
            except (json.JSONDecodeError, OSError):
                pass

        return cart_ids

    # ------------------------------------------------------------------
    # Internal: avoidance pattern detection
    # ------------------------------------------------------------------

    def _detect_avoidance_patterns(
        self,
        decisions: List[Dict[str, Any]],
        underweighted: List[str],
        avoided_types: List[str],
    ) -> List[str]:
        """Detect behavioral avoidance patterns."""
        patterns: List[str] = []

        if underweighted:
            patterns.append(
                f"Domain avoidance: {', '.join(underweighted)} have "
                f"disproportionately few decisions"
            )

        if avoided_types:
            patterns.append(
                f"Decision type gap: {', '.join(avoided_types)} "
                f"never used in decision-making"
            )

        # Check for temporal clustering (all decisions in small time window)
        if len(decisions) >= 5:
            timestamps = []
            for d in decisions:
                ts = d.get("timestamp")
                if ts:
                    try:
                        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                        timestamps.append(dt)
                    except (ValueError, TypeError):
                        pass

            if len(timestamps) >= 5:
                timestamps.sort()
                span = (timestamps[-1] - timestamps[0]).days
                if span <= 3 and len(timestamps) >= 5:
                    patterns.append(
                        "Temporal clustering: all decisions made within "
                        f"{span} day(s). Consider more consistent decision cadence."
                    )

        # Check if outcomes are rarely recorded
        with_outcomes = sum(
            1 for d in decisions
            if d.get("outcome_valence") is not None
        )
        total = len(decisions)
        if total >= 5 and with_outcomes < total * 0.3:
            patterns.append(
                f"Outcome tracking gap: only {with_outcomes}/{total} "
                f"decisions have recorded outcomes. "
                f"Closing the feedback loop is critical for compounding."
            )

        return patterns

    # ------------------------------------------------------------------
    # Internal: coverage scoring
    # ------------------------------------------------------------------

    def _compute_coverage_score(self, dist: Counter) -> float:
        """
        Compute domain coverage score (0-100).

        100 = perfectly even distribution across all known domains.
        0 = all decisions in one domain or no decisions at all.
        """
        if not dist:
            return 0.0

        total = sum(dist.values())
        if total == 0:
            return 0.0

        n_domains = len(self._known_domains)
        if n_domains <= 1:
            return 100.0

        # Expected even distribution
        expected = total / n_domains

        # Sum of absolute deviations from expected
        deviation = sum(
            abs(dist.get(d, 0) - expected) for d in self._known_domains
        )

        # Max possible deviation (all in one domain)
        max_deviation = 2 * total * (n_domains - 1) / n_domains

        if max_deviation == 0:
            return 100.0

        score = 100.0 * (1 - deviation / max_deviation)
        return round(max(0.0, min(100.0, score)), 1)

    # ------------------------------------------------------------------
    # Internal: suggestions
    # ------------------------------------------------------------------

    def _generate_suggestions(
        self,
        underweighted: List[str],
        avoided_types: List[str],
        never_fired: List[str],
        avoided_patterns: List[str],
    ) -> List[str]:
        """Generate actionable suggestions from blind spot analysis."""
        suggestions: List[str] = []

        if underweighted:
            top = underweighted[:3]
            suggestions.append(
                f"Explore decisions in: {', '.join(top)}. "
                f"These domains lack attention."
            )

        if avoided_types:
            top = avoided_types[:3]
            suggestions.append(
                f"Try making {', '.join(top)} decisions. "
                f"These types are consistently skipped."
            )

        if never_fired:
            top = never_fired[:3]
            suggestions.append(
                f"Review unused cartridges: {', '.join(top)}. "
                f"They may hold untapped insights."
            )

        if any("outcome tracking" in p.lower() for p in avoided_patterns):
            suggestions.append(
                "Record outcomes for past decisions. "
                "Feedback loops compound intelligence."
            )

        if not suggestions:
            suggestions.append(
                "No major blind spots detected. "
                "Continue diversified decision-making."
            )

        return suggestions

    # ------------------------------------------------------------------
    # Internal: persistence
    # ------------------------------------------------------------------

    def _persist_analysis(
        self,
        conn: sqlite3.Connection,
        tables: set,
        report: BlindSpotReport,
    ) -> None:
        """Save analysis to BlindSpot_Log table."""
        if "BlindSpot_Log" not in tables:
            return

        try:
            conn.execute(
                """INSERT INTO BlindSpot_Log
                (analysis_date, underweighted_domains, avoided_patterns,
                 cartridges_never_fired, suggested_focus, acknowledged)
                VALUES (?, ?, ?, ?, ?, 0)""",
                (
                    report.analysis_date,
                    json.dumps(report.underweighted_domains),
                    json.dumps(report.avoided_patterns),
                    json.dumps(report.cartridges_never_fired),
                    json.dumps(report.suggested_focus),
                ),
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.warning("Failed to persist blind spot analysis: %s", e)

    # ------------------------------------------------------------------
    # Internal: DB helpers
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


__all__ = [
    "BlindSpotMapper",
    "BlindSpotReport",
    "ALL_KNOWN_DOMAINS",
    "ALL_DECISION_TYPES",
    "UNDERWEIGHT_THRESHOLD",
]
