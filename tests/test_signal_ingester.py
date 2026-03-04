"""
Tests for aeOS Phase 5 — Signal_Ingester (A10)
================================================
Tests ingestCalendar, ingestFinancial, ingestMarketSignal,
ingestManual, getActiveSignals, expire.
Uses temporary SQLite database — no production data affected.
"""
import json
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.signal_ingester import (
    Signal,
    SignalIngester,
    VALID_SOURCES,
    VALID_DOMAINS,
)


class TestSignalIngester(unittest.TestCase):
    """Test suite for Signal_Ingester."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_aeos.db")

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS External_Signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL DEFAULT 'manual',
                content TEXT NOT NULL,
                domain TEXT NOT NULL DEFAULT 'unknown',
                relevance_score REAL NOT NULL DEFAULT 0.5,
                ingested_at TEXT NOT NULL,
                expires_at TEXT,
                consumed_count INTEGER NOT NULL DEFAULT 0,
                metadata TEXT NOT NULL DEFAULT '{}'
            );
        """)
        conn.commit()
        conn.close()

        self.ingester = SignalIngester(db_path=self.db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _count_signals(self):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT COUNT(*) FROM External_Signals").fetchone()
        conn.close()
        return row[0]

    def _get_all_signals_raw(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM External_Signals").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # ingestCalendar tests
    # ------------------------------------------------------------------

    def test_ingest_calendar_single_event(self):
        """Single calendar event creates one signal."""
        self.ingester.ingest_calendar([
            {"title": "Board meeting with investors", "start": "2026-03-10T10:00:00"},
        ])
        self.assertEqual(self._count_signals(), 1)
        signals = self._get_all_signals_raw()
        self.assertEqual(signals[0]["source"], "calendar")
        self.assertIn("Board meeting", signals[0]["content"])

    def test_ingest_calendar_multiple_events(self):
        """Multiple events create multiple signals."""
        self.ingester.ingest_calendar([
            {"title": "Team standup"},
            {"title": "Client call"},
            {"title": "Gym session"},
        ])
        self.assertEqual(self._count_signals(), 3)

    def test_ingest_calendar_domain_inference(self):
        """Domain is inferred from event content."""
        self.ingester.ingest_calendar([
            {"title": "Workout at gym", "description": "Leg day exercise routine"},
        ])
        signals = self._get_all_signals_raw()
        self.assertEqual(signals[0]["domain"], "health")

    def test_ingest_calendar_with_description(self):
        """Event description is included in content."""
        self.ingester.ingest_calendar([
            {"title": "Meeting", "description": "Review Q1 revenue numbers"},
        ])
        signals = self._get_all_signals_raw()
        self.assertIn("revenue", signals[0]["content"])

    def test_ingest_calendar_empty_events(self):
        """Empty events list creates nothing."""
        self.ingester.ingest_calendar([])
        self.assertEqual(self._count_signals(), 0)

    def test_ingest_calendar_skips_empty_title(self):
        """Events without title are skipped."""
        self.ingester.ingest_calendar([{"title": ""}])
        self.assertEqual(self._count_signals(), 0)

    def test_ingest_calendar_stores_metadata(self):
        """Event metadata (start, location) is stored."""
        self.ingester.ingest_calendar([
            {"title": "Meeting", "start": "2026-03-10T10:00:00", "location": "Room A"},
        ])
        signals = self._get_all_signals_raw()
        meta = json.loads(signals[0]["metadata"])
        self.assertIn("start", meta)
        self.assertIn("location", meta)

    def test_ingest_calendar_has_expiry(self):
        """Calendar signals have an expiry timestamp."""
        self.ingester.ingest_calendar([{"title": "Test"}])
        signals = self._get_all_signals_raw()
        self.assertIsNotNone(signals[0]["expires_at"])

    # ------------------------------------------------------------------
    # ingestFinancial tests
    # ------------------------------------------------------------------

    def test_ingest_financial_creates_signal(self):
        """Financial data creates a finance signal."""
        self.ingester.ingest_financial({
            "cash_balance": 50000, "monthly_burn": 8000,
        })
        self.assertEqual(self._count_signals(), 1)
        signals = self._get_all_signals_raw()
        self.assertEqual(signals[0]["source"], "finance")
        self.assertEqual(signals[0]["domain"], "finance")

    def test_ingest_financial_content_summary(self):
        """Financial content includes data summary."""
        self.ingester.ingest_financial({"revenue": 25000, "expenses": 15000})
        signals = self._get_all_signals_raw()
        self.assertIn("revenue", signals[0]["content"])
        self.assertIn("expenses", signals[0]["content"])

    def test_ingest_financial_metadata(self):
        """Financial data is stored in metadata."""
        data = {"cash_balance": 50000, "monthly_burn": 8000}
        self.ingester.ingest_financial(data)
        signals = self._get_all_signals_raw()
        meta = json.loads(signals[0]["metadata"])
        self.assertEqual(meta["cash_balance"], 50000)

    def test_ingest_financial_empty_data(self):
        """Empty financial data still creates signal."""
        self.ingester.ingest_financial({})
        self.assertEqual(self._count_signals(), 1)

    def test_ingest_financial_relevance_scales_with_data(self):
        """More data fields increase relevance score."""
        self.ingester.ingest_financial({"a": 1})
        self.ingester.ingest_financial({"a": 1, "b": 2, "c": 3, "d": 4, "e": 5})
        signals = self._get_all_signals_raw()
        self.assertLess(signals[0]["relevance_score"], signals[1]["relevance_score"])

    # ------------------------------------------------------------------
    # ingestMarketSignal tests
    # ------------------------------------------------------------------

    def test_ingest_market_signal_creates_signal(self):
        """Market signal creates a market-source signal."""
        self.ingester.ingest_market_signal({
            "content": "Competitor launched new pricing tier",
        })
        self.assertEqual(self._count_signals(), 1)
        signals = self._get_all_signals_raw()
        self.assertEqual(signals[0]["source"], "market")

    def test_ingest_market_signal_with_domain(self):
        """Explicit domain is preserved."""
        self.ingester.ingest_market_signal({
            "content": "Industry report published",
            "domain": "business",
        })
        signals = self._get_all_signals_raw()
        self.assertEqual(signals[0]["domain"], "business")

    def test_ingest_market_signal_with_relevance(self):
        """Explicit relevance is preserved."""
        self.ingester.ingest_market_signal({
            "content": "Critical market shift",
            "relevance": 0.95,
        })
        signals = self._get_all_signals_raw()
        self.assertEqual(signals[0]["relevance_score"], 0.95)

    def test_ingest_market_signal_empty_content_skipped(self):
        """Empty content is skipped."""
        self.ingester.ingest_market_signal({"content": ""})
        self.assertEqual(self._count_signals(), 0)

    def test_ingest_market_signal_metadata(self):
        """Extra fields stored in metadata."""
        self.ingester.ingest_market_signal({
            "content": "News item",
            "source_url": "https://example.com",
        })
        signals = self._get_all_signals_raw()
        meta = json.loads(signals[0]["metadata"])
        self.assertIn("source_url", meta)

    # ------------------------------------------------------------------
    # ingestManual tests
    # ------------------------------------------------------------------

    def test_ingest_manual_creates_signal(self):
        """Manual text creates a manual-source signal."""
        self.ingester.ingest_manual("Client postponed meeting", domain="business")
        self.assertEqual(self._count_signals(), 1)
        signals = self._get_all_signals_raw()
        self.assertEqual(signals[0]["source"], "manual")
        self.assertEqual(signals[0]["domain"], "business")

    def test_ingest_manual_domain_inference(self):
        """Domain is inferred when not specified or unknown."""
        self.ingester.ingest_manual(
            "Revenue from new client exceeded budget projections",
            domain="invalid_domain",
        )
        signals = self._get_all_signals_raw()
        # Should infer finance or business from keywords
        self.assertNotEqual(signals[0]["domain"], "invalid_domain")

    def test_ingest_manual_empty_text_skipped(self):
        """Empty text is skipped."""
        self.ingester.ingest_manual("", domain="business")
        self.assertEqual(self._count_signals(), 0)

    def test_ingest_manual_whitespace_text_skipped(self):
        """Whitespace-only text is skipped."""
        self.ingester.ingest_manual("   ", domain="business")
        self.assertEqual(self._count_signals(), 0)

    def test_ingest_manual_strips_whitespace(self):
        """Content is stripped of surrounding whitespace."""
        self.ingester.ingest_manual("  Important signal  ", domain="business")
        signals = self._get_all_signals_raw()
        self.assertEqual(signals[0]["content"], "Important signal")

    # ------------------------------------------------------------------
    # getActiveSignals tests
    # ------------------------------------------------------------------

    def test_get_active_signals_returns_list(self):
        """getActiveSignals() returns a list."""
        result = self.ingester.get_active_signals()
        self.assertIsInstance(result, list)

    def test_get_active_signals_empty_db(self):
        """Empty database returns empty list."""
        result = self.ingester.get_active_signals()
        self.assertEqual(len(result), 0)

    def test_get_active_signals_returns_signal_objects(self):
        """Active signals are Signal objects."""
        self.ingester.ingest_manual("Test signal", domain="business")
        result = self.ingester.get_active_signals()
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], Signal)

    def test_get_active_signals_excludes_expired(self):
        """Expired signals are not returned."""
        conn = sqlite3.connect(self.db_path)
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conn.execute(
            """INSERT INTO External_Signals
            (source, content, domain, relevance_score, ingested_at, expires_at)
            VALUES ('manual', 'Expired signal', 'business', 0.5, ?, ?)""",
            (past, past),
        )
        conn.commit()
        conn.close()

        result = self.ingester.get_active_signals()
        self.assertEqual(len(result), 0)

    def test_get_active_signals_includes_no_expiry(self):
        """Signals without expiry are always active."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO External_Signals
            (source, content, domain, relevance_score, ingested_at, expires_at)
            VALUES ('manual', 'Permanent signal', 'business', 0.5, ?, NULL)""",
            (now,),
        )
        conn.commit()
        conn.close()

        result = self.ingester.get_active_signals()
        self.assertEqual(len(result), 1)

    def test_get_active_signals_sorted_by_relevance(self):
        """Signals are sorted by relevance descending."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        for i, score in enumerate([0.3, 0.9, 0.6]):
            conn.execute(
                """INSERT INTO External_Signals
                (source, content, domain, relevance_score, ingested_at, expires_at)
                VALUES ('manual', ?, 'business', ?, ?, ?)""",
                (f"Signal {i}", score, now, future),
            )
        conn.commit()
        conn.close()

        result = self.ingester.get_active_signals()
        scores = [s.relevance_score for s in result]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_get_active_signals_bumps_consumed_count(self):
        """Getting active signals increments consumed_count."""
        self.ingester.ingest_manual("Test", domain="business")

        # First fetch
        result1 = self.ingester.get_active_signals()
        self.assertEqual(result1[0].consumed_count, 1)

        # Second fetch — DB has count=1 after first bump, returns count+1=2
        result2 = self.ingester.get_active_signals()
        self.assertEqual(result2[0].consumed_count, 2)

    def test_get_active_signals_filter_by_domain(self):
        """Active signals can be filtered by domain."""
        self.ingester.ingest_manual("Business signal", domain="business")
        self.ingester.ingest_manual("Health signal about exercise", domain="health")

        result = self.ingester.get_active_signals(domain="business")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].domain, "business")

    def test_get_active_signals_filter_by_source(self):
        """Active signals can be filtered by source."""
        self.ingester.ingest_manual("Manual signal", domain="business")
        self.ingester.ingest_financial({"revenue": 1000})

        result = self.ingester.get_active_signals(source="finance")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, "finance")

    def test_get_active_signals_limit(self):
        """Active signals respect limit parameter."""
        for i in range(10):
            self.ingester.ingest_manual(f"Signal {i}", domain="business")

        result = self.ingester.get_active_signals(limit=3)
        self.assertEqual(len(result), 3)

    # ------------------------------------------------------------------
    # expire tests
    # ------------------------------------------------------------------

    def test_expire_removes_signal_from_active(self):
        """Expired signal no longer appears in active signals."""
        self.ingester.ingest_manual("Will expire", domain="business")
        signals = self.ingester.get_active_signals()
        self.assertEqual(len(signals), 1)
        signal_id = signals[0].signal_id

        self.ingester.expire(signal_id)

        result = self.ingester.get_active_signals()
        self.assertEqual(len(result), 0)

    def test_expire_nonexistent_id(self):
        """Expiring nonexistent ID doesn't raise."""
        self.ingester.expire(99999)  # Should not raise

    def test_expire_only_affects_target(self):
        """Expiring one signal doesn't affect others."""
        self.ingester.ingest_manual("Signal A", domain="business")
        self.ingester.ingest_manual("Signal B", domain="business")

        signals = self.ingester.get_active_signals()
        self.assertEqual(len(signals), 2)

        self.ingester.expire(signals[0].signal_id)

        remaining = self.ingester.get_active_signals()
        self.assertEqual(len(remaining), 1)

    # ------------------------------------------------------------------
    # cleanup_expired tests
    # ------------------------------------------------------------------

    def test_cleanup_expired_removes_old_signals(self):
        """cleanup_expired() removes expired signals from DB."""
        conn = sqlite3.connect(self.db_path)
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        now = datetime.now(timezone.utc).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

        conn.execute(
            """INSERT INTO External_Signals
            (source, content, domain, relevance_score, ingested_at, expires_at)
            VALUES ('manual', 'Expired', 'business', 0.5, ?, ?)""",
            (past, past),
        )
        conn.execute(
            """INSERT INTO External_Signals
            (source, content, domain, relevance_score, ingested_at, expires_at)
            VALUES ('manual', 'Active', 'business', 0.5, ?, ?)""",
            (now, future),
        )
        conn.commit()
        conn.close()

        removed = self.ingester.cleanup_expired()
        self.assertEqual(removed, 1)
        self.assertEqual(self._count_signals(), 1)

    def test_cleanup_expired_returns_zero_when_none(self):
        """No expired signals returns 0."""
        self.ingester.ingest_manual("Fresh signal", domain="business")
        removed = self.ingester.cleanup_expired()
        self.assertEqual(removed, 0)

    # ------------------------------------------------------------------
    # Domain inference tests
    # ------------------------------------------------------------------

    def test_infer_finance_domain(self):
        """Finance keywords map to finance domain."""
        self.ingester.ingest_manual("Revenue projections for Q2 budget", domain="invalid_xyz")
        signals = self._get_all_signals_raw()
        self.assertEqual(signals[0]["domain"], "finance")

    def test_infer_health_domain(self):
        """Health keywords map to health domain."""
        self.ingester.ingest_manual("Morning workout and nutrition plan", domain="invalid_xyz")
        signals = self._get_all_signals_raw()
        self.assertEqual(signals[0]["domain"], "health")

    def test_infer_business_domain(self):
        """Business keywords map to business domain."""
        self.ingester.ingest_manual("New client sales pipeline review", domain="invalid_xyz")
        signals = self._get_all_signals_raw()
        self.assertEqual(signals[0]["domain"], "business")

    # ------------------------------------------------------------------
    # Relevance scoring tests
    # ------------------------------------------------------------------

    def test_urgency_boosts_relevance(self):
        """Urgent keywords boost relevance score."""
        self.ingester.ingest_manual("Normal update", domain="business")
        self.ingester.ingest_manual("URGENT critical deadline risk", domain="business")
        signals = self._get_all_signals_raw()
        normal = signals[0]["relevance_score"]
        urgent = signals[1]["relevance_score"]
        self.assertGreater(urgent, normal)

    # ------------------------------------------------------------------
    # Data class tests
    # ------------------------------------------------------------------

    def test_signal_to_dict(self):
        """Signal.to_dict() returns a dict."""
        signal = Signal(
            signal_id=1,
            source="manual",
            content="Test",
            domain="business",
            relevance_score=0.5,
            ingested_at="2026-03-01T00:00:00",
        )
        d = signal.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("signal_id", d)
        self.assertIn("source", d)
        self.assertIn("relevance_score", d)

    def test_signal_defaults(self):
        """Signal has correct defaults."""
        signal = Signal(
            signal_id=1, source="manual", content="Test",
            domain="business", relevance_score=0.5,
            ingested_at="2026-03-01T00:00:00",
        )
        self.assertIsNone(signal.expires_at)
        self.assertEqual(signal.consumed_count, 0)
        self.assertEqual(signal.metadata, {})


if __name__ == "__main__":
    unittest.main()
