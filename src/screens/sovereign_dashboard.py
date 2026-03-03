"""
aeOS Phase 5 — Sovereign_Dashboard (A9)
=========================================
Single-screen cockpit showing aeOS state at a glance.

The entire point of building aeOS is having one place to see everything.
This is the primary Phase 5 UI surface.

Layer: 7 (Screen)
Screen Path: / (HOME) — replaces or augments existing HOME screen
Dependencies: All domain modules (aggregated), Proactive_Alert_Engine,
              COMPOUND_FLYWHEEL, Reflection_Engine, Blind_Spot_Mapper,
              Contradiction_Detector, Audit_Trail, all Phase 4 modules.

Interface Contract (from Addendum A):
    getSnapshot()               -> DashboardSnapshot
    getDomainStatus(domain)     -> DomainStatus
    getAlerts()                 -> list[Alert]
    getTrajectory(days?)        -> TrajectoryMap

DashboardSnapshot Schema:
    compound_score, compound_trend (rising|stable|declining),
    active_alerts[], trajectory_30day: Map<domain,trend>,
    top_cartridges_firing[], pending_decisions[], blind_spots[],
    reflection_due: bool, last_reflection_summary, system_health,
    decisions_this_week, outcomes_this_week, consistency_score

Performance: Full snapshot < 2s. Incremental refresh < 200ms.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
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
class Alert:
    """Active alert requiring Sovereign attention."""
    alert_id: str
    source: str
    alert_type: str
    severity: str  # critical, high, medium, low
    message: str
    timestamp: str
    acknowledged: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DomainStatus:
    """Per-domain drill-down status."""
    domain: str
    decisions_count: int
    avg_confidence: float
    positive_rate: float
    negative_rate: float
    top_cartridges: List[str]
    recent_decisions: List[Dict[str, Any]]
    trend: str  # rising, stable, declining
    blind_spots: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TrajectoryPoint:
    """Single data point in a domain trajectory."""
    date: str
    decisions: int
    positive_outcomes: int
    negative_outcomes: int
    avg_confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TrajectoryMap:
    """30-day trajectory per domain."""
    days: int
    period_start: str
    period_end: str
    domains: Dict[str, List[TrajectoryPoint]]
    overall_trend: str  # rising, stable, declining

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class DashboardSnapshot:
    """Complete system state at a glance."""
    generated_at: str
    compound_score: float
    compound_trend: str  # rising, stable, declining
    active_alerts: List[Alert]
    trajectory_30day: Dict[str, str]  # domain -> trend
    top_cartridges_firing: List[str]
    pending_decisions: List[Dict[str, Any]]
    blind_spots: List[str]
    reflection_due: bool
    last_reflection_summary: str
    system_health: Dict[str, Any]
    decisions_this_week: int
    outcomes_this_week: int
    consistency_score: float

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# SovereignDashboard
# ---------------------------------------------------------------------------

class SovereignDashboard:
    """
    Single-screen cockpit for aeOS sovereign intelligence.

    Aggregates data from all Phase 4/5 modules into a unified
    snapshot for the Sovereign. This is the primary aeOS interface.

    Usage:
        dashboard = SovereignDashboard(db_path="/path/to/aeOS.db")

        # Full state
        snapshot = dashboard.get_snapshot()

        # Per-domain drill-down
        status = dashboard.get_domain_status("business")

        # Active alerts
        alerts = dashboard.get_alerts()

        # Trajectory analysis
        trajectory = dashboard.get_trajectory(days=30)
    """

    # Severity ordering for alert sorting
    _SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

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
    # Public API: getSnapshot
    # ------------------------------------------------------------------

    def get_snapshot(self) -> DashboardSnapshot:
        """
        Complete system state at a glance.

        Aggregates compound score, alerts, trajectories, cartridge usage,
        blind spots, reflection status, and system health into a single
        DashboardSnapshot.

        Returns:
            DashboardSnapshot with all dashboard data.
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)

            compound_score = self._get_compound_score(conn, tables)
            compound_trend = self._get_compound_trend(conn, tables)
            alerts = self._query_alerts(conn, tables)
            trajectory = self._compute_domain_trends(conn, tables, days=30)
            top_carts = self._get_top_cartridges(conn, tables, days=7)
            pending = self._get_pending_decisions(conn, tables)
            blind_spots = self._get_blind_spots(conn, tables)
            reflection_due, last_summary = self._get_reflection_status(
                conn, tables
            )
            health = self._get_system_health(conn, tables)
            week_decisions = self._count_decisions(conn, tables, days=7)
            week_outcomes = self._count_outcomes(conn, tables, days=7)
            consistency = self._get_consistency_score(conn, tables)

            return DashboardSnapshot(
                generated_at=now_iso,
                compound_score=compound_score,
                compound_trend=compound_trend,
                active_alerts=alerts,
                trajectory_30day=trajectory,
                top_cartridges_firing=top_carts,
                pending_decisions=pending,
                blind_spots=blind_spots,
                reflection_due=reflection_due,
                last_reflection_summary=last_summary,
                system_health=health,
                decisions_this_week=week_decisions,
                outcomes_this_week=week_outcomes,
                consistency_score=consistency,
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: getDomainStatus
    # ------------------------------------------------------------------

    def get_domain_status(self, domain: str) -> DomainStatus:
        """
        Per-domain drill-down.

        Args:
            domain: Life domain to examine (business, finance, health, etc.)

        Returns:
            DomainStatus with decision stats, trends, and blind spots.
        """
        cutoff_90 = (
            datetime.now(timezone.utc) - timedelta(days=90)
        ).isoformat()
        cutoff_30 = (
            datetime.now(timezone.utc) - timedelta(days=30)
        ).isoformat()

        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            decisions = []
            confidences = []
            outcomes_pos = 0
            outcomes_neg = 0
            outcomes_total = 0
            cartridge_counts: Counter = Counter()

            if "Compound_Intelligence_Log" in tables:
                rows = conn.execute(
                    """SELECT decision_id, context, confidence,
                              cartridges_fired, outcome_valence, timestamp
                       FROM Compound_Intelligence_Log
                       WHERE domain = ? AND timestamp >= ?
                       ORDER BY timestamp DESC""",
                    (domain, cutoff_90),
                ).fetchall()

                for row in rows:
                    decisions.append(dict(row))
                    if row["confidence"] is not None:
                        confidences.append(float(row["confidence"]))
                    if row["outcome_valence"] is not None:
                        outcomes_total += 1
                        if row["outcome_valence"] > 0:
                            outcomes_pos += 1
                        elif row["outcome_valence"] < 0:
                            outcomes_neg += 1

                    carts = row["cartridges_fired"]
                    if carts:
                        try:
                            for c in json.loads(carts):
                                cartridge_counts[c] += 1
                        except (json.JSONDecodeError, TypeError):
                            pass

            avg_conf = (
                round(sum(confidences) / len(confidences), 4)
                if confidences else 0.0
            )
            safe_total = max(outcomes_total, 1)

            # Trend: compare last 30 days vs previous 30 days
            trend = self._compute_single_domain_trend(
                conn, tables, domain, cutoff_30
            )

            # Domain-specific blind spots from latest BlindSpot_Log
            domain_blind_spots = []
            if "BlindSpot_Log" in tables:
                row = conn.execute(
                    """SELECT underweighted_domains FROM BlindSpot_Log
                       ORDER BY analysis_date DESC LIMIT 1"""
                ).fetchone()
                if row:
                    try:
                        underweighted = json.loads(row[0])
                        if domain in underweighted:
                            domain_blind_spots.append(
                                f"'{domain}' is underweighted in decision-making"
                            )
                    except (json.JSONDecodeError, TypeError):
                        pass

            return DomainStatus(
                domain=domain,
                decisions_count=len(decisions),
                avg_confidence=avg_conf,
                positive_rate=round(outcomes_pos / safe_total, 4),
                negative_rate=round(outcomes_neg / safe_total, 4),
                top_cartridges=[c for c, _ in cartridge_counts.most_common(5)],
                recent_decisions=decisions[:5],
                trend=trend,
                blind_spots=domain_blind_spots,
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: getAlerts
    # ------------------------------------------------------------------

    def get_alerts(self) -> List[Alert]:
        """
        Active alerts requiring Sovereign attention.

        Aggregates alerts from Audit_Log (errors/criticals) and
        Contradiction_Log (unresolved high-severity contradictions).
        Sorted by severity then timestamp.

        Returns:
            List of Alert objects.
        """
        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            return self._query_alerts(conn, tables)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: getTrajectory
    # ------------------------------------------------------------------

    def get_trajectory(self, days: int = 30) -> TrajectoryMap:
        """
        Domain trajectory over time.

        Computes daily decision counts, outcomes, and confidence
        per domain for the given period.

        Args:
            days: Number of days to analyze (default 30).

        Returns:
            TrajectoryMap with per-domain daily data points.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()

        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            domains_data: Dict[str, List[TrajectoryPoint]] = {}

            if "Compound_Intelligence_Log" in tables:
                rows = conn.execute(
                    """SELECT domain, timestamp, confidence,
                              outcome_valence
                       FROM Compound_Intelligence_Log
                       WHERE timestamp >= ?
                       ORDER BY timestamp ASC""",
                    (cutoff_iso,),
                ).fetchall()

                # Group by domain and date
                daily: Dict[str, Dict[str, dict]] = {}
                for row in rows:
                    domain = row["domain"] or "unknown"
                    ts = str(row["timestamp"])[:10]  # YYYY-MM-DD

                    if domain not in daily:
                        daily[domain] = {}
                    if ts not in daily[domain]:
                        daily[domain][ts] = {
                            "decisions": 0, "pos": 0, "neg": 0,
                            "confidences": [],
                        }

                    daily[domain][ts]["decisions"] += 1
                    if row["confidence"] is not None:
                        daily[domain][ts]["confidences"].append(
                            float(row["confidence"])
                        )
                    if row["outcome_valence"] is not None:
                        if row["outcome_valence"] > 0:
                            daily[domain][ts]["pos"] += 1
                        elif row["outcome_valence"] < 0:
                            daily[domain][ts]["neg"] += 1

                for domain, dates in daily.items():
                    points = []
                    for date_str in sorted(dates.keys()):
                        d = dates[date_str]
                        confs = d["confidences"]
                        avg_c = (
                            round(sum(confs) / len(confs), 4)
                            if confs else 0.0
                        )
                        points.append(TrajectoryPoint(
                            date=date_str,
                            decisions=d["decisions"],
                            positive_outcomes=d["pos"],
                            negative_outcomes=d["neg"],
                            avg_confidence=avg_c,
                        ))
                    domains_data[domain] = points

            # Overall trend from domain trends
            domain_trends = self._compute_domain_trends(conn, tables, days)
            trends_list = list(domain_trends.values())
            if trends_list.count("rising") > len(trends_list) / 2:
                overall = "rising"
            elif trends_list.count("declining") > len(trends_list) / 2:
                overall = "declining"
            else:
                overall = "stable"

            return TrajectoryMap(
                days=days,
                period_start=cutoff_iso,
                period_end=now.isoformat(),
                domains=domains_data,
                overall_trend=overall,
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internal: compound score
    # ------------------------------------------------------------------

    def _get_compound_score(
        self, conn: sqlite3.Connection, tables: set
    ) -> float:
        """Compute compound score from Compound_Intelligence_Log."""
        if "Compound_Intelligence_Log" not in tables:
            return 0.0

        try:
            row = conn.execute(
                """SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN outcome_recorded = 1 THEN 1 ELSE 0 END) as with_out,
                    AVG(confidence) as avg_conf,
                    SUM(CASE WHEN outcome_valence = 1 THEN 1 ELSE 0 END) as positive
                FROM Compound_Intelligence_Log"""
            ).fetchone()

            if not row or row["total"] == 0:
                return 0.0

            total = row["total"]
            with_out = row["with_out"] or 0
            avg_conf = float(row["avg_conf"] or 0)
            positive = row["positive"] or 0

            completeness = with_out / total if total > 0 else 0
            pos_rate = positive / max(with_out, 1)

            score = (
                min(total / 100, 1.0) * 30
                + completeness * 25
                + pos_rate * 25
                + avg_conf * 20
            )
            return round(score, 2)
        except sqlite3.Error:
            return 0.0

    def _get_compound_trend(
        self, conn: sqlite3.Connection, tables: set
    ) -> str:
        """Determine compound score trend (rising/stable/declining)."""
        if "Reflection_Log" not in tables:
            return "stable"

        try:
            rows = conn.execute(
                """SELECT compound_score_at_time FROM Reflection_Log
                   ORDER BY generated_at DESC LIMIT 3"""
            ).fetchall()

            if len(rows) < 2:
                return "stable"

            scores = [float(r[0]) for r in rows]
            # Compare most recent to older
            if scores[0] > scores[-1] * 1.05:
                return "rising"
            elif scores[0] < scores[-1] * 0.95:
                return "declining"
            return "stable"
        except sqlite3.Error:
            return "stable"

    # ------------------------------------------------------------------
    # Internal: alerts
    # ------------------------------------------------------------------

    def _query_alerts(
        self, conn: sqlite3.Connection, tables: set
    ) -> List[Alert]:
        """Aggregate alerts from multiple sources."""
        alerts: List[Alert] = []
        alert_counter = 0

        # From Audit_Log: error/critical events
        if "Audit_Log" in tables:
            cutoff = (
                datetime.now(timezone.utc) - timedelta(days=7)
            ).isoformat()
            try:
                rows = conn.execute(
                    """SELECT id, event_type, module_source, timestamp,
                              severity, event_data
                       FROM Audit_Log
                       WHERE severity IN ('error', 'critical')
                         AND timestamp >= ?
                       ORDER BY timestamp DESC LIMIT 20""",
                    (cutoff,),
                ).fetchall()
                for row in rows:
                    alert_counter += 1
                    data = {}
                    try:
                        data = json.loads(row["event_data"]) if row["event_data"] else {}
                    except (json.JSONDecodeError, TypeError):
                        pass
                    alerts.append(Alert(
                        alert_id=f"AUDIT-{row['id']}",
                        source="audit_trail",
                        alert_type=row["event_type"],
                        severity=row["severity"],
                        message=f"{row['event_type']} in {row['module_source']}",
                        timestamp=row["timestamp"],
                        metadata=data,
                    ))
            except sqlite3.Error:
                pass

        # From Contradiction_Log: unresolved high-severity
        if "Contradiction_Log" in tables:
            try:
                rows = conn.execute(
                    """SELECT id, severity, explanation, detected_at, domain
                       FROM Contradiction_Log
                       WHERE resolution IS NULL
                         AND severity IN ('high', 'critical')
                       ORDER BY detected_at DESC LIMIT 10"""
                ).fetchall()
                for row in rows:
                    alert_counter += 1
                    alerts.append(Alert(
                        alert_id=f"CONTRA-{row['id']}",
                        source="contradiction_detector",
                        alert_type="UNRESOLVED_CONTRADICTION",
                        severity=row["severity"],
                        message=row["explanation"][:200],
                        timestamp=row["detected_at"],
                        metadata={"domain": row["domain"]},
                    ))
            except sqlite3.Error:
                pass

        # Sort by severity then timestamp
        alerts.sort(
            key=lambda a: (
                self._SEVERITY_ORDER.get(a.severity, 99),
                a.timestamp,
            )
        )

        return alerts

    # ------------------------------------------------------------------
    # Internal: trajectories and trends
    # ------------------------------------------------------------------

    def _compute_domain_trends(
        self, conn: sqlite3.Connection, tables: set, days: int
    ) -> Dict[str, str]:
        """Compute trend (rising/stable/declining) per domain."""
        if "Compound_Intelligence_Log" not in tables:
            return {}

        mid = days // 2
        now = datetime.now(timezone.utc)
        cutoff_full = (now - timedelta(days=days)).isoformat()
        cutoff_mid = (now - timedelta(days=mid)).isoformat()

        try:
            # First half counts
            first_half = conn.execute(
                """SELECT domain, COUNT(*) as cnt
                   FROM Compound_Intelligence_Log
                   WHERE timestamp >= ? AND timestamp < ?
                   GROUP BY domain""",
                (cutoff_full, cutoff_mid),
            ).fetchall()
            first = {r["domain"]: r["cnt"] for r in first_half}

            # Second half counts
            second_half = conn.execute(
                """SELECT domain, COUNT(*) as cnt
                   FROM Compound_Intelligence_Log
                   WHERE timestamp >= ?
                   GROUP BY domain""",
                (cutoff_mid,),
            ).fetchall()
            second = {r["domain"]: r["cnt"] for r in second_half}

            all_domains = set(first.keys()) | set(second.keys())
            trends = {}
            for domain in all_domains:
                f = first.get(domain, 0)
                s = second.get(domain, 0)
                if s > f * 1.2:
                    trends[domain] = "rising"
                elif s < f * 0.8:
                    trends[domain] = "declining"
                else:
                    trends[domain] = "stable"

            return trends
        except sqlite3.Error:
            return {}

    def _compute_single_domain_trend(
        self, conn: sqlite3.Connection, tables: set,
        domain: str, cutoff: str,
    ) -> str:
        """Compute trend for a single domain."""
        trends = self._compute_domain_trends(conn, tables, days=60)
        return trends.get(domain, "stable")

    # ------------------------------------------------------------------
    # Internal: cartridges
    # ------------------------------------------------------------------

    def _get_top_cartridges(
        self, conn: sqlite3.Connection, tables: set, days: int
    ) -> List[str]:
        """Get most frequently fired cartridges."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()
        counts: Counter = Counter()

        if "Cartridge_Performance_Log" in tables:
            try:
                rows = conn.execute(
                    """SELECT cartridge_id, COUNT(*) as cnt
                       FROM Cartridge_Performance_Log
                       WHERE timestamp >= ?
                       GROUP BY cartridge_id
                       ORDER BY cnt DESC LIMIT 5""",
                    (cutoff,),
                ).fetchall()
                for r in rows:
                    counts[r["cartridge_id"]] = r["cnt"]
            except sqlite3.Error:
                pass

        if not counts and "Compound_Intelligence_Log" in tables:
            try:
                rows = conn.execute(
                    """SELECT cartridges_fired FROM Compound_Intelligence_Log
                       WHERE timestamp >= ?
                         AND cartridges_fired IS NOT NULL""",
                    (cutoff,),
                ).fetchall()
                for r in rows:
                    try:
                        carts = json.loads(r[0]) if r[0] else []
                        for c in carts:
                            counts[c] += 1
                    except (json.JSONDecodeError, TypeError):
                        pass
            except sqlite3.Error:
                pass

        return [c for c, _ in counts.most_common(5)]

    # ------------------------------------------------------------------
    # Internal: decisions and outcomes
    # ------------------------------------------------------------------

    def _get_pending_decisions(
        self, conn: sqlite3.Connection, tables: set
    ) -> List[Dict[str, Any]]:
        """Get decisions without recorded outcomes."""
        if "Compound_Intelligence_Log" not in tables:
            return []

        try:
            rows = conn.execute(
                """SELECT decision_id, context, domain, confidence, timestamp
                   FROM Compound_Intelligence_Log
                   WHERE outcome_recorded = 0
                   ORDER BY timestamp DESC LIMIT 10"""
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error:
            return []

    def _count_decisions(
        self, conn: sqlite3.Connection, tables: set, days: int
    ) -> int:
        """Count decisions in the given period."""
        if "Compound_Intelligence_Log" not in tables:
            return 0

        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM Compound_Intelligence_Log WHERE timestamp >= ?",
                (cutoff,),
            ).fetchone()
            return row[0] if row else 0
        except sqlite3.Error:
            return 0

    def _count_outcomes(
        self, conn: sqlite3.Connection, tables: set, days: int
    ) -> int:
        """Count outcomes recorded in the given period."""
        if "Compound_Intelligence_Log" not in tables:
            return 0

        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()
        try:
            row = conn.execute(
                """SELECT COUNT(*) FROM Compound_Intelligence_Log
                   WHERE outcome_recorded = 1
                     AND outcome_timestamp >= ?""",
                (cutoff,),
            ).fetchone()
            return row[0] if row else 0
        except sqlite3.Error:
            return 0

    # ------------------------------------------------------------------
    # Internal: blind spots
    # ------------------------------------------------------------------

    def _get_blind_spots(
        self, conn: sqlite3.Connection, tables: set
    ) -> List[str]:
        """Get latest blind spots from BlindSpot_Log."""
        if "BlindSpot_Log" not in tables:
            return []

        try:
            row = conn.execute(
                """SELECT underweighted_domains, avoided_patterns
                   FROM BlindSpot_Log
                   ORDER BY analysis_date DESC LIMIT 1"""
            ).fetchone()
            if not row:
                return []

            spots = []
            try:
                domains = json.loads(row[0]) if row[0] else []
                if domains:
                    spots.append(
                        f"Underweighted domains: {', '.join(domains[:3])}"
                    )
            except (json.JSONDecodeError, TypeError):
                pass

            try:
                patterns = json.loads(row[1]) if row[1] else []
                for p in patterns[:2]:
                    spots.append(str(p)[:100])
            except (json.JSONDecodeError, TypeError):
                pass

            return spots
        except sqlite3.Error:
            return []

    # ------------------------------------------------------------------
    # Internal: reflection status
    # ------------------------------------------------------------------

    def _get_reflection_status(
        self, conn: sqlite3.Connection, tables: set
    ) -> tuple:
        """Check if reflection is due and get last summary."""
        if "Reflection_Log" not in tables:
            return True, "No reflections yet."

        try:
            row = conn.execute(
                """SELECT generated_at, period, recommended_focus
                   FROM Reflection_Log
                   ORDER BY generated_at DESC LIMIT 1"""
            ).fetchone()

            if not row:
                return True, "No reflections yet."

            # Check if weekly reflection is overdue (> 7 days)
            last_at = row["generated_at"]
            try:
                last_dt = datetime.fromisoformat(
                    str(last_at).replace("Z", "+00:00")
                )
                age = datetime.now(timezone.utc) - last_dt
                is_due = age > timedelta(days=7)
            except (ValueError, TypeError):
                is_due = True

            summary = row["recommended_focus"] or "No summary available."
            return is_due, summary
        except sqlite3.Error:
            return True, "No reflections yet."

    # ------------------------------------------------------------------
    # Internal: system health
    # ------------------------------------------------------------------

    def _get_system_health(
        self, conn: sqlite3.Connection, tables: set
    ) -> Dict[str, Any]:
        """Compute system health status."""
        health: Dict[str, Any] = {
            "status": "healthy",
            "tables_present": len(tables),
            "error_count_7d": 0,
            "contradiction_count_7d": 0,
            "audit_events_7d": 0,
            "health_score": 100.0,
        }

        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=7)
        ).isoformat()

        if "Audit_Log" in tables:
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM Audit_Log WHERE timestamp >= ?",
                    (cutoff,),
                ).fetchone()
                health["audit_events_7d"] = row[0] if row else 0

                row = conn.execute(
                    """SELECT COUNT(*) FROM Audit_Log
                       WHERE severity IN ('error', 'critical')
                         AND timestamp >= ?""",
                    (cutoff,),
                ).fetchone()
                health["error_count_7d"] = row[0] if row else 0
            except sqlite3.Error:
                pass

        if "Contradiction_Log" in tables:
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM Contradiction_Log WHERE detected_at >= ?",
                    (cutoff,),
                ).fetchone()
                health["contradiction_count_7d"] = row[0] if row else 0
            except sqlite3.Error:
                pass

        # Health score: deduct for errors and contradictions
        errors = health["error_count_7d"]
        contras = health["contradiction_count_7d"]
        total_events = max(health["audit_events_7d"], 1)
        error_rate = errors / total_events
        score = max(100.0 - (error_rate * 100) - (contras * 2), 0.0)
        health["health_score"] = round(score, 1)

        if score < 50:
            health["status"] = "degraded"
        elif score < 80:
            health["status"] = "warning"

        return health

    # ------------------------------------------------------------------
    # Internal: consistency
    # ------------------------------------------------------------------

    def _get_consistency_score(
        self, conn: sqlite3.Connection, tables: set
    ) -> float:
        """Get consistency score from Contradiction_Log."""
        if "Contradiction_Log" not in tables:
            return 100.0

        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=30)
        ).isoformat()

        try:
            total_row = conn.execute(
                "SELECT COUNT(*) FROM Contradiction_Log WHERE detected_at >= ?",
                (cutoff,),
            ).fetchone()
            total = total_row[0] if total_row else 0

            if total == 0:
                return 100.0

            # Each contradiction reduces score
            decision_row = conn.execute(
                "SELECT COUNT(*) FROM Compound_Intelligence_Log WHERE timestamp >= ?",
                (cutoff,),
            ).fetchone() if "Compound_Intelligence_Log" in tables else None

            decisions = (decision_row[0] if decision_row else 0) or 1
            contra_rate = total / decisions
            score = max(100.0 - (contra_rate * 100), 0.0)
            return round(score, 1)
        except sqlite3.Error:
            return 100.0

    # ------------------------------------------------------------------
    # DB helpers
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
    "SovereignDashboard",
    "DashboardSnapshot",
    "DomainStatus",
    "TrajectoryMap",
    "TrajectoryPoint",
    "Alert",
]
