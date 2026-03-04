"""
Tests for aeOS Phase 4 — Cartridge_Arbitrator (A4)
====================================================
Tests detectConflicts, arbitrate, getArbitrationHistory, setDomainPriority.
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

from src.core.cartridge_arbitrator import (
    ArbitrationResult,
    CartridgeArbitrator,
    CartridgeRecommendation,
    Conflict,
)


def _make_rec(
    cart_id="CART-001", name="TestCart", rec="Do X",
    confidence=0.7, domain="business", validated_at=None,
):
    return CartridgeRecommendation(
        cartridge_id=cart_id,
        cartridge_name=name,
        recommendation=rec,
        confidence=confidence,
        domain=domain,
        validated_at=validated_at,
    )


class TestCartridgeArbitrator(unittest.TestCase):
    """Test suite for Cartridge_Arbitrator."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_aeos.db")

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript("""
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

        self.arb = CartridgeArbitrator(db_path=self.db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # detectConflicts tests
    # ------------------------------------------------------------------

    def test_detect_conflicts_no_recs(self):
        """No conflicts with fewer than 2 recommendations."""
        conflicts = self.arb.detect_conflicts(["CART-001"], [_make_rec()])
        self.assertEqual(len(conflicts), 0)

    def test_detect_conflicts_no_conflict(self):
        """Non-contradictory recommendations produce no conflicts."""
        rec_a = _make_rec(cart_id="CART-001", name="Alpha", rec="Expand marketing spend")
        rec_b = _make_rec(cart_id="CART-002", name="Beta", rec="Hire more engineers")
        conflicts = self.arb.detect_conflicts(
            ["CART-001", "CART-002"], [rec_a, rec_b]
        )
        self.assertEqual(len(conflicts), 0)

    def test_detect_conflicts_finds_negation_conflict(self):
        """Detects conflict via negation pairs (buy vs sell)."""
        rec_a = _make_rec(cart_id="CART-001", name="Alpha", rec="Buy more inventory")
        rec_b = _make_rec(cart_id="CART-002", name="Beta", rec="Sell all inventory")
        conflicts = self.arb.detect_conflicts(
            ["CART-001", "CART-002"], [rec_a, rec_b]
        )
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].conflict_type, "recommendation")
        self.assertIn("CART-001", conflicts[0].cartridge_ids)
        self.assertIn("CART-002", conflicts[0].cartridge_ids)

    def test_detect_conflicts_multiple_pairs(self):
        """Detects conflicts between multiple contradictory pairs."""
        rec_a = _make_rec(cart_id="CART-001", name="Alpha", rec="Should invest")
        rec_b = _make_rec(cart_id="CART-002", name="Beta", rec="Should not invest")
        rec_c = _make_rec(cart_id="CART-003", name="Gamma", rec="Start the project now")
        conflicts = self.arb.detect_conflicts(
            ["CART-001", "CART-002", "CART-003"], [rec_a, rec_b, rec_c]
        )
        self.assertGreaterEqual(len(conflicts), 1)

    def test_detect_conflicts_returns_conflict_objects(self):
        """Conflicts are Conflict dataclass instances."""
        rec_a = _make_rec(cart_id="C1", name="A", rec="Accept the deal")
        rec_b = _make_rec(cart_id="C2", name="B", rec="Reject the deal")
        conflicts = self.arb.detect_conflicts(["C1", "C2"], [rec_a, rec_b])
        self.assertIsInstance(conflicts[0], Conflict)

    def test_detect_conflicts_conflict_id_format(self):
        """Conflict IDs follow CONF-XXXX format."""
        rec_a = _make_rec(cart_id="C1", name="A", rec="Keep all products")
        rec_b = _make_rec(cart_id="C2", name="B", rec="Kill all products")
        conflicts = self.arb.detect_conflicts(["C1", "C2"], [rec_a, rec_b])
        self.assertTrue(conflicts[0].conflict_id.startswith("CONF-"))

    def test_detect_conflicts_cross_domain(self):
        """Cross-domain conflicts are labeled correctly."""
        rec_a = _make_rec(cart_id="C1", name="A", rec="Buy now", domain="finance")
        rec_b = _make_rec(cart_id="C2", name="B", rec="Sell now", domain="strategy")
        conflicts = self.arb.detect_conflicts(["C1", "C2"], [rec_a, rec_b])
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].domain, "cross-domain")

    # ------------------------------------------------------------------
    # arbitrate tests
    # ------------------------------------------------------------------

    def test_arbitrate_by_confidence(self):
        """Arbitrates by confidence when gap >= 0.1."""
        rec_a = _make_rec(cart_id="C1", name="Alpha", rec="Buy more", confidence=0.9)
        rec_b = _make_rec(cart_id="C2", name="Beta", rec="Sell more", confidence=0.5)
        conflict = Conflict(
            conflict_id="CONF-TEST",
            cartridge_ids=["C1", "C2"],
            recommendations=[rec_a, rec_b],
            conflict_type="recommendation",
        )
        result = self.arb.arbitrate(conflict)
        self.assertIsInstance(result, ArbitrationResult)
        self.assertEqual(result.winner_cart_id, "C1")
        self.assertEqual(result.resolution_method, "confidence")

    def test_arbitrate_by_domain_priority(self):
        """Arbitrates by domain priority when set."""
        self.arb.set_domain_priority("finance", 1)
        self.arb.set_domain_priority("strategy", 5)

        rec_a = _make_rec(
            cart_id="C1", name="Finance", rec="Buy it", confidence=0.5, domain="finance"
        )
        rec_b = _make_rec(
            cart_id="C2", name="Strategy", rec="Sell it", confidence=0.9, domain="strategy"
        )
        conflict = Conflict(
            conflict_id="CONF-DP",
            cartridge_ids=["C1", "C2"],
            recommendations=[rec_a, rec_b],
            conflict_type="recommendation",
        )
        result = self.arb.arbitrate(conflict)
        self.assertEqual(result.winner_cart_id, "C1")
        self.assertEqual(result.resolution_method, "domain_specificity")

    def test_arbitrate_by_recency(self):
        """Arbitrates by recency when confidence tie."""
        rec_a = _make_rec(
            cart_id="C1", name="Old", rec="Keep it", confidence=0.7,
            validated_at="2026-01-01T00:00:00",
        )
        rec_b = _make_rec(
            cart_id="C2", name="New", rec="Kill it", confidence=0.7,
            validated_at="2026-03-01T00:00:00",
        )
        conflict = Conflict(
            conflict_id="CONF-REC",
            cartridge_ids=["C1", "C2"],
            recommendations=[rec_a, rec_b],
            conflict_type="recommendation",
        )
        result = self.arb.arbitrate(conflict)
        self.assertEqual(result.winner_cart_id, "C2")
        self.assertEqual(result.resolution_method, "recency")

    def test_arbitrate_escalates_when_tied(self):
        """Escalates to Sovereign when no resolution method succeeds."""
        rec_a = _make_rec(cart_id="C1", name="A", rec="Go left", confidence=0.7)
        rec_b = _make_rec(cart_id="C2", name="B", rec="Go right", confidence=0.7)
        conflict = Conflict(
            conflict_id="CONF-ESC",
            cartridge_ids=["C1", "C2"],
            recommendations=[rec_a, rec_b],
            conflict_type="recommendation",
        )
        result = self.arb.arbitrate(conflict)
        self.assertTrue(result.escalated)
        self.assertEqual(result.resolution_method, "sovereign_escalation")
        self.assertIsNone(result.winner_cart_id)

    def test_arbitrate_single_rec_no_conflict(self):
        """Single recommendation returns no_conflict."""
        rec = _make_rec(cart_id="C1", name="Only", rec="Do it")
        conflict = Conflict(
            conflict_id="CONF-SINGLE",
            cartridge_ids=["C1"],
            recommendations=[rec],
            conflict_type="recommendation",
        )
        result = self.arb.arbitrate(conflict)
        self.assertEqual(result.resolution_method, "no_conflict")
        self.assertEqual(result.winner_cart_id, "C1")

    def test_arbitrate_logs_to_db(self):
        """Arbitration result is logged to database."""
        rec_a = _make_rec(cart_id="C1", name="A", rec="Buy", confidence=0.9)
        rec_b = _make_rec(cart_id="C2", name="B", rec="Sell", confidence=0.3)
        conflict = Conflict(
            conflict_id="CONF-LOG",
            cartridge_ids=["C1", "C2"],
            recommendations=[rec_a, rec_b],
            conflict_type="recommendation",
        )
        self.arb.arbitrate(conflict)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM Cartridge_Arbitration_Log").fetchall()
        conn.close()
        self.assertGreater(len(rows), 0)
        self.assertEqual(rows[0]["winner_cart_id"], "C1")

    # ------------------------------------------------------------------
    # getArbitrationHistory tests
    # ------------------------------------------------------------------

    def test_get_arbitration_history_empty(self):
        """getArbitrationHistory() returns empty list when no arbitrations."""
        history = self.arb.get_arbitration_history()
        self.assertEqual(len(history), 0)

    def test_get_arbitration_history_after_arbitrate(self):
        """getArbitrationHistory() returns results after arbitration."""
        rec_a = _make_rec(cart_id="C1", name="A", rec="Buy", confidence=0.9)
        rec_b = _make_rec(cart_id="C2", name="B", rec="Sell", confidence=0.4)
        conflict = Conflict(
            conflict_id="CONF-HIST",
            cartridge_ids=["C1", "C2"],
            recommendations=[rec_a, rec_b],
            conflict_type="recommendation",
        )
        self.arb.arbitrate(conflict)

        history = self.arb.get_arbitration_history()
        self.assertGreater(len(history), 0)
        self.assertIsInstance(history[0], ArbitrationResult)

    def test_get_arbitration_history_limit(self):
        """getArbitrationHistory() respects the limit parameter."""
        for i in range(5):
            rec_a = _make_rec(cart_id=f"C{i}a", name="A", rec="Buy", confidence=0.9)
            rec_b = _make_rec(cart_id=f"C{i}b", name="B", rec="Sell", confidence=0.3)
            conflict = Conflict(
                conflict_id=f"CONF-{i}",
                cartridge_ids=[f"C{i}a", f"C{i}b"],
                recommendations=[rec_a, rec_b],
                conflict_type="recommendation",
            )
            self.arb.arbitrate(conflict)

        history = self.arb.get_arbitration_history(limit=3)
        self.assertEqual(len(history), 3)

    # ------------------------------------------------------------------
    # setDomainPriority tests
    # ------------------------------------------------------------------

    def test_set_domain_priority(self):
        """setDomainPriority() stores priority."""
        self.arb.set_domain_priority("finance", 1)
        priorities = self.arb.get_domain_priorities()
        self.assertEqual(priorities["finance"], 1)

    def test_set_domain_priority_multiple(self):
        """Multiple domain priorities stored correctly."""
        self.arb.set_domain_priority("finance", 1)
        self.arb.set_domain_priority("health", 2)
        self.arb.set_domain_priority("strategy", 3)
        priorities = self.arb.get_domain_priorities()
        self.assertEqual(len(priorities), 3)
        self.assertEqual(priorities["finance"], 1)
        self.assertEqual(priorities["health"], 2)

    def test_set_domain_priority_overwrite(self):
        """Setting priority again overwrites."""
        self.arb.set_domain_priority("finance", 1)
        self.arb.set_domain_priority("finance", 5)
        priorities = self.arb.get_domain_priorities()
        self.assertEqual(priorities["finance"], 5)

    # ------------------------------------------------------------------
    # Data class tests
    # ------------------------------------------------------------------

    def test_cartridge_recommendation_to_dict(self):
        """CartridgeRecommendation.to_dict() returns a dict."""
        rec = _make_rec()
        d = rec.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("cartridge_id", d)
        self.assertIn("confidence", d)

    def test_conflict_to_dict(self):
        """Conflict.to_dict() returns a dict."""
        conflict = Conflict(
            conflict_id="TEST",
            cartridge_ids=["A", "B"],
            recommendations=[],
            conflict_type="recommendation",
        )
        d = conflict.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("conflict_id", d)

    def test_arbitration_result_to_dict(self):
        """ArbitrationResult.to_dict() returns a dict."""
        result = ArbitrationResult(
            conflict_id="TEST",
            winner_cart_id="C1",
            winner_recommendation="Do X",
            resolution_method="confidence",
        )
        d = result.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("resolution_method", d)


if __name__ == "__main__":
    unittest.main()
