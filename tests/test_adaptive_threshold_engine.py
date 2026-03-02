"""Tests for AdaptiveThresholdEngine"""
import pytest
from src.cognitive.adaptive_threshold_engine import AdaptiveThresholdEngine


def test_volatile_data_higher_threshold():
    ate = AdaptiveThresholdEngine()
    volatile = [1, 100, 1, 100, 1, 100, 1, 100]
    steady = [50, 50, 50, 50, 50, 50, 50, 50]
    r_vol = ate.compute_threshold("volatile", volatile)
    r_std = ate.compute_threshold("steady", steady)
    assert r_vol["threshold"] > r_std["threshold"]


def test_steady_data_low_threshold():
    ate = AdaptiveThresholdEngine()
    result = ate.compute_threshold("metric_a", [10, 10, 10, 10, 10])
    assert result["std"] == pytest.approx(0.0, abs=0.01)


def test_alert_triggers_above_threshold():
    ate = AdaptiveThresholdEngine()
    ate.compute_threshold("cpu", [10, 11, 12, 10, 11, 10, 12])
    result = ate.is_alert_triggered("cpu", 1000)
    assert result["triggered"] is True


def test_no_alert_below_threshold():
    ate = AdaptiveThresholdEngine()
    ate.compute_threshold("cpu", [10, 11, 12, 10, 11, 10, 12])
    result = ate.is_alert_triggered("cpu", 5)
    assert result["triggered"] is False


def test_recalibrate_updates_multiple():
    ate = AdaptiveThresholdEngine()
    result = ate.recalibrate_all({
        "metric_a": [1, 2, 3, 4, 5],
        "metric_b": [10, 20, 30, 40, 50],
    })
    assert "metric_a" in result["updated"]
    assert "metric_b" in result["updated"]
    assert len(result["thresholds"]) == 2


def test_update_threshold_incremental():
    ate = AdaptiveThresholdEngine()
    ate.compute_threshold("mem", [50, 55, 60])
    r1 = ate.get_threshold("mem")
    ate.update_threshold("mem", 65)
    r2 = ate.get_threshold("mem")
    assert r2 is not None


def test_unknown_metric_no_alert():
    ate = AdaptiveThresholdEngine()
    result = ate.is_alert_triggered("nonexistent", 100)
    assert result["triggered"] is False
