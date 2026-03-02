"""PM_BOARD screen — Single-project deep dive view for aeOS.

Aggregates PROJECT_MGR and DECISION_ENGINE data for burndown,
task list, blocker log, milestone timeline, and risk assessment.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from src.cognitive.project_mgr import ProjectManager
from src.cognitive.decision_engine import DecisionEngine


class PMBoard:
    """PM_BOARD screen data provider.

    Aggregates PROJECT_MGR, DECISION_ENGINE for single-project view.
    """

    def __init__(
        self,
        project_mgr: Optional[ProjectManager] = None,
        decision_engine: Optional[DecisionEngine] = None,
    ) -> None:
        self._pm = project_mgr or ProjectManager()
        self._de = decision_engine or DecisionEngine()

    def get_project_view(
        self, project_id: str, project_data: dict
    ) -> dict:
        """Full PM_BOARD data bundle for a single project.

        Returns:
            {project_id, name, status, completion_pct, burndown,
             velocity, blockers, milestones, active_alerts,
             risk_assessment, next_action}
        """
        if not isinstance(project_data, dict):
            return self._empty_view(project_id)

        name = str(project_data.get("name", project_id))
        status = str(project_data.get("status", "unknown"))
        completion_pct = float(project_data.get("completion_pct", 0))

        # Velocity
        log_entries = project_data.get("log_entries", [])
        velocity = self._pm.velocity(project_id, log_entries)

        # Burndown
        total_tasks = int(project_data.get("total_tasks", 0))
        completed_tasks = project_data.get("completed_tasks", [])
        deadline = str(project_data.get("deadline", ""))
        burndown = self._pm.burndown(
            project_id, total_tasks, completed_tasks, deadline
        )

        # Blockers
        blocker_list = project_data.get("blockers", [])
        blockers = self._pm.blocker_analysis(project_id, blocker_list)

        # Milestones with risk
        milestones_raw = project_data.get("milestones", [])
        milestones = self._pm.milestone_risk(
            project_id, milestones_raw, velocity.get("velocity", 0)
        )

        # Alerts
        alerts = self._pm.get_alerts(project_id, project_data)

        # Risk assessment
        risk = self._de.assess_risk(project_id, project_data)

        # Next action
        context = {
            "project_health": {
                "velocity": velocity.get("velocity", 0),
                "completion": completion_pct,
                "blockers": blockers.get("count_by_category", {}),
            },
            "runway_months": project_data.get("runway_months", 12),
        }
        recommendation = self._de.recommend(context)
        next_action = (
            recommendation["recommendations"][0]
            if recommendation.get("recommendations")
            else {}
        )

        return {
            "project_id": project_id,
            "name": name,
            "status": status,
            "completion_pct": completion_pct,
            "burndown": burndown,
            "velocity": velocity,
            "blockers": blockers,
            "milestones": milestones,
            "active_alerts": alerts,
            "risk_assessment": risk,
            "next_action": next_action,
        }

    def get_task_list(
        self,
        project_id: str,
        tasks: List[dict],
        filter_status: Optional[str] = None,
    ) -> List[dict]:
        """Return filtered, sorted task list.

        Sorted: blocked first, then by priority, then by due date.
        """
        if not isinstance(tasks, list):
            return []

        filtered = []
        for t in tasks:
            if not isinstance(t, dict):
                continue
            if filter_status and str(t.get("status", "")) != filter_status:
                continue
            filtered.append(t)

        def sort_key(task: dict) -> tuple:
            is_blocked = 0 if str(task.get("status", "")).lower() == "blocked" else 1
            priority = int(task.get("priority", 99))
            due = str(task.get("due_date", "9999-12-31"))
            return (is_blocked, priority, due)

        return sorted(filtered, key=sort_key)

    def get_milestone_timeline(
        self,
        project_id: str,
        milestones: List[dict],
        current_velocity: float,
    ) -> List[dict]:
        """Return milestones enriched with risk levels and projected dates."""
        return self._pm.milestone_risk(
            project_id, milestones, current_velocity
        )

    @staticmethod
    def _empty_view(project_id: str) -> dict:
        return {
            "project_id": project_id,
            "name": project_id,
            "status": "unknown",
            "completion_pct": 0.0,
            "burndown": {},
            "velocity": {},
            "blockers": {},
            "milestones": [],
            "active_alerts": [],
            "risk_assessment": {},
            "next_action": {},
        }
