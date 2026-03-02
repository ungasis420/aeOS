"""Tests for ClaudeAPIBridge"""
import pytest
from unittest.mock import patch
from src.ai.claude_api_bridge import ClaudeAPIBridge
from src.core.safety import SafetyGuard


def test_cost_guard_blocks_when_exceeded():
    sg = SafetyGuard(daily_cap=0.0001, monthly_cap=0.0001)
    bridge = ClaudeAPIBridge(safety_guard=sg)
    result = bridge.call("test prompt", max_tokens=1_000_000)
    assert result["success"] is False
    assert "cap" in result["error"].lower() or "exceeded" in result["error"].lower()


def test_pii_sanitized_before_call():
    bridge = ClaudeAPIBridge()
    with patch.object(bridge, "_http_call", return_value={
        "success": True, "text": "response", "tokens_used": 50, "error": None
    }) as mock_call:
        bridge.call("My email is test@example.com")
        args = mock_call.call_args
        prompt_sent = args[0][0]
        assert "test@example.com" not in prompt_sent
        assert "[REDACTED]" in prompt_sent


def test_irreversible_holds_for_review():
    bridge = ClaudeAPIBridge()
    result = bridge.call("delete everything", irreversible=True)
    assert result["held_for_review"] is True
    assert result["response"] is None
    pending = bridge.get_pending_reviews()
    assert len(pending) == 1


def test_approve_review_releases_response():
    bridge = ClaudeAPIBridge()
    result = bridge.call("delete data", irreversible=True)
    pending = bridge.get_pending_reviews()
    req_id = pending[0]["request_id"]
    approved = bridge.approve_review(req_id)
    assert approved["success"] is True
    assert approved["response"] is not None


def test_usage_summary_structure():
    bridge = ClaudeAPIBridge()
    bridge.call("test")
    summary = bridge.get_usage_summary()
    for key in ["daily_calls", "daily_tokens", "daily_cost",
                 "monthly_calls", "daily_cap", "monthly_cap",
                 "daily_remaining", "monthly_remaining"]:
        assert key in summary


def test_graceful_without_api_key():
    """Should not crash when ANTHROPIC_API_KEY is unset."""
    bridge = ClaudeAPIBridge()
    result = bridge.call("test prompt")
    assert result["success"] is True
    assert result["response"] is not None


def test_reject_review():
    bridge = ClaudeAPIBridge()
    bridge.call("test", irreversible=True)
    pending = bridge.get_pending_reviews()
    req_id = pending[0]["request_id"]
    assert bridge.reject_review(req_id, "not needed") is True
    assert len(bridge.get_pending_reviews()) == 0
