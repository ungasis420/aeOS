"""Tests for PMBoard screen"""
import pytest
from src.screens.pm_board import PMBoard


def test_project_view_returns_all_keys():
    board = PMBoard()
    data = {
        "name": "Project Alpha",
        "status": "active",
        "completion_pct": 65.0,
        "total_tasks": 20,
        "completed_tasks": [{"ts": 1}] * 13,
        "deadline": "2030-06-01",
        "log_entries": [],
        "blockers": [],
        "milestones": [],
    }
    view = board.get_project_view("p1", data)
    required_keys = [
        "project_id", "name", "status", "completion_pct",
        "burndown", "velocity", "blockers", "milestones",
        "active_alerts", "risk_assessment", "next_action",
    ]
    for key in required_keys:
        assert key in view


def test_task_list_sorts_blocked_first():
    board = PMBoard()
    tasks = [
        {"name": "T1", "status": "in_progress", "priority": 1, "due_date": "2030-01-01"},
        {"name": "T2", "status": "blocked", "priority": 2, "due_date": "2030-02-01"},
        {"name": "T3", "status": "completed", "priority": 3, "due_date": "2030-03-01"},
    ]
    sorted_tasks = board.get_task_list("p1", tasks)
    assert sorted_tasks[0]["status"] == "blocked"


def test_milestone_timeline_enriches_with_risk():
    board = PMBoard()
    milestones = [
        {"milestone_id": "m1", "name": "Launch", "due_date": "2030-06-01",
         "remaining_tasks": 10, "days_until_due": 30},
    ]
    result = board.get_milestone_timeline("p1", milestones, 0.5)
    assert len(result) == 1
    assert "risk_level" in result[0]


def test_empty_project_safe_defaults():
    board = PMBoard()
    view = board.get_project_view("p1", {})
    assert view["project_id"] == "p1"
    assert view["status"] == "unknown"


def test_status_propagates():
    board = PMBoard()
    data = {
        "name": "Test",
        "status": "paused",
        "completion_pct": 30.0,
        "total_tasks": 0,
        "deadline": "2030-01-01",
    }
    view = board.get_project_view("p1", data)
    assert view["status"] == "paused"


def test_filter_tasks():
    board = PMBoard()
    tasks = [
        {"name": "T1", "status": "active", "priority": 1},
        {"name": "T2", "status": "blocked", "priority": 2},
    ]
    active = board.get_task_list("p1", tasks, filter_status="active")
    assert len(active) == 1
    assert active[0]["name"] == "T1"
