"""
Tests for aeOS Phase 4 — Contradiction_Detector (A2)
=====================================================
Tests checkDecision, checkAgainstLaws, getHistory, getConsistencyScore.
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

from src.core.contradiction_detector import (
    ContradictionDetector,
    ContradictionResult,
    LawViolation,
    MASTER_LAWS,
)


class TestContradictionDetector(unittest.TestCase):
    """Test suite for Contradiction_Detector."""

    def setUp(self):
        """Create a temporary database with required tables."""
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_aeos.db")

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")

        conn.executescript("""
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

            CREATE TABLE IF NOT EXISTS Decision_Tree_Log (
                Decision_ID TEXT PRIMARY KEY,
                Decision_Description TEXT,
                Decision_Type TEXT DEFAULT 'strategic',
                Decision_Date TEXT
            );

            -- Seed some past decisions
            INSERT INTO Decision_Tree_Log
                (Decision_ID, Decision_Description, Decision_Type, Decision_Date)
            VALUES
                ('DEC-001', 'We should invest heavily in SaaS products', 'strategic', '2026-01-15'),
                ('DEC-002', 'Hire 3 more backend engineers this quarter', 'operational', '2026-02-01'),
                ('DEC-003', 'Keep all current product lines active', 'strategic', '2026-02-10'),
                ('DEC-004', 'Focus on B2B enterprise sales channel', 'strategic', '2026-02-20');
        """)
        conn.commit()
        conn.close()

        self.detector = ContradictionDetector(db_path=self.db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # checkDecision tests
    # ------------------------------------------------------------------

    def test_check_decision_returns_result(self):
        """checkDecision() returns a ContradictionResult."""
        result = self.detector.check_decision(
            decision={"description": "Launch a new marketing campaign"},
            domain="business",
        )
        self.assertIsInstance(result, ContradictionResult)

    def test_check_decision_no_contradiction(self):
        """No contradiction for unrelated decision."""
        result = self.detector.check_decision(
            decision={"description": "xyz 1234567890"},
            domain="engineering",
        )
        self.assertFalse(result.has_contradiction)
        self.assertEqual(result.severity, "low")

    def test_check_decision_detects_contradiction(self):
        """Detects contradiction against past decisions via negation pairs."""
        result = self.detector.check_decision(
            decision={"description": "We should divest from SaaS products and stop investing"},
            domain="business",
        )
        self.assertTrue(result.has_contradiction)
        self.assertIn("contradict", result.explanation.lower())

    def test_check_decision_empty_description(self):
        """Empty description returns no contradiction."""
        result = self.detector.check_decision(
            decision={"description": ""},
            domain="business",
        )
        self.assertFalse(result.has_contradiction)

    def test_check_decision_with_id(self):
        """Decision ID is preserved in result."""
        result = self.detector.check_decision(
            decision={"id": "DEC-NEW-001", "description": "Something new"},
            domain="business",
        )
        self.assertEqual(result.new_decision_id, "DEC-NEW-001")

    def test_check_decision_law_violation_takes_priority(self):
        """Master Law violation is detected before historical comparison."""
        result = self.detector.check_decision(
            decision={"description": "We should skip scoring entirely, feelings only"},
            domain="business",
        )
        self.assertTrue(result.has_contradiction)
        self.assertEqual(result.severity, "critical")
        self.assertIn("Master Law", result.explanation)

    def test_check_decision_logs_to_db(self):
        """Detected contradiction is logged to Contradiction_Log."""
        self.detector.check_decision(
            decision={"description": "We should skip scoring entirely, feelings only"},
            domain="business",
        )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM Contradiction_Log").fetchall()
        conn.close()
        self.assertGreater(len(rows), 0)
        self.assertEqual(rows[0]["severity"], "critical")

    def test_check_decision_domain_preserved(self):
        """Domain is preserved in result."""
        result = self.detector.check_decision(
            decision={"description": "Expand to new markets"},
            domain="growth",
        )
        self.assertEqual(result.domain, "growth")

    # ------------------------------------------------------------------
    # checkAgainstLaws tests
    # ------------------------------------------------------------------

    def test_check_against_laws_no_violation(self):
        """Clean recommendation passes all laws."""
        violations = self.detector.check_against_laws(
            "We should score all ideas and validate with evidence"
        )
        self.assertEqual(len(violations), 0)

    def test_check_against_laws_detects_law1_scanner(self):
        """Detects Law 1 (Scanner) violation."""
        violations = self.detector.check_against_laws(
            "Let's skip scan on this conversation, no analysis needed"
        )
        law_ids = [v.law_id for v in violations]
        self.assertIn("LAW_1", law_ids)

    def test_check_against_laws_detects_law2_kill(self):
        """Detects Law 2 (Kill) violation."""
        violations = self.detector.check_against_laws(
            "We should keep everything and never kill any ideas"
        )
        law_ids = [v.law_id for v in violations]
        self.assertIn("LAW_2", law_ids)

    def test_check_against_laws_detects_law3_pain(self):
        """Detects Law 3 (Pain) violation."""
        violations = self.detector.check_against_laws(
            "Pain doesn't matter for this project, ignore pain signals"
        )
        law_ids = [v.law_id for v in violations]
        self.assertIn("LAW_3", law_ids)

    def test_check_against_laws_detects_law4_score(self):
        """Detects Law 4 (Score) violation."""
        violations = self.detector.check_against_laws(
            "Don't score this, just go with feelings only"
        )
        law_ids = [v.law_id for v in violations]
        self.assertIn("LAW_4", law_ids)

    def test_check_against_laws_detects_law5_evidence(self):
        """Detects Law 5 (Evidence) violation."""
        violations = self.detector.check_against_laws(
            "No evidence needed for this decision, trust blindly"
        )
        law_ids = [v.law_id for v in violations]
        self.assertIn("LAW_5", law_ids)

    def test_check_against_laws_multiple_violations(self):
        """Detects multiple law violations in one text."""
        violations = self.detector.check_against_laws(
            "Keep everything, never kill ideas. Don't score anything. No evidence needed."
        )
        self.assertGreaterEqual(len(violations), 2)

    def test_check_against_laws_returns_law_violation_objects(self):
        """Returns LawViolation dataclass instances."""
        violations = self.detector.check_against_laws("Trust blindly without proof")
        self.assertGreater(len(violations), 0)
        v = violations[0]
        self.assertIsInstance(v, LawViolation)
        self.assertEqual(v.severity, "critical")
        self.assertIsNotNone(v.principle)

    def test_check_against_laws_empty_string(self):
        """Empty recommendation returns no violations."""
        violations = self.detector.check_against_laws("")
        self.assertEqual(len(violations), 0)

    # ------------------------------------------------------------------
    # getHistory tests
    # ------------------------------------------------------------------

    def test_get_history_empty(self):
        """getHistory() returns empty list when no contradictions logged."""
        history = self.detector.get_history()
        self.assertEqual(len(history), 0)

    def test_get_history_after_detection(self):
        """getHistory() returns logged contradictions."""
        self.detector.check_decision(
            decision={"description": "Don't score anything, feelings only"},
            domain="business",
        )
        history = self.detector.get_history()
        self.assertGreater(len(history), 0)
        self.assertTrue(history[0].has_contradiction)

    def test_get_history_filter_by_domain(self):
        """getHistory() can filter by domain."""
        self.detector.check_decision(
            decision={"description": "Don't score this, feelings only"},
            domain="finance",
        )
        self.detector.check_decision(
            decision={"description": "Skip scoring here too, feelings only"},
            domain="health",
        )
        finance_history = self.detector.get_history(domain="finance")
        self.assertTrue(
            all(h.domain == "finance" for h in finance_history)
        )

    def test_get_history_filter_by_severity(self):
        """getHistory() can filter by severity."""
        self.detector.check_decision(
            decision={"description": "No evidence needed, trust blindly"},
            domain="business",
        )
        critical = self.detector.get_history(severity="critical")
        self.assertTrue(all(h.severity == "critical" for h in critical))

    # ------------------------------------------------------------------
    # getConsistencyScore tests
    # ------------------------------------------------------------------

    def test_consistency_score_perfect(self):
        """No contradictions = 100.0 consistency score."""
        score = self.detector.get_consistency_score()
        self.assertEqual(score, 100.0)

    def test_consistency_score_decreases_with_contradictions(self):
        """Score decreases after contradictions are logged."""
        self.detector.check_decision(
            decision={"description": "Don't score, feelings only"},
            domain="business",
        )
        score = self.detector.get_consistency_score()
        self.assertLess(score, 100.0)

    def test_consistency_score_domain_filter(self):
        """Score can be filtered by domain."""
        self.detector.check_decision(
            decision={"description": "Skip scoring, feelings only"},
            domain="finance",
        )
        finance_score = self.detector.get_consistency_score(domain="finance")
        other_score = self.detector.get_consistency_score(domain="health")
        self.assertLess(finance_score, 100.0)
        self.assertEqual(other_score, 100.0)

    def test_consistency_score_range(self):
        """Score is between 0 and 100."""
        score = self.detector.get_consistency_score()
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    # ------------------------------------------------------------------
    # Data class tests
    # ------------------------------------------------------------------

    def test_contradiction_result_to_dict(self):
        """ContradictionResult.to_dict() returns a dict."""
        result = self.detector.check_decision(
            decision={"description": "Test decision"},
            domain="test",
        )
        d = result.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("has_contradiction", d)
        self.assertIn("severity", d)
        self.assertIn("domain", d)

    def test_law_violation_to_dict(self):
        """LawViolation.to_dict() returns a dict."""
        v = LawViolation(
            law_id="LAW_1",
            law_name="Test Law",
            principle="Test principle",
            violation_text="Test violation",
        )
        d = v.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("law_id", d)

    def test_master_laws_contains_five_laws(self):
        """MASTER_LAWS has exactly 5 laws."""
        self.assertEqual(len(MASTER_LAWS), 5)


if __name__ == "__main__":
    unittest.main()
