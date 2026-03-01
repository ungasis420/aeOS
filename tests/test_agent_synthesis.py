"""
tests/test_agent_synthesis.py

Phase 5 tests for src/agents/agent_synthesis.py
Uses pytest + unittest.mock — no real DB or Ollama connections.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.agents.agent_synthesis import (
    synthesize_kb,
    synthesize_week,
    cross_domain_synthesis,
    generate_synthesis_report,
    save_synthesis,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn(fetchall=None, fetchone=None):
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = fetchall if fetchall is not None else []
    cursor.fetchone.return_value = fetchone
    conn.cursor.return_value = cursor
    return conn


def _make_kb_conn():
    """Return a MagicMock that satisfies ChromaDB / dict-style kb_conn."""
    kb = MagicMock()
    kb.list_collections.return_value = []
    # Simulate query() returning an empty result set
    kb.query.return_value = {"documents": [[]], "metadatas": [[]], "ids": [[]]}
    return kb


# ---------------------------------------------------------------------------
# synthesize_kb
# ---------------------------------------------------------------------------

@patch("src.agents.agent_synthesis.infer_json")
@patch("src.agents.agent_synthesis.infer")
def test_synthesize_kb_returns_themes(mock_infer, mock_infer_json):
    mock_infer.return_value = {"response": "synthesis output", "success": True}
    mock_infer_json.return_value = {
        "success": True,
        "response": {
            "themes": [
                {"theme": "Revenue growth", "strength": "high", "evidence": ["Record Q1"]},
                {"theme": "Cost reduction", "strength": "medium", "evidence": ["Ops cuts"]},
            ],
            "summary": "Two dominant themes identified.",
        },
    }
    result = synthesize_kb(_make_kb_conn())
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert "themes" in result
    assert isinstance(result["themes"], list)


@patch("src.agents.agent_synthesis.infer")
def test_synthesize_kb_empty_kb_still_succeeds(mock_infer):
    mock_infer.return_value = {"response": "", "success": True}
    result = synthesize_kb(_make_kb_conn())
    assert isinstance(result, dict)
    assert result.get("success") is True


# ---------------------------------------------------------------------------
# synthesize_week
# ---------------------------------------------------------------------------

@patch("src.agents.agent_synthesis.infer_json")
@patch("src.agents.agent_synthesis.infer")
def test_synthesize_week_returns_period_data(mock_infer, mock_infer_json):
    mock_infer.return_value = {"response": "weekly synthesis", "success": True}
    mock_infer_json.return_value = {
        "success": True,
        "response": {
            "period": "2025-01-13 to 2025-01-20",
            "weekly_insight": "Momentum building in sales funnel.",
            "emerging_patterns": ["Pattern A", "Pattern B"],
            "recommended_focus": "Double down on outreach.",
        },
    }
    rows = [
        (1, "Pain A", "open", 8.0, "2025-01-15"),
        (2, "Pain B", "active", 6.0, "2025-01-17"),
    ]
    conn = _make_conn(fetchall=rows)
    result = synthesize_week(conn, _make_kb_conn())
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert "period" in result
    assert "weekly_insight" in result or "emerging_patterns" in result


@patch("src.agents.agent_synthesis.infer")
def test_synthesize_week_empty_db(mock_infer):
    mock_infer.return_value = {"response": "", "success": True}
    conn = _make_conn(fetchall=[])
    result = synthesize_week(conn, _make_kb_conn())
    assert isinstance(result, dict)
    assert result.get("success") is True


# ---------------------------------------------------------------------------
# cross_domain_synthesis
# ---------------------------------------------------------------------------

@patch("src.agents.agent_synthesis.infer_json")
@patch("src.agents.agent_synthesis.infer")
def test_cross_domain_synthesis_returns_insights(mock_infer, mock_infer_json):
    mock_infer.return_value = {"response": "cross-domain output", "success": True}
    mock_infer_json.return_value = {
        "success": True,
        "response": {
            "domain_pairs": [["business", "personal"]],
            "insights": [
                {
                    "domains": ["business", "personal"],
                    "connection": "Focus techniques transfer across domains",
                    "application": "Apply pomodoro to client delivery blocks",
                    "confidence": 0.75,
                }
            ],
        },
    }
    conn = _make_conn(fetchall=[])
    result = cross_domain_synthesis(conn, _make_kb_conn())
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert "insights" in result
    assert isinstance(result["insights"], list)


@patch("src.agents.agent_synthesis.infer")
def test_cross_domain_synthesis_offline_fallback(mock_infer):
    """LLM offline → keyword overlap heuristic should still return a valid result."""
    mock_infer.return_value = {"success": False, "error": "connection refused"}
    conn = _make_conn(fetchall=[])
    result = cross_domain_synthesis(conn, _make_kb_conn())
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert "insights" in result


# ---------------------------------------------------------------------------
# generate_synthesis_report
# ---------------------------------------------------------------------------

@patch("src.agents.agent_synthesis.synthesize_kb")
@patch("src.agents.agent_synthesis.synthesize_week")
@patch("src.agents.agent_synthesis.cross_domain_synthesis")
def test_generate_synthesis_report_has_all_sections(
    mock_cross, mock_week, mock_kb
):
    mock_kb.return_value = {
        "success": True,
        "themes": [{"theme": "T1", "strength": "high", "evidence": ["E1"]}],
    }
    mock_week.return_value = {
        "success": True,
        "period": "2025-01-13 to 2025-01-20",
        "weekly_insight": "Strong momentum.",
        "emerging_patterns": ["Rapid iteration paying off"],
        "recommended_focus": "Invest in outreach.",
    }
    mock_cross.return_value = {
        "success": True,
        "domain_pairs": [["business", "personal"]],
        "insights": [
            {
                "domains": ["business", "personal"],
                "connection": "Focus tools apply across contexts",
                "application": "Use time-boxing in client work",
                "confidence": 0.7,
            }
        ],
    }

    conn = _make_conn()
    result = generate_synthesis_report(conn, _make_kb_conn())
    assert isinstance(result, dict)
    assert result.get("success") is True

    # Required sections
    assert "report" in result
    assert "themes" in result
    assert "patterns" in result
    assert "recommended_actions" in result

    report_text = result["report"]
    assert isinstance(report_text, str)
    assert len(report_text) > 0

    # Report must contain section headers
    assert "KB Themes" in report_text or "Weekly" in report_text


@patch("src.agents.agent_synthesis.synthesize_kb")
@patch("src.agents.agent_synthesis.synthesize_week")
@patch("src.agents.agent_synthesis.cross_domain_synthesis")
def test_generate_synthesis_report_handles_empty_subsystems(
    mock_cross, mock_week, mock_kb
):
    mock_kb.return_value = {"success": True, "themes": []}
    mock_week.return_value = {"success": True, "period": "", "weekly_insight": "", "emerging_patterns": [], "recommended_focus": ""}
    mock_cross.return_value = {"success": True, "domain_pairs": [], "insights": []}
    conn = _make_conn()
    result = generate_synthesis_report(conn, _make_kb_conn())
    assert isinstance(result, dict)
    assert result.get("success") is True


# ---------------------------------------------------------------------------
# save_synthesis
# ---------------------------------------------------------------------------

@patch("src.agents.agent_synthesis.infer")
def test_save_synthesis_returns_synthesis_id(mock_infer):
    mock_infer.return_value = {"response": "", "success": True}
    conn = _make_conn()
    payload = {
        "report": "# Test Report\n\nContent here.",
        "themes": [{"theme": "Growth", "strength": "high", "evidence": []}],
        "patterns": ["Pattern A"],
        "recommended_actions": ["Action 1"],
    }
    result = save_synthesis(conn, payload)
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert "synthesis_id" in result
    assert isinstance(result["synthesis_id"], str)
    assert len(result["synthesis_id"]) > 0


@patch("src.agents.agent_synthesis.infer")
def test_save_synthesis_null_conn_returns_error(mock_infer):
    mock_infer.return_value = {"response": "", "success": True}
    result = save_synthesis(None, {"report": "test"})
    assert isinstance(result, dict)
    assert result.get("success") is False

# S✅ T✅ L✅ A✅
