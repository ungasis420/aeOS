"""
Tests for aeOS Phase 4 — Offline_Mode (A3)
============================================
Tests getStatus, getDegradedResponse, getCapabilities, onConnectivityChange.
Uses manual availability overrides to avoid real network calls.
"""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.offline_mode import (
    CapabilityMap,
    ConnectivityStatus,
    DegradationLevel,
    DegradedResponse,
    OfflineMode,
    TIER_NAMES,
)


class TestOfflineMode(unittest.TestCase):
    """Test suite for Offline_Mode."""

    def setUp(self):
        """Create a temporary database and OfflineMode instance."""
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_aeos.db")

        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS Offline_Mode_Log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                previous_state TEXT NOT NULL,
                new_state TEXT NOT NULL,
                tiers_available TEXT NOT NULL DEFAULT '[]',
                trigger_reason TEXT,
                duration_ms INTEGER
            );
        """)
        conn.commit()
        conn.close()

        # Create with all services unavailable (avoid real network checks)
        self.offline = OfflineMode(
            db_path=self.db_path,
            ollama_url="http://localhost:99999",  # won't connect
            groq_available=False,
            claude_available=False,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # getStatus tests
    # ------------------------------------------------------------------

    def test_get_status_returns_connectivity_status(self):
        """getStatus() returns a ConnectivityStatus."""
        status = self.offline.get_status()
        self.assertIsInstance(status, ConnectivityStatus)

    def test_get_status_has_required_fields(self):
        """ConnectivityStatus has all required fields."""
        status = self.offline.get_status()
        self.assertIsNotNone(status.level)
        self.assertIsInstance(status.tiers_available, list)
        self.assertIsInstance(status.internet_available, bool)
        self.assertIsInstance(status.ollama_available, bool)
        self.assertIsNotNone(status.checked_at)
        self.assertIsNotNone(status.response_source)

    def test_get_status_sovereign_core_when_nothing_available(self):
        """Status is SOVEREIGN_CORE_ONLY when no services available."""
        # Force everything off
        self.offline.set_ollama_available(False)
        self.offline.set_internet_available(False)
        self.offline.set_groq_available(False)
        self.offline.set_claude_available(False)
        status = self.offline.get_status()
        self.assertEqual(status.level, DegradationLevel.SOVEREIGN_CORE_ONLY)
        self.assertIn(0, status.tiers_available)

    def test_get_status_local_only_with_ollama(self):
        """Status is LOCAL_ONLY when Ollama available but no internet."""
        self.offline.set_ollama_available(True)
        self.offline.set_internet_available(False)
        status = self.offline.get_status()
        self.assertEqual(status.level, DegradationLevel.LOCAL_ONLY)
        self.assertIn(1, status.tiers_available)

    def test_get_status_cloud_restricted_with_internet(self):
        """Status is CLOUD_RESTRICTED with internet but no Claude."""
        self.offline.set_internet_available(True)
        self.offline.set_claude_available(False)
        status = self.offline.get_status()
        self.assertEqual(status.level, DegradationLevel.CLOUD_RESTRICTED)

    def test_get_status_full_with_claude(self):
        """Status is FULL when Claude is available."""
        self.offline.set_ollama_available(True)
        self.offline.set_internet_available(True)
        self.offline.set_groq_available(True)
        self.offline.set_claude_available(True)
        status = self.offline.get_status()
        self.assertEqual(status.level, DegradationLevel.FULL)
        self.assertIn(5, status.tiers_available)

    def test_get_status_tier0_always_available(self):
        """Tier 0 (sovereign core) is always available."""
        status = self.offline.get_status()
        self.assertIn(0, status.tiers_available)

    # ------------------------------------------------------------------
    # getDegradedResponse tests
    # ------------------------------------------------------------------

    def test_get_degraded_response_returns_degraded_response(self):
        """getDegradedResponse() returns a DegradedResponse."""
        response = self.offline.get_degraded_response("What should I focus on?")
        self.assertIsInstance(response, DegradedResponse)

    def test_get_degraded_response_tier0_when_offline(self):
        """Returns Tier 0 response when fully offline."""
        self.offline.set_ollama_available(False)
        self.offline.set_internet_available(False)
        response = self.offline.get_degraded_response("Test query")
        self.assertEqual(response.response_source, "sovereign_core")
        self.assertEqual(response.tier_reached, 0)
        self.assertTrue(response.offline_capable)

    def test_get_degraded_response_tier1_with_ollama(self):
        """Returns Tier 1 response when Ollama available."""
        self.offline.set_ollama_available(True)
        self.offline.set_internet_available(False)
        response = self.offline.get_degraded_response("Test query")
        self.assertEqual(response.response_source, "local_llm")
        self.assertEqual(response.tier_reached, 1)
        self.assertTrue(response.offline_capable)

    def test_get_degraded_response_includes_query(self):
        """Response content references the query."""
        response = self.offline.get_degraded_response("My important question")
        self.assertIn("My important question", response.content)

    def test_get_degraded_response_confidence_scales(self):
        """Higher tiers produce higher confidence."""
        self.offline.set_ollama_available(False)
        self.offline.set_internet_available(False)
        response_t0 = self.offline.get_degraded_response("test")

        self.offline.set_ollama_available(True)
        response_t1 = self.offline.get_degraded_response("test")

        self.assertLess(response_t0.confidence, response_t1.confidence)

    def test_get_degraded_response_has_degradation_level(self):
        """Response includes current degradation level."""
        response = self.offline.get_degraded_response("test")
        self.assertIn(response.degradation_level, [
            DegradationLevel.FULL,
            DegradationLevel.CLOUD_RESTRICTED,
            DegradationLevel.LOCAL_ONLY,
            DegradationLevel.SOVEREIGN_CORE_ONLY,
            DegradationLevel.EMPTY,
        ])

    # ------------------------------------------------------------------
    # getCapabilities tests
    # ------------------------------------------------------------------

    def test_get_capabilities_returns_capability_map(self):
        """getCapabilities() returns a CapabilityMap."""
        caps = self.offline.get_capabilities()
        self.assertIsInstance(caps, CapabilityMap)

    def test_get_capabilities_always_has_core(self):
        """KB search, pattern recognition, cartridge reasoning always available."""
        caps = self.offline.get_capabilities()
        self.assertTrue(caps.kb_search)
        self.assertTrue(caps.pattern_recognition)
        self.assertTrue(caps.cartridge_reasoning)

    def test_get_capabilities_local_llm_reflects_ollama(self):
        """local_llm capability matches Ollama availability."""
        self.offline.set_ollama_available(False)
        caps = self.offline.get_capabilities()
        self.assertFalse(caps.local_llm)

        self.offline.set_ollama_available(True)
        caps = self.offline.get_capabilities()
        self.assertTrue(caps.local_llm)

    def test_get_capabilities_web_search_reflects_internet(self):
        """web_search capability matches internet availability."""
        self.offline.set_internet_available(False)
        caps = self.offline.get_capabilities()
        self.assertFalse(caps.web_search)

        self.offline.set_internet_available(True)
        caps = self.offline.get_capabilities()
        self.assertTrue(caps.web_search)

    def test_get_capabilities_paid_api_reflects_claude(self):
        """paid_cloud_api matches Claude availability."""
        self.offline.set_claude_available(False)
        caps = self.offline.get_capabilities()
        self.assertFalse(caps.paid_cloud_api)

        self.offline.set_claude_available(True)
        caps = self.offline.get_capabilities()
        self.assertTrue(caps.paid_cloud_api)

    def test_get_capabilities_has_level(self):
        """CapabilityMap includes current degradation level."""
        caps = self.offline.get_capabilities()
        self.assertIsNotNone(caps.level)

    # ------------------------------------------------------------------
    # onConnectivityChange tests
    # ------------------------------------------------------------------

    def test_on_connectivity_change_returns_subscription_id(self):
        """onConnectivityChange() returns a subscription ID string."""
        sub_id = self.offline.on_connectivity_change(lambda s: None)
        self.assertIsInstance(sub_id, str)
        self.assertGreater(len(sub_id), 0)

    def test_on_connectivity_change_notifies_subscriber(self):
        """Subscriber callback is called when connectivity changes."""
        callback = MagicMock()
        self.offline.on_connectivity_change(callback)

        # Trigger a state change
        self.offline.set_ollama_available(True)
        callback.assert_called()
        status = callback.call_args[0][0]
        self.assertIsInstance(status, ConnectivityStatus)

    def test_unsubscribe_stops_notifications(self):
        """unsubscribe() removes the callback."""
        callback = MagicMock()
        sub_id = self.offline.on_connectivity_change(callback)
        self.offline.unsubscribe(sub_id)

        # Reset call count
        callback.reset_mock()

        # Force a state change that would trigger notification
        self.offline.set_ollama_available(False)
        self.offline.set_ollama_available(True)
        # After unsubscribe, should NOT be called (or only from internal level update)
        # We need to be careful: set_ollama_available triggers _update_level
        # which calls _notify_subscribers only if level changed.
        # Since we unsubscribed, callback should not be called.
        callback.assert_not_called()

    def test_multiple_subscribers(self):
        """Multiple subscribers all get notified."""
        cb1 = MagicMock()
        cb2 = MagicMock()
        self.offline.on_connectivity_change(cb1)
        self.offline.on_connectivity_change(cb2)

        self.offline.set_ollama_available(True)
        cb1.assert_called()
        cb2.assert_called()

    # ------------------------------------------------------------------
    # Manual override tests
    # ------------------------------------------------------------------

    def test_set_ollama_available(self):
        """set_ollama_available updates status."""
        self.offline.set_ollama_available(True)
        status = self.offline.get_status()
        self.assertTrue(status.ollama_available)

    def test_set_internet_available(self):
        """set_internet_available updates status."""
        self.offline.set_internet_available(True)
        status = self.offline.get_status()
        self.assertTrue(status.internet_available)

    def test_set_groq_available(self):
        """set_groq_available updates tiers."""
        self.offline.set_internet_available(True)  # needed for groq tier
        self.offline.set_groq_available(True)
        status = self.offline.get_status()
        self.assertTrue(status.groq_available)
        self.assertIn(4, status.tiers_available)

    def test_set_claude_available(self):
        """set_claude_available upgrades to FULL."""
        self.offline.set_claude_available(True)
        status = self.offline.get_status()
        self.assertTrue(status.claude_available)
        self.assertEqual(status.level, DegradationLevel.FULL)

    # ------------------------------------------------------------------
    # Data class tests
    # ------------------------------------------------------------------

    def test_connectivity_status_to_dict(self):
        """ConnectivityStatus.to_dict() returns a dict."""
        status = self.offline.get_status()
        d = status.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("level", d)
        self.assertIn("tiers_available", d)

    def test_degraded_response_to_dict(self):
        """DegradedResponse.to_dict() returns a dict."""
        response = self.offline.get_degraded_response("test")
        d = response.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("response_source", d)

    def test_capability_map_to_dict(self):
        """CapabilityMap.to_dict() returns a dict."""
        caps = self.offline.get_capabilities()
        d = caps.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("kb_search", d)

    def test_tier_names_has_six_entries(self):
        """TIER_NAMES has entries for tiers 0-5."""
        self.assertEqual(len(TIER_NAMES), 6)
        for i in range(6):
            self.assertIn(i, TIER_NAMES)

    def test_degradation_level_constants(self):
        """DegradationLevel has all expected constants."""
        self.assertEqual(DegradationLevel.FULL, "FULL")
        self.assertEqual(DegradationLevel.CLOUD_RESTRICTED, "CLOUD_RESTRICTED")
        self.assertEqual(DegradationLevel.LOCAL_ONLY, "LOCAL_ONLY")
        self.assertEqual(DegradationLevel.SOVEREIGN_CORE_ONLY, "SOVEREIGN_CORE_ONLY")
        self.assertEqual(DegradationLevel.EMPTY, "EMPTY")


if __name__ == "__main__":
    unittest.main()
