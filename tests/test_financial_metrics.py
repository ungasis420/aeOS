"""58 tests for src/financial_metrics.py"""
import math
import pytest
from src.financial_metrics import (
    calc_cac, calc_ltv, calc_ltv_cac_ratio, calc_payback_period_months,
    calc_contribution_margin, calc_break_even_units, calc_gross_margin_pct,
    calc_net_margin_pct, calc_mrr, calc_arr, calc_churn_rate,
    calc_nrr, calc_runway_months, calc_revenue_per_hour, calc_utilization_rate,
)


# ── calc_cac ─────────────────────────────────────────────────────────────────
def test_cac_basic():
    assert calc_cac(10_000, 100) == pytest.approx(100.0)

def test_cac_zero_spend():
    assert calc_cac(0, 10) == pytest.approx(0.0)

def test_cac_zero_customers_raises():
    pytest.raises(ValueError, calc_cac, 1000, 0)

def test_cac_negative_raises():
    pytest.raises(ValueError, calc_cac, -100, 10)

def test_cac_bool_rejected():
    pytest.raises(ValueError, calc_cac, True, 10)

# ── calc_ltv ─────────────────────────────────────────────────────────────────
def test_ltv_ratio():
    assert calc_ltv(100, 0.70, 0.05) == pytest.approx(1400.0)

def test_ltv_pct():
    assert calc_ltv(100, 70, 5) == pytest.approx(1400.0)

def test_ltv_mixed():
    assert calc_ltv(100, 0.70, 5) == pytest.approx(1400.0)

def test_ltv_zero_churn_raises():
    pytest.raises(ValueError, calc_ltv, 100, 0.7, 0)

def test_ltv_negative_arpc_raises():
    pytest.raises(ValueError, calc_ltv, -1, 0.7, 0.05)

def test_ltv_margin_over_100_raises():
    pytest.raises(ValueError, calc_ltv, 100, 150, 0.05)

# ── calc_ltv_cac_ratio ───────────────────────────────────────────────────────
def test_ltv_cac_healthy():
    assert calc_ltv_cac_ratio(1400, 350) == pytest.approx(4.0)

def test_ltv_cac_zero_ltv():
    assert calc_ltv_cac_ratio(0, 200) == pytest.approx(0.0)

def test_ltv_cac_zero_cac_raises():
    pytest.raises(ValueError, calc_ltv_cac_ratio, 1400, 0)

# ── calc_payback_period_months ───────────────────────────────────────────────
def test_payback_basic():
    assert calc_payback_period_months(500, 100, 0.5) == pytest.approx(10.0)

def test_payback_pct():
    assert calc_payback_period_months(500, 100, 50) == pytest.approx(10.0)

def test_payback_zero_margin_raises():
    pytest.raises(ValueError, calc_payback_period_months, 500, 100, 0)

def test_payback_zero_cac_raises():
    pytest.raises(ValueError, calc_payback_period_months, 0, 100, 0.5)

def test_payback_neg_mrr_raises():
    pytest.raises(ValueError, calc_payback_period_months, 500, -10, 0.5)

# ── calc_contribution_margin ─────────────────────────────────────────────────
def test_contrib_positive():
    assert calc_contribution_margin(1000, 600) == pytest.approx(400.0)

def test_contrib_negative():
    assert calc_contribution_margin(500, 700) == pytest.approx(-200.0)

def test_contrib_zero():
    assert calc_contribution_margin(0, 0) == pytest.approx(0.0)

def test_contrib_neg_rev_raises():
    pytest.raises(ValueError, calc_contribution_margin, -1, 0)

# ── calc_break_even_units ────────────────────────────────────────────────────
def test_breakeven_basic():
    assert calc_break_even_units(10_000, 50, 30) == pytest.approx(500.0)

def test_breakeven_zero_fixed():
    assert calc_break_even_units(0, 50, 30) == pytest.approx(0.0)

def test_breakeven_eq_raises():
    pytest.raises(ValueError, calc_break_even_units, 1000, 30, 30)

def test_breakeven_below_raises():
    pytest.raises(ValueError, calc_break_even_units, 1000, 20, 30)

# ── calc_gross_margin_pct ────────────────────────────────────────────────────
def test_gross_70():
    assert calc_gross_margin_pct(1000, 300) == pytest.approx(70.0)

def test_gross_zero_cogs():
    assert calc_gross_margin_pct(1000, 0) == pytest.approx(100.0)

def test_gross_negative():
    assert calc_gross_margin_pct(100, 150) == pytest.approx(-50.0)

def test_gross_zero_rev_raises():
    pytest.raises(ValueError, calc_gross_margin_pct, 0, 0)

# ── calc_net_margin_pct ──────────────────────────────────────────────────────
def test_net_basic():
    assert calc_net_margin_pct(1000, 200) == pytest.approx(20.0)

def test_net_negative():
    assert calc_net_margin_pct(1000, -100) == pytest.approx(-10.0)

def test_net_zero_rev_raises():
    pytest.raises(ValueError, calc_net_margin_pct, 0, 100)

# ── calc_mrr / calc_arr ─────────────────────────────────────────────────────
def test_mrr_basic():
    assert calc_mrr(200, 49) == pytest.approx(9800.0)

def test_arr_12x():
    assert calc_arr(calc_mrr(200, 49)) == pytest.approx(9800 * 12)

def test_mrr_zero_subs():
    assert calc_mrr(0, 99) == pytest.approx(0.0)

def test_arr_neg_raises():
    pytest.raises(ValueError, calc_arr, -100)

# ── calc_churn_rate ──────────────────────────────────────────────────────────
def test_churn_basic():
    assert calc_churn_rate(10, 200) == pytest.approx(0.05)

def test_churn_zero_lost():
    assert calc_churn_rate(0, 100) == pytest.approx(0.0)

def test_churn_full():
    assert calc_churn_rate(100, 100) == pytest.approx(1.0)

def test_churn_exceeds_raises():
    pytest.raises(ValueError, calc_churn_rate, 110, 100)

def test_churn_zero_start_raises():
    pytest.raises(ValueError, calc_churn_rate, 0, 0)

# ── calc_nrr ─────────────────────────────────────────────────────────────────
def test_nrr_expansion():
    assert calc_nrr(10_000, 2_000, 500) == pytest.approx(1.15)

def test_nrr_flat():
    assert calc_nrr(10_000, 0, 0) == pytest.approx(1.0)

def test_nrr_below():
    assert calc_nrr(10_000, 0, 3_000) == pytest.approx(0.7)

def test_nrr_zero_start_raises():
    pytest.raises(ValueError, calc_nrr, 0, 1000, 0)

# ── calc_runway_months ───────────────────────────────────────────────────────
def test_runway_basic():
    assert calc_runway_months(300_000, 25_000) == pytest.approx(12.0)

def test_runway_zero_cash():
    assert calc_runway_months(0, 10_000) == pytest.approx(0.0)

def test_runway_zero_burn_raises():
    pytest.raises(ValueError, calc_runway_months, 100_000, 0)

# ── calc_revenue_per_hour ────────────────────────────────────────────────────
def test_rev_per_hour_basic():
    assert calc_revenue_per_hour(8_000, 160) == pytest.approx(50.0)

def test_rev_per_hour_zero():
    assert calc_revenue_per_hour(0, 160) == pytest.approx(0.0)

def test_rev_per_hour_zero_hours_raises():
    pytest.raises(ValueError, calc_revenue_per_hour, 8000, 0)

# ── calc_utilization_rate ────────────────────────────────────────────────────
def test_util_basic():
    assert calc_utilization_rate(120, 160) == pytest.approx(0.75)

def test_util_full():
    assert calc_utilization_rate(160, 160) == pytest.approx(1.0)

def test_util_zero():
    assert calc_utilization_rate(0, 160) == pytest.approx(0.0)

def test_util_exceeds_raises():
    pytest.raises(ValueError, calc_utilization_rate, 170, 160)

def test_util_zero_avail_raises():
    pytest.raises(ValueError, calc_utilization_rate, 0, 0)
