"""
Tests for aeOS Phase 5 — Sovereign_Dashboard (A9)
===================================================
Tests getSnapshot, getDomainStatus, getAlerts, getTrajectory.
Uses temporary SQLite database — no production data affected.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.screens.sovereign_dashboard import (
    Alert,
    DashboardSnapshot,
    DomainStatus,
    SovereignDashboard,
    TrajectoryMap,
    TrajectoryPoint,
)


class TestSovereignDashboard(unittest.TestCase):
    """Test suite for Sovereign_Dashboard."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_aeos.db")

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS Compound_Intelligence_Log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id TEXT NOT NULL,
                event_type TEXT NOT NULL DEFAULT 'DECISION_MADE',
                timestamp TEXT NOT NULL,
                context TEXT,
                cartridges_fired TEXT DEFAULT '[]',
                cartridge_count INTEGER DEFAULT 0,
                reasoning_summary TEXT,
                confidence REAL DEFAULT 0.0,
                domain TEXT DEFAULT 'unknown',
                session_id TEXT,
                outcome_recorded INTEGER DEFAULT 0,
                outcome_valence INTEGER,
                outcome_magnitude REAL,
                outcome_description TEXT,
                outcome_timestamp TEXT,
                metadata TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS Cartridge_Performance_Log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT DEFAULT 'CARTRIDGE_PERFORMANCE',
                timestamp TEXT NOT NULL,
                cartridge_id TEXT NOT NULL,
                decision_id TEXT,
                relevance_score REAL DEFAULT 0.0,
                was_accepted INTEGER DEFAULT 0,
                domain TEXT DEFAULT 'unknown'
            );

            CREATE TABLE IF NOT EXISTS Audit_Log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                event_data TEXT NOT NULL DEFAULT '{}',
                module_source TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                session_id TEXT,
                severity TEXT NOT NULL DEFAULT 'info'
            );

            CREATE TABLE IF NOT EXISTS Contradiction_Log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                detected_at TEXT NOT NULL,
                new_decision_id TEXT,
                conflicting_decision_id TEXT,
                severity TEXT NOT NULL DEFAULT 'low',
                explanation TEXT NOT NULL,
                resolution TEXT,
                resolution_note TEXT,
                domain TEXT NOT NULL DEFAULT 'unknown',
                resolved_at TEXT
            );

            CREATE TABLE IF NOT EXISTS Reflection_Log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period TEXT NOT NULL DEFAULT 'adhoc',
                report_json TEXT NOT NULL DEFAULT '{}',
                compound_score_at_time REAL NOT NULL DEFAULT 0.0,
                decisions_reviewed INTEGER NOT NULL DEFAULT 0,
                top_patterns TEXT NOT NULL DEFAULT '[]',
                failed_outcomes TEXT NOT NULL DEFAULT '[]',
                cartridges_most_fired TEXT NOT NULL DEFAULT '[]',
                recommended_focus TEXT,
                generated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS BlindSpot_Log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_date TEXT NOT NULL,
                underweighted_domains TEXT NOT NULL DEFAULT '[]',
                avoided_patterns TEXT NOT NULL DEFAULT '[]',
                cartridges_never_fired TEXT NOT NULL DEFAULT '[]',
                suggested_focus TEXT NOT NULL DEFAULT '[]',
                acknowledged INTEGER NOT NULL DEFAULT 0
            );
        """)
        conn.commit()
        conn.close()

        self.dashboard = SovereignDashboard(db_path=self.db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _seed_decisions(self, count=10, days_spread=5):
        """Seed Compound_Intelligence_Log with test decisions."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc)
        domains = ["business", "finance", "health", "career"]
        for i in range(count):
            ts = (now - timedelta(days=i % days_spread, hours=i)).isoformat()
            domain = domains[i % len(domains)]
            valence = 1 if i % 3 == 0 else (-1 if i % 3 == 1 else 0)
            out_ts = ts if valence is not None else None
            carts = json.dumps(["negotiation", "systems-thinking"][:((i % 2) + 1)])
            conn.execute(
                """INSERT INTO Compound_Intelligence_Log
                (decision_id, timestamp, context, domain, confidence,
                 cartridges_fired, cartridge_count,
                 outcome_recorded, outcome_valence, outcome_magnitude,
                 outcome_timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"DEC-{i:03d}", ts,
                    f"Decision about {domain} #{i}", domain,
                    0.5 + (i % 5) * 0.1,
                    carts, (i % 2) + 1,
                    1, valence, 0.6,
                    out_ts,
                ),
            )
        conn.commit()
        conn.close()

    def _seed_alerts(self, count=3):
        """Seed Audit_Log with error events."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc)
        for i in range(count):
            ts = (now - timedelta(hours=i)).isoformat()
            severity = "critical" if i == 0 else "error"
            conn.execute(
                """INSERT INTO Audit_Log
                (event_type, event_data, module_source, timestamp, severity)
                VALUES (?, '{}', 'test_module', ?, ?)""",
                (f"ERROR_{i}", ts, severity),
            )
        conn.commit()
        conn.close()

    def _seed_contradictions(self, count=2):
        """Seed Contradiction_Log with unresolved contradictions."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc)
        for i in range(count):
            ts = (now - timedelta(hours=i)).isoformat()
            conn.execute(
                """INSERT INTO Contradiction_Log
                (detected_at, severity, explanation, domain)
                VALUES (?, 'high', ?, 'business')""",
                (ts, f"Contradiction #{i}: conflicting strategy"),
            )
        conn.commit()
        conn.close()

    def _seed_reflection(self, days_ago=2):
        """Seed Reflection_Log with a recent reflection."""
        conn = sqlite3.connect(self.db_path)
        ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        conn.execute(
            """INSERT INTO Reflection_Log
            (period, report_json, compound_score_at_time, decisions_reviewed,
             recommended_focus, generated_at)
            VALUES ('weekly', '{}', 45.0, 10, 'Focus on finance domain.', ?)""",
            (ts,),
        )
        conn.commit()
        conn.close()

    def _seed_blind_spots(self):
        """Seed BlindSpot_Log."""
        conn = sqlite3.connect(self.db_path)
        ts = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO BlindSpot_Log
            (analysis_date, underweighted_domains, avoided_patterns)
            VALUES (?, '["relationships", "creative"]',
                    '["Domain avoidance: relationships, creative"]')""",
            (ts,),
        )
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # getSnapshot tests
    # ------------------------------------------------------------------

    def test_get_snapshot_returns_dashboard_snapshot(self):
        """getSnapshot() returns a DashboardSnapshot."""
        snapshot = self.dashboard.get_snapshot()
        self.assertIsInstance(snapshot, DashboardSnapshot)

    def test_get_snapshot_empty_db(self):
        """Empty database returns valid snapshot with defaults."""
        snapshot = self.dashboard.get_snapshot()
        self.assertEqual(snapshot.compound_score, 0.0)
        self.assertEqual(snapshot.decisions_this_week, 0)
        self.assertEqual(snapshot.outcomes_this_week, 0)
        self.assertEqual(snapshot.active_alerts, [])
        self.assertIsNotNone(snapshot.generated_at)

    def test_get_snapshot_with_decisions(self):
        """Snapshot reflects seeded decisions."""
        self._seed_decisions(20, days_spread=5)
        snapshot = self.dashboard.get_snapshot()
        self.assertGreater(snapshot.compound_score, 0)
        self.assertGreater(snapshot.decisions_this_week, 0)
        self.assertGreater(len(snapshot.trajectory_30day), 0)
        self.assertGreater(len(snapshot.top_cartridges_firing), 0)

    def test_get_snapshot_with_alerts(self):
        """Snapshot includes active alerts."""
        self._seed_alerts(3)
        snapshot = self.dashboard.get_snapshot()
        self.assertEqual(len(snapshot.active_alerts), 3)
        # Critical should be first
        self.assertEqual(snapshot.active_alerts[0].severity, "critical")

    def test_get_snapshot_with_contradictions(self):
        """Snapshot includes unresolved contradictions as alerts."""
        self._seed_contradictions(2)
        snapshot = self.dashboard.get_snapshot()
        contra_alerts = [
            a for a in snapshot.active_alerts
            if a.source == "contradiction_detector"
        ]
        self.assertEqual(len(contra_alerts), 2)

    def test_get_snapshot_compound_trend(self):
        """Compound trend is one of rising/stable/declining."""
        snapshot = self.dashboard.get_snapshot()
        self.assertIn(snapshot.compound_trend, ("rising", "stable", "declining"))

    def test_get_snapshot_reflection_due(self):
        """Reflection is due when no recent reflections exist."""
        snapshot = self.dashboard.get_snapshot()
        self.assertTrue(snapshot.reflection_due)

    def test_get_snapshot_reflection_not_due(self):
        """Reflection not due when recent reflection exists."""
        self._seed_reflection(days_ago=2)
        snapshot = self.dashboard.get_snapshot()
        self.assertFalse(snapshot.reflection_due)

    def test_get_snapshot_blind_spots(self):
        """Snapshot includes blind spots from latest analysis."""
        self._seed_blind_spots()
        snapshot = self.dashboard.get_snapshot()
        self.assertGreater(len(snapshot.blind_spots), 0)

    def test_get_snapshot_consistency_score(self):
        """Consistency score is between 0 and 100."""
        snapshot = self.dashboard.get_snapshot()
        self.assertGreaterEqual(snapshot.consistency_score, 0.0)
        self.assertLessEqual(snapshot.consistency_score, 100.0)

    def test_get_snapshot_system_health(self):
        """System health includes health_score and status."""
        snapshot = self.dashboard.get_snapshot()
        self.assertIn("health_score", snapshot.system_health)
        self.assertIn("status", snapshot.system_health)

    def test_get_snapshot_pending_decisions(self):
        """Snapshot shows pending decisions without outcomes."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO Compound_Intelligence_Log
            (decision_id, timestamp, context, domain, confidence,
             outcome_recorded)
            VALUES ('PEND-001', ?, 'Pending decision', 'business', 0.7, 0)""",
            (now,),
        )
        conn.commit()
        conn.close()

        snapshot = self.dashboard.get_snapshot()
        self.assertGreater(len(snapshot.pending_decisions), 0)

    # ------------------------------------------------------------------
    # getDomainStatus tests
    # ------------------------------------------------------------------

    def test_get_domain_status_returns_domain_status(self):
        """getDomainStatus() returns a DomainStatus."""
        status = self.dashboard.get_domain_status("business")
        self.assertIsInstance(status, DomainStatus)
        self.assertEqual(status.domain, "business")

    def test_get_domain_status_empty_db(self):
        """Empty database returns zero-count status."""
        status = self.dashboard.get_domain_status("business")
        self.assertEqual(status.decisions_count, 0)
        self.assertEqual(status.avg_confidence, 0.0)

    def test_get_domain_status_with_data(self):
        """Domain status reflects domain-specific data."""
        self._seed_decisions(20, days_spread=30)
        status = self.dashboard.get_domain_status("business")
        self.assertGreater(status.decisions_count, 0)
        self.assertGreater(status.avg_confidence, 0)

    def test_get_domain_status_trend(self):
        """Domain status includes a trend."""
        status = self.dashboard.get_domain_status("business")
        self.assertIn(status.trend, ("rising", "stable", "declining"))

    def test_get_domain_status_top_cartridges(self):
        """Domain status includes top cartridges."""
        self._seed_decisions(20, days_spread=30)
        status = self.dashboard.get_domain_status("business")
        self.assertIsInstance(status.top_cartridges, list)

    def test_get_domain_status_recent_decisions(self):
        """Domain status includes recent decisions."""
        self._seed_decisions(20, days_spread=30)
        status = self.dashboard.get_domain_status("business")
        self.assertIsInstance(status.recent_decisions, list)
        self.assertLessEqual(len(status.recent_decisions), 5)

    def test_get_domain_status_blind_spots(self):
        """Domain status includes domain-specific blind spots."""
        self._seed_blind_spots()
        status = self.dashboard.get_domain_status("relationships")
        self.assertGreater(len(status.blind_spots), 0)

    # ------------------------------------------------------------------
    # getAlerts tests
    # ------------------------------------------------------------------

    def test_get_alerts_returns_list(self):
        """getAlerts() returns a list."""
        alerts = self.dashboard.get_alerts()
        self.assertIsInstance(alerts, list)

    def test_get_alerts_empty_db(self):
        """Empty database returns no alerts."""
        alerts = self.dashboard.get_alerts()
        self.assertEqual(len(alerts), 0)

    def test_get_alerts_from_audit_log(self):
        """Alerts include error/critical events from Audit_Log."""
        self._seed_alerts(3)
        alerts = self.dashboard.get_alerts()
        self.assertEqual(len(alerts), 3)
        self.assertIsInstance(alerts[0], Alert)

    def test_get_alerts_from_contradiction_log(self):
        """Alerts include unresolved contradictions."""
        self._seed_contradictions(2)
        alerts = self.dashboard.get_alerts()
        contra = [a for a in alerts if a.source == "contradiction_detector"]
        self.assertEqual(len(contra), 2)

    def test_get_alerts_sorted_by_severity(self):
        """Alerts are sorted by severity (critical first)."""
        self._seed_alerts(3)
        alerts = self.dashboard.get_alerts()
        severities = [a.severity for a in alerts]
        self.assertEqual(severities[0], "critical")

    def test_get_alerts_mixed_sources(self):
        """Alerts from multiple sources are combined."""
        self._seed_alerts(2)
        self._seed_contradictions(1)
        alerts = self.dashboard.get_alerts()
        self.assertEqual(len(alerts), 3)
        sources = {a.source for a in alerts}
        self.assertEqual(sources, {"audit_trail", "contradiction_detector"})

    def test_alert_has_required_fields(self):
        """Alert objects have all required fields."""
        self._seed_alerts(1)
        alert = self.dashboard.get_alerts()[0]
        self.assertIsNotNone(alert.alert_id)
        self.assertIsNotNone(alert.source)
        self.assertIsNotNone(alert.severity)
        self.assertIsNotNone(alert.message)
        self.assertIsNotNone(alert.timestamp)

    # ------------------------------------------------------------------
    # getTrajectory tests
    # ------------------------------------------------------------------

    def test_get_trajectory_returns_trajectory_map(self):
        """getTrajectory() returns a TrajectoryMap."""
        traj = self.dashboard.get_trajectory()
        self.assertIsInstance(traj, TrajectoryMap)

    def test_get_trajectory_empty_db(self):
        """Empty database returns empty trajectory."""
        traj = self.dashboard.get_trajectory()
        self.assertEqual(traj.domains, {})
        self.assertEqual(traj.days, 30)

    def test_get_trajectory_with_data(self):
        """Trajectory includes domain data points."""
        self._seed_decisions(20, days_spread=15)
        traj = self.dashboard.get_trajectory(days=30)
        self.assertGreater(len(traj.domains), 0)
        self.assertIn("business", traj.domains)

    def test_get_trajectory_points_have_data(self):
        """Trajectory points have required fields."""
        self._seed_decisions(20, days_spread=15)
        traj = self.dashboard.get_trajectory(days=30)
        for domain, points in traj.domains.items():
            for p in points:
                self.assertIsInstance(p, TrajectoryPoint)
                self.assertIsNotNone(p.date)
                self.assertGreaterEqual(p.decisions, 0)

    def test_get_trajectory_overall_trend(self):
        """Trajectory includes overall trend."""
        traj = self.dashboard.get_trajectory()
        self.assertIn(traj.overall_trend, ("rising", "stable", "declining"))

    def test_get_trajectory_custom_days(self):
        """Trajectory respects custom days parameter."""
        traj = self.dashboard.get_trajectory(days=7)
        self.assertEqual(traj.days, 7)

    # ------------------------------------------------------------------
    # Data class tests
    # ------------------------------------------------------------------

    def test_dashboard_snapshot_to_dict(self):
        """DashboardSnapshot.to_dict() returns a dict."""
        snapshot = self.dashboard.get_snapshot()
        d = snapshot.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("compound_score", d)
        self.assertIn("active_alerts", d)
        self.assertIn("system_health", d)

    def test_domain_status_to_dict(self):
        """DomainStatus.to_dict() returns a dict."""
        status = self.dashboard.get_domain_status("business")
        d = status.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("domain", d)
        self.assertIn("trend", d)

    def test_trajectory_map_to_dict(self):
        """TrajectoryMap.to_dict() returns a dict."""
        traj = self.dashboard.get_trajectory()
        d = traj.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("days", d)
        self.assertIn("overall_trend", d)

    def test_alert_to_dict(self):
        """Alert.to_dict() returns a dict."""
        alert = Alert(
            alert_id="TEST-1",
            source="test",
            alert_type="TEST",
            severity="low",
            message="Test alert",
            timestamp="2026-03-01T00:00:00",
        )
        d = alert.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("alert_id", d)
        self.assertIn("severity", d)


if __name__ == "__main__":
    unittest.main()
