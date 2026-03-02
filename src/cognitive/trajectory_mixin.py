"""TrajectoryMixin — Trajectory forecasting for PatternRecognitionEngine.

Provides predict_trajectory() that returns a TrajectoryForecast dataclass
with projected values, confidence band, and trend metadata.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TrajectoryForecast:
    """Result of a trajectory prediction."""
    series: List[float]
    projected: List[float]
    upper_bound: List[float]
    lower_bound: List[float]
    trend_direction: str  # 'up', 'down', 'flat'
    trend_strength: float  # 0.0–1.0
    confidence: float  # 0.0–1.0
    horizon: int
    method: str
    generated_at: float = field(default_factory=time.time)


class TrajectoryMixin:
    """Mixin providing trajectory prediction to PatternRecognitionEngine.

    Uses linear regression extrapolation with confidence bands
    based on historical variance.
    """

    def predict_trajectory(
        self,
        series: List[float],
        horizon: int = 7,
        confidence_level: float = 0.95,
    ) -> TrajectoryForecast:
        """Predict future trajectory from a time series.

        Args:
            series: Historical data points (at least 2).
            horizon: Number of future periods to forecast.
            confidence_level: Confidence level for bounds (0.0–1.0).

        Returns:
            TrajectoryForecast with projected values and bounds.
        """
        if not isinstance(series, list) or len(series) < 2:
            return TrajectoryForecast(
                series=list(series) if isinstance(series, list) else [],
                projected=[],
                upper_bound=[],
                lower_bound=[],
                trend_direction="flat",
                trend_strength=0.0,
                confidence=0.0,
                horizon=horizon,
                method="insufficient_data",
            )

        n = len(series)
        xs = list(range(n))
        x_mean = sum(xs) / n
        y_mean = sum(series) / n

        ss_xy = sum((xs[i] - x_mean) * (series[i] - y_mean) for i in range(n))
        ss_xx = sum((xs[i] - x_mean) ** 2 for i in range(n))

        if ss_xx == 0:
            slope = 0.0
        else:
            slope = ss_xy / ss_xx
        intercept = y_mean - slope * x_mean

        # R-squared
        ss_res = sum((series[i] - (slope * xs[i] + intercept)) ** 2 for i in range(n))
        ss_tot = sum((series[i] - y_mean) ** 2 for i in range(n))
        r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        # Residual standard error
        if n > 2:
            residual_std = math.sqrt(ss_res / (n - 2))
        else:
            residual_std = 0.0

        # Z-multiplier approximation for confidence
        z_map = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}
        z = z_map.get(confidence_level, 1.96)

        projected = []
        upper_bound = []
        lower_bound = []
        for step in range(1, horizon + 1):
            x_proj = n - 1 + step
            y_proj = slope * x_proj + intercept
            margin = z * residual_std * math.sqrt(1 + 1 / n)
            projected.append(round(y_proj, 4))
            upper_bound.append(round(y_proj + margin, 4))
            lower_bound.append(round(y_proj - margin, 4))

        # Trend classification
        if abs(slope) < 1e-10:
            direction = "flat"
        elif slope > 0:
            direction = "up"
        else:
            direction = "down"

        strength = min(abs(r_squared), 1.0)

        return TrajectoryForecast(
            series=list(series),
            projected=projected,
            upper_bound=upper_bound,
            lower_bound=lower_bound,
            trend_direction=direction,
            trend_strength=round(strength, 4),
            confidence=round(max(r_squared, 0.0), 4),
            horizon=horizon,
            method="linear_regression",
        )
