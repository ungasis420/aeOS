"""Tests for SafetyGuard in src/core/safety.py"""
import time
import pytest
from src.core.safety import SafetyGuard


def test_rate_limit_allows_under_limit():
    sg = SafetyGuard(rate_limit=5)
    result = sg.check_rate_limit("test_endpoint")
    assert result["allowed"] is True
    assert result["remaining"] >= 0


def test_rate_limit_blocks_after_limit():
    sg = SafetyGuard(rate_limit=3)
    for _ in range(3):
        sg.check_rate_limit("test_ep")
    result = sg.check_rate_limit("test_ep")
    assert result["allowed"] is False
    assert result["remaining"] == 0


def test_pii_detects_email():
    sg = SafetyGuard()
    result = sg.detect_pii("Contact me at john@example.com please")
    assert result["has_pii"] is True
    assert len(result["detected_types"]) > 0
    assert "[REDACTED]" in result["sanitized"]


def test_pii_detects_phone():
    sg = SafetyGuard()
    result = sg.detect_pii("Call me at 0917-123-4567")
    assert result["has_pii"] is True


def test_pii_safe_text_passes():
    sg = SafetyGuard()
    result = sg.detect_pii("Hello world, nothing sensitive here")
    assert result["has_pii"] is False
    assert result["sanitized"] == "Hello world, nothing sensitive here"


def test_cost_guard_blocks_when_exceeded():
    sg = SafetyGuard(daily_cap=0.001)
    result = sg.check_cost_guard("claude-sonnet-4-20250514", 1_000_000)
    assert result["approved"] is False


def test_cost_guard_approves_within_budget():
    sg = SafetyGuard(daily_cap=100.0, monthly_cap=1000.0)
    result = sg.check_cost_guard("claude-sonnet-4-20250514", 100)
    assert result["approved"] is True
    assert result["daily_remaining"] >= 0


def test_log_safety_event():
    sg = SafetyGuard()
    sg.log_safety_event("TEST_EVENT", {"key": "value"})
    events = sg.get_safety_events()
    assert len(events) == 1
    assert events[0]["event_type"] == "TEST_EVENT"
