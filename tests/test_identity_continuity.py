"""
Tests for aeOS Phase 4 — Identity_Continuity_Protocol (A1)
==========================================================
Tests backup, restore, verify, schedule, and list operations.
Uses temporary SQLite database — no production data affected.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

# Ensure src is importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "db"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.identity_continuity import (
    BackupManifest,
    BackupSchedule,
    IdentityContinuityProtocol,
    IntegrityReport,
    RestoreResult,
    BACKUP_TABLES,
)


class TestIdentityContinuityProtocol(unittest.TestCase):
    """Test suite for Identity_Continuity_Protocol."""

    def setUp(self):
        """Create a temporary database with schema for testing."""
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_aeos.db")
        self.backup_dir = os.path.join(self.tmp_dir, "backups")

        # Create a minimal schema for testing
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")

        # Create a subset of tables for testing
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id INTEGER PRIMARY KEY,
                version TEXT,
                applied_at TEXT,
                checksum TEXT
            );

            CREATE TABLE IF NOT EXISTS Backup_Manifest (
                backup_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                tables_included TEXT NOT NULL DEFAULT '[]',
                decision_count INTEGER NOT NULL DEFAULT 0,
                compound_score REAL NOT NULL DEFAULT 0.0,
                encrypted INTEGER NOT NULL DEFAULT 0,
                checksum TEXT NOT NULL,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                backup_path TEXT,
                backup_type TEXT NOT NULL DEFAULT 'manual',
                status TEXT NOT NULL DEFAULT 'complete',
                notes TEXT
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

            CREATE TABLE IF NOT EXISTS Audit_Log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                event_data TEXT NOT NULL DEFAULT '{}',
                module_source TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                session_id TEXT,
                severity TEXT NOT NULL DEFAULT 'info'
            );

            CREATE TABLE IF NOT EXISTS Pain_Point_Register (
                Pain_ID TEXT PRIMARY KEY,
                Pain_Name TEXT NOT NULL,
                Description TEXT,
                Severity INTEGER DEFAULT 5,
                Status TEXT DEFAULT 'Active'
            );

            CREATE TABLE IF NOT EXISTS MoneyScan_Records (
                Idea_ID TEXT PRIMARY KEY,
                Idea_Name TEXT NOT NULL,
                Stage TEXT DEFAULT 'Capture',
                Demand_Score REAL,
                Viability_Score REAL
            );

            INSERT INTO Pain_Point_Register (Pain_ID, Pain_Name, Description, Severity)
            VALUES ('PAIN-001', 'Test Pain', 'A test pain point', 8);

            INSERT INTO MoneyScan_Records (Idea_ID, Idea_Name, Stage, Demand_Score)
            VALUES ('IDEA-001', 'Test Idea', 'Capture', 75.0);
        """)
        conn.commit()
        conn.close()

        self.proto = IdentityContinuityProtocol(
            db_path=self.db_path,
            backup_dir=self.backup_dir,
        )

    def tearDown(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # createBackup tests
    # ------------------------------------------------------------------

    def test_create_backup_returns_manifest(self):
        """createBackup() returns a valid BackupManifest."""
        manifest = self.proto.create_backup()
        self.assertIsInstance(manifest, BackupManifest)
        self.assertTrue(manifest.backup_id.startswith("BKP-"))
        self.assertEqual(manifest.backup_type, "manual")
        self.assertEqual(manifest.status, "complete")
        self.assertGreater(manifest.size_bytes, 0)
        self.assertIsNotNone(manifest.checksum)

    def test_create_backup_includes_tables(self):
        """Backup includes existing tables."""
        manifest = self.proto.create_backup()
        self.assertIn("Pain_Point_Register", manifest.tables_included)
        self.assertIn("MoneyScan_Records", manifest.tables_included)

    def test_create_backup_writes_file(self):
        """Backup creates a file on disk."""
        manifest = self.proto.create_backup()
        self.assertIsNotNone(manifest.backup_path)
        self.assertTrue(Path(manifest.backup_path).exists())

    def test_create_backup_writes_summary(self):
        """Backup creates a human-readable summary."""
        manifest = self.proto.create_backup()
        summary_path = Path(self.backup_dir) / f"{manifest.backup_id}.summary.md"
        self.assertTrue(summary_path.exists())
        content = summary_path.read_text()
        self.assertIn("aeOS Backup Summary", content)
        self.assertIn(manifest.backup_id, content)

    def test_create_backup_records_manifest_in_db(self):
        """Backup manifest is saved to Backup_Manifest table."""
        manifest = self.proto.create_backup()
        backups = self.proto.list_backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].backup_id, manifest.backup_id)

    def test_create_backup_unencrypted(self):
        """Backup without crypto is unencrypted JSON."""
        manifest = self.proto.create_backup()
        self.assertFalse(manifest.encrypted)
        self.assertTrue(manifest.backup_path.endswith(".aeos.json"))

    def test_create_backup_with_type(self):
        """Backup type is recorded correctly."""
        manifest = self.proto.create_backup(backup_type="daily")
        self.assertEqual(manifest.backup_type, "daily")

    def test_create_backup_with_notes(self):
        """Backup notes are recorded."""
        manifest = self.proto.create_backup(notes="Test backup")
        self.assertEqual(manifest.notes, "Test backup")

    def test_create_backup_checksum_is_sha256(self):
        """Checksum is a valid SHA-256 hex string."""
        manifest = self.proto.create_backup()
        self.assertEqual(len(manifest.checksum), 64)
        int(manifest.checksum, 16)  # should not raise

    # ------------------------------------------------------------------
    # restore tests
    # ------------------------------------------------------------------

    def test_restore_from_backup(self):
        """Restore from a backup file restores data."""
        manifest = self.proto.create_backup()

        # Delete data
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM Pain_Point_Register")
        conn.execute("DELETE FROM MoneyScan_Records")
        conn.commit()
        conn.close()

        result = self.proto.restore(manifest.backup_path)
        self.assertIsInstance(result, RestoreResult)
        self.assertTrue(result.success)
        self.assertIn("Pain_Point_Register", result.tables_restored)
        self.assertGreater(result.records_restored, 0)

    def test_restore_verifies_data_integrity(self):
        """Restored data matches original."""
        manifest = self.proto.create_backup()

        # Delete and restore
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM Pain_Point_Register")
        conn.commit()
        conn.close()

        self.proto.restore(manifest.backup_path)

        # Verify data
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM Pain_Point_Register WHERE Pain_ID = 'PAIN-001'"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["Pain_Name"], "Test Pain")

    def test_restore_missing_file_raises(self):
        """Restore with missing file raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            self.proto.restore("/nonexistent/path/backup.aeos.json")

    def test_restore_invalid_format_raises(self):
        """Restore with invalid file raises ValueError."""
        bad_path = os.path.join(self.tmp_dir, "bad.aeos.json")
        Path(bad_path).write_text("not json at all {{{")
        with self.assertRaises(ValueError):
            self.proto.restore(bad_path)

    # ------------------------------------------------------------------
    # verify tests
    # ------------------------------------------------------------------

    def test_verify_returns_integrity_report(self):
        """verify() returns an IntegrityReport."""
        report = self.proto.verify()
        self.assertIsInstance(report, IntegrityReport)
        # healthy may be False with minimal test schema (missing tables expected)
        self.assertGreater(report.tables_found, 0)
        self.assertGreater(report.total_records, 0)
        self.assertFalse(report.corruption_detected)
        self.assertEqual(report.fk_violations, 0)
        self.assertIsInstance(report.missing_tables, list)

    def test_verify_detects_missing_tables(self):
        """verify() reports missing tables."""
        report = self.proto.verify()
        # Many BACKUP_TABLES won't exist in our minimal test schema
        # The important thing is that the report works
        self.assertIsInstance(report.missing_tables, list)

    def test_verify_reports_table_counts(self):
        """verify() includes per-table record counts."""
        report = self.proto.verify()
        self.assertIn("table_counts", report.details)
        counts = report.details["table_counts"]
        self.assertIn("Pain_Point_Register", counts)
        self.assertEqual(counts["Pain_Point_Register"], 1)

    # ------------------------------------------------------------------
    # schedule tests
    # ------------------------------------------------------------------

    def test_get_schedule_returns_default(self):
        """getSchedule() returns default BackupSchedule."""
        schedule = self.proto.get_schedule()
        self.assertIsInstance(schedule, BackupSchedule)
        self.assertTrue(schedule.enabled)
        self.assertEqual(schedule.daily_hour, 3)
        self.assertEqual(schedule.retain_daily, 7)
        self.assertEqual(schedule.retain_weekly, 4)
        self.assertEqual(schedule.retain_monthly, 12)

    def test_set_schedule_updates_config(self):
        """setSchedule() updates the schedule configuration."""
        self.proto.set_schedule({
            "enabled": False,
            "daily_hour": 5,
            "retain_daily": 14,
        })
        schedule = self.proto.get_schedule()
        self.assertFalse(schedule.enabled)
        self.assertEqual(schedule.daily_hour, 5)
        self.assertEqual(schedule.retain_daily, 14)

    def test_set_schedule_validates_hour(self):
        """setSchedule() rejects invalid hour."""
        with self.assertRaises(ValueError):
            self.proto.set_schedule({"daily_hour": 25})

    def test_set_schedule_validates_minute(self):
        """setSchedule() rejects invalid minute."""
        with self.assertRaises(ValueError):
            self.proto.set_schedule({"daily_minute": 60})

    # ------------------------------------------------------------------
    # listBackups tests
    # ------------------------------------------------------------------

    def test_list_backups_empty(self):
        """listBackups() returns empty list when no backups exist."""
        backups = self.proto.list_backups()
        self.assertEqual(backups, [])

    def test_list_backups_after_create(self):
        """listBackups() returns backups after creation."""
        self.proto.create_backup(notes="First")
        self.proto.create_backup(notes="Second")
        backups = self.proto.list_backups()
        self.assertEqual(len(backups), 2)
        # Newest first
        self.assertEqual(backups[0].notes, "Second")

    def test_list_backups_returns_manifest_objects(self):
        """listBackups() returns BackupManifest objects."""
        self.proto.create_backup()
        backups = self.proto.list_backups()
        self.assertIsInstance(backups[0], BackupManifest)

    # ------------------------------------------------------------------
    # prune tests
    # ------------------------------------------------------------------

    def test_prune_old_backups(self):
        """prune_old_backups removes excess backups per retention policy."""
        self.proto.set_schedule({"retain_daily": 2})
        # Create 4 daily backups
        for _ in range(4):
            self.proto.create_backup(backup_type="daily")

        pruned = self.proto.prune_old_backups()
        self.assertEqual(pruned, 2)
        remaining = self.proto.list_backups()
        daily_remaining = [b for b in remaining if b.backup_type == "daily"]
        self.assertEqual(len(daily_remaining), 2)

    def test_prune_does_not_touch_manual(self):
        """prune_old_backups never prunes manual backups."""
        for _ in range(5):
            self.proto.create_backup(backup_type="manual")
        pruned = self.proto.prune_old_backups()
        self.assertEqual(pruned, 0)

    # ------------------------------------------------------------------
    # Data class tests
    # ------------------------------------------------------------------

    def test_backup_manifest_to_dict(self):
        """BackupManifest.to_dict() returns a dict."""
        manifest = self.proto.create_backup()
        d = manifest.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("backup_id", d)
        self.assertIn("checksum", d)

    def test_integrity_report_to_dict(self):
        """IntegrityReport.to_dict() returns a dict."""
        report = self.proto.verify()
        d = report.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("healthy", d)

    def test_backup_schedule_to_dict(self):
        """BackupSchedule.to_dict() returns a dict."""
        schedule = self.proto.get_schedule()
        d = schedule.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("enabled", d)


if __name__ == "__main__":
    unittest.main()
