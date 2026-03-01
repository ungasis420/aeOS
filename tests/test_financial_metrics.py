"""
test_financial_metrics.py
=========================
58 tests covering every public function in src/financial_metrics.py.

Each function is exercised for:
  - happy-path / basic correctness
  - edge / boundary values
  - input-validation errors (TypeError, ValueError)
"""
from __future__ import annotations

import math
import sys
import os

import pytest

# Ensure src/ is importable regardless of working directory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from financial_metrics import (
    calculate_roi,
    calculate_npv,
    calculate_payback_period,
    calculate_profit_margin,
    calculate_gross_margin,
    calculate_break_even,
    calculate_cagr,
    calculate_debt_to_equity,
    calculate_current_ratio,
    calculate_revenue_growth,
    calculate_clv,
    calculate_burn_rate,
    calculate_runway,
    calculate_mrr,
    risk_adjust_return,
    rate_financial_health,
    summarize_metrics,
)


# ── calculate_roi ────────────────────────────────────────────────────────

def test_roi_basic():
    r = calculate_roi(gain=1500, cost=1000)
    assert r["roi_pct"] == 50.0
    assert r["net_gain"] == 500.0


def test_roi_loss():
    r = calculate_roi(gain=800, cost=1000)
    assert r["roi_pct"] == -20.0
    assert r["net_gain"] == -200.0


def test_roi_zero_cost_raises():
    with pytest.raises(ValueError):
        calculate_roi(gain=100, cost=0)


def test_roi_non_numeric_raises():
    with pytest.raises(TypeError):
        calculate_roi(gain="abc", cost=100)


# ── calculate_npv ────────────────────────────────────────────────────────

def test_npv_basic():
    r = calculate_npv(0.10, [-1000, 400, 400, 400])
    assert r["periods"] == 4
    assert r["npv"] == pytest.approx(-5.2592, abs=0.01)


def test_npv_zero_rate():
    r = calculate_npv(0.0, [-500, 200, 200, 200])
    assert r["npv"] == pytest.approx(100.0, abs=0.01)


def test_npv_empty_raises():
    with pytest.raises(ValueError):
        calculate_npv(0.10, [])


def test_npv_bad_list_raises():
    with pytest.raises(ValueError):
        calculate_npv(0.10, "not_a_list")


# ── calculate_payback_period ─────────────────────────────────────────────

def test_payback_basic():
    r = calculate_payback_period(12000, 4000)
    assert r["payback_years"] == 3.0


def test_payback_fractional():
    r = calculate_payback_period(10000, 3000)
    assert r["payback_years"] == pytest.approx(3.3333, abs=0.001)


def test_payback_zero_investment_raises():
    with pytest.raises(ValueError):
        calculate_payback_period(0, 1000)


# ── calculate_profit_margin ──────────────────────────────────────────────

def test_profit_margin_basic():
    r = calculate_profit_margin(revenue=2000, cost=1500)
    assert r["margin_pct"] == 25.0
    assert r["profit"] == 500.0


def test_profit_margin_negative():
    r = calculate_profit_margin(revenue=1000, cost=1200)
    assert r["margin_pct"] == -20.0


def test_profit_margin_zero_revenue_raises():
    with pytest.raises(ValueError):
        calculate_profit_margin(revenue=0, cost=100)


# ── calculate_gross_margin ───────────────────────────────────────────────

def test_gross_margin_basic():
    r = calculate_gross_margin(revenue=5000, cogs=2000)
    assert r["gross_margin_pct"] == 60.0
    assert r["gross_profit"] == 3000.0


def test_gross_margin_zero_cogs():
    r = calculate_gross_margin(revenue=1000, cogs=0)
    assert r["gross_margin_pct"] == 100.0


def test_gross_margin_negative_cogs_raises():
    with pytest.raises(ValueError):
        calculate_gross_margin(revenue=1000, cogs=-100)


# ── calculate_break_even ─────────────────────────────────────────────────

def test_break_even_basic():
    r = calculate_break_even(fixed_costs=10000, price_per_unit=50, variable_cost_per_unit=30)
    assert r["break_even_units"] == 500.0
    assert r["contribution_margin"] == 20.0


def test_break_even_zero_fixed_costs():
    r = calculate_break_even(fixed_costs=0, price_per_unit=10, variable_cost_per_unit=5)
    assert r["break_even_units"] == 0.0


def test_break_even_no_margin_raises():
    with pytest.raises(ValueError, match="must exceed"):
        calculate_break_even(fixed_costs=1000, price_per_unit=10, variable_cost_per_unit=10)


def test_break_even_negative_price_raises():
    with pytest.raises(ValueError):
        calculate_break_even(fixed_costs=1000, price_per_unit=-5, variable_cost_per_unit=3)


# ── calculate_cagr ───────────────────────────────────────────────────────

def test_cagr_basic():
    r = calculate_cagr(beginning_value=1000, ending_value=2000, periods=3)
    assert r["cagr_pct"] == pytest.approx(25.9921, abs=0.01)


def test_cagr_no_growth():
    r = calculate_cagr(beginning_value=500, ending_value=500, periods=5)
    assert r["cagr_pct"] == 0.0


def test_cagr_decline():
    r = calculate_cagr(beginning_value=1000, ending_value=500, periods=2)
    assert r["cagr_pct"] < 0


def test_cagr_zero_periods_raises():
    with pytest.raises(ValueError):
        calculate_cagr(1000, 2000, 0)


# ── calculate_debt_to_equity ─────────────────────────────────────────────

def test_de_ratio_basic():
    r = calculate_debt_to_equity(total_debt=5000, total_equity=10000)
    assert r["de_ratio"] == 0.5


def test_de_ratio_zero_debt():
    r = calculate_debt_to_equity(total_debt=0, total_equity=10000)
    assert r["de_ratio"] == 0.0


def test_de_ratio_zero_equity_raises():
    with pytest.raises(ValueError):
        calculate_debt_to_equity(total_debt=1000, total_equity=0)


# ── calculate_current_ratio ──────────────────────────────────────────────

def test_current_ratio_healthy():
    r = calculate_current_ratio(current_assets=50000, current_liabilities=25000)
    assert r["current_ratio"] == 2.0


def test_current_ratio_tight():
    r = calculate_current_ratio(current_assets=10000, current_liabilities=10000)
    assert r["current_ratio"] == 1.0


def test_current_ratio_zero_liabilities_raises():
    with pytest.raises(ValueError):
        calculate_current_ratio(current_assets=5000, current_liabilities=0)


# ── calculate_revenue_growth ─────────────────────────────────────────────

def test_revenue_growth_positive():
    r = calculate_revenue_growth(previous_revenue=10000, current_revenue=15000)
    assert r["growth_pct"] == 50.0
    assert r["delta"] == 5000.0


def test_revenue_growth_decline():
    r = calculate_revenue_growth(previous_revenue=20000, current_revenue=15000)
    assert r["growth_pct"] == -25.0


def test_revenue_growth_zero_previous_raises():
    with pytest.raises(ValueError):
        calculate_revenue_growth(previous_revenue=0, current_revenue=5000)


# ── calculate_clv ────────────────────────────────────────────────────────

def test_clv_basic():
    r = calculate_clv(avg_purchase_value=50, purchase_frequency=4, customer_lifespan=5)
    assert r["clv"] == 1000.0


def test_clv_fractional():
    r = calculate_clv(avg_purchase_value=29.99, purchase_frequency=2.5, customer_lifespan=3)
    assert r["clv"] == pytest.approx(224.925, abs=0.01)


def test_clv_zero_frequency_raises():
    with pytest.raises(ValueError):
        calculate_clv(avg_purchase_value=50, purchase_frequency=0, customer_lifespan=5)


# ── calculate_burn_rate ──────────────────────────────────────────────────

def test_burn_rate_basic():
    r = calculate_burn_rate(starting_cash=120000, ending_cash=60000, months=6)
    assert r["monthly_burn_rate"] == 10000.0
    assert r["total_burned"] == 60000.0


def test_burn_rate_growing_cash():
    r = calculate_burn_rate(starting_cash=50000, ending_cash=80000, months=3)
    assert r["monthly_burn_rate"] == pytest.approx(-10000.0)


def test_burn_rate_zero_months_raises():
    with pytest.raises(ValueError):
        calculate_burn_rate(starting_cash=100000, ending_cash=50000, months=0)


# ── calculate_runway ─────────────────────────────────────────────────────

def test_runway_basic():
    r = calculate_runway(cash_balance=120000, monthly_burn_rate=10000)
    assert r["runway_months"] == 12.0


def test_runway_zero_cash():
    r = calculate_runway(cash_balance=0, monthly_burn_rate=5000)
    assert r["runway_months"] == 0.0


def test_runway_zero_burn_raises():
    with pytest.raises(ValueError):
        calculate_runway(cash_balance=100000, monthly_burn_rate=0)


# ── calculate_mrr ────────────────────────────────────────────────────────

def test_mrr_basic():
    r = calculate_mrr(subscribers=200, avg_revenue_per_user=49.99)
    assert r["mrr"] == pytest.approx(9998.0, abs=0.01)
    assert r["arr"] == pytest.approx(119976.0, abs=0.1)


def test_mrr_zero_subscribers():
    r = calculate_mrr(subscribers=0, avg_revenue_per_user=10)
    assert r["mrr"] == 0.0
    assert r["arr"] == 0.0


def test_mrr_negative_subscribers_raises():
    with pytest.raises(ValueError):
        calculate_mrr(subscribers=-1, avg_revenue_per_user=10)


# ── risk_adjust_return ───────────────────────────────────────────────────

def test_risk_adjust_conservative():
    r = risk_adjust_return(expected_return=1000, risk_factor=0.2, profile="conservative")
    assert r["adjusted_return"] == pytest.approx(560.0)
    assert r["multiplier"] == 0.7
    assert r["profile"] == "conservative"


def test_risk_adjust_aggressive_zero_risk():
    r = risk_adjust_return(expected_return=1000, risk_factor=0.0, profile="aggressive")
    assert r["adjusted_return"] == 1000.0


def test_risk_adjust_invalid_profile_raises():
    with pytest.raises(ValueError, match="profile must be"):
        risk_adjust_return(expected_return=100, risk_factor=0.1, profile="yolo")


def test_risk_adjust_risk_out_of_range_raises():
    with pytest.raises(ValueError, match="between 0.0 and 1.0"):
        risk_adjust_return(expected_return=100, risk_factor=1.5, profile="moderate")


# ── rate_financial_health ────────────────────────────────────────────────

def test_health_all_excellent():
    metrics = {
        "roi_pct": 60,
        "margin_pct": 35,
        "current_ratio": 3.0,
        "de_ratio": 0.3,
    }
    r = rate_financial_health(metrics)
    assert all(v == "excellent" for v in r["ratings"].values())
    assert r["score"] == 100


def test_health_mixed():
    metrics = {"roi_pct": 10, "current_ratio": 0.4}
    r = rate_financial_health(metrics)
    assert r["ratings"]["roi_pct"] == "fair"
    assert r["ratings"]["current_ratio"] == "poor"


def test_health_empty_dict():
    r = rate_financial_health({})
    assert r["score"] == 0
    assert r["ratings"] == {}


def test_health_non_dict_raises():
    with pytest.raises(TypeError):
        rate_financial_health("not a dict")


# ── summarize_metrics ────────────────────────────────────────────────────

def test_summarize_basic():
    records = [
        {"roi_pct": 20, "net_gain": 200},
        {"roi_pct": 40, "net_gain": 400},
    ]
    r = summarize_metrics(records)
    assert r["count"] == 2
    assert r["summary"]["roi_pct"]["mean"] == 30.0
    assert r["summary"]["roi_pct"]["min"] == 20.0
    assert r["summary"]["roi_pct"]["max"] == 40.0


def test_summarize_empty():
    r = summarize_metrics([])
    assert r["count"] == 0
    assert r["summary"] == {}


def test_summarize_non_list_raises():
    with pytest.raises(TypeError):
        summarize_metrics("bad")


def test_summarize_ignores_non_numeric():
    records = [{"name": "test", "value": 42}]
    r = summarize_metrics(records)
    assert "name" not in r["summary"]
    assert "value" in r["summary"]
