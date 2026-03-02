"""Tests for Workflow and WorkflowRegistry"""
import pytest
from src.core.workflow import Workflow, WorkflowStep, WorkflowRegistry


def _handler_a(ctx):
    ctx["step_a"] = True
    return {"step_a_done": True}

def _handler_b(ctx):
    ctx["step_b"] = True
    return {"step_b_done": True}

def _handler_fail(ctx):
    raise RuntimeError("Step failed")

def _error_handler(ctx):
    ctx["error_handled"] = True
    return {"recovered": True}


def test_linear_workflow_completes():
    steps = [
        WorkflowStep(name="a", handler=_handler_a),
        WorkflowStep(name="b", handler=_handler_b),
    ]
    wf = Workflow("test_wf", steps)
    result = wf.run()
    assert result["status"] == "completed"
    assert "a" in result["steps_completed"]
    assert "b" in result["steps_completed"]


def test_step_failure_triggers_error():
    steps = [
        WorkflowStep(name="a", handler=_handler_a),
        WorkflowStep(name="fail", handler=_handler_fail,
                     on_error="recover"),
        WorkflowStep(name="recover", handler=_error_handler),
    ]
    wf = Workflow("test_wf", steps)
    result = wf.run()
    # Should have tried to recover
    assert "a" in result["steps_completed"]


def test_context_passes_between_steps():
    steps = [
        WorkflowStep(name="a", handler=_handler_a),
        WorkflowStep(name="b", handler=_handler_b),
    ]
    wf = Workflow("test_wf", steps)
    result = wf.run({"initial": True})
    assert result["final_context"].get("step_a_done") is True
    assert result["final_context"].get("step_b_done") is True


def test_resume_from_step():
    steps = [
        WorkflowStep(name="a", handler=_handler_a),
        WorkflowStep(name="b", handler=_handler_b),
    ]
    wf = Workflow("test_wf", steps)
    result = wf.resume("b", {"initial": True})
    assert result["status"] == "completed"
    assert "b" in result["steps_completed"]


def test_empty_workflow_raises():
    with pytest.raises(ValueError):
        Workflow("empty", [])


def test_get_status():
    steps = [WorkflowStep(name="a", handler=_handler_a)]
    wf = Workflow("test_wf", steps)
    status = wf.get_status()
    assert status["status"] == "pending"
    assert status["total_steps"] == 1


def test_registry_create_instance():
    reg = WorkflowRegistry()
    steps = [WorkflowStep(name="a", handler=_handler_a)]
    reg.register("my_wf", steps)
    wf = reg.create_instance("my_wf")
    assert isinstance(wf, Workflow)


def test_registry_list_workflows():
    reg = WorkflowRegistry()
    steps = [WorkflowStep(name="a", handler=_handler_a)]
    reg.register("wf1", steps)
    listing = reg.list_workflows()
    assert len(listing) == 1
    assert listing[0]["workflow_id"] == "wf1"
