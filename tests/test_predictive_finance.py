"""Tests for PredictiveFinance"""
import pytest
from src.cognitive.predictive_finance import PredictiveFinance, DISCLAIMER


def test_price_forecast_returns_all_percentiles():
    pf = PredictiveFinance()
    prices = [100, 102, 105, 103, 108, 110, 112, 115]
    result = pf.price_forecast(prices, horizon_days=5)
    for key in ("p10", "p25", "p50", "p75", "p90"):
        assert key in result
        assert isinstance(result[key], float)
    assert result["p10"] <= result["p50"] <= result["p90"]


def test_trend_strength_in_range():
    pf = PredictiveFinance()
    prices = [100, 102, 104, 106, 108, 110]
    result = pf.trend_strength(prices)
    assert -1.0 <= result["score"] <= 1.0
    assert result["direction"] in ("up", "down", "flat")


def test_all_outputs_contain_disclaimer():
    pf = PredictiveFinance()
    prices = [100, 102, 104, 106, 108]
    assert pf.price_forecast(prices, 5)["disclaimer"] == DISCLAIMER
    assert pf.trend_strength(prices)["disclaimer"] == DISCLAIMER
    assert pf.volatility_forecast(prices)["disclaimer"] == DISCLAIMER
    assert pf.scenario_analysis(
        [{"current_value": 1000}],
        [{"name": "crash", "shock_pct": -20}]
    )["disclaimer"] == DISCLAIMER


def test_scenario_analysis_returns_per_scenario():
    pf = PredictiveFinance()
    portfolio = [{"ticker": "X", "weight": 1.0, "current_value": 10000}]
    scenarios = [
        {"name": "bull", "shock_pct": 20, "description": "Bull market"},
        {"name": "bear", "shock_pct": -30, "description": "Bear market"},
    ]
    result = pf.scenario_analysis(portfolio, scenarios)
    assert len(result["results"]) == 2
    assert result["worst_case"] == "bear"
    assert result["best_case"] == "bull"


def test_volatility_non_negative():
    pf = PredictiveFinance()
    prices = [100, 105, 95, 110, 90, 115]
    result = pf.volatility_forecast(prices)
    assert result["current_vol"] >= 0
    assert result["forecast_vol"] >= 0
    assert result["regime"] in ("low", "normal", "high")


def test_model_performance():
    pf = PredictiveFinance()
    predictions = [
        {"actual": 100, "predicted": 102, "method": "regression"},
        {"actual": 105, "predicted": 104, "method": "regression"},
    ]
    result = pf.get_model_performance("TEST", predictions)
    assert result["sample_size"] == 2
    assert result["mae"] >= 0


def test_empty_prices_safe():
    pf = PredictiveFinance()
    result = pf.price_forecast([], 5)
    assert result["p50"] == 0.0
