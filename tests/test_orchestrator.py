"""
tests/test_orchestrator.py

Pytest unit tests for `src.orchestrator.orchestrator`.

All external dependencies are mocked (DB file, KB connect, Ollama pings).
Stamp: S✅ T✅ L✅ A✅
"""

from __future__ import annotations

import os
import sqlite3
import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure repo root is importable when running `pytest` from different CWDs.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import src.orchestrator.orchestrator as orchestrator


@pytest.fixture()
def orch():
    """Orchestrator instance wired to in-memory DB + mocked KB + mocked Ollama."""
    conn = sqlite3.connect(":memory:")
    kb = MagicMock()

    with patch.object(orchestrator, "_connect_db", return_value=conn):
        with patch.object(orchestrator, "_connect_kb", return_value=kb):
            with patch.object(orchestrator, "_ollama_ok", return_value=True):
                o = orchestrator.Orchestrator(db_path=":memory:", kb_path="kb")
                try:
                    yield o
                finally:
                    o.close()


def test_orchestrator_initializes_cleanly(orch):
    """Orchestrator should initialize and expose a complete status snapshot."""
    status = orch.get_status()
    assert isinstance(status, dict)

    # Status contract.
    for k in ("ollama_connected", "agents_loaded", "db_connected", "kb_connected", "version"):
        assert k in status

    assert status["db_connected"] is True
    assert status["kb_connected"] is True
    assert status["agents_loaded"] is True
    assert status["ollama_connected"] is True


def test_process_routes_pain_query(orch):
    """process() should route pain_analysis intent to agent_pain."""
    detect = {"intent": "pain_analysis", "confidence": 0.99, "suggested_agent": "ai_infer"}

    with patch.object(orch.router, "detect_intent", return_value=detect):
        # Stub handler so we don't depend on DB schema or LLM calls.
        with patch.object(orch, "_handle_pain_intent", return_value={"success": True, "response": "OK"}) as h:
            out = orch.process("Analyze PAIN-20260228-001")

    assert isinstance(out, dict)
    assert out.get("agent_used") == "agent_pain"
    assert out.get("intent") == "pain_analysis"
    assert out.get("success") is True
    assert h.call_count == 1


def test_daily_briefing_returns_string(orch):
    """run_daily_briefing() should return a non-empty string."""
    with patch.object(orch.agent_pain, "generate_pain_summary", return_value="Pain Summary: ok"):
        with patch.object(
            orch.agent_solution,
            "suggest_quick_wins",
            return_value=[{"solution_id": "SOL-20260228-001", "title": "Cache dashboard", "impact_score": 7, "effort_score": 2}],
        ):
            with patch.object(orch.agent_prediction, "get_calibration_insight", return_value="Calibration: stable"):
                briefing = orch.run_daily_briefing()

    assert isinstance(briefing, str)
    assert briefing.strip() != ""


def test_get_status_returns_all_keys(orch):
    """get_status() must include the full key set for health checks."""
    status = orch.get_status()
    assert set(status.keys()) >= {"ollama_connected", "agents_loaded", "db_connected", "kb_connected", "version"}
