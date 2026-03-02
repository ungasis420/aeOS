"""Tests for PatternRecognitionEngine"""
import pytest
from src.cognitive.pattern_recognition_engine import PatternRecognitionEngine


def test_uptrend_detected():
    pre = PatternRecognitionEngine()
    result = pre.detect_trend([1, 2, 3, 4, 5, 6, 7])
    assert result["direction"] == "up"
    assert result["strength"] > 0.5
    assert result["slope"] > 0


def test_downtrend_detected():
    pre = PatternRecognitionEngine()
    result = pre.detect_trend([10, 9, 8, 7, 6, 5, 4])
    assert result["direction"] == "down"


def test_flat_series():
    pre = PatternRecognitionEngine()
    result = pre.detect_trend([5, 5, 5, 5, 5])
    assert result["direction"] == "flat"


def test_anomaly_detected_at_3std():
    pre = PatternRecognitionEngine()
    series = [10, 10, 10, 10, 10, 10, 10, 50]
    result = pre.detect_anomaly(series, threshold_std=2.0)
    assert result["anomaly_count"] > 0
    assert 7 in result["anomalies"]


def test_empty_series_safe_defaults():
    pre = PatternRecognitionEngine()
    assert pre.detect_trend([])["direction"] == "flat"
    assert pre.detect_anomaly([])["anomaly_count"] == 0


def test_feature_vector_consistent_length():
    pre = PatternRecognitionEngine()
    v1 = pre.extract_feature_vector({"revenue": 100, "costs": 50})
    v2 = pre.extract_feature_vector({"churn": 0.05})
    assert len(v1) == len(v2) == 8


def test_recurring_pattern_detected():
    pre = PatternRecognitionEngine()
    import time
    base = time.time()
    events = [
        {"type": "deploy", "timestamp": base},
        {"type": "deploy", "timestamp": base + 86400 * 7},
        {"type": "deploy", "timestamp": base + 86400 * 14},
    ]
    result = pre.detect_recurring_pattern(events, "type")
    assert len(result["patterns"]) > 0
    assert result["patterns"][0]["pattern"] == "deploy"


def test_scan_execution_log():
    pre = PatternRecognitionEngine()
    entries = [
        {"status": "completed", "velocity": 5},
        {"status": "blocked", "velocity": 3},
        {"status": "blocked", "velocity": 2},
        {"status": "blocked", "velocity": 1},
    ]
    result = pre.scan_execution_log(entries)
    assert "high_blocker_rate" in result["flags"]
    assert result["feature_vectors"]
