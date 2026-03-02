"""ProjectManager — Project and task lifecycle intelligence for aeOS.

Tracks execution velocity, burndown, blockers, and portfolio health.
Feeds DECISION_ENGINE prioritisation.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Optional


class ProjectManager:
    """Project and portfolio intelligence layer.

    Reads Project_Execution_Log to compute health signals.
    Feeds DECISION_ENGINE prioritisation.
    """

    def velocity(
        self,
        project_id: str,
        log_entries: List[dict],
        window_days: int = 7,
    ) -> dict:
        """Rolling average tasks completed per day over window.

        Returns:
            {velocity: float, window_days: int,
             tasks_in_window: int, trend: 'improving'|'declining'|'stable'}
        """
        if not isinstance(log_entries, list) or not log_entries:
            return {
                "velocity": 0.0,
                "window_days": window_days,
                "tasks_in_window": 0,
                "trend": "stable",
            }

        now = time.time()
        cutoff = now - (window_days * 86400)

        completed = [
            e
            for e in log_entries
            if isinstance(e, dict)
            and str(e.get("status", "")).lower() == "completed"
            and float(e.get("completed_at", e.get("timestamp", 0))) > cutoff
        ]

        tasks_in_window = len(completed)
        velocity = tasks_in_window / max(window_days, 1)

        # Trend: compare first half vs second half of window
        mid = now - (window_days * 86400 / 2)
        first_half = len(
            [
                e
                for e in completed
                if float(e.get("completed_at", e.get("timestamp", 0))) <= mid
            ]
        )
        second_half = tasks_in_window - first_half

        if second_half > first_half * 1.2:
            trend = "improving"
        elif second_half < first_half * 0.8:
            trend = "declining"
        else:
            trend = "stable"

        return {
            "velocity": round(velocity, 4),
            "window_days": window_days,
            "tasks_in_window": tasks_in_window,
            "trend": trend,
        }

    def burndown(
        self,
        project_id: str,
        total_tasks: int,
        completed_tasks: List[dict],
        deadline: str,
    ) -> dict:
        """Ideal vs actual burndown curve.

        Returns:
            {ideal: list[float], actual: list[float],
             projected_end: str, variance_days: float, on_track: bool}
        """
        if total_tasks <= 0:
            return {
                "ideal": [],
                "actual": [],
                "projected_end": deadline,
                "variance_days": 0.0,
                "on_track": True,
            }

        try:
            deadline_dt = datetime.fromisoformat(deadline)
        except (ValueError, TypeError):
            deadline_dt = datetime.now()

        now = datetime.now()
        total_days = max((deadline_dt - now).days, 1)

        # Ideal burndown (linear)
        ideal = [
            round(total_tasks * (1 - i / total_days), 2)
            for i in range(total_days + 1)
        ]

        # Actual burndown based on completion timestamps
        completed_count = len(completed_tasks) if completed_tasks else 0
        remaining = total_tasks - completed_count

        # Simplified actual curve
        actual = [float(total_tasks)]
        if completed_count > 0:
            step = completed_count / max(total_days, 1)
            for i in range(1, total_days + 1):
                val = total_tasks - min(step * i, completed_count)
                actual.append(round(max(val, remaining), 2))
        else:
            actual = [float(total_tasks)] * (total_days + 1)

        # Projected end
        if completed_count > 0:
            rate = completed_count / max(total_days, 1)
            if rate > 0:
                days_needed = remaining / rate
                variance = days_needed - total_days
            else:
                variance = float(total_days)
        else:
            variance = float(total_days)

        on_track = variance <= total_days * 0.1

        return {
            "ideal": ideal[:20],  # Cap for sanity
            "actual": actual[:20],
            "projected_end": deadline,
            "variance_days": round(variance, 1),
            "on_track": on_track,
        }

    def blocker_analysis(
        self, project_id: str, blockers: List[dict]
    ) -> dict:
        """Analyze blockers by category.

        Returns:
            {count_by_category: dict[str, int], avg_duration_days: float,
             estimated_delay_days: float, top_blocker_type: str}
        """
        if not isinstance(blockers, list) or not blockers:
            return {
                "count_by_category": {},
                "avg_duration_days": 0.0,
                "estimated_delay_days": 0.0,
                "top_blocker_type": "none",
            }

        by_category: Dict[str, int] = {}
        durations: List[float] = []

        for b in blockers:
            if not isinstance(b, dict):
                continue
            cat = str(b.get("category", b.get("type", "unknown")))
            by_category[cat] = by_category.get(cat, 0) + 1

            duration = float(b.get("duration_days", 0))
            if duration > 0:
                durations.append(duration)

        avg_duration = (
            sum(durations) / len(durations) if durations else 0.0
        )
        top_type = max(by_category, key=by_category.get) if by_category else "none"  # type: ignore
        estimated_delay = avg_duration * len(blockers) * 0.3  # heuristic

        return {
            "count_by_category": by_category,
            "avg_duration_days": round(avg_duration, 2),
            "estimated_delay_days": round(estimated_delay, 2),
            "top_blocker_type": top_type,
        }

    def portfolio_health(self, projects: List[dict]) -> dict:
        """Aggregate across all active projects.

        Returns:
            {total, by_status, avg_completion_pct, at_risk, total_blockers,
             health_score}
        """
        if not isinstance(projects, list) or not projects:
            return {
                "total": 0,
                "by_status": {},
                "avg_completion_pct": 0.0,
                "at_risk": [],
                "total_blockers": 0,
                "health_score": 0.0,
            }

        by_status: Dict[str, int] = {}
        completions: List[float] = []
        at_risk: List[str] = []
        total_blockers = 0

        for p in projects:
            if not isinstance(p, dict):
                continue
            status = str(p.get("status", "unknown"))
            by_status[status] = by_status.get(status, 0) + 1

            comp = float(p.get("completion_pct", 0))
            completions.append(comp)

            blockers = int(p.get("blocker_count", 0))
            total_blockers += blockers

            # At risk: behind schedule or high blocker count
            if p.get("behind_schedule") or blockers > 3:
                pid = str(p.get("project_id", p.get("name", "unknown")))
                at_risk.append(pid)

        avg_comp = sum(completions) / len(completions) if completions else 0.0

        # Health score heuristic
        risk_ratio = len(at_risk) / len(projects) if projects else 0
        health = max(1.0 - risk_ratio - (total_blockers * 0.02), 0.0)

        return {
            "total": len(projects),
            "by_status": by_status,
            "avg_completion_pct": round(avg_comp, 2),
            "at_risk": at_risk,
            "total_blockers": total_blockers,
            "health_score": round(min(health, 1.0), 4),
        }

    def milestone_risk(
        self,
        project_id: str,
        milestones: List[dict],
        current_velocity: float,
    ) -> List[dict]:
        """For each upcoming milestone, probability of on-time delivery.

        Returns:
            list[{milestone_id, name, due_date,
                  on_time_probability, risk_level}]
        """
        if not isinstance(milestones, list) or not milestones:
            return []

        results = []
        for ms in milestones:
            if not isinstance(ms, dict):
                continue
            remaining = int(ms.get("remaining_tasks", 0))
            days_until = float(ms.get("days_until_due", 0))

            if current_velocity > 0 and days_until > 0:
                needed_velocity = remaining / days_until
                ratio = current_velocity / needed_velocity if needed_velocity > 0 else 2.0
                prob = min(ratio, 1.0)
            elif remaining == 0:
                prob = 1.0
            else:
                prob = 0.0

            if prob >= 0.8:
                risk = "low"
            elif prob >= 0.5:
                risk = "medium"
            else:
                risk = "high"

            results.append({
                "milestone_id": str(ms.get("milestone_id", "")),
                "name": str(ms.get("name", "")),
                "due_date": str(ms.get("due_date", "")),
                "on_time_probability": round(prob, 4),
                "risk_level": risk,
            })

        return results

    def get_alerts(
        self, project_id: str, project_data: dict
    ) -> List[dict]:
        """Return active alerts for a project.

        Alert types: overdue_milestone, velocity_drop, blocker_surge,
                    resource_conflict.
        """
        if not isinstance(project_data, dict):
            return []

        alerts = []

        # Overdue milestones
        milestones = project_data.get("milestones", [])
        for ms in milestones:
            if isinstance(ms, dict) and ms.get("overdue"):
                alerts.append({
                    "type": "overdue_milestone",
                    "severity": "high",
                    "message": f"Milestone '{ms.get('name', '')}' is overdue",
                    "data": ms,
                })

        # Velocity drop
        velocity_drop = float(project_data.get("velocity_drop_pct", 0))
        if velocity_drop > 30:
            alerts.append({
                "type": "velocity_drop",
                "severity": "medium",
                "message": f"Velocity dropped {velocity_drop:.0f}% below 30-day avg",
                "data": {"drop_pct": velocity_drop},
            })

        # Blocker surge
        blocker_count = int(project_data.get("new_blockers_7d", 0))
        prev_blockers = int(project_data.get("prev_blockers_7d", 1))
        if prev_blockers > 0 and blocker_count >= prev_blockers * 2:
            alerts.append({
                "type": "blocker_surge",
                "severity": "high",
                "message": f"Blocker count surged: {blocker_count} vs {prev_blockers} prev week",
                "data": {"current": blocker_count, "previous": prev_blockers},
            })

        return alerts
