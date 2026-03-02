"""Tests for ProjectManager"""
import time
import pytest
from src.cognitive.project_mgr import ProjectManager


def test_velocity_returns_float():
    pm = ProjectManager()
    now = time.time()
    entries = [
        {"status": "completed", "timestamp": now - 86400},
        {"status": "completed", "timestamp": now - 86400 * 2},
    ]
    result = pm.velocity("p1", entries, window_days=7)
    assert isinstance(result["velocity"], float)
    assert result["velocity"] > 0


def test_burndown_shows_ideal_line():
    pm = ProjectManager()
    result = pm.burndown("p1", 10, [{"ts": 1}] * 3, "2030-01-01")
    assert result["ideal"]
    assert result["ideal"][0] == 10.0


def test_blocker_analysis_counts_by_category():
    pm = ProjectManager()
    blockers = [
        {"category": "tech", "duration_days": 2},
        {"category": "tech", "duration_days": 3},
        {"category": "people", "duration_days": 1},
    ]
    result = pm.blocker_analysis("p1", blockers)
    assert result["count_by_category"]["tech"] == 2
    assert result["count_by_category"]["people"] == 1
    assert result["top_blocker_type"] == "tech"


def test_portfolio_health_flags_at_risk():
    pm = ProjectManager()
    projects = [
        {"project_id": "p1", "status": "active", "completion_pct": 80,
         "blocker_count": 0},
        {"project_id": "p2", "status": "active", "completion_pct": 20,
         "blocker_count": 5, "behind_schedule": True},
    ]
    result = pm.portfolio_health(projects)
    assert "p2" in result["at_risk"]
    assert result["total"] == 2


def test_velocity_drop_alert():
    pm = ProjectManager()
    alerts = pm.get_alerts("p1", {
        "velocity_drop_pct": 50,
        "milestones": [],
    })
    assert any(a["type"] == "velocity_drop" for a in alerts)


def test_milestone_risk():
    pm = ProjectManager()
    milestones = [
        {"milestone_id": "m1", "name": "Launch", "due_date": "2030-06-01",
         "remaining_tasks": 10, "days_until_due": 30},
    ]
    result = pm.milestone_risk("p1", milestones, current_velocity=0.5)
    assert len(result) == 1
    assert "risk_level" in result[0]


def test_empty_entries_safe():
    pm = ProjectManager()
    result = pm.velocity("p1", [], window_days=7)
    assert result["velocity"] == 0.0
    assert result["trend"] == "stable"
