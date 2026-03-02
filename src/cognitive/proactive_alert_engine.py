"""ProactiveAlertEngine — Surfaces notifications requiring human attention.

Generates and manages user-facing alerts by aggregating signals from
AdaptiveThresholdEngine, PatternRecognitionEngine, SAFETY, and BUDGET.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from src.cognitive.adaptive_threshold_engine import AdaptiveThresholdEngine


class ProactiveAlertEngine:
    """Generates and manages user-facing alerts.

    Aggregates signals from Adaptive_Threshold_Engine,
    Pattern_Recognition_Engine, SAFETY, and BUDGET.
    """

    SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def __init__(self) -> None:
        self._alerts: Dict[str, dict] = {}

    def generate_alert(
        self,
        source: str,
        alert_type: str,
        details: dict,
        severity: str = "medium",
    ) -> dict:
        """Create alert record.

        Returns:
            {alert_id: str, source: str, type: str,
             severity: 'low'|'medium'|'high'|'critical',
             message: str, timestamp: float,
             acknowledged: bool, metadata: dict}
        """
        valid_sev = {"low", "medium", "high", "critical"}
        if severity not in valid_sev:
            severity = "medium"

        alert_id = str(uuid.uuid4())
        message = details.get("message", f"{alert_type} alert from {source}")

        alert = {
            "alert_id": alert_id,
            "source": str(source),
            "type": str(alert_type),
            "severity": severity,
            "message": str(message),
            "timestamp": time.time(),
            "acknowledged": False,
            "metadata": dict(details) if isinstance(details, dict) else {},
        }
        self._alerts[alert_id] = alert
        return dict(alert)

    def get_active_alerts(
        self, severity_filter: Optional[str] = None
    ) -> List[dict]:
        """Return unacknowledged alerts, optionally filtered by severity.

        Sorted by severity (critical first) then timestamp.
        """
        alerts = [
            a for a in self._alerts.values() if not a["acknowledged"]
        ]
        if severity_filter:
            alerts = [a for a in alerts if a["severity"] == severity_filter]

        return sorted(
            alerts,
            key=lambda a: (
                self.SEVERITY_ORDER.get(a["severity"], 9),
                a["timestamp"],
            ),
        )

    def acknowledge_alert(self, alert_id: str) -> bool:
        """Mark alert as acknowledged. Returns True if found."""
        if alert_id not in self._alerts:
            return False
        self._alerts[alert_id]["acknowledged"] = True
        return True

    def check_all_thresholds(
        self,
        metrics: Dict[str, float],
        threshold_engine: AdaptiveThresholdEngine,
    ) -> List[dict]:
        """Run all metrics against adaptive thresholds.

        Returns list of triggered alert dicts.
        """
        triggered_alerts = []
        if not isinstance(metrics, dict):
            return triggered_alerts

        for metric_name, value in metrics.items():
            result = threshold_engine.is_alert_triggered(metric_name, value)
            if result.get("triggered"):
                alert = self.generate_alert(
                    source="adaptive_threshold",
                    alert_type=f"threshold_breach_{metric_name}",
                    details={
                        "metric": metric_name,
                        "current": result["current"],
                        "threshold": result["threshold"],
                        "excess_pct": result["excess_pct"],
                        "message": (
                            f"{metric_name} exceeded threshold: "
                            f"{result['current']} > {result['threshold']}"
                        ),
                    },
                    severity=result.get("severity", "medium"),
                )
                triggered_alerts.append(alert)

        return triggered_alerts

    def get_alert_summary(self) -> dict:
        """Return alert summary statistics.

        Returns:
            {total: int, by_severity: dict,
             unacknowledged: int, oldest_unack_hours: float}
        """
        all_alerts = list(self._alerts.values())
        total = len(all_alerts)
        unacked = [a for a in all_alerts if not a["acknowledged"]]

        by_severity: Dict[str, int] = {}
        for a in all_alerts:
            sev = a["severity"]
            by_severity[sev] = by_severity.get(sev, 0) + 1

        if unacked:
            oldest_ts = min(a["timestamp"] for a in unacked)
            oldest_hours = (time.time() - oldest_ts) / 3600.0
        else:
            oldest_hours = 0.0

        return {
            "total": total,
            "by_severity": by_severity,
            "unacknowledged": len(unacked),
            "oldest_unack_hours": round(oldest_hours, 2),
        }
