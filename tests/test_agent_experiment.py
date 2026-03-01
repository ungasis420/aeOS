"""
tests/test_agent_experiment.py

Phase 5 tests for src/agents/agent_experiment.py
Uses pytest + unittest.mock — no real DB or Ollama connections.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.agents.agent_experiment import (
    design_experiment,
    evaluate_experiment,
    list_active_experiments,
    generate_hypothesis,
    get_experiment_insights,
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
    kb = MagicMock()
    kb.list_collections.return_value = []
    return kb


# ---------------------------------------------------------------------------
# create_experiment  (maps to "design_experiment" in test spec)
# ---------------------------------------------------------------------------

@patch("src.agents.agent_experiment.infer_json")
@patch("src.agents.agent_experiment.infer")
def test_design_experiment_returns_required_fields(mock_infer, mock_infer_json):
    mock_infer.return_value = {"response": "experiment design text", "success": True}
    mock_infer_json.return_value = {
        "success": True,
        "data": {
            "hypothesis": "Reducing onboarding steps will improve activation by 20%",
            "test_design": "A/B test: current flow vs. 3-step flow",
            "duration_days": 14,
            "success_criteria": "Activation rate >= 20% improvement",
        },
    }
    conn = _make_conn()
    result = design_experiment(conn, pain_id=1)
    assert isinstance(result, dict)
    assert result.get("success") is True
    for key in ("pain_id", "hypothesis", "test_design", "duration_days", "success_criteria"):
        assert key in result, f"Missing key: {key}"


@patch("src.agents.agent_experiment.infer_json")
@patch("src.agents.agent_experiment.infer")
def test_design_experiment_missing_pain_id_fails_gracefully(mock_infer, mock_infer_json):
    mock_infer.return_value = {"response": "", "success": True}
    mock_infer_json.return_value = {"success": False, "error": "no data"}
    conn = _make_conn()
    result = design_experiment(conn, pain_id=None)
    assert isinstance(result, dict)
    assert "success" in result


# ---------------------------------------------------------------------------
# update_experiment  (maps to "evaluate_experiment" in test spec)
# ---------------------------------------------------------------------------

@patch("src.agents.agent_experiment.infer_json")
@patch("src.agents.agent_experiment.infer")
def test_evaluate_experiment_returns_outcome(mock_infer, mock_infer_json):
    mock_infer.return_value = {"response": "experiment concluded", "success": True}
    mock_infer_json.return_value = {
        "success": True,
        "data": {"outcome": "Activation improved by 23%", "learning": "Shorter flow works"},
    }
    # evaluate_experiment uses _fetch_one_dict which needs cursor.description
    conn = MagicMock()
    cursor = MagicMock()
    cursor.description = [
        ("experiment_id",), ("pain_id",), ("hypothesis",), ("test_design",),
        ("duration_days",), ("start_date",), ("success_criteria",), ("status",),
        ("outcome",), ("learning",),
    ]
    cursor.fetchone.return_value = (
        "exp-uuid-001", 1, "Test hyp", "design", 14, "2025-01-01", "20% lift", "active", None, None
    )
    cursor.fetchall.return_value = []
    conn.cursor.return_value = cursor
    result = evaluate_experiment(conn, experiment_id="exp-uuid-001")
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert "outcome" in result or "experiment_id" in result


@patch("src.agents.agent_experiment.infer")
def test_evaluate_experiment_nonexistent_id(mock_infer):
    mock_infer.return_value = {"response": "", "success": True}
    conn = _make_conn(fetchone=None)
    result = evaluate_experiment(conn, experiment_id="does-not-exist")
    assert isinstance(result, dict)
    assert "success" in result


# ---------------------------------------------------------------------------
# list_active_experiments
# ---------------------------------------------------------------------------

@patch("src.agents.agent_experiment.infer")
def test_list_active_experiments_returns_categorized(mock_infer):
    mock_infer.return_value = {"response": "", "success": True}
    # Simulate rows: (experiment_id, pain_id, hypothesis, test_design, duration_days,
    #                  start_date, success_criteria, status, outcome, learning, created_at)
    rows = [
        ("exp-001", 1, "Hyp A", "Design A", 7, "2025-01-01", "10% lift", "active", None, None, "2025-01-01"),
        ("exp-002", 2, "Hyp B", "Design B", 14, "2024-12-01", "20% lift", "success", "Met", "Good", "2024-12-01"),
        ("exp-003", 3, "Hyp C", "Design C", 7, "2024-11-01", "5% lift", "failure", "Missed", "Bad", "2024-11-01"),
    ]
    conn = _make_conn(fetchall=rows)
    result = list_active_experiments(conn)
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert "active" in result
    assert "overdue" in result
    assert "completed" in result
    assert isinstance(result["active"], list)
    assert isinstance(result["overdue"], list)
    assert isinstance(result["completed"], list)


@patch("src.agents.agent_experiment.infer")
def test_list_active_experiments_empty_db(mock_infer):
    mock_infer.return_value = {"response": "", "success": True}
    conn = _make_conn(fetchall=[])
    result = list_active_experiments(conn)
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert result["active"] == []
    assert result["completed"] == []


# ---------------------------------------------------------------------------
# generate_hypothesis
# ---------------------------------------------------------------------------

@patch("src.agents.agent_experiment.infer_json")
@patch("src.agents.agent_experiment.infer")
def test_generate_hypothesis_returns_three_hypotheses(mock_infer, mock_infer_json):
    mock_infer.return_value = {"response": "", "success": True}
    mock_infer_json.return_value = {
        "success": True,
        "data": {
            "topic": "sales conversion",
            "hypotheses": [
                {"statement": "H1", "rationale": "R1", "testability_score": 0.8, "suggested_test": "T1"},
                {"statement": "H2", "rationale": "R2", "testability_score": 0.7, "suggested_test": "T2"},
                {"statement": "H3", "rationale": "R3", "testability_score": 0.6, "suggested_test": "T3"},
            ],
        },
    }
    conn = _make_conn()
    result = generate_hypothesis(conn, _make_kb_conn(), "sales conversion")
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert "hypotheses" in result
    hyps = result["hypotheses"]
    assert isinstance(hyps, list)
    assert len(hyps) == 3


@patch("src.agents.agent_experiment.infer_json")
@patch("src.agents.agent_experiment.infer")
def test_generate_hypothesis_llm_offline_uses_fallback(mock_infer, mock_infer_json):
    """LLM fails → built-in default hypotheses must be returned."""
    mock_infer.return_value = {"success": False, "error": "offline"}
    mock_infer_json.return_value = {"success": False, "error": "offline"}
    conn = _make_conn()
    result = generate_hypothesis(conn, _make_kb_conn(), "onboarding friction")
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert len(result.get("hypotheses", [])) == 3


# ---------------------------------------------------------------------------
# get_experiment_insights
# ---------------------------------------------------------------------------

@patch("src.agents.agent_experiment.infer_json")
@patch("src.agents.agent_experiment.infer")
def test_get_experiment_insights_returns_stats(mock_infer, mock_infer_json):
    mock_infer.return_value = {"response": "", "success": True}
    mock_infer_json.return_value = {
        "success": True,
        "data": {
            "patterns": ["Short experiments succeed more often"],
            "key_learnings": ["Baseline measurement is critical"],
        },
    }
    rows = [
        ("exp-001", 1, "Hyp A", "Design", "10% lift", "success", "Result A", "Learning A", "2025-01-10"),
        ("exp-002", 2, "Hyp B", "Design", "20% lift", "failure", "Result B", "Learning B", "2025-01-05"),
        ("exp-003", 3, "Hyp C", "Design", "5% lift", "success", "Result C", "Learning C", "2025-01-01"),
    ]
    conn = _make_conn(fetchall=rows)
    result = get_experiment_insights(conn)
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert "total_experiments" in result
    assert "success_rate" in result
    assert "key_learnings" in result
    assert isinstance(result["key_learnings"], list)


@patch("src.agents.agent_experiment.infer")
def test_get_experiment_insights_empty_db(mock_infer):
    mock_infer.return_value = {"response": "", "success": True}
    conn = _make_conn(fetchall=[])
    result = get_experiment_insights(conn)
    assert isinstance(result, dict)
    assert result.get("success") is True
    assert result.get("total_experiments") == 0

# S✅ T✅ L✅ A✅
