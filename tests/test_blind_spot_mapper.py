"""
Tests for aeOS Phase 5 — Blind_Spot_Mapper (A8)
=================================================
Tests analyze, getUnderweightedDomains, getAvoidedDecisionTypes,
getCartridgesNeverFired, getSuggestedFocus.
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

from src.core.blind_spot_mapper import (
    BlindSpotMapper,
    BlindSpotReport,
    ALL_KNOWN_DOMAINS,
)


class TestBlindSpotMapper(unittest.TestCase):
    """Test suite for Blind_Spot_Mapper."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_aeos.db")
        self.cart_dir = os.path.join(self.tmp_dir, "cartridges")
        os.makedirs(self.cart_dir, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS BlindSpot_Log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_date TEXT NOT NULL,
                underweighted_domains TEXT NOT NULL DEFAULT '[]',
                avoided_patterns TEXT NOT NULL DEFAULT '[]',
                cartridges_never_fired TEXT NOT NULL DEFAULT '[]',
                suggested_focus TEXT NOT NULL DEFAULT '[]',
                acknowledged INTEGER NOT NULL DEFAULT 0
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

            CREATE TABLE IF NOT EXISTS Cartridge_Arbitration_Log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                conflicting_carts TEXT NOT NULL DEFAULT '[]',
                conflict_type TEXT NOT NULL DEFAULT 'recommendation',
                winner_cart_id TEXT,
                resolution_method TEXT NOT NULL DEFAULT 'priority_chain',
                domain TEXT NOT NULL DEFAULT 'unknown',
                escalated INTEGER NOT NULL DEFAULT 0,
                notes TEXT
            );
        """)
        conn.commit()
        conn.close()

        # Create test cartridges
        self._create_cartridge("CART-NEGOTIATION", "negotiation")
        self._create_cartridge("CART-SYSTEMS", "systems_thinking")
        self._create_cartridge("CART-STOIC", "philosophy")
        self._create_cartridge("CART-LEADERSHIP", "leadership")
        self._create_cartridge("CART-ENERGY", "energy_management")

        self.mapper = BlindSpotMapper(
            db_path=self.db_path,
            cartridge_dir=self.cart_dir,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _create_cartridge(self, cart_id: str, domain: str):
        """Create a test cartridge JSON file."""
        data = {"id": cart_id, "domain": domain, "rules": []}
        filepath = os.path.join(self.cart_dir, f"{cart_id.lower()}.json")
        with open(filepath, "w") as f:
            json.dump(data, f)

    def _seed_decisions(self, domains=None, count=10):
        """Seed decisions with specified domain distribution."""
        if domains is None:
            domains = ["business"] * count
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc)
        for i, domain in enumerate(domains):
            ts = (now - timedelta(days=i % 30, hours=i)).isoformat()
            carts = json.dumps(["CART-NEGOTIATION"])
            conn.execute(
                """INSERT INTO Compound_Intelligence_Log
                (decision_id, timestamp, context, domain, confidence,
                 cartridges_fired, cartridge_count,
                 outcome_recorded, outcome_valence, outcome_magnitude)
                VALUES (?, ?, ?, ?, 0.7, ?, 1, 1, 1, 0.6)""",
                (f"DEC-{i:03d}", ts, f"Decision {i}", domain, carts),
            )
        conn.commit()
        conn.close()

    def _seed_cartridge_performance(self, cart_ids):
        """Seed Cartridge_Performance_Log with fired cartridges."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc)
        for i, cid in enumerate(cart_ids):
            ts = (now - timedelta(days=i)).isoformat()
            conn.execute(
                """INSERT INTO Cartridge_Performance_Log
                (timestamp, cartridge_id, decision_id, relevance_score,
                 was_accepted, domain)
                VALUES (?, ?, ?, 0.8, 1, 'business')""",
                (ts, cid, f"DEC-{i:03d}"),
            )
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # analyze tests
    # ------------------------------------------------------------------

    def test_analyze_returns_report(self):
        """analyze() returns a BlindSpotReport."""
        report = self.mapper.analyze()
        self.assertIsInstance(report, BlindSpotReport)

    def test_analyze_empty_db(self):
        """Empty database shows all domains as underweighted."""
        report = self.mapper.analyze()
        self.assertEqual(report.total_decisions_analyzed, 0)
        # All known domains are underweighted since there's no data
        self.assertEqual(
            sorted(report.underweighted_domains),
            sorted(ALL_KNOWN_DOMAINS),
        )

    def test_analyze_with_concentrated_decisions(self):
        """Concentrated decisions surface underweighted domains."""
        # All decisions in 'business' — every other domain is underweighted
        self._seed_decisions(domains=["business"] * 20)
        report = self.mapper.analyze()
        self.assertNotIn("business", report.underweighted_domains)
        self.assertGreater(len(report.underweighted_domains), 0)

    def test_analyze_persists_to_db(self):
        """Analysis is saved to BlindSpot_Log."""
        self._seed_decisions(count=5)
        self.mapper.analyze()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM BlindSpot_Log").fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["acknowledged"], 0)

    def test_analyze_includes_coverage_score(self):
        """Report includes a coverage score between 0-100."""
        self._seed_decisions(count=10)
        report = self.mapper.analyze()
        self.assertGreaterEqual(report.coverage_score, 0.0)
        self.assertLessEqual(report.coverage_score, 100.0)

    def test_analyze_low_coverage_score_concentrated(self):
        """Concentrated decisions yield low coverage score."""
        self._seed_decisions(domains=["business"] * 20)
        report = self.mapper.analyze()
        self.assertLess(report.coverage_score, 50.0)

    def test_analyze_higher_coverage_diversified(self):
        """Diversified decisions yield higher coverage score."""
        domains = [
            "business", "finance", "health", "career",
            "creative", "learning", "personal", "relationships",
        ] * 3
        self._seed_decisions(domains=domains)
        report = self.mapper.analyze()
        self.assertGreater(report.coverage_score, 50.0)

    # ------------------------------------------------------------------
    # getUnderweightedDomains tests
    # ------------------------------------------------------------------

    def test_get_underweighted_domains_returns_list(self):
        """getUnderweightedDomains() returns a list."""
        result = self.mapper.get_underweighted_domains()
        self.assertIsInstance(result, list)

    def test_get_underweighted_domains_empty_db(self):
        """All domains underweighted with no data."""
        result = self.mapper.get_underweighted_domains()
        self.assertEqual(sorted(result), sorted(ALL_KNOWN_DOMAINS))

    def test_get_underweighted_domains_concentrated(self):
        """Identifies neglected domains."""
        self._seed_decisions(domains=["business"] * 20)
        result = self.mapper.get_underweighted_domains()
        self.assertNotIn("business", result)
        self.assertIn("health", result)
        self.assertIn("relationships", result)

    def test_get_underweighted_domains_well_distributed(self):
        """Well-distributed decisions yield fewer underweighted domains."""
        domains = list(ALL_KNOWN_DOMAINS) * 5
        self._seed_decisions(domains=domains)
        result = self.mapper.get_underweighted_domains()
        self.assertEqual(len(result), 0)

    # ------------------------------------------------------------------
    # getAvoidedDecisionTypes tests
    # ------------------------------------------------------------------

    def test_get_avoided_decision_types_returns_list(self):
        """getAvoidedDecisionTypes() returns a list."""
        result = self.mapper.get_avoided_decision_types()
        self.assertIsInstance(result, list)

    def test_get_avoided_decision_types_no_dtl(self):
        """Without Decision_Tree_Log, all types are avoided."""
        result = self.mapper.get_avoided_decision_types()
        # No Decision_Tree_Log table means no decision_type data
        # so all known types should be listed
        from src.core.blind_spot_mapper import ALL_DECISION_TYPES
        self.assertEqual(sorted(result), sorted(ALL_DECISION_TYPES))

    # ------------------------------------------------------------------
    # getCartridgesNeverFired tests
    # ------------------------------------------------------------------

    def test_get_cartridges_never_fired_returns_list(self):
        """getCartridgesNeverFired() returns a list."""
        result = self.mapper.get_cartridges_never_fired()
        self.assertIsInstance(result, list)

    def test_get_cartridges_never_fired_all_unused(self):
        """All cartridges are unused when no performance data exists."""
        result = self.mapper.get_cartridges_never_fired()
        # All 5 test cartridges should be listed
        self.assertEqual(len(result), 5)
        self.assertIn("CART-NEGOTIATION", result)
        self.assertIn("CART-STOIC", result)

    def test_get_cartridges_never_fired_some_used(self):
        """Only unused cartridges are returned after some fire."""
        self._seed_cartridge_performance(["CART-NEGOTIATION", "CART-SYSTEMS"])
        result = self.mapper.get_cartridges_never_fired()
        self.assertNotIn("CART-NEGOTIATION", result)
        self.assertNotIn("CART-SYSTEMS", result)
        self.assertIn("CART-STOIC", result)
        self.assertIn("CART-LEADERSHIP", result)
        self.assertIn("CART-ENERGY", result)

    def test_get_cartridges_never_fired_all_used(self):
        """No unused cartridges when all have been fired."""
        all_carts = [
            "CART-NEGOTIATION", "CART-SYSTEMS", "CART-STOIC",
            "CART-LEADERSHIP", "CART-ENERGY",
        ]
        self._seed_cartridge_performance(all_carts)
        result = self.mapper.get_cartridges_never_fired()
        self.assertEqual(len(result), 0)

    def test_get_cartridges_fired_from_cil(self):
        """Cartridges detected from Compound_Intelligence_Log JSON."""
        # Seed CIL with cartridges_fired JSON
        self._seed_decisions(domains=["business"] * 5)
        # CART-NEGOTIATION is in the seeded decisions
        result = self.mapper.get_cartridges_never_fired()
        self.assertNotIn("CART-NEGOTIATION", result)

    # ------------------------------------------------------------------
    # getSuggestedFocus tests
    # ------------------------------------------------------------------

    def test_get_suggested_focus_returns_list(self):
        """getSuggestedFocus() returns a list."""
        result = self.mapper.get_suggested_focus()
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)

    def test_get_suggested_focus_includes_domain_advice(self):
        """Suggestions include domain-specific advice."""
        self._seed_decisions(domains=["business"] * 20)
        result = self.mapper.get_suggested_focus()
        has_domain_advice = any("domain" in s.lower() for s in result)
        self.assertTrue(has_domain_advice)

    def test_get_suggested_focus_includes_cartridge_advice(self):
        """Suggestions mention unused cartridges."""
        result = self.mapper.get_suggested_focus()
        has_cartridge_advice = any("cartridge" in s.lower() for s in result)
        self.assertTrue(has_cartridge_advice)

    # ------------------------------------------------------------------
    # Avoidance pattern detection tests
    # ------------------------------------------------------------------

    def test_outcome_tracking_gap_detected(self):
        """Detects when outcomes are rarely recorded."""
        conn = sqlite3.connect(self.db_path)
        now = datetime.now(timezone.utc)
        for i in range(10):
            ts = (now - timedelta(days=i)).isoformat()
            conn.execute(
                """INSERT INTO Compound_Intelligence_Log
                (decision_id, timestamp, context, domain, confidence,
                 outcome_recorded)
                VALUES (?, ?, 'No outcome', 'business', 0.7, 0)""",
                (f"NO-OUT-{i:03d}", ts),
            )
        conn.commit()
        conn.close()

        report = self.mapper.analyze()
        has_outcome_pattern = any(
            "outcome" in p.lower() for p in report.avoided_patterns
        )
        self.assertTrue(has_outcome_pattern)

    def test_domain_avoidance_pattern_detected(self):
        """Detects domain avoidance as a pattern."""
        self._seed_decisions(domains=["business"] * 20)
        report = self.mapper.analyze()
        has_domain_pattern = any(
            "domain avoidance" in p.lower() for p in report.avoided_patterns
        )
        self.assertTrue(has_domain_pattern)

    # ------------------------------------------------------------------
    # Data class tests
    # ------------------------------------------------------------------

    def test_blind_spot_report_to_dict(self):
        """BlindSpotReport.to_dict() returns a dict."""
        report = self.mapper.analyze()
        d = report.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("underweighted_domains", d)
        self.assertIn("coverage_score", d)
        self.assertIn("suggested_focus", d)

    def test_blind_spot_report_has_all_fields(self):
        """BlindSpotReport has all required fields."""
        report = self.mapper.analyze()
        self.assertIsNotNone(report.analysis_date)
        self.assertIsInstance(report.underweighted_domains, list)
        self.assertIsInstance(report.avoided_patterns, list)
        self.assertIsInstance(report.cartridges_never_fired, list)
        self.assertIsInstance(report.suggested_focus, list)
        self.assertIsInstance(report.domain_distribution, dict)
        self.assertIsInstance(report.decision_type_distribution, dict)

    # ------------------------------------------------------------------
    # Edge case tests
    # ------------------------------------------------------------------

    def test_no_cartridge_dir(self):
        """Works when cartridge directory doesn't exist."""
        mapper = BlindSpotMapper(
            db_path=self.db_path,
            cartridge_dir="/nonexistent/path",
        )
        result = mapper.get_cartridges_never_fired()
        self.assertEqual(result, [])

    def test_custom_domains(self):
        """Accepts custom known domains set."""
        custom_domains = {"alpha", "beta", "gamma"}
        mapper = BlindSpotMapper(
            db_path=self.db_path,
            cartridge_dir=self.cart_dir,
            known_domains=custom_domains,
        )
        result = mapper.get_underweighted_domains()
        self.assertEqual(sorted(result), sorted(custom_domains))


if __name__ == "__main__":
    unittest.main()
