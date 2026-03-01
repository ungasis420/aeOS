"""
tests/test_agent_graph.py

Phase 5 tests for src/agents/agent_graph.py
Uses pytest + unittest.mock — no real DB or Ollama connections.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.agents.agent_graph import (
    find_connections,
    build_entity_graph,
    traverse_from_pain,
    find_root_causes_across_portfolio,
    suggest_leverage_points,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn(fetchall=None, fetchone=None):
    """Return a minimal MagicMock mimicking sqlite3.Connection."""
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
    return kb


# ---------------------------------------------------------------------------
# find_connections
# ---------------------------------------------------------------------------

@patch("src.agents.agent_graph.infer")
def test_find_connections_returns_dict(mock_infer):
    mock_infer.return_value = {"response": "test insight", "success": True}
    conn = _make_conn()
    result = find_connections(conn, _make_kb_conn(), "client acquisition")
    assert isinstance(result, dict)


@patch("src.agents.agent_graph.infer")
def test_find_connections_has_required_keys(mock_infer):
    mock_infer.return_value = {"response": "insight text", "success": True}
    conn = _make_conn()
    result = find_connections(conn, _make_kb_conn(), "client acquisition")
    assert result.get("success") is True
    assert "concept" in result
    assert "direct_matches" in result
    assert "related_concepts" in result
    assert "cross_domain_insights" in result


@patch("src.agents.agent_graph.infer")
def test_find_connections_empty_concept_returns_error(mock_infer):
    """Blank concept should fail gracefully."""
    mock_infer.return_value = {"response": "", "success": True}
    conn = _make_conn()
    result = find_connections(conn, _make_kb_conn(), "")
    assert isinstance(result, dict)
    # Must never raise; success=False is acceptable for empty input
    assert "success" in result


# ---------------------------------------------------------------------------
# build_entity_graph
# ---------------------------------------------------------------------------

@patch("src.agents.agent_graph.infer")
def test_build_entity_graph_returns_node_count(mock_infer):
    mock_infer.return_value = {"response": "{}", "success": True}
    conn = _make_conn(fetchall=[
        (1, "Revenue drop", "open", 8.0),
        (2, "Slow hiring", "open", 6.5),
    ])
    result = build_entity_graph(conn)
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert "node_count" in result or "nodes" in result


@patch("src.agents.agent_graph.infer")
def test_build_entity_graph_empty_db_still_succeeds(mock_infer):
    mock_infer.return_value = {"response": "{}", "success": True}
    conn = _make_conn(fetchall=[])
    result = build_entity_graph(conn)
    assert isinstance(result, dict)
    assert result.get("success") is True


# ---------------------------------------------------------------------------
# traverse_from_pain
# ---------------------------------------------------------------------------

@patch("src.agents.agent_graph.infer")
def test_traverse_from_pain_returns_required_fields(mock_infer):
    mock_infer.return_value = {"response": "traversal insight", "success": True}
    conn = _make_conn(fetchall=[])
    result = traverse_from_pain(conn, _make_kb_conn(), pain_id=1)
    assert isinstance(result, dict)
    assert result.get("success") is True
    for key in ("pain_id", "solutions", "predictions", "mental_models", "insight"):
        assert key in result, f"Missing key: {key}"


@patch("src.agents.agent_graph.infer")
def test_traverse_from_pain_with_data_rows(mock_infer):
    mock_infer.return_value = {"response": "deep insight", "success": True}
    conn = _make_conn(fetchall=[
        (1, "Sol A", "active"),
        (2, "Sol B", "pending"),
    ])
    result = traverse_from_pain(conn, _make_kb_conn(), pain_id=42)
    assert isinstance(result, dict)
    assert "pain_id" in result


# ---------------------------------------------------------------------------
# find_root_causes_across_portfolio
# ---------------------------------------------------------------------------

@patch("src.agents.agent_graph.infer")
def test_find_root_causes_returns_clusters(mock_infer):
    mock_infer.return_value = {"response": '{"clusters": []}', "success": True}
    conn = _make_conn(fetchall=[
        (1, "Cash flow issue", "finance", 9.0),
        (2, "Team morale", "hr", 7.0),
        (3, "Lead gen stalled", "sales", 8.5),
    ])
    result = find_root_causes_across_portfolio(conn, _make_kb_conn())
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert "root_cause_clusters" in result


@patch("src.agents.agent_graph.infer")
def test_find_root_causes_empty_portfolio(mock_infer):
    mock_infer.return_value = {"response": "{}", "success": True}
    conn = _make_conn(fetchall=[])
    result = find_root_causes_across_portfolio(conn, _make_kb_conn())
    assert isinstance(result, dict)
    assert result.get("success") is True


# ---------------------------------------------------------------------------
# suggest_leverage_points
# ---------------------------------------------------------------------------

@patch("src.agents.agent_graph.infer")
def test_suggest_leverage_points_returns_list(mock_infer):
    mock_infer.return_value = {
        "response": '{"leverage_points": [{"point": "Fix onboarding", "impact": "high"}]}',
        "success": True,
    }
    conn = _make_conn(fetchall=[
        (1, "Onboarding slow", "ops", 8.0),
    ])
    result = suggest_leverage_points(conn, _make_kb_conn())
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert "leverage_points" in result
    assert isinstance(result["leverage_points"], list)


@patch("src.agents.agent_graph.infer")
def test_suggest_leverage_points_offline_fallback(mock_infer):
    """LLM returning garbage should still produce a valid result."""
    mock_infer.return_value = {"response": "NOT JSON !!!", "success": True}
    conn = _make_conn(fetchall=[
        (1, "Tech debt", "eng", 7.0),
        (2, "No docs", "eng", 6.0),
    ])
    result = suggest_leverage_points(conn, _make_kb_conn())
    assert isinstance(result, dict)
    assert result.get("success") is True

# S✅ T✅ L✅ A✅
