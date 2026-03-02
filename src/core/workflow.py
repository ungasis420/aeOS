"""Workflow — Multi-step task orchestration for aeOS.

Sequences operations across modules with defined transitions,
error handling, and resume capability.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class WorkflowStep:
    """A single step in a workflow."""
    name: str
    handler: Callable
    on_success: Optional[str] = None  # next step name
    on_error: Optional[str] = None    # error step name
    timeout_seconds: float = 30.0


class Workflow:
    """Multi-step job with defined transitions and error handling.

    Resumable after crash via PERSIST.
    """

    def __init__(
        self, workflow_id: str, steps: List[WorkflowStep]
    ) -> None:
        if not isinstance(workflow_id, str) or not workflow_id.strip():
            raise ValueError("workflow_id must be a non-empty string")
        if not isinstance(steps, list) or not steps:
            raise ValueError("steps must be a non-empty list")

        self.workflow_id = workflow_id
        self._steps: Dict[str, WorkflowStep] = {}
        self._step_order: List[str] = []
        for step in steps:
            self._steps[step.name] = step
            self._step_order.append(step.name)

        self._status = "pending"
        self._steps_completed: List[str] = []
        self._context: Dict[str, Any] = {}
        self._error: Optional[str] = None
        self._start_time: Optional[float] = None
        self._end_time: Optional[float] = None

    def run(self, initial_context: Optional[dict] = None) -> dict:
        """Execute workflow from start step.

        Returns:
            {workflow_id: str, status: 'completed'|'failed'|'paused',
             steps_completed: list[str], final_context: dict,
             error: str|None, duration_seconds: float}
        """
        self._start_time = time.time()
        self._status = "running"
        self._context = dict(initial_context) if initial_context else {}
        self._steps_completed = []
        self._error = None

        current_step_name = self._step_order[0]

        while current_step_name:
            step = self._steps.get(current_step_name)
            if step is None:
                self._error = f"Step not found: {current_step_name}"
                self._status = "failed"
                break

            try:
                result = step.handler(self._context)
                if isinstance(result, dict):
                    self._context.update(result)
                self._steps_completed.append(step.name)

                # Determine next step
                if step.on_success and step.on_success in self._steps:
                    current_step_name = step.on_success
                else:
                    # Try sequential next
                    idx = self._step_order.index(step.name)
                    if idx + 1 < len(self._step_order):
                        current_step_name = self._step_order[idx + 1]
                    else:
                        current_step_name = None  # workflow complete

            except Exception as exc:
                self._error = f"Step '{step.name}' failed: {str(exc)}"
                if step.on_error and step.on_error in self._steps:
                    current_step_name = step.on_error
                else:
                    self._status = "failed"
                    break

        if self._status == "running":
            self._status = "completed"

        self._end_time = time.time()
        duration = self._end_time - self._start_time

        return {
            "workflow_id": self.workflow_id,
            "status": self._status,
            "steps_completed": list(self._steps_completed),
            "final_context": dict(self._context),
            "error": self._error,
            "duration_seconds": round(duration, 4),
        }

    def resume(self, from_step: str, context: dict) -> dict:
        """Resume a paused/failed workflow from a specific step."""
        if from_step not in self._steps:
            return {
                "workflow_id": self.workflow_id,
                "status": "failed",
                "steps_completed": list(self._steps_completed),
                "final_context": dict(context),
                "error": f"Step not found: {from_step}",
                "duration_seconds": 0.0,
            }

        # Rebuild step order from the resume point
        idx = self._step_order.index(from_step)
        resume_steps = [
            self._steps[name] for name in self._step_order[idx:]
        ]

        resumed_wf = Workflow(self.workflow_id, resume_steps)
        return resumed_wf.run(context)

    def get_status(self) -> dict:
        """Return current workflow state and progress."""
        total = len(self._step_order)
        completed = len(self._steps_completed)
        return {
            "workflow_id": self.workflow_id,
            "status": self._status,
            "total_steps": total,
            "completed_steps": completed,
            "progress_pct": round(
                (completed / total * 100) if total > 0 else 0, 1
            ),
            "current_step": (
                self._steps_completed[-1]
                if self._steps_completed
                else self._step_order[0] if self._step_order else None
            ),
            "error": self._error,
        }


class WorkflowRegistry:
    """Manages workflow definitions and execution history."""

    def __init__(self) -> None:
        self._definitions: Dict[str, List[WorkflowStep]] = {}
        self._instances: Dict[str, Workflow] = {}
        self._history: Dict[str, dict] = {}

    def register(
        self, workflow_id: str, steps: List[WorkflowStep]
    ) -> None:
        """Register a reusable workflow definition."""
        if not isinstance(workflow_id, str) or not workflow_id.strip():
            raise ValueError("workflow_id must be a non-empty string")
        if not isinstance(steps, list) or not steps:
            raise ValueError("steps must be a non-empty list")
        self._definitions[workflow_id] = list(steps)

    def create_instance(self, workflow_id: str) -> Workflow:
        """Instantiate a registered workflow."""
        if workflow_id not in self._definitions:
            raise ValueError(f"Workflow '{workflow_id}' not registered")
        instance_id = f"{workflow_id}_{uuid.uuid4().hex[:8]}"
        wf = Workflow(instance_id, self._definitions[workflow_id])
        self._instances[instance_id] = wf
        return wf

    def list_workflows(self) -> List[dict]:
        """Return registered workflow definitions.

        Returns:
            [{workflow_id, step_count, last_run, status}]
        """
        result = []
        for wf_id, steps in self._definitions.items():
            last_run = self._history.get(wf_id, {}).get("last_run")
            status = self._history.get(wf_id, {}).get("status", "never_run")
            result.append({
                "workflow_id": wf_id,
                "step_count": len(steps),
                "last_run": last_run,
                "status": status,
            })
        return result
