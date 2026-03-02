"""Tests for Agents and AgentOrchestrator"""
import pytest
from src.cognitive.agents import Agent, AgentType, AgentOrchestrator


def test_research_agent_completes():
    agent = Agent(AgentType.RESEARCH, "Find market data")
    result = agent.run({"sources": ["web", "db"]})
    assert result["status"] == "completed"
    assert result["output"] is not None
    assert result["output"]["type"] == "research"


def test_write_outside_sandbox_requires_approval():
    agent = Agent(AgentType.REPORT, "Generate report", sandbox=False)
    result = agent.run({"write_to_file": True, "output_path": "report.md"})
    assert result["requires_approval"] is True
    assert result["status"] == "pending_approval"


def test_sandbox_mode_no_approval():
    agent = Agent(AgentType.REPORT, "Generate report", sandbox=True)
    result = agent.run({"write_to_file": True})
    assert result["requires_approval"] is False
    assert result["status"] == "completed"


def test_agent_log_records_steps():
    agent = Agent(AgentType.ANALYSIS, "Analyze data")
    result = agent.run({"record_count": 100})
    assert len(result["log"]) > 0
    assert any("Step completed" in msg for msg in result["log"])


def test_failed_agent_returns_status():
    # Create an agent that will fail via bad internal state
    agent = Agent(AgentType.RESEARCH, "Test failure")
    # Monkey-patch to force failure
    def _fail(ctx):
        raise RuntimeError("Simulated failure")
    agent._execute_research = _fail
    result = agent.run()
    assert result["status"] == "failed"


def test_orchestrator_create_and_run():
    orch = AgentOrchestrator()
    agent = orch.create_agent(AgentType.ANALYSIS, "Test analysis")
    result = orch.run_agent(agent.agent_id)
    assert result["status"] == "completed"


def test_orchestrator_approval_flow():
    orch = AgentOrchestrator()
    agent = orch.create_agent(AgentType.REPORT, "Report", sandbox=False)
    orch.run_agent(agent.agent_id, {"write_to_file": True})
    pending = orch.get_pending_approvals()
    assert len(pending) > 0
    approved = orch.approve_agent_action(
        pending[0]["agent_id"], pending[0]["action_id"]
    )
    assert approved is True


def test_orchestrator_list_agents():
    orch = AgentOrchestrator()
    orch.create_agent(AgentType.RESEARCH, "Research 1")
    orch.create_agent(AgentType.ANALYSIS, "Analysis 1")
    agents = orch.list_agents()
    assert len(agents) == 2
