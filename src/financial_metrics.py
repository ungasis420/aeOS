"""
financial_metrics.py
====================
Pure-calculation module for financial metrics and ratios.

Purpose
-------
Provide validated, deterministic financial metric calculations for use by
agents, scoring engines, and reporting pipelines within aeOS.

Inputs
------
Numeric primitives (float / int).  Every public function validates its own
inputs and raises ``TypeError`` or ``ValueError`` on bad data.

Outputs
-------
Plain ``dict`` results with standardised keys so callers can feed them
directly into reports or database rows.

Notes
-----
- Stdlib-only — no external dependencies.
- All monetary values are currency-agnostic (caller decides unit).
- Percentages are returned as floats in [0..100] range (not 0..1).

Stamp: S✅ T✅ L✅ A✅
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

__all__ = [
    "calculate_roi",
    "calculate_npv",
    "calculate_payback_period",
    "calculate_profit_margin",
    "calculate_gross_margin",
    "calculate_break_even",
    "calculate_cagr",
    "calculate_debt_to_equity",
    "calculate_current_ratio",
    "calculate_revenue_growth",
    "calculate_clv",
    "calculate_burn_rate",
    "calculate_runway",
    "calculate_mrr",
    "risk_adjust_return",
    "rate_financial_health",
    "summarize_metrics",
]

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _require_number(value: Any, name: str) -> float:
    """Validate that *value* is a finite number and return it as float."""
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number, got {type(value).__name__}")
    val = float(value)
    if math.isnan(val) or math.isinf(val):
        raise ValueError(f"{name} must be finite, got {val}")
    return val


def _require_positive(value: Any, name: str) -> float:
    """Validate that *value* is a positive finite number."""
    val = _require_number(value, name)
    if val <= 0:
        raise ValueError(f"{name} must be positive, got {val}")
    return val


def _require_non_negative(value: Any, name: str) -> float:
    """Validate that *value* is a non-negative finite number."""
    val = _require_number(value, name)
    if val < 0:
        raise ValueError(f"{name} must be non-negative, got {val}")
    return val


# ---------------------------------------------------------------------------
# Public API — individual metrics
# ---------------------------------------------------------------------------

def calculate_roi(gain: float, cost: float) -> Dict[str, Any]:
    """Return on Investment as a percentage.

    Formula: ((gain - cost) / cost) * 100

    Args:
        gain: Total gain from the investment.
        cost: Total cost of the investment (must be positive).

    Returns:
        dict with ``roi_pct`` (float) and ``net_gain`` (float).
    """
    gain = _require_number(gain, "gain")
    cost = _require_positive(cost, "cost")
    net = gain - cost
    roi = (net / cost) * 100.0
    return {"roi_pct": round(roi, 4), "net_gain": round(net, 4)}


def calculate_npv(
    discount_rate: float, cash_flows: List[float]
) -> Dict[str, Any]:
    """Net Present Value of a series of cash flows.

    Args:
        discount_rate: Discount rate per period (e.g. 0.10 for 10 %).
        cash_flows:    List of cash flows; index 0 is the initial outlay
                       (typically negative).

    Returns:
        dict with ``npv`` (float) and ``periods`` (int).
    """
    rate = _require_number(discount_rate, "discount_rate")
    if rate <= -1.0:
        raise ValueError("discount_rate must be greater than -1.0")
    if not isinstance(cash_flows, list) or len(cash_flows) == 0:
        raise ValueError("cash_flows must be a non-empty list of numbers")
    total = 0.0
    for i, cf in enumerate(cash_flows):
        cf = _require_number(cf, f"cash_flows[{i}]")
        total += cf / ((1 + rate) ** i)
    return {"npv": round(total, 4), "periods": len(cash_flows)}


def calculate_payback_period(
    initial_investment: float, annual_cash_flow: float
) -> Dict[str, Any]:
    """Simple payback period in years.

    Args:
        initial_investment: Up-front cost (positive number).
        annual_cash_flow:   Expected annual cash inflow (positive number).

    Returns:
        dict with ``payback_years`` (float).
    """
    inv = _require_positive(initial_investment, "initial_investment")
    acf = _require_positive(annual_cash_flow, "annual_cash_flow")
    return {"payback_years": round(inv / acf, 4)}


def calculate_profit_margin(
    revenue: float, cost: float
) -> Dict[str, Any]:
    """Net profit margin as a percentage.

    Formula: ((revenue - cost) / revenue) * 100

    Args:
        revenue: Total revenue (must be positive).
        cost:    Total cost.

    Returns:
        dict with ``margin_pct`` and ``profit``.
    """
    rev = _require_positive(revenue, "revenue")
    cst = _require_number(cost, "cost")
    profit = rev - cst
    margin = (profit / rev) * 100.0
    return {"margin_pct": round(margin, 4), "profit": round(profit, 4)}


def calculate_gross_margin(
    revenue: float, cogs: float
) -> Dict[str, Any]:
    """Gross margin percentage.

    Formula: ((revenue - cogs) / revenue) * 100

    Args:
        revenue: Total revenue (positive).
        cogs:    Cost of goods sold (non-negative).

    Returns:
        dict with ``gross_margin_pct`` and ``gross_profit``.
    """
    rev = _require_positive(revenue, "revenue")
    c = _require_non_negative(cogs, "cogs")
    gp = rev - c
    return {
        "gross_margin_pct": round((gp / rev) * 100.0, 4),
        "gross_profit": round(gp, 4),
    }


def calculate_break_even(
    fixed_costs: float,
    price_per_unit: float,
    variable_cost_per_unit: float,
) -> Dict[str, Any]:
    """Break-even point in units.

    Formula: fixed_costs / (price_per_unit - variable_cost_per_unit)

    Args:
        fixed_costs:            Total fixed costs (non-negative).
        price_per_unit:         Selling price per unit (positive).
        variable_cost_per_unit: Variable cost per unit (non-negative).

    Returns:
        dict with ``break_even_units`` (float) and ``contribution_margin``.
    """
    fc = _require_non_negative(fixed_costs, "fixed_costs")
    ppu = _require_positive(price_per_unit, "price_per_unit")
    vcu = _require_non_negative(variable_cost_per_unit, "variable_cost_per_unit")
    cm = ppu - vcu
    if cm <= 0:
        raise ValueError(
            "price_per_unit must exceed variable_cost_per_unit for break-even"
        )
    return {
        "break_even_units": round(fc / cm, 4),
        "contribution_margin": round(cm, 4),
    }


def calculate_cagr(
    beginning_value: float, ending_value: float, periods: int
) -> Dict[str, Any]:
    """Compound Annual Growth Rate.

    Formula: (ending / beginning) ^ (1/periods) - 1   (× 100 for %)

    Args:
        beginning_value: Starting value (positive).
        ending_value:    Ending value (positive).
        periods:         Number of periods (positive int).

    Returns:
        dict with ``cagr_pct``.
    """
    bv = _require_positive(beginning_value, "beginning_value")
    ev = _require_positive(ending_value, "ending_value")
    if not isinstance(periods, int) or periods <= 0:
        raise ValueError("periods must be a positive integer")
    cagr = ((ev / bv) ** (1.0 / periods) - 1) * 100.0
    return {"cagr_pct": round(cagr, 4)}


def calculate_debt_to_equity(
    total_debt: float, total_equity: float
) -> Dict[str, Any]:
    """Debt-to-equity ratio.

    Args:
        total_debt:   Total debt (non-negative).
        total_equity: Total equity (positive).

    Returns:
        dict with ``de_ratio``.
    """
    d = _require_non_negative(total_debt, "total_debt")
    e = _require_positive(total_equity, "total_equity")
    return {"de_ratio": round(d / e, 4)}


def calculate_current_ratio(
    current_assets: float, current_liabilities: float
) -> Dict[str, Any]:
    """Current ratio (liquidity).

    Args:
        current_assets:      Total current assets (non-negative).
        current_liabilities: Total current liabilities (positive).

    Returns:
        dict with ``current_ratio``.
    """
    ca = _require_non_negative(current_assets, "current_assets")
    cl = _require_positive(current_liabilities, "current_liabilities")
    return {"current_ratio": round(ca / cl, 4)}


def calculate_revenue_growth(
    previous_revenue: float, current_revenue: float
) -> Dict[str, Any]:
    """Revenue growth rate as a percentage.

    Formula: ((current - previous) / previous) * 100

    Args:
        previous_revenue: Prior-period revenue (positive).
        current_revenue:  Current-period revenue (non-negative).

    Returns:
        dict with ``growth_pct`` and ``delta``.
    """
    prev = _require_positive(previous_revenue, "previous_revenue")
    curr = _require_non_negative(current_revenue, "current_revenue")
    delta = curr - prev
    pct = (delta / prev) * 100.0
    return {"growth_pct": round(pct, 4), "delta": round(delta, 4)}


def calculate_clv(
    avg_purchase_value: float,
    purchase_frequency: float,
    customer_lifespan: float,
) -> Dict[str, Any]:
    """Customer Lifetime Value.

    Formula: avg_purchase_value * purchase_frequency * customer_lifespan

    Args:
        avg_purchase_value: Average value per purchase (positive).
        purchase_frequency: Average purchases per period (positive).
        customer_lifespan:  Expected customer lifespan in periods (positive).

    Returns:
        dict with ``clv``.
    """
    apv = _require_positive(avg_purchase_value, "avg_purchase_value")
    pf = _require_positive(purchase_frequency, "purchase_frequency")
    cl = _require_positive(customer_lifespan, "customer_lifespan")
    return {"clv": round(apv * pf * cl, 4)}


def calculate_burn_rate(
    starting_cash: float, ending_cash: float, months: int
) -> Dict[str, Any]:
    """Monthly burn rate.

    Formula: (starting_cash - ending_cash) / months

    Args:
        starting_cash: Cash at period start (non-negative).
        ending_cash:   Cash at period end (non-negative).
        months:        Number of months in the period (positive int).

    Returns:
        dict with ``monthly_burn_rate`` and ``total_burned``.
    """
    sc = _require_non_negative(starting_cash, "starting_cash")
    ec = _require_non_negative(ending_cash, "ending_cash")
    if not isinstance(months, int) or months <= 0:
        raise ValueError("months must be a positive integer")
    burned = sc - ec
    return {
        "monthly_burn_rate": round(burned / months, 4),
        "total_burned": round(burned, 4),
    }


def calculate_runway(
    cash_balance: float, monthly_burn_rate: float
) -> Dict[str, Any]:
    """Cash runway in months.

    Args:
        cash_balance:      Available cash (non-negative).
        monthly_burn_rate: Monthly cash burn (positive).

    Returns:
        dict with ``runway_months``.
    """
    cb = _require_non_negative(cash_balance, "cash_balance")
    mbr = _require_positive(monthly_burn_rate, "monthly_burn_rate")
    return {"runway_months": round(cb / mbr, 4)}


def calculate_mrr(
    subscribers: int, avg_revenue_per_user: float
) -> Dict[str, Any]:
    """Monthly Recurring Revenue.

    Args:
        subscribers:          Number of active subscribers (non-negative int).
        avg_revenue_per_user: ARPU (positive).

    Returns:
        dict with ``mrr`` and ``arr`` (annualised).
    """
    if not isinstance(subscribers, int) or subscribers < 0:
        raise ValueError("subscribers must be a non-negative integer")
    arpu = _require_positive(avg_revenue_per_user, "avg_revenue_per_user")
    mrr = subscribers * arpu
    return {"mrr": round(mrr, 4), "arr": round(mrr * 12, 4)}


def risk_adjust_return(
    expected_return: float,
    risk_factor: float,
    profile: str = "moderate",
) -> Dict[str, Any]:
    """Apply a risk adjustment to an expected return.

    The adjustment multiplier varies by investor profile:
      - conservative: 0.7
      - moderate:     0.85
      - aggressive:   1.0

    Formula: expected_return * multiplier * (1 - risk_factor)

    Args:
        expected_return: Gross expected return (number).
        risk_factor:     Risk factor in [0, 1].
        profile:         One of ``conservative``, ``moderate``, ``aggressive``.

    Returns:
        dict with ``adjusted_return``, ``multiplier``, ``profile``.
    """
    er = _require_number(expected_return, "expected_return")
    rf = _require_number(risk_factor, "risk_factor")
    if rf < 0.0 or rf > 1.0:
        raise ValueError("risk_factor must be between 0.0 and 1.0")
    _MULTIPLIERS = {
        "conservative": 0.7,
        "moderate": 0.85,
        "aggressive": 1.0,
    }
    profile = profile.lower().strip()
    if profile not in _MULTIPLIERS:
        raise ValueError(
            f"profile must be one of {list(_MULTIPLIERS)}, got '{profile}'"
        )
    mult = _MULTIPLIERS[profile]
    adjusted = er * mult * (1 - rf)
    return {
        "adjusted_return": round(adjusted, 4),
        "multiplier": mult,
        "profile": profile,
    }


# ---------------------------------------------------------------------------
# Composite / rating helpers
# ---------------------------------------------------------------------------

_HEALTH_THRESHOLDS: Dict[str, List[Tuple[float, str]]] = {
    "roi_pct": [(50, "excellent"), (20, "good"), (0, "fair")],
    "margin_pct": [(30, "excellent"), (15, "good"), (0, "fair")],
    "gross_margin_pct": [(60, "excellent"), (40, "good"), (20, "fair")],
    "current_ratio": [(2.0, "excellent"), (1.0, "good"), (0.5, "fair")],
    "de_ratio": [(0.5, "excellent"), (1.0, "good"), (2.0, "fair")],
    "runway_months": [(18, "excellent"), (6, "good"), (3, "fair")],
}


def rate_financial_health(metrics: Dict[str, float]) -> Dict[str, Any]:
    """Rate a set of financial metrics against built-in thresholds.

    Each recognised key in *metrics* is scored as one of:
    ``excellent``, ``good``, ``fair``, or ``poor``.

    Args:
        metrics: Dict mapping metric names to their float values.

    Returns:
        dict with ``ratings`` (per-metric dict) and ``score`` (0-100 int).
    """
    if not isinstance(metrics, dict):
        raise TypeError("metrics must be a dict")
    ratings: Dict[str, str] = {}
    scored = 0
    total = 0
    for key, thresholds in _HEALTH_THRESHOLDS.items():
        if key not in metrics:
            continue
        val = _require_number(metrics[key], key)
        total += 1
        # de_ratio is inverse (lower is better)
        if key == "de_ratio":
            for limit, label in thresholds:
                if val <= limit:
                    ratings[key] = label
                    break
            else:
                ratings[key] = "poor"
        else:
            for limit, label in thresholds:
                if val >= limit:
                    ratings[key] = label
                    break
            else:
                ratings[key] = "poor"
        _SCORE_MAP = {"excellent": 100, "good": 75, "fair": 50, "poor": 25}
        scored += _SCORE_MAP[ratings[key]]
    overall = round(scored / total) if total > 0 else 0
    return {"ratings": ratings, "score": overall}


def summarize_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate a list of metric dicts into summary statistics.

    Computes count, mean, min, and max for every numeric key found across
    all *records*.

    Args:
        records: List of dicts (e.g. outputs of other metric functions).

    Returns:
        dict with ``count``, ``summary`` (per-key stats), and ``keys``.
    """
    if not isinstance(records, list):
        raise TypeError("records must be a list")
    if len(records) == 0:
        return {"count": 0, "summary": {}, "keys": []}
    accum: Dict[str, List[float]] = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        for k, v in rec.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                accum.setdefault(k, []).append(float(v))
    summary: Dict[str, Dict[str, float]] = {}
    for k, vals in accum.items():
        summary[k] = {
            "mean": round(sum(vals) / len(vals), 4),
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
            "count": len(vals),
        }
    return {
        "count": len(records),
        "summary": summary,
        "keys": sorted(accum.keys()),
    }
