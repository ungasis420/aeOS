"""AdaptiveThresholdEngine — Dynamic alert thresholds for aeOS.

Computes and maintains dynamic thresholds based on historical behavior
using EMA smoothing and statistical methods instead of fixed cutoffs.
"""
from __future__ import annotations

import math
import time
from typing import Dict, List, Optional


class AdaptiveThresholdEngine:
    """Computes and maintains dynamic alert thresholds.

    Uses EMA and statistical history instead of fixed values.
    """

    def __init__(self, default_sensitivity: float = 2.0) -> None:
        self._thresholds: Dict[str, dict] = {}
        self._default_sensitivity = float(default_sensitivity)

    def compute_threshold(
        self,
        metric_name: str,
        history: List[float],
        sensitivity: float = 2.0,
    ) -> dict:
        """Compute dynamic threshold from historical data.

        Returns:
            {threshold: float, mean: float, std: float,
             method: 'ema'|'rolling', sensitivity: float}
        Uses EMA for smoothing + n*std above mean as threshold.
        """
        if not isinstance(history, list) or len(history) < 2:
            return {
                "threshold": 0.0,
                "mean": 0.0,
                "std": 0.0,
                "method": "insufficient_data",
                "sensitivity": sensitivity,
            }

        n = len(history)
        mean = sum(history) / n
        variance = sum((x - mean) ** 2 for x in history) / n
        std = math.sqrt(variance)

        # EMA smoothing (alpha = 2/(n+1))
        alpha = 2.0 / (n + 1)
        ema = history[0]
        for val in history[1:]:
            ema = alpha * val + (1 - alpha) * ema

        threshold = ema + sensitivity * std
        method = "ema" if n >= 5 else "rolling"

        result = {
            "threshold": round(threshold, 4),
            "mean": round(mean, 4),
            "std": round(std, 4),
            "method": method,
            "sensitivity": sensitivity,
        }

        self._thresholds[metric_name] = {
            **result,
            "history": list(history),
            "updated_at": time.time(),
        }

        return result

    def update_threshold(
        self, metric_name: str, new_value: float
    ) -> dict:
        """Incrementally update stored threshold with new observation.

        Returns:
            Updated threshold dict.
        """
        if metric_name not in self._thresholds:
            return self.compute_threshold(
                metric_name, [float(new_value)], self._default_sensitivity
            )

        stored = self._thresholds[metric_name]
        history = stored.get("history", [])
        history.append(float(new_value))

        # Keep last 100 observations
        if len(history) > 100:
            history = history[-100:]

        sensitivity = stored.get("sensitivity", self._default_sensitivity)
        return self.compute_threshold(metric_name, history, sensitivity)

    def is_alert_triggered(
        self, metric_name: str, current_value: float
    ) -> dict:
        """Check if current value triggers an alert.

        Returns:
            {triggered: bool, current: float, threshold: float,
             excess_pct: float, severity: 'low'|'medium'|'high'}
        """
        current = float(current_value)

        if metric_name not in self._thresholds:
            return {
                "triggered": False,
                "current": current,
                "threshold": 0.0,
                "excess_pct": 0.0,
                "severity": "low",
            }

        stored = self._thresholds[metric_name]
        threshold = stored["threshold"]

        if threshold == 0:
            triggered = False
            excess_pct = 0.0
        else:
            triggered = current > threshold
            excess_pct = (
                ((current - threshold) / threshold) * 100.0
                if triggered and threshold > 0
                else 0.0
            )

        if not triggered:
            severity = "low"
        elif excess_pct > 50:
            severity = "high"
        elif excess_pct > 20:
            severity = "medium"
        else:
            severity = "low"

        return {
            "triggered": triggered,
            "current": round(current, 4),
            "threshold": round(threshold, 4),
            "excess_pct": round(excess_pct, 2),
            "severity": severity,
        }

    def recalibrate_all(
        self, metrics_history: Dict[str, List[float]]
    ) -> dict:
        """Batch recalibrate all tracked metrics.

        Returns:
            {updated: list[str], thresholds: dict[str, float]}
        """
        if not isinstance(metrics_history, dict):
            return {"updated": [], "thresholds": {}}

        updated = []
        thresholds = {}
        for metric_name, history in metrics_history.items():
            if not isinstance(history, list) or len(history) < 2:
                continue
            sensitivity = self._default_sensitivity
            if metric_name in self._thresholds:
                sensitivity = self._thresholds[metric_name].get(
                    "sensitivity", self._default_sensitivity
                )
            result = self.compute_threshold(metric_name, history, sensitivity)
            updated.append(metric_name)
            thresholds[metric_name] = result["threshold"]

        return {"updated": updated, "thresholds": thresholds}

    def get_threshold(self, metric_name: str) -> Optional[dict]:
        """Get current threshold data for a metric."""
        stored = self._thresholds.get(metric_name)
        if stored is None:
            return None
        return {k: v for k, v in stored.items() if k != "history"}
