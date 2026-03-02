"""PredictiveFinance — Financial forecasting and predictive analytics for aeOS.

All forecast outputs include confidence intervals and the DISCLAIMER field.
Not investment advice. Past model performance does not guarantee future accuracy.
"""
from __future__ import annotations

import math
import random
import time
from typing import Any, Dict, List, Optional

DISCLAIMER = (
    "Quantitative model output. Not investment advice. "
    "Past model performance does not guarantee future accuracy."
)


class PredictiveFinance:
    """Financial forecasting and predictive analytics.

    All forecast outputs carry the DISCLAIMER field.
    """

    def price_forecast(
        self,
        prices: List[float],
        horizon_days: int,
        method: str = "ensemble",
    ) -> dict:
        """Project price range over horizon.

        method: 'regression'|'monte_carlo'|'ensemble'

        Returns:
            {p10, p25, p50, p75, p90, method, assumptions, disclaimer}
        """
        if not isinstance(prices, list) or len(prices) < 2 or horizon_days <= 0:
            return {
                "p10": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0,
                "method": method,
                "assumptions": {"data_points": 0},
                "disclaimer": DISCLAIMER,
            }

        valid_methods = {"regression", "monte_carlo", "ensemble"}
        if method not in valid_methods:
            method = "ensemble"

        n = len(prices)
        returns = [
            (prices[i] - prices[i - 1]) / prices[i - 1]
            for i in range(1, n)
            if prices[i - 1] != 0
        ]

        if not returns:
            last = prices[-1]
            return {
                "p10": last, "p25": last, "p50": last, "p75": last, "p90": last,
                "method": method,
                "assumptions": {"data_points": n},
                "disclaimer": DISCLAIMER,
            }

        mean_ret = sum(returns) / len(returns)
        var_ret = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        std_ret = math.sqrt(var_ret) if var_ret > 0 else 0.001

        last_price = prices[-1]

        if method == "regression":
            projections = self._regression_forecast(
                prices, horizon_days, mean_ret, std_ret
            )
        elif method == "monte_carlo":
            projections = self._monte_carlo_forecast(
                last_price, horizon_days, mean_ret, std_ret
            )
        else:
            # Ensemble: average of both
            reg = self._regression_forecast(
                prices, horizon_days, mean_ret, std_ret
            )
            mc = self._monte_carlo_forecast(
                last_price, horizon_days, mean_ret, std_ret
            )
            projections = sorted([(r + m) / 2 for r, m in zip(reg, mc)])

        projections.sort()
        pctls = self._percentiles(projections, [10, 25, 50, 75, 90])

        return {
            "p10": round(pctls[0], 2),
            "p25": round(pctls[1], 2),
            "p50": round(pctls[2], 2),
            "p75": round(pctls[3], 2),
            "p90": round(pctls[4], 2),
            "method": method,
            "assumptions": {
                "data_points": n,
                "mean_return": round(mean_ret, 6),
                "std_return": round(std_ret, 6),
            },
            "disclaimer": DISCLAIMER,
        }

    def trend_strength(
        self, prices: List[float], period: int = 14
    ) -> dict:
        """Composite trend score from EMA, momentum, and slope.

        Returns:
            {score: float (-1 to +1), direction, components, disclaimer}
        """
        if not isinstance(prices, list) or len(prices) < 3:
            return {
                "score": 0.0,
                "direction": "flat",
                "components": {},
                "disclaimer": DISCLAIMER,
            }

        data = prices[-period:] if len(prices) > period else prices
        n = len(data)

        # Slope component
        xs = list(range(n))
        x_mean = sum(xs) / n
        y_mean = sum(data) / n
        ss_xy = sum((xs[i] - x_mean) * (data[i] - y_mean) for i in range(n))
        ss_xx = sum((xs[i] - x_mean) ** 2 for i in range(n))
        slope = ss_xy / ss_xx if ss_xx > 0 else 0.0
        slope_norm = max(min(slope / (y_mean if y_mean != 0 else 1), 1.0), -1.0)

        # EMA component
        alpha = 2.0 / (n + 1)
        ema = data[0]
        for val in data[1:]:
            ema = alpha * val + (1 - alpha) * ema
        ema_signal = (ema - y_mean) / (y_mean if y_mean != 0 else 1)
        ema_norm = max(min(ema_signal, 1.0), -1.0)

        # Momentum (rate of change)
        if data[0] != 0:
            momentum = (data[-1] - data[0]) / abs(data[0])
        else:
            momentum = 0.0
        momentum_norm = max(min(momentum, 1.0), -1.0)

        score = (slope_norm * 0.4 + ema_norm * 0.3 + momentum_norm * 0.3)
        score = max(min(score, 1.0), -1.0)

        if score > 0.1:
            direction = "up"
        elif score < -0.1:
            direction = "down"
        else:
            direction = "flat"

        return {
            "score": round(score, 4),
            "direction": direction,
            "components": {
                "slope": round(slope_norm, 4),
                "ema": round(ema_norm, 4),
                "momentum": round(momentum_norm, 4),
            },
            "disclaimer": DISCLAIMER,
        }

    def volatility_forecast(
        self, prices: List[float], horizon_days: int = 30
    ) -> dict:
        """Projected annualised volatility using GARCH(1,1) approximation.

        Returns:
            {current_vol, forecast_vol, vol_percentile,
             regime, disclaimer}
        """
        if not isinstance(prices, list) or len(prices) < 3:
            return {
                "current_vol": 0.0,
                "forecast_vol": 0.0,
                "vol_percentile": 0.0,
                "regime": "low",
                "disclaimer": DISCLAIMER,
            }

        returns = [
            (prices[i] - prices[i - 1]) / prices[i - 1]
            for i in range(1, len(prices))
            if prices[i - 1] != 0
        ]

        if not returns:
            return {
                "current_vol": 0.0,
                "forecast_vol": 0.0,
                "vol_percentile": 0.0,
                "regime": "low",
                "disclaimer": DISCLAIMER,
            }

        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        current_vol = math.sqrt(variance) * math.sqrt(252)  # annualised

        # GARCH(1,1) approximation
        omega = 0.000001
        alpha_g = 0.1
        beta_g = 0.85
        forecast_var = omega + alpha_g * (returns[-1] ** 2) + beta_g * variance
        forecast_vol = math.sqrt(max(forecast_var, 0)) * math.sqrt(252)

        # Percentile (heuristic based on typical vol range 0-100%)
        vol_pct = min(current_vol / 1.0, 1.0) * 100

        if current_vol < 0.15:
            regime = "low"
        elif current_vol < 0.30:
            regime = "normal"
        else:
            regime = "high"

        return {
            "current_vol": round(current_vol, 4),
            "forecast_vol": round(forecast_vol, 4),
            "vol_percentile": round(vol_pct, 2),
            "regime": regime,
            "disclaimer": DISCLAIMER,
        }

    def scenario_analysis(
        self,
        portfolio: List[dict],
        scenarios: List[dict],
    ) -> dict:
        """For each named scenario, project portfolio impact.

        Returns:
            {results, worst_case, best_case, disclaimer}
        """
        if not portfolio or not scenarios:
            return {
                "results": [],
                "worst_case": "N/A",
                "best_case": "N/A",
                "disclaimer": DISCLAIMER,
            }

        total_value = sum(
            float(p.get("current_value", 0)) for p in portfolio
        )

        results = []
        for sc in scenarios:
            if not isinstance(sc, dict):
                continue
            shock = float(sc.get("shock_pct", 0)) / 100.0
            impact_pct = shock * 100
            dollar_impact = total_value * shock

            if abs(impact_pct) > 20:
                severity = "high"
            elif abs(impact_pct) > 10:
                severity = "medium"
            else:
                severity = "low"

            results.append({
                "scenario": sc.get("name", "unnamed"),
                "portfolio_impact_pct": round(impact_pct, 2),
                "dollar_impact": round(dollar_impact, 2),
                "severity": severity,
            })

        worst = min(results, key=lambda r: r["portfolio_impact_pct"]) if results else None
        best = max(results, key=lambda r: r["portfolio_impact_pct"]) if results else None

        return {
            "results": results,
            "worst_case": worst["scenario"] if worst else "N/A",
            "best_case": best["scenario"] if best else "N/A",
            "disclaimer": DISCLAIMER,
        }

    def get_model_performance(
        self, ticker: str, predictions: List[dict]
    ) -> dict:
        """Historical accuracy metrics per model.

        Returns:
            {mae, rmse, directional_accuracy, best_method, sample_size}
        """
        if not predictions:
            return {
                "mae": 0.0,
                "rmse": 0.0,
                "directional_accuracy": 0.0,
                "best_method": "none",
                "sample_size": 0,
            }

        errors = []
        sq_errors = []
        correct_dir = 0
        total_dir = 0
        by_method: Dict[str, List[float]] = {}

        for pred in predictions:
            if not isinstance(pred, dict):
                continue
            actual = float(pred.get("actual", 0))
            predicted = float(pred.get("predicted", 0))
            method = str(pred.get("method", "unknown"))

            error = abs(actual - predicted)
            errors.append(error)
            sq_errors.append(error ** 2)

            by_method.setdefault(method, []).append(error)

            if pred.get("prev_actual") is not None:
                prev = float(pred["prev_actual"])
                actual_dir = actual - prev
                pred_dir = predicted - prev
                if (actual_dir > 0 and pred_dir > 0) or (
                    actual_dir < 0 and pred_dir < 0
                ):
                    correct_dir += 1
                total_dir += 1

        n = len(errors)
        mae = sum(errors) / n if n > 0 else 0.0
        rmse = math.sqrt(sum(sq_errors) / n) if n > 0 else 0.0
        dir_acc = correct_dir / total_dir if total_dir > 0 else 0.0

        best_method = "none"
        best_mae = float("inf")
        for method, errs in by_method.items():
            avg_err = sum(errs) / len(errs)
            if avg_err < best_mae:
                best_mae = avg_err
                best_method = method

        return {
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "directional_accuracy": round(dir_acc, 4),
            "best_method": best_method,
            "sample_size": n,
        }

    # ── Internal helpers ───────────────────────────────────────

    @staticmethod
    def _regression_forecast(
        prices: List[float],
        horizon: int,
        mean_ret: float,
        std_ret: float,
    ) -> List[float]:
        n = len(prices)
        xs = list(range(n))
        x_mean = sum(xs) / n
        y_mean = sum(prices) / n
        ss_xy = sum((xs[i] - x_mean) * (prices[i] - y_mean) for i in range(n))
        ss_xx = sum((xs[i] - x_mean) ** 2 for i in range(n))
        slope = ss_xy / ss_xx if ss_xx > 0 else 0
        intercept = y_mean - slope * x_mean

        projections = []
        for d in range(1, horizon + 1):
            base = slope * (n - 1 + d) + intercept
            # Add spread based on std
            for mult in [-1.5, -0.5, 0, 0.5, 1.5]:
                projections.append(base + mult * std_ret * prices[-1])
        return projections

    @staticmethod
    def _monte_carlo_forecast(
        last_price: float,
        horizon: int,
        mean_ret: float,
        std_ret: float,
        simulations: int = 50,
    ) -> List[float]:
        results = []
        rng = random.Random(42)  # Deterministic for reproducibility
        for _ in range(simulations):
            price = last_price
            for _ in range(horizon):
                ret = rng.gauss(mean_ret, std_ret)
                price *= 1 + ret
            results.append(price)
        return results

    @staticmethod
    def _percentiles(data: List[float], pcts: List[int]) -> List[float]:
        if not data:
            return [0.0] * len(pcts)
        sorted_data = sorted(data)
        n = len(sorted_data)
        result = []
        for p in pcts:
            idx = (p / 100) * (n - 1)
            lower = int(math.floor(idx))
            upper = min(lower + 1, n - 1)
            weight = idx - lower
            val = sorted_data[lower] * (1 - weight) + sorted_data[upper] * weight
            result.append(val)
        return result
