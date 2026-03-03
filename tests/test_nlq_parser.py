"""
Tests for aeOS Phase 4 — NLQ_Parser (A5)
==========================================
Tests parse, getSuggestions, getExamples, train.
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

from src.core.nlq_parser import (
    EXAMPLE_QUERIES,
    IntentFeedback,
    IntentType,
    NLQParser,
    ParsedIntent,
)


class TestNLQParser(unittest.TestCase):
    """Test suite for NLQ_Parser."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_aeos.db")

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS NLQ_Parse_Log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_query TEXT NOT NULL,
                parsed_intent TEXT NOT NULL DEFAULT '{}',
                confidence REAL NOT NULL DEFAULT 0.0,
                routed_to TEXT,
                was_corrected INTEGER NOT NULL DEFAULT 0,
                correction TEXT,
                timestamp TEXT NOT NULL
            );
        """)
        conn.commit()
        conn.close()

        self.parser = NLQParser(db_path=self.db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # parse tests — intent classification
    # ------------------------------------------------------------------

    def test_parse_returns_parsed_intent(self):
        """parse() returns a ParsedIntent."""
        result = self.parser.parse("What should I focus on this week?")
        self.assertIsInstance(result, ParsedIntent)

    def test_parse_priority_query(self):
        """Parses priority-related queries."""
        result = self.parser.parse("What should I focus on today?")
        self.assertEqual(result.intent_type, IntentType.PRIORITY_QUERY)
        self.assertEqual(result.domain, "strategy")

    def test_parse_finance_status(self):
        """Parses finance-related queries."""
        result = self.parser.parse("How am I doing financially?")
        self.assertEqual(result.intent_type, IntentType.FINANCE_STATUS)
        self.assertEqual(result.domain, "finance")

    def test_parse_decision_request(self):
        """Parses decision-related queries."""
        result = self.parser.parse("Should I take this client project?")
        self.assertEqual(result.intent_type, IntentType.DECISION_REQUEST)
        self.assertEqual(result.domain, "decision")

    def test_parse_reflection(self):
        """Parses reflection queries."""
        result = self.parser.parse("What worked well last month?")
        self.assertEqual(result.intent_type, IntentType.REFLECTION)

    def test_parse_audit(self):
        """Parses audit queries."""
        result = self.parser.parse("What did aeOS do last week?")
        self.assertEqual(result.intent_type, IntentType.AUDIT)

    def test_parse_search(self):
        """Parses search queries."""
        result = self.parser.parse("What is the Hormozi Value Equation?")
        self.assertEqual(result.intent_type, IntentType.SEARCH)

    def test_parse_compare(self):
        """Parses comparison queries."""
        result = self.parser.parse("Compare SaaS vs consulting")
        self.assertEqual(result.intent_type, IntentType.COMPARE)

    def test_parse_forecast(self):
        """Parses forecast queries."""
        result = self.parser.parse("What if we double our marketing budget?")
        self.assertEqual(result.intent_type, IntentType.FORECAST)

    def test_parse_pain_analysis(self):
        """Parses pain analysis queries."""
        result = self.parser.parse("What are the biggest pain points?")
        self.assertEqual(result.intent_type, IntentType.PAIN_ANALYSIS)

    def test_parse_idea_scan(self):
        """Parses idea-related queries."""
        result = self.parser.parse("Scan for new business opportunities")
        self.assertEqual(result.intent_type, IntentType.IDEA_SCAN)

    def test_parse_backup(self):
        """Parses backup queries."""
        result = self.parser.parse("Create a backup now")
        self.assertEqual(result.intent_type, IntentType.BACKUP)

    def test_parse_status(self):
        """Parses system status queries."""
        result = self.parser.parse("Show system status dashboard")
        self.assertEqual(result.intent_type, IntentType.STATUS)

    def test_parse_help(self):
        """Parses help queries."""
        result = self.parser.parse("Help me understand commands")
        self.assertEqual(result.intent_type, IntentType.HELP)

    def test_parse_empty_string(self):
        """Empty string returns UNKNOWN intent."""
        result = self.parser.parse("")
        self.assertEqual(result.intent_type, IntentType.UNKNOWN)
        self.assertEqual(result.confidence, 0.0)

    def test_parse_whitespace_only(self):
        """Whitespace-only returns UNKNOWN intent."""
        result = self.parser.parse("   ")
        self.assertEqual(result.intent_type, IntentType.UNKNOWN)

    def test_parse_unknown_falls_to_search(self):
        """Unrecognized query falls back to SEARCH."""
        result = self.parser.parse("xyzzy plugh")
        self.assertEqual(result.intent_type, IntentType.SEARCH)
        self.assertEqual(result.routed_to, "kb_search")
        self.assertLess(result.confidence, 0.5)

    # ------------------------------------------------------------------
    # parse tests — routing and confidence
    # ------------------------------------------------------------------

    def test_parse_routes_to_correct_handler(self):
        """Parse routes to the correct handler."""
        result = self.parser.parse("What should I focus on this week?")
        self.assertEqual(result.routed_to, "priorities")

    def test_parse_confidence_above_zero(self):
        """Matched intent has confidence > 0."""
        result = self.parser.parse("What should I focus on today?")
        self.assertGreater(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)

    def test_parse_preserves_original_query(self):
        """ParsedIntent preserves the original query."""
        query = "Show me the dashboard"
        result = self.parser.parse(query)
        self.assertEqual(result.original_query, query)

    # ------------------------------------------------------------------
    # parse tests — parameter extraction
    # ------------------------------------------------------------------

    def test_parse_extracts_time_reference(self):
        """Extracts time reference parameter."""
        result = self.parser.parse("What should I focus on this week?")
        self.assertEqual(result.parameters.get("time_reference"), "this_week")

    def test_parse_extracts_numeric_params(self):
        """Extracts numeric parameters (e.g., 'top 5')."""
        result = self.parser.parse("What are my top 5 priorities?")
        self.assertEqual(result.parameters.get("count"), 5)
        self.assertEqual(result.parameters.get("count_type"), "top")

    def test_parse_extracts_domain_mention(self):
        """Extracts mentioned domain from query."""
        result = self.parser.parse("Tell me about my finance situation")
        self.assertEqual(result.parameters.get("mentioned_domain"), "finance")

    # ------------------------------------------------------------------
    # parse tests — logging
    # ------------------------------------------------------------------

    def test_parse_logs_to_db(self):
        """Parse results are logged to NLQ_Parse_Log."""
        self.parser.parse("What should I focus on today?")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM NLQ_Parse_Log").fetchall()
        conn.close()
        self.assertGreater(len(rows), 0)
        self.assertIn("focus", rows[0]["original_query"])

    # ------------------------------------------------------------------
    # getSuggestions tests
    # ------------------------------------------------------------------

    def test_get_suggestions_returns_list(self):
        """getSuggestions() returns a list."""
        suggestions = self.parser.get_suggestions("focus")
        self.assertIsInstance(suggestions, list)

    def test_get_suggestions_finds_matches(self):
        """getSuggestions() finds matching example queries."""
        suggestions = self.parser.get_suggestions("focus")
        self.assertGreater(len(suggestions), 0)
        self.assertTrue(any("focus" in s.lower() for s in suggestions))

    def test_get_suggestions_short_input(self):
        """getSuggestions() returns empty for very short input."""
        suggestions = self.parser.get_suggestions("a")
        self.assertEqual(len(suggestions), 0)

    def test_get_suggestions_no_match(self):
        """getSuggestions() returns empty for no-match input."""
        suggestions = self.parser.get_suggestions("xyzzyplugh")
        self.assertEqual(len(suggestions), 0)

    def test_get_suggestions_max_10(self):
        """getSuggestions() returns at most 10 results."""
        suggestions = self.parser.get_suggestions("the")
        self.assertLessEqual(len(suggestions), 10)

    # ------------------------------------------------------------------
    # getExamples tests
    # ------------------------------------------------------------------

    def test_get_examples_all_domains(self):
        """getExamples() returns examples from all domains."""
        examples = self.parser.get_examples()
        self.assertGreater(len(examples), 0)

    def test_get_examples_filtered_by_domain(self):
        """getExamples() filters by domain."""
        examples = self.parser.get_examples(domain="strategy")
        self.assertGreater(len(examples), 0)
        # All strategy examples should be from EXAMPLE_QUERIES["strategy"]
        expected = EXAMPLE_QUERIES["strategy"]
        for e in examples:
            self.assertIn(e, expected)

    def test_get_examples_unknown_domain(self):
        """getExamples() returns all examples for unknown domain."""
        examples = self.parser.get_examples(domain="nonexistent_domain")
        self.assertGreater(len(examples), 0)

    # ------------------------------------------------------------------
    # train tests
    # ------------------------------------------------------------------

    def test_train_learns_correction(self):
        """train() causes future parse to use corrected intent."""
        query = "xyzzy plugh"
        # Before training: unknown -> SEARCH fallback
        result_before = self.parser.parse(query)
        self.assertEqual(result_before.intent_type, IntentType.SEARCH)

        # Train with correction
        feedback = IntentFeedback(
            original_query=query,
            parsed_intent=IntentType.SEARCH,
            correct_intent=IntentType.PRIORITY_QUERY,
            correct_domain="strategy",
        )
        self.parser.train(feedback)

        # After training: should use corrected intent
        result_after = self.parser.parse(query)
        self.assertEqual(result_after.intent_type, IntentType.PRIORITY_QUERY)
        self.assertEqual(result_after.confidence, 0.95)

    def test_train_logs_correction_to_db(self):
        """train() logs the correction to NLQ_Parse_Log."""
        feedback = IntentFeedback(
            original_query="test query",
            parsed_intent=IntentType.SEARCH,
            correct_intent=IntentType.AUDIT,
            correct_domain="audit",
        )
        self.parser.train(feedback)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM NLQ_Parse_Log WHERE was_corrected = 1"
        ).fetchall()
        conn.close()
        self.assertGreater(len(rows), 0)

    # ------------------------------------------------------------------
    # Data class tests
    # ------------------------------------------------------------------

    def test_parsed_intent_to_dict(self):
        """ParsedIntent.to_dict() returns a dict."""
        result = self.parser.parse("What should I focus on?")
        d = result.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("intent_type", d)
        self.assertIn("confidence", d)
        self.assertIn("routed_to", d)

    def test_intent_feedback_to_dict(self):
        """IntentFeedback.to_dict() returns a dict."""
        feedback = IntentFeedback(
            original_query="test",
            parsed_intent="SEARCH",
            correct_intent="AUDIT",
            correct_domain="audit",
        )
        d = feedback.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("correct_intent", d)

    def test_intent_type_constants(self):
        """IntentType has all expected constants."""
        self.assertEqual(IntentType.PRIORITY_QUERY, "PRIORITY_QUERY")
        self.assertEqual(IntentType.FINANCE_STATUS, "FINANCE_STATUS")
        self.assertEqual(IntentType.UNKNOWN, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
