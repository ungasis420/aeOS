"""
tests/test_agent_pain.py

Pytest unit tests for `src.agents.agent_pain`.

These tests use an in-memory SQLite DB and mock all local-LLM calls.
Stamp: S✅ T✅ L✅ A✅
"""

from __future__ import annotations

import os
import sqlite3
import sys
from unittest.mock import patch

import pytest

# Ensure repo root is importable when running `pytest` from different CWDs.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import src.agents.agent_pain as agent_pain


@pytest.fixture(autouse=True)
def _disable_optional_persistence(monkeypatch):
    """Disable optional persistence layer to keep tests deterministic."""
    monkeypatch.setattr(agent_pain, "pain_persist", None, raising=False)


@pytest.fixture()
def conn():
    """In-memory DB with the minimal Pain_Point_Register table."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    cur = c.cursor()
    cur.execute(
        """
        CREATE TABLE Pain_Point_Register (
            Pain_ID TEXT PRIMARY KEY,
            Pain_Name TEXT,
            Description TEXT,
            Root_Cause TEXT,
            Frequency REAL,
            Severity REAL,
            Impact_Score REAL,
            Monetizability_Flag INTEGER,
            Pain_Score REAL,
            Status TEXT
        );
        """
    )
    c.commit()
    yield c
    c.close()


def _insert_pain(
    c: sqlite3.Connection,
    *,
    pain_id: str,
    name: str,
    description: str,
    root_cause: str = "",
    frequency: float = 5.0,
    severity: float = 7.0,
    impact: float = 6.0,
    monetizable: int = 1,
    pain_score: float = 70.0,
    status: str = "Active",
) -> None:
    cur = c.cursor()
    cur.execute(
        """
        INSERT INTO Pain_Point_Register (
            Pain_ID, Pain_Name, Description, Root_Cause,
            Frequency, Severity, Impact_Score, Monetizability_Flag,
            Pain_Score, Status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (pain_id, name, description, root_cause, frequency, severity, impact, monetizable, pain_score, status),
    )
    c.commit()


def test_analyze_pain_returns_required_fields(conn):
    """analyze_pain() should return the required analysis fields."""
    pid = "PAIN-20260228-001"
    _insert_pain(
        conn,
        pain_id=pid,
        name="Dashboard lag",
        description="Dashboard is slow when loading sales metrics.",
        root_cause="",
        frequency=6,
        severity=8,
        impact=7,
        monetizable=1,
        pain_score=78,
    )

    fake = {
        "success": True,
        "data": {
            "root_cause": "Too many unindexed queries",
            "severity_assessment": {"label": "High", "score_estimate": 75, "rationale": "Repeated timeouts."},
            "recommended_actions": ["Add indexes", "Cache dashboard queries"],
            "confidence": 0.8,
        },
    }

    with patch.object(agent_pain, "build_pain_context", return_value="CTX"):
        with patch.object(agent_pain, "infer_json", return_value=fake):
            out = agent_pain.analyze_pain(conn, pid)

    assert isinstance(out, dict)
    for k in ("root_cause", "severity_assessment", "recommended_actions", "confidence"):
        assert k in out

    assert isinstance(out["root_cause"], str)
    assert isinstance(out["severity_assessment"], dict)
    assert isinstance(out["recommended_actions"], list)
    assert isinstance(out["confidence"], float)


def test_score_pain_with_ai_returns_numeric(conn):
    """score_pain_with_ai() should return a numeric ai_score in a stable range."""
    pain_dict = {
        "Pain_ID": "PAIN-20260228-002",
        "Pain_Name": "Dashboard refresh timeout",
        "Description": "Dashboard sometimes times out during refresh.",
        "Frequency": 6,
        "Severity": 7,
        "Impact_Score": 5,
        "Monetizability_Flag": 1,
        "Pain_Score": 65,
    }

    fake = {"success": True, "data": {"ai_score": 55, "reasoning": "Looks slightly overstated.", "agreement_with_calc": False}}

    # Keep calc deterministic for the test.
    with patch.object(agent_pain, "calculate_pain_score", side_effect=lambda sev, freq, monet, imp: 50.0):
        with patch.object(agent_pain, "build_portfolio_context", return_value="PORT"):
            with patch.object(agent_pain, "infer_json", return_value=fake):
                out = agent_pain.score_pain_with_ai(conn, pain_dict)

    assert isinstance(out, dict)
    assert "ai_score" in out

    ai_score = out["ai_score"]
    assert isinstance(ai_score, float)
    assert 0.0 <= ai_score <= 100.0


def test_detect_patterns_returns_list(conn):
    """detect_pain_patterns() should return a non-empty list when patterns exist."""
    # Important: avoid repeating the same token within a single record (name + description),
    # otherwise the baseline extractor may produce 3+ themes and attempt an LLM refinement.
    _insert_pain(conn, pain_id="PAIN-20260228-010", name="Dashboard lag", description="Slow on load", pain_score=70)
    _insert_pain(conn, pain_id="PAIN-20260228-011", name="Dashboard refresh", description="Timeout during update", pain_score=60)
    _insert_pain(conn, pain_id="PAIN-20260228-012", name="Dashboard filter", description="Bug in selector", pain_score=50)

    # Baseline extraction should return early (<3 themes) and NOT call the LLM.
    with patch.object(agent_pain, "infer_json", side_effect=AssertionError("infer_json should not be called for baseline<3")):
        patterns = agent_pain.detect_pain_patterns(conn)

    assert isinstance(patterns, list)
    assert patterns, "Expected at least one theme in patterns"


def test_generate_pain_summary_returns_string(conn):
    """generate_pain_summary() should return a string summary when infer succeeds."""
    _insert_pain(conn, pain_id="PAIN-20260228-020", name="Dashboard lag", description="Slow on load", pain_score=80)

    fake_infer = {"success": True, "response": "Pain Summary: focus on dashboard lag."}

    with patch.object(agent_pain, "build_portfolio_context", return_value="PORT"):
        with patch.object(agent_pain, "detect_pain_patterns", return_value=[]):
            with patch.object(agent_pain, "infer", return_value=fake_infer):
                summary = agent_pain.generate_pain_summary(conn)

    assert isinstance(summary, str)
    assert summary.strip() != ""
