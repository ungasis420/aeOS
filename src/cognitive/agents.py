"""Agents — Autonomous task execution framework for aeOS.

Agents combine AI calls, data queries, and module operations into
goal-directed sequences without per-step user input.
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentType(Enum):
    RESEARCH = "research"    # gather and synthesise data
    ANALYSIS = "analysis"    # run analytics pipeline
    REPORT = "report"        # generate formatted output


class Agent:
    """Goal-directed autonomous task executor.

    All agent runs logged. Human approval required for write operations
    outside sandbox.
    """

    def __init__(
        self,
        agent_type: AgentType,
        goal: str,
        sandbox: bool = True,
    ) -> None:
        self.agent_id = str(uuid.uuid4())
        self.agent_type = agent_type
        self.goal = str(goal)
        self.sandbox = sandbox
        self._status = "created"
        self._steps: List[dict] = []
        self._output: Any = None
        self._pending_approvals: List[dict] = []
        self._log: List[str] = []
        self._created_at = time.time()
        self._start_time: Optional[float] = None
        self._end_time: Optional[float] = None

    def run(self, context: Optional[dict] = None) -> dict:
        """Execute agent toward goal.

        Returns:
            {agent_id, type, goal, status, steps_taken, output,
             requires_approval, duration_seconds, log}
        """
        self._start_time = time.time()
        self._status = "running"
        self._log.append(f"Agent started: {self.goal}")
        ctx = dict(context) if context else {}

        try:
            # Simulate agent execution steps based on type
            if self.agent_type == AgentType.RESEARCH:
                self._execute_research(ctx)
            elif self.agent_type == AgentType.ANALYSIS:
                self._execute_analysis(ctx)
            elif self.agent_type == AgentType.REPORT:
                self._execute_report(ctx)

            if self._pending_approvals:
                self._status = "pending_approval"
            else:
                self._status = "completed"

        except Exception as exc:
            self._status = "failed"
            self._log.append(f"Agent failed: {str(exc)}")
            self._output = {"error": str(exc)}

        self._end_time = time.time()
        duration = self._end_time - self._start_time

        return {
            "agent_id": self.agent_id,
            "type": self.agent_type.value,
            "goal": self.goal,
            "status": self._status,
            "steps_taken": list(self._steps),
            "output": self._output,
            "requires_approval": bool(self._pending_approvals),
            "duration_seconds": round(duration, 4),
            "log": list(self._log),
        }

    def get_status(self) -> dict:
        """Return current agent state and progress."""
        return {
            "agent_id": self.agent_id,
            "type": self.agent_type.value,
            "goal": self.goal,
            "status": self._status,
            "steps_completed": len(self._steps),
            "pending_approvals": len(self._pending_approvals),
            "created_at": self._created_at,
        }

    def _add_step(self, name: str, result: Any) -> None:
        self._steps.append({
            "step": name,
            "result": result,
            "timestamp": time.time(),
        })
        self._log.append(f"Step completed: {name}")

    def _request_write_approval(self, action: str, data: Any) -> None:
        if not self.sandbox:
            approval = {
                "action_id": str(uuid.uuid4()),
                "action": action,
                "data": data,
                "status": "pending",
                "requested_at": time.time(),
            }
            self._pending_approvals.append(approval)
            self._log.append(f"Write approval requested: {action}")

    def _execute_research(self, ctx: dict) -> None:
        self._add_step("gather_data", {"sources": ctx.get("sources", [])})
        self._add_step("analyze", {"summary": f"Research on: {self.goal}"})
        self._output = {
            "type": "research",
            "summary": f"Research completed for: {self.goal}",
            "findings": ctx.get("findings", []),
        }

    def _execute_analysis(self, ctx: dict) -> None:
        self._add_step("load_data", {"records": ctx.get("record_count", 0)})
        self._add_step("compute", {"metrics": ctx.get("metrics", {})})
        self._output = {
            "type": "analysis",
            "summary": f"Analysis completed for: {self.goal}",
            "results": ctx.get("results", {}),
        }

    def _execute_report(self, ctx: dict) -> None:
        self._add_step("compile", {"sections": ctx.get("sections", [])})
        if ctx.get("write_to_file"):
            self._request_write_approval(
                "write_report", {"path": ctx.get("output_path", "report.md")}
            )
        self._output = {
            "type": "report",
            "summary": f"Report generated for: {self.goal}",
            "content": ctx.get("content", ""),
        }


class AgentOrchestrator:
    """Manages agent lifecycle and approval gates."""

    def __init__(self) -> None:
        self._agents: Dict[str, Agent] = {}
        self._run_results: Dict[str, dict] = {}

    def create_agent(
        self,
        agent_type: AgentType,
        goal: str,
        sandbox: bool = True,
    ) -> Agent:
        """Create and register a new agent."""
        agent = Agent(agent_type=agent_type, goal=goal, sandbox=sandbox)
        self._agents[agent.agent_id] = agent
        return agent

    def run_agent(
        self, agent_id: str, context: Optional[dict] = None
    ) -> dict:
        """Run a registered agent. Returns run result."""
        if agent_id not in self._agents:
            return {
                "agent_id": agent_id,
                "status": "failed",
                "error": "Agent not found",
            }
        agent = self._agents[agent_id]
        result = agent.run(context)
        self._run_results[agent_id] = result
        return result

    def get_pending_approvals(self) -> List[dict]:
        """Return agents waiting for write-operation approval."""
        pending = []
        for agent in self._agents.values():
            if agent._status == "pending_approval":
                for approval in agent._pending_approvals:
                    if approval["status"] == "pending":
                        pending.append({
                            "agent_id": agent.agent_id,
                            "goal": agent.goal,
                            **approval,
                        })
        return pending

    def approve_agent_action(
        self, agent_id: str, action_id: str
    ) -> bool:
        """Approve a pending write action."""
        if agent_id not in self._agents:
            return False
        agent = self._agents[agent_id]
        for approval in agent._pending_approvals:
            if approval["action_id"] == action_id:
                approval["status"] = "approved"
                approval["approved_at"] = time.time()
                agent._log.append(f"Action approved: {approval['action']}")
                return True
        return False

    def list_agents(self) -> List[dict]:
        """Return agent list.

        Returns:
            [{agent_id, type, goal, status, created_at}]
        """
        return [
            {
                "agent_id": a.agent_id,
                "type": a.agent_type.value,
                "goal": a.goal,
                "status": a._status,
                "created_at": a._created_at,
            }
            for a in self._agents.values()
        ]

    def get_run_log(self, agent_id: str) -> List[dict]:
        """Return execution log for a specific agent run."""
        if agent_id not in self._agents:
            return []
        agent = self._agents[agent_id]
        return [
            {"message": msg, "index": i}
            for i, msg in enumerate(agent._log)
        ]
