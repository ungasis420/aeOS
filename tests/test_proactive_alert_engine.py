"""Tests for ProactiveAlertEngine"""
import pytest
from src.cognitive.proactive_alert_engine import ProactiveAlertEngine
from src.cognitive.adaptive_threshold_engine import AdaptiveThresholdEngine


def test_alert_generated_with_correct_fields():
    pae = ProactiveAlertEngine()
    alert = pae.generate_alert("safety", "rate_limit", {"message": "Rate exceeded"}, "high")
    assert alert["alert_id"]
    assert alert["source"] == "safety"
    assert alert["type"] == "rate_limit"
    assert alert["severity"] == "high"
    assert alert["acknowledged"] is False


def test_active_alerts_sorted_by_severity():
    pae = ProactiveAlertEngine()
    pae.generate_alert("s1", "t1", {"message": "low"}, "low")
    pae.generate_alert("s2", "t2", {"message": "critical"}, "critical")
    pae.generate_alert("s3", "t3", {"message": "medium"}, "medium")
    alerts = pae.get_active_alerts()
    assert alerts[0]["severity"] == "critical"
    assert alerts[-1]["severity"] == "low"


def test_acknowledge_clears_from_active():
    pae = ProactiveAlertEngine()
    alert = pae.generate_alert("src", "type", {"message": "test"})
    assert len(pae.get_active_alerts()) == 1
    pae.acknowledge_alert(alert["alert_id"])
    assert len(pae.get_active_alerts()) == 0


def test_critical_before_medium():
    pae = ProactiveAlertEngine()
    pae.generate_alert("a", "t", {"message": "m"}, "medium")
    pae.generate_alert("b", "t", {"message": "c"}, "critical")
    active = pae.get_active_alerts()
    assert active[0]["severity"] == "critical"
    assert active[1]["severity"] == "medium"


def test_empty_state_safe_defaults():
    pae = ProactiveAlertEngine()
    summary = pae.get_alert_summary()
    assert summary["total"] == 0
    assert summary["unacknowledged"] == 0
    assert summary["oldest_unack_hours"] == 0.0


def test_check_all_thresholds_triggers():
    ate = AdaptiveThresholdEngine()
    ate.compute_threshold("cpu", [10, 10, 10, 10, 10])
    pae = ProactiveAlertEngine()
    alerts = pae.check_all_thresholds({"cpu": 1000}, ate)
    assert len(alerts) > 0
    assert alerts[0]["type"].startswith("threshold_breach")


def test_severity_filter():
    pae = ProactiveAlertEngine()
    pae.generate_alert("s1", "t1", {"message": "h"}, "high")
    pae.generate_alert("s2", "t2", {"message": "l"}, "low")
    high_only = pae.get_active_alerts(severity_filter="high")
    assert len(high_only) == 1
    assert high_only[0]["severity"] == "high"
