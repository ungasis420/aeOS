"""
Tests for aeOS Phase 4 — Audit_Trail (A6)
============================================
Tests generateReport, exportCSV, exportJSON, getTimeline, log_event.
Uses temporary SQLite database — no production data affected.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.audit_trail import (
    AuditReport,
    AuditTrail,
    TimelineEvent,
)


class TestAuditTrail(unittest.TestCase):
    """Test suite for Audit_Trail."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_aeos.db")
        self.export_dir = os.path.join(self.tmp_dir, "exports")

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript("""
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
        """)
        conn.commit()
        conn.close()

        self.audit = AuditTrail(db_path=self.db_path, export_dir=self.export_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _seed_events(self, count=10):
        """Seed the Audit_Log with test events."""
        conn = sqlite3.connect(self.db_path)
        for i in range(count):
            severity = "info" if i % 3 != 0 else "error"
            event_type = "DECISION_MADE" if i % 2 == 0 else "API_CALL"
            module = "decision_engine" if i % 2 == 0 else "smart_router"
            conn.execute(
                """INSERT INTO Audit_Log
                (event_type, event_data, module_source, timestamp, severity)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    event_type,
                    json.dumps({"test": True, "index": i}),
                    module,
                    f"2026-03-01T{i:02d}:00:00+00:00",
                    severity,
                ),
            )
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # log_event tests
    # ------------------------------------------------------------------

    def test_log_event_inserts_to_db(self):
        """log_event() inserts an event into Audit_Log."""
        self.audit.log_event(
            event_type="TEST_EVENT",
            module_source="test_module",
            event_data={"key": "value"},
            severity="info",
        )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM Audit_Log").fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_type"], "TEST_EVENT")
        self.assertEqual(rows[0]["module_source"], "test_module")

    def test_log_event_with_session_id(self):
        """log_event() stores session_id."""
        self.audit.log_event(
            event_type="TEST",
            module_source="test",
            session_id="sess-123",
        )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM Audit_Log").fetchone()
        conn.close()
        self.assertEqual(row["session_id"], "sess-123")

    def test_log_event_invalid_severity_defaults_to_info(self):
        """Invalid severity defaults to 'info'."""
        self.audit.log_event(
            event_type="TEST",
            module_source="test",
            severity="invalid_severity",
        )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM Audit_Log").fetchone()
        conn.close()
        self.assertEqual(row["severity"], "info")

    def test_log_event_serializes_event_data(self):
        """Event data is serialized as JSON."""
        self.audit.log_event(
            event_type="TEST",
            module_source="test",
            event_data={"nested": {"value": 42}},
        )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM Audit_Log").fetchone()
        conn.close()
        data = json.loads(row["event_data"])
        self.assertEqual(data["nested"]["value"], 42)

    # ------------------------------------------------------------------
    # generateReport tests
    # ------------------------------------------------------------------

    def test_generate_report_returns_audit_report(self):
        """generateReport() returns an AuditReport."""
        report = self.audit.generate_report(days=30)
        self.assertIsInstance(report, AuditReport)

    def test_generate_report_empty_db(self):
        """Empty database returns zero-count report."""
        report = self.audit.generate_report(days=30)
        self.assertEqual(report.total_events, 0)
        self.assertEqual(report.days, 30)
        self.assertIsNotNone(report.period_start)
        self.assertIsNotNone(report.period_end)

    def test_generate_report_with_events(self):
        """Report reflects seeded events."""
        self._seed_events(10)
        report = self.audit.generate_report(days=30)
        self.assertEqual(report.total_events, 10)
        self.assertIn("DECISION_MADE", report.events_by_type)
        self.assertIn("API_CALL", report.events_by_type)

    def test_generate_report_events_by_module(self):
        """Report includes events_by_module breakdown."""
        self._seed_events(10)
        report = self.audit.generate_report(days=30)
        self.assertIn("decision_engine", report.events_by_module)
        self.assertIn("smart_router", report.events_by_module)

    def test_generate_report_events_by_severity(self):
        """Report includes events_by_severity breakdown."""
        self._seed_events(10)
        report = self.audit.generate_report(days=30)
        self.assertIn("info", report.events_by_severity)
        self.assertIn("error", report.events_by_severity)

    def test_generate_report_decisions_count(self):
        """Report counts DECISION_MADE events."""
        self._seed_events(10)
        report = self.audit.generate_report(days=30)
        self.assertGreater(report.decisions_logged, 0)

    def test_generate_report_health_score(self):
        """Report computes system health score."""
        self._seed_events(10)
        report = self.audit.generate_report(days=30)
        self.assertGreaterEqual(report.system_health_score, 0.0)
        self.assertLessEqual(report.system_health_score, 100.0)

    def test_generate_report_health_score_perfect(self):
        """No errors = 100.0 health score."""
        # Seed only info events
        conn = sqlite3.connect(self.db_path)
        for i in range(5):
            conn.execute(
                """INSERT INTO Audit_Log
                (event_type, event_data, module_source, timestamp, severity)
                VALUES (?, '{}', 'test', ?, 'info')""",
                (f"EVENT_{i}", f"2026-03-01T{i:02d}:00:00+00:00"),
            )
        conn.commit()
        conn.close()
        report = self.audit.generate_report(days=30)
        self.assertEqual(report.system_health_score, 100.0)

    def test_generate_report_contradictions_count(self):
        """Report includes contradiction count from Contradiction_Log."""
        # Seed a contradiction
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT INTO Contradiction_Log
            (detected_at, severity, explanation, domain)
            VALUES ('2026-03-01T00:00:00+00:00', 'high', 'Test contradiction', 'business')"""
        )
        conn.commit()
        conn.close()
        report = self.audit.generate_report(days=30)
        self.assertEqual(report.contradictions_detected, 1)

    # ------------------------------------------------------------------
    # getTimeline tests
    # ------------------------------------------------------------------

    def test_get_timeline_returns_list(self):
        """getTimeline() returns a list."""
        timeline = self.audit.get_timeline(days=30)
        self.assertIsInstance(timeline, list)

    def test_get_timeline_empty_db(self):
        """Empty database returns empty timeline."""
        timeline = self.audit.get_timeline(days=30)
        self.assertEqual(len(timeline), 0)

    def test_get_timeline_with_events(self):
        """Timeline includes seeded events."""
        self._seed_events(5)
        timeline = self.audit.get_timeline(days=30)
        self.assertEqual(len(timeline), 5)
        self.assertIsInstance(timeline[0], TimelineEvent)

    def test_get_timeline_newest_first(self):
        """Timeline is ordered newest first."""
        self._seed_events(5)
        timeline = self.audit.get_timeline(days=30)
        for i in range(len(timeline) - 1):
            self.assertGreaterEqual(timeline[i].timestamp, timeline[i + 1].timestamp)

    def test_get_timeline_filter_by_event_type(self):
        """getTimeline() filters by event_type."""
        self._seed_events(10)
        timeline = self.audit.get_timeline(days=30, event_type="DECISION_MADE")
        self.assertTrue(all(e.event_type == "DECISION_MADE" for e in timeline))

    def test_get_timeline_filter_by_module(self):
        """getTimeline() filters by module_source."""
        self._seed_events(10)
        timeline = self.audit.get_timeline(days=30, module_source="smart_router")
        self.assertTrue(all(e.module_source == "smart_router" for e in timeline))

    def test_get_timeline_limit(self):
        """getTimeline() respects limit parameter."""
        self._seed_events(20)
        timeline = self.audit.get_timeline(days=30, limit=5)
        self.assertEqual(len(timeline), 5)

    def test_get_timeline_event_has_data(self):
        """Timeline events have deserialized event_data."""
        self._seed_events(1)
        timeline = self.audit.get_timeline(days=30)
        self.assertIsInstance(timeline[0].event_data, dict)

    # ------------------------------------------------------------------
    # exportCSV tests
    # ------------------------------------------------------------------

    def test_export_csv_creates_file(self):
        """exportCSV() creates a CSV file."""
        self._seed_events(5)
        filepath = self.audit.export_csv(days=30)
        self.assertTrue(os.path.exists(filepath))
        self.assertTrue(filepath.endswith(".csv"))

    def test_export_csv_content(self):
        """Exported CSV has header and data rows."""
        self._seed_events(5)
        filepath = self.audit.export_csv(days=30)
        with open(filepath, "r") as f:
            lines = f.readlines()
        # Header + 5 data rows
        self.assertEqual(len(lines), 6)
        self.assertIn("timestamp", lines[0])
        self.assertIn("event_type", lines[0])

    def test_export_csv_empty_db(self):
        """CSV export with no events creates file with header only."""
        filepath = self.audit.export_csv(days=30)
        self.assertTrue(os.path.exists(filepath))
        with open(filepath, "r") as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 1)  # Header only

    # ------------------------------------------------------------------
    # exportJSON tests
    # ------------------------------------------------------------------

    def test_export_json_creates_file(self):
        """exportJSON() creates a JSON file."""
        self._seed_events(5)
        filepath = self.audit.export_json(days=30)
        self.assertTrue(os.path.exists(filepath))
        self.assertTrue(filepath.endswith(".json"))

    def test_export_json_content(self):
        """Exported JSON has expected structure."""
        self._seed_events(5)
        filepath = self.audit.export_json(days=30)
        with open(filepath, "r") as f:
            data = json.load(f)
        self.assertIn("exported_at", data)
        self.assertIn("days", data)
        self.assertIn("total_events", data)
        self.assertIn("events", data)
        self.assertEqual(data["total_events"], 5)
        self.assertEqual(len(data["events"]), 5)

    def test_export_json_empty_db(self):
        """JSON export with no events creates valid file."""
        filepath = self.audit.export_json(days=30)
        with open(filepath, "r") as f:
            data = json.load(f)
        self.assertEqual(data["total_events"], 0)
        self.assertEqual(len(data["events"]), 0)

    # ------------------------------------------------------------------
    # Data class tests
    # ------------------------------------------------------------------

    def test_audit_report_to_dict(self):
        """AuditReport.to_dict() returns a dict."""
        report = self.audit.generate_report(days=30)
        d = report.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("total_events", d)
        self.assertIn("system_health_score", d)
        self.assertIn("period_start", d)

    def test_timeline_event_to_dict(self):
        """TimelineEvent.to_dict() returns a dict."""
        event = TimelineEvent(
            event_type="TEST",
            module_source="test",
            timestamp="2026-03-01T00:00:00",
        )
        d = event.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("event_type", d)
        self.assertIn("severity", d)

    def test_timeline_event_defaults(self):
        """TimelineEvent has correct defaults."""
        event = TimelineEvent(
            event_type="TEST",
            module_source="test",
            timestamp="2026-03-01T00:00:00",
        )
        self.assertEqual(event.severity, "info")
        self.assertEqual(event.event_data, {})
        self.assertIsNone(event.session_id)


if __name__ == "__main__":
    unittest.main()
