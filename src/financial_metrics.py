"""aeOS Financial Metrics — 15 pure financial calculation functions."""
from __future__ import annotations

import math
from typing import Union

Number = Union[int, float]


def _as_finite_float(value: Number, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    f = float(value)
    if not math.isfinite(f):
        raise ValueError(f"{name} must be a finite number")
    return f


def _require_non_negative(value: Number, name: str) -> float:
    f = _as_finite_float(value, name)
    if f < 0:
        raise ValueError(f"{name} must be >= 0")
    return f


def _require_positive(value: Number, name: str) -> float:
    f = _as_finite_float(value, name)
    if f <= 0:
        raise ValueError(f"{name} must be > 0")
    return f


def _normalize_pct_or_ratio(value: Number, name: str) -> float:
    f = _as_finite_float(value, name)
    if f < 0:
        raise ValueError(f"{name} must be between 0 and 1 (ratio) or 0 and 100 (percent)")
    if f <= 1:
        return f
    if f <= 100:
        return f / 100.0
    raise ValueError(f"{name} must be between 0 and 1 (ratio) or 0 and 100 (percent)")


def calc_cac(total_sales_marketing_spend: Number, new_customers_acquired: Number) -> float:
    """Customer Acquisition Cost."""
    return _require_non_negative(total_sales_marketing_spend, "total_sales_marketing_spend") / \
           _require_positive(new_customers_acquired, "new_customers_acquired")


def calc_ltv(avg_revenue_per_customer: Number, gross_margin_pct: Number, churn_rate: Number) -> float:
    """Customer Lifetime Value."""
    arpc = _require_non_negative(avg_revenue_per_customer, "avg_revenue_per_customer")
    gm = _normalize_pct_or_ratio(gross_margin_pct, "gross_margin_pct")
    churn = _normalize_pct_or_ratio(churn_rate, "churn_rate")
    if churn <= 0:
        raise ValueError("churn_rate must be > 0")
    return (arpc * gm) / churn


def calc_ltv_cac_ratio(ltv: Number, cac: Number) -> float:
    """LTV:CAC ratio. Healthy = 3:1+, Excellent = 5:1+."""
    return _require_non_negative(ltv, "ltv") / _require_positive(cac, "cac")


def calc_payback_period_months(cac: Number, monthly_revenue_per_customer: Number, gross_margin_pct: Number) -> float:
    """Months to recover CAC."""
    cac_v = _require_positive(cac, "cac")
    mrrpc = _require_positive(monthly_revenue_per_customer, "monthly_revenue_per_customer")
    gm = _normalize_pct_or_ratio(gross_margin_pct, "gross_margin_pct")
    if gm <= 0:
        raise ValueError("gross_margin_pct must be > 0")
    return cac_v / (mrrpc * gm)


def calc_contribution_margin(revenue: Number, variable_costs: Number) -> float:
    """Revenue minus variable costs."""
    return _require_non_negative(revenue, "revenue") - \
           _require_non_negative(variable_costs, "variable_costs")


def calc_break_even_units(fixed_costs: Number, price_per_unit: Number, variable_cost_per_unit: Number) -> float:
    """Units needed to cover fixed costs."""
    fixed = _require_non_negative(fixed_costs, "fixed_costs")
    price = _require_positive(price_per_unit, "price_per_unit")
    var = _require_non_negative(variable_cost_per_unit, "variable_cost_per_unit")
    cpu = price - var
    if cpu <= 0:
        raise ValueError("price_per_unit must be greater than variable_cost_per_unit to break even")
    return fixed / cpu


def calc_gross_margin_pct(revenue: Number, cogs: Number) -> float:
    """Gross margin as percentage."""
    rev = _require_positive(revenue, "revenue")
    return ((rev - _require_non_negative(cogs, "cogs")) / rev) * 100.0


def calc_net_margin_pct(revenue: Number, net_income: Number) -> float:
    """Net margin as percentage."""
    return (_as_finite_float(net_income, "net_income") /
            _require_positive(revenue, "revenue")) * 100.0


def calc_mrr(active_subscriptions: Number, avg_monthly_price: Number) -> float:
    """Monthly Recurring Revenue."""
    return _require_non_negative(active_subscriptions, "active_subscriptions") * \
           _require_non_negative(avg_monthly_price, "avg_monthly_price")


def calc_arr(mrr: Number) -> float:
    """Annual Recurring Revenue = MRR * 12."""
    return _require_non_negative(mrr, "mrr") * 12.0


def calc_churn_rate(customers_lost: Number, customers_start_of_period: Number) -> float:
    """Churn rate as ratio (0–1)."""
    lost = _require_non_negative(customers_lost, "customers_lost")
    start = _require_positive(customers_start_of_period, "customers_start_of_period")
    if lost > start:
        raise ValueError("customers_lost cannot exceed customers_start_of_period")
    return lost / start


def calc_nrr(starting_mrr: Number, expansion_mrr: Number, churned_mrr: Number) -> float:
    """Net Revenue Retention ratio. >1.0 means expansion."""
    start = _require_positive(starting_mrr, "starting_mrr")
    return (start + _require_non_negative(expansion_mrr, "expansion_mrr") -
            _require_non_negative(churned_mrr, "churned_mrr")) / start


def calc_runway_months(cash_balance: Number, monthly_burn_rate: Number) -> float:
    """Months of runway remaining."""
    return _require_non_negative(cash_balance, "cash_balance") / \
           _require_positive(monthly_burn_rate, "monthly_burn_rate")


def calc_revenue_per_hour(revenue: Number, hours_worked: Number) -> float:
    """Revenue generated per hour worked."""
    return _require_non_negative(revenue, "revenue") / \
           _require_positive(hours_worked, "hours_worked")


def calc_utilization_rate(billable_hours: Number, total_available_hours: Number) -> float:
    """Billable utilization ratio (0–1)."""
    b = _require_non_negative(billable_hours, "billable_hours")
    a = _require_positive(total_available_hours, "total_available_hours")
    if b > a:
        raise ValueError("billable_hours cannot exceed total_available_hours")
    return b / a
