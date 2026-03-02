"""PatternRecognitionEngine — Detects recurring structures, anomalies, and trends.

Scans aeOS data streams for patterns, anomalies, and trends. Produces
pattern flags and feature vectors for ML/NLP modules.
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional

from src.cognitive.trajectory_mixin import TrajectoryMixin


class PatternRecognitionEngine(TrajectoryMixin):
    """Scans aeOS data streams for patterns, anomalies, and trends.

    Produces pattern flags and feature vectors for ML/NLP modules.
    """

    def __init__(self, flywheel_logger: Any = None) -> None:
        self._flywheel_logger = flywheel_logger

    def detect_trend(
        self, series: List[float], window: int = 7
    ) -> dict:
        """Detect trend direction and strength via linear regression.

        Returns:
            {direction: 'up'|'down'|'flat', strength: float 0-1,
             slope: float, r_squared: float, label: str}
        """
        if not isinstance(series, list) or len(series) < 2:
            return {
                "direction": "flat",
                "strength": 0.0,
                "slope": 0.0,
                "r_squared": 0.0,
                "label": "insufficient data",
            }

        data = series[-window:] if len(series) > window else series
        n = len(data)
        xs = list(range(n))
        x_mean = sum(xs) / n
        y_mean = sum(data) / n

        ss_xy = sum((xs[i] - x_mean) * (data[i] - y_mean) for i in range(n))
        ss_xx = sum((xs[i] - x_mean) ** 2 for i in range(n))

        if ss_xx == 0:
            slope = 0.0
        else:
            slope = ss_xy / ss_xx

        intercept = y_mean - slope * x_mean
        ss_res = sum((data[i] - (slope * xs[i] + intercept)) ** 2 for i in range(n))
        ss_tot = sum((data[i] - y_mean) ** 2 for i in range(n))
        r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
        r_squared = max(r_squared, 0.0)

        if abs(slope) < 1e-10:
            direction = "flat"
            label = "No significant trend"
        elif slope > 0:
            direction = "up"
            label = f"Uptrend (slope={slope:.4f})"
        else:
            direction = "down"
            label = f"Downtrend (slope={slope:.4f})"

        return {
            "direction": direction,
            "strength": round(min(abs(r_squared), 1.0), 4),
            "slope": round(slope, 6),
            "r_squared": round(r_squared, 4),
            "label": label,
        }

    def detect_anomaly(
        self, series: List[float], threshold_std: float = 2.0
    ) -> dict:
        """Z-score anomaly detection.

        Returns:
            {anomalies: list[int] (indices), scores: list[float],
             threshold: float, anomaly_count: int}
        """
        if not isinstance(series, list) or len(series) < 2:
            return {
                "anomalies": [],
                "scores": [],
                "threshold": threshold_std,
                "anomaly_count": 0,
            }

        n = len(series)
        mean = sum(series) / n
        variance = sum((x - mean) ** 2 for x in series) / n
        std = math.sqrt(variance) if variance > 0 else 0.0

        scores = []
        anomalies = []
        for i, val in enumerate(series):
            if std > 0:
                z = abs(val - mean) / std
            else:
                z = 0.0
            scores.append(round(z, 4))
            if z > threshold_std:
                anomalies.append(i)

        return {
            "anomalies": anomalies,
            "scores": scores,
            "threshold": threshold_std,
            "anomaly_count": len(anomalies),
        }

    def detect_recurring_pattern(
        self,
        events: List[dict],
        key_field: str,
        window_days: int = 30,
    ) -> dict:
        """Identify events that recur with statistical regularity.

        Returns:
            {patterns: list[{pattern: str, frequency: float,
             avg_interval_days: float, confidence: float}]}
        """
        if not isinstance(events, list) or not events:
            return {"patterns": []}

        # Group events by key_field value
        groups: Dict[str, List[float]] = {}
        for evt in events:
            if not isinstance(evt, dict):
                continue
            key = evt.get(key_field)
            if key is None:
                continue
            ts = evt.get("timestamp", evt.get("created_at", 0))
            groups.setdefault(str(key), []).append(float(ts))

        patterns = []
        for pattern_name, timestamps in groups.items():
            timestamps.sort()
            count = len(timestamps)
            if count < 2:
                continue
            intervals = [
                (timestamps[i + 1] - timestamps[i]) / 86400.0
                for i in range(len(timestamps) - 1)
            ]
            avg_interval = sum(intervals) / len(intervals) if intervals else 0.0
            # Confidence based on regularity (low variance = high confidence)
            if len(intervals) > 1 and avg_interval > 0:
                variance = sum(
                    (iv - avg_interval) ** 2 for iv in intervals
                ) / len(intervals)
                cv = math.sqrt(variance) / avg_interval if avg_interval > 0 else 1.0
                confidence = max(1.0 - cv, 0.0)
            else:
                confidence = 0.5

            patterns.append({
                "pattern": pattern_name,
                "frequency": round(count / max(window_days, 1), 4),
                "avg_interval_days": round(avg_interval, 2),
                "confidence": round(min(confidence, 1.0), 4),
            })

        return {"patterns": patterns}

    def extract_feature_vector(self, data_snapshot: dict) -> List[float]:
        """Convert aeOS data snapshot into numeric feature vector for ML.

        Feature order: [revenue, costs, margin, velocity, churn,
                       satisfaction, risk_score, confidence]

        Returns:
            list[float] of normalized features.
        """
        if not isinstance(data_snapshot, dict):
            return [0.0] * 8

        fields = [
            "revenue", "costs", "margin", "velocity",
            "churn", "satisfaction", "risk_score", "confidence",
        ]
        vector = []
        for f in fields:
            val = data_snapshot.get(f, 0.0)
            try:
                vector.append(float(val))
            except (TypeError, ValueError):
                vector.append(0.0)
        return vector

    def scan_execution_log(self, log_entries: List[dict]) -> dict:
        """Scan Project_Execution_Log entries for patterns.

        Returns:
            {flags: list[str], feature_vectors: list[list[float]],
             summary: str}
        """
        if not isinstance(log_entries, list) or not log_entries:
            return {
                "flags": [],
                "feature_vectors": [],
                "summary": "No log entries to scan",
            }

        flags = []
        feature_vectors = []
        blocker_count = 0
        total = len(log_entries)

        for entry in log_entries:
            if not isinstance(entry, dict):
                continue
            fv = self.extract_feature_vector(entry)
            feature_vectors.append(fv)
            status = str(entry.get("status", "")).lower()
            if status in ("blocked", "blocker"):
                blocker_count += 1

        if blocker_count > total * 0.3:
            flags.append("high_blocker_rate")
        if total > 0 and blocker_count == 0:
            flags.append("no_blockers")

        # Velocity trend
        velocities = [
            float(e.get("velocity", 0))
            for e in log_entries
            if isinstance(e, dict) and "velocity" in e
        ]
        if len(velocities) >= 3:
            trend = self.detect_trend(velocities)
            if trend["direction"] == "down" and trend["strength"] > 0.5:
                flags.append("velocity_declining")

        summary = (
            f"Scanned {total} entries: {blocker_count} blockers, "
            f"{len(flags)} flags raised"
        )
        return {
            "flags": flags,
            "feature_vectors": feature_vectors,
            "summary": summary,
        }
