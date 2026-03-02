"""Tests for DecisionEngine"""
import pytest
from src.cognitive.decision_engine import DecisionEngine


def test_recommend_returns_3_ranked():
    de = DecisionEngine()
    result = de.recommend({"runway_months": 4, "pipeline_value": 50000})
    recs = result["recommendations"]
    assert len(recs) == 3
    assert recs[0]["rank"] == 1
    assert recs[1]["rank"] == 2
    assert recs[2]["rank"] == 3


def test_compare_options_ranks_by_weighted_score():
    de = DecisionEngine()
    options = [
        {"name": "A", "cost": 3, "quality": 8},
        {"name": "B", "cost": 7, "quality": 9},
    ]
    criteria = [
        {"name": "cost", "weight": 1.0, "higher_is_better": False},
        {"name": "quality", "weight": 2.0, "higher_is_better": True},
    ]
    result = de.compare_options(options, criteria)
    assert result["winner"] in ("A", "B")
    assert len(result["ranked"]) == 2


def test_risk_assessment_valid_severity():
    de = DecisionEngine()
    result = de.assess_risk("d1", {
        "risk_factors": [
            {"factor": "market", "probability": 0.8, "impact": 0.9},
        ]
    })
    assert result["overall_risk"] in ("low", "medium", "high")
    assert result["go_no_go"] in ("go", "caution", "no-go")


def test_feedback_recording():
    de = DecisionEngine()
    assert de.record_feedback("d1", "accepted", "Worked well") is True


def test_empty_context_safe_defaults():
    de = DecisionEngine()
    result = de.recommend({})
    assert len(result["recommendations"]) == 3
    for rec in result["recommendations"]:
        assert rec["confidence"] > 0


def test_history_returned():
    de = DecisionEngine()
    de.recommend({"runway_months": 12})
    de.recommend({"pipeline_value": 100000})
    history = de.get_recommendation_history()
    assert len(history) == 2
