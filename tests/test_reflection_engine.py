"""
Tests for aeOS Phase 5 — Reflection_Engine (A7)
=================================================
Tests weeklyReflection, monthlyReflection, patternSummary,
whatCompounded, whatFailed, generateInsight.
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

from src.core.reflection_engine import (
    CompoundItem,
    FailureItem,
    PatternSummary,
    ReflectionEngine,
    ReflectionReport,
)


class TestReflectionEngine(unittest.TestCase):
    """Test suite for Reflection_Engine."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_aeos.db")

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript("""
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
        """)
        conn.commit()
        conn.close()

        self.engine = ReflectionEngine(db_path=self.db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _seed_decisions(self, count=10, days_ago=5):
        """Seed Compound_Intelligence_Log with test decisions."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc)
        for i in range(count):
            ts = (now - timedelta(days=days_ago, hours=i)).isoformat()
            valence = 1 if i % 3 == 0 else (-1 if i % 3 == 1 else 0)
            magnitude = 0.3 + (i % 5) * 0.15
            domain = ["business", "finance", "health", "career"][i % 4]
            carts = json.dumps(["negotiation", "systems-thinking"][:((i % 2) + 1)])

            conn.execute(
                """INSERT INTO Compound_Intelligence_Log
                (decision_id, timestamp, context, domain, confidence,
                 cartridges_fired, cartridge_count,
                 outcome_recorded, outcome_valence, outcome_magnitude)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    f"DEC-{i:03d}",
                    ts,
                    f"Decision context {i} about {domain}",
                    domain,
                    0.5 + (i % 5) * 0.1,
                    carts,
                    (i % 2) + 1,
                    valence,
                    round(magnitude, 2),
                ),
            )
        conn.commit()
        conn.close()

    def _seed_compound_winners(self, count=3):
        """Seed decisions with high positive outcomes (compounders)."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc)
        for i in range(count):
            ts = (now - timedelta(days=2, hours=i)).isoformat()
            conn.execute(
                """INSERT INTO Compound_Intelligence_Log
                (decision_id, timestamp, context, domain, confidence,
                 cartridges_fired, cartridge_count,
                 outcome_recorded, outcome_valence, outcome_magnitude)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?)""",
                (
                    f"WIN-{i:03d}",
                    ts,
                    f"Winning decision {i}",
                    "business",
                    0.8,
                    '["negotiation"]',
                    1,
                    0.7 + i * 0.1,
                ),
            )
        conn.commit()
        conn.close()

    def _seed_failures(self, count=3):
        """Seed decisions with negative outcomes."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc)
        for i in range(count):
            ts = (now - timedelta(days=3, hours=i)).isoformat()
            conn.execute(
                """INSERT INTO Compound_Intelligence_Log
                (decision_id, timestamp, context, domain, confidence,
                 cartridges_fired, cartridge_count,
                 outcome_recorded, outcome_valence, outcome_magnitude)
                VALUES (?, ?, ?, ?, ?, '[]', 0, 1, -1, ?)""",
                (
                    f"FAIL-{i:03d}",
                    ts,
                    f"Failed decision {i}",
                    "finance",
                    0.85,
                    0.5 + i * 0.1,
                ),
            )
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # weeklyReflection tests
    # ------------------------------------------------------------------

    def test_weekly_reflection_returns_report(self):
        """weeklyReflection() returns a ReflectionReport."""
        report = self.engine.weekly_reflection()
        self.assertIsInstance(report, ReflectionReport)
        self.assertEqual(report.period, "weekly")

    def test_weekly_reflection_empty_db(self):
        """Weekly reflection with no data returns empty report."""
        report = self.engine.weekly_reflection()
        self.assertEqual(report.decisions_reviewed, 0)
        self.assertEqual(report.compounded, [])
        self.assertEqual(report.failed, [])

    def test_weekly_reflection_with_data(self):
        """Weekly reflection includes recent decisions."""
        self._seed_decisions(count=10, days_ago=3)
        report = self.engine.weekly_reflection()
        self.assertGreater(report.decisions_reviewed, 0)
        self.assertIsNotNone(report.generated_at)
        self.assertIsNotNone(report.period_start)
        self.assertIsNotNone(report.period_end)

    def test_weekly_reflection_persists_to_db(self):
        """Weekly reflection is saved to Reflection_Log."""
        self._seed_decisions(5)
        self.engine.weekly_reflection()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM Reflection_Log").fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["period"], "weekly")

    def test_weekly_only_last_7_days(self):
        """Weekly reflection only reviews decisions from past 7 days."""
        # Seed old decisions (20 days ago)
        self._seed_decisions(count=5, days_ago=20)
        # Seed recent decisions (2 days ago)
        self._seed_compound_winners(count=3)

        report = self.engine.weekly_reflection()
        # Should only see the 3 recent, not the 5 old
        self.assertEqual(report.decisions_reviewed, 3)

    # ------------------------------------------------------------------
    # monthlyReflection tests
    # ------------------------------------------------------------------

    def test_monthly_reflection_returns_report(self):
        """monthlyReflection() returns a ReflectionReport."""
        report = self.engine.monthly_reflection()
        self.assertIsInstance(report, ReflectionReport)
        self.assertEqual(report.period, "monthly")

    def test_monthly_reflection_covers_30_days(self):
        """Monthly reflection includes decisions from past 30 days."""
        self._seed_decisions(count=5, days_ago=20)
        self._seed_compound_winners(count=3)

        report = self.engine.monthly_reflection()
        # Should see all 8 (5 old + 3 recent, all within 30 days)
        self.assertEqual(report.decisions_reviewed, 8)

    # ------------------------------------------------------------------
    # patternSummary tests
    # ------------------------------------------------------------------

    def test_pattern_summary_returns_pattern_summary(self):
        """patternSummary() returns a PatternSummary."""
        summary = self.engine.pattern_summary(days=30)
        self.assertIsInstance(summary, PatternSummary)

    def test_pattern_summary_empty_db(self):
        """Pattern summary with no data returns zero counts."""
        summary = self.engine.pattern_summary(days=30)
        self.assertEqual(summary.total_decisions, 0)
        self.assertEqual(summary.domains_active, {})
        self.assertEqual(summary.avg_confidence, 0.0)

    def test_pattern_summary_with_data(self):
        """Pattern summary includes domain distribution and stats."""
        self._seed_decisions(10)
        summary = self.engine.pattern_summary(days=30)
        self.assertEqual(summary.total_decisions, 10)
        self.assertIn("business", summary.domains_active)
        self.assertIn("finance", summary.domains_active)
        self.assertGreater(summary.avg_confidence, 0.0)

    def test_pattern_summary_top_cartridges(self):
        """Pattern summary surfaces top cartridges."""
        self._seed_decisions(10)
        summary = self.engine.pattern_summary(days=30)
        self.assertIsInstance(summary.top_cartridges, list)

    def test_pattern_summary_positive_negative_rates(self):
        """Pattern summary computes outcome rates."""
        self._seed_decisions(10)
        summary = self.engine.pattern_summary(days=30)
        self.assertGreaterEqual(summary.positive_rate, 0.0)
        self.assertLessEqual(summary.positive_rate, 1.0)
        self.assertGreaterEqual(summary.negative_rate, 0.0)
        self.assertLessEqual(summary.negative_rate, 1.0)

    def test_pattern_summary_days_parameter(self):
        """Pattern summary respects days parameter."""
        self._seed_decisions(count=5, days_ago=3)
        self._seed_decisions(count=5, days_ago=20)

        short = self.engine.pattern_summary(days=7)
        long = self.engine.pattern_summary(days=30)
        self.assertLessEqual(short.total_decisions, long.total_decisions)

    # ------------------------------------------------------------------
    # whatCompounded tests
    # ------------------------------------------------------------------

    def test_what_compounded_returns_list(self):
        """whatCompounded() returns a list."""
        result = self.engine.what_compounded()
        self.assertIsInstance(result, list)

    def test_what_compounded_empty_db(self):
        """Empty database returns empty list."""
        result = self.engine.what_compounded()
        self.assertEqual(result, [])

    def test_what_compounded_finds_winners(self):
        """whatCompounded() finds high-magnitude positive outcomes."""
        self._seed_compound_winners(3)
        result = self.engine.what_compounded()
        self.assertEqual(len(result), 3)
        for item in result:
            self.assertIsInstance(item, CompoundItem)
            self.assertEqual(item.outcome_valence, 1)
            self.assertGreaterEqual(item.outcome_magnitude, 0.5)

    def test_what_compounded_sorted_by_magnitude(self):
        """Results are sorted by outcome_magnitude descending."""
        self._seed_compound_winners(3)
        result = self.engine.what_compounded()
        for i in range(len(result) - 1):
            self.assertGreaterEqual(
                result[i].outcome_magnitude,
                result[i + 1].outcome_magnitude,
            )

    def test_what_compounded_excludes_negatives(self):
        """whatCompounded() excludes negative outcomes."""
        self._seed_failures(3)
        self._seed_compound_winners(2)
        result = self.engine.what_compounded()
        # Only the 2 winners, not the 3 failures
        self.assertEqual(len(result), 2)
        for item in result:
            self.assertEqual(item.outcome_valence, 1)

    def test_compound_item_has_cartridges(self):
        """CompoundItem includes cartridges_fired list."""
        self._seed_compound_winners(1)
        result = self.engine.what_compounded()
        self.assertIsInstance(result[0].cartridges_fired, list)

    # ------------------------------------------------------------------
    # whatFailed tests
    # ------------------------------------------------------------------

    def test_what_failed_returns_list(self):
        """whatFailed() returns a list."""
        result = self.engine.what_failed()
        self.assertIsInstance(result, list)

    def test_what_failed_empty_db(self):
        """Empty database returns empty list."""
        result = self.engine.what_failed()
        self.assertEqual(result, [])

    def test_what_failed_finds_negatives(self):
        """whatFailed() finds negative outcomes."""
        self._seed_failures(3)
        result = self.engine.what_failed()
        self.assertEqual(len(result), 3)
        for item in result:
            self.assertIsInstance(item, FailureItem)
            self.assertEqual(item.outcome_valence, -1)

    def test_what_failed_finds_overconfident(self):
        """whatFailed() detects high-confidence neutral outcomes."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc)
        conn.execute(
            """INSERT INTO Compound_Intelligence_Log
            (decision_id, timestamp, context, domain, confidence,
             outcome_recorded, outcome_valence, outcome_magnitude)
            VALUES (?, ?, 'Overconfident', 'business', 0.9, 1, 0, 0.5)""",
            ("OVER-001", (now - timedelta(days=1)).isoformat()),
        )
        conn.commit()
        conn.close()

        result = self.engine.what_failed()
        self.assertGreaterEqual(len(result), 1)
        overconf = [f for f in result if f.decision_id == "OVER-001"]
        self.assertEqual(len(overconf), 1)
        self.assertIn("confidence", overconf[0].failure_reason.lower())

    def test_what_failed_excludes_positive(self):
        """whatFailed() excludes positive outcomes."""
        self._seed_compound_winners(3)
        result = self.engine.what_failed()
        self.assertEqual(len(result), 0)

    # ------------------------------------------------------------------
    # generateInsight tests
    # ------------------------------------------------------------------

    def test_generate_insight_returns_string(self):
        """generateInsight() returns a string."""
        result = self.engine.generate_insight()
        self.assertIsInstance(result, str)

    def test_generate_insight_empty_db(self):
        """Empty database returns 'no decisions' message."""
        result = self.engine.generate_insight()
        self.assertIn("No decisions", result)

    def test_generate_insight_with_data(self):
        """Insight includes decision count and domain info."""
        self._seed_decisions(10)
        result = self.engine.generate_insight(days=30)
        self.assertIn("10", result)
        self.assertIn("decisions", result.lower())

    def test_generate_insight_with_compounds(self):
        """Insight mentions compound winners when present."""
        self._seed_compound_winners(2)
        result = self.engine.generate_insight(days=30)
        self.assertIn("compound", result.lower())

    def test_generate_insight_with_failures(self):
        """Insight mentions failures when present."""
        self._seed_failures(3)
        result = self.engine.generate_insight(days=30)
        self.assertIn("underperformed", result.lower())

    def test_generate_insight_focus_recommendation(self):
        """Insight includes a recommended focus area."""
        self._seed_decisions(10)
        result = self.engine.generate_insight(days=30)
        self.assertIn("RECOMMENDED FOCUS", result)

    # ------------------------------------------------------------------
    # ReflectionReport structure tests
    # ------------------------------------------------------------------

    def test_reflection_report_to_dict(self):
        """ReflectionReport.to_dict() returns a dict."""
        report = self.engine.weekly_reflection()
        d = report.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("period", d)
        self.assertIn("decisions_reviewed", d)
        self.assertIn("compound_score", d)

    def test_pattern_summary_to_dict(self):
        """PatternSummary.to_dict() returns a dict."""
        summary = self.engine.pattern_summary()
        d = summary.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("total_decisions", d)
        self.assertIn("domains_active", d)

    def test_compound_item_to_dict(self):
        """CompoundItem.to_dict() returns a dict."""
        item = CompoundItem(
            decision_id="DEC-001",
            context="Test",
            domain="business",
            confidence=0.8,
            outcome_valence=1,
            outcome_magnitude=0.7,
        )
        d = item.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("decision_id", d)

    def test_failure_item_to_dict(self):
        """FailureItem.to_dict() returns a dict."""
        item = FailureItem(
            decision_id="DEC-002",
            context="Test",
            domain="finance",
            confidence_at_decision=0.9,
            outcome_valence=-1,
            outcome_magnitude=0.6,
        )
        d = item.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("failure_reason", d)


if __name__ == "__main__":
    unittest.main()
