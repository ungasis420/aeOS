"""
aeOS v9.0 — Predictive Life Engine — Trajectory Extension (F1.1)
================================================================
FUNCTIONAL — adds predict_trajectory() to Pattern_Recognition_Engine.
This is the ~20-line addition to Phase 3's Pattern_Recognition_Engine
that wires it into v9.0's temporal prediction capability.
Without this method defined now, the engine has no output contract for
F2.5 (Cognitive Twin) and F1.6 (Causal Inference) to consume.
Integration point:
  Phase 3 builds Pattern_Recognition_Engine in src/cognitive/pattern_recognition.py
  Add this mixin/method to that class during Phase 3 P1 build.
Feeds:
  - Cognitive Digital Twin (F2.5) — 30/60/90-day state predictions
  - Proactive Alert Engine (Phase 3) — surfaces predictions as alerts
  - PREDICTIVE_FINANCE (Phase 3) — financial trajectory specifically
"""
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone, timedelta
from enum import Enum
class TrajectoryConfidence(Enum):
    HIGH    = "high"     # > 0.75 — strong pattern, stable domain
    MEDIUM  = "medium"   # 0.50–0.75 — emerging pattern
    LOW     = "low"      # 0.25–0.50 — sparse data
    UNKNOWN = "unknown"  # < 0.25 — insufficient data
@dataclass
class TrajectoryPoint:
    """A single point in a predicted trajectory."""
    horizon_days: int             # 30, 60, or 90
    projected_date: str           # ISO date string
    predicted_state: dict         # domain-specific state prediction
    confidence: TrajectoryConfidence
    confidence_score: float       # 0.0–1.0
    key_drivers: list[str]        # top variables driving this prediction
    risks: list[str]              # what could derail this trajectory
    opportunities: list[str]      # what could accelerate it
@dataclass
class TrajectoryForecast:
    """
    Full 30/60/90-day trajectory for a life domain.
    Output of predict_trajectory().
    """
    domain: str
    generated_at: str
    current_state_summary: str
    trajectory_direction: str     # "improving", "declining", "stable", "volatile"
    points: list[TrajectoryPoint]
    overall_confidence: TrajectoryConfidence
    data_points_used: int
    recommendation: str
    caveat: str = ""
class TrajectoryMixin:
    """
    Mixin for Pattern_Recognition_Engine.
    Adds predict_trajectory() — the core Predictive Life Engine method.
    Add to Pattern_Recognition_Engine in Phase 3:
        class PatternRecognitionEngine(TrajectoryMixin):
            ...
    Then call:
        engine = PatternRecognitionEngine(flywheel_logger=logger)
        forecast = engine.predict_trajectory(domain="business", horizons=[30, 60, 90])
    """
    # Minimum decisions with outcomes needed for trajectory prediction
    _MIN_TRAJECTORY_DATA = 10
    def predict_trajectory(
        self,
        domain: str,
        horizons: list[int] = None,
        context: Optional[dict] = None
    ) -> TrajectoryForecast:
        """
        Generate 30/60/90-day trajectory forecast for a life domain.
        Projects current patterns forward using:
          - FlywheelLogger decision history in this domain
          - Outcome valence trends (improving/declining?)
          - Confidence trends (getting clearer or murkier?)
          - Cartridge effectiveness patterns
          - Any causal edges from CausalInferenceEngine (if available)
        Args:
            domain:   Life domain to forecast. Must be in VALID_DOMAINS.
            horizons: Days to forecast. Default: [30, 60, 90].
            context:  Optional current state to factor in
                      (e.g. {"energy": "low", "cash_runway_months": 4}).
        Returns:
            TrajectoryForecast with points at each horizon.
            Returns low-confidence stub if < 10 decisions with outcomes.
        Usage:
            # In Pattern_Recognition_Engine after Phase 3 build:
            forecast = self.predict_trajectory(domain="business")
            print(f"90-day outlook: {forecast.points[-1].predicted_state}")
            print(f"Confidence: {forecast.overall_confidence.value}")
            print(f"Key drivers: {forecast.points[-1].key_drivers}")
        """
        if horizons is None:
            horizons = [30, 60, 90]
        now = datetime.now(timezone.utc)
        generated_at = now.isoformat()
        # Attempt to get domain history from FlywheelLogger
        domain_data = self._get_domain_data_for_trajectory(domain)
        data_count = domain_data.get("total", 0)
        with_outcomes = domain_data.get("with_outcomes", 0)
        # Insufficient data path
        if with_outcomes < self._MIN_TRAJECTORY_DATA:
            shortfall = self._MIN_TRAJECTORY_DATA - with_outcomes
            return TrajectoryForecast(
                domain=domain,
                generated_at=generated_at,
                current_state_summary="Insufficient data for trajectory prediction.",
                trajectory_direction="unknown",
                points=[
                    TrajectoryPoint(
                        horizon_days=h,
                        projected_date=(now + timedelta(days=h)).date().isoformat(),
                        predicted_state={"status": "insufficient_data"},
                        confidence=TrajectoryConfidence.UNKNOWN,
                        confidence_score=0.0,
                        key_drivers=[],
                        risks=[f"Need {shortfall} more logged outcomes"],
                        opportunities=["Log decisions + outcomes via FlywheelLogger"]
                    )
                    for h in horizons
                ],
                overall_confidence=TrajectoryConfidence.UNKNOWN,
                data_points_used=with_outcomes,
                recommendation=(
                    f"Log {shortfall} more decisions with outcomes in '{domain}' "
                    f"to unlock trajectory forecasting."
                ),
                caveat="Trajectory forecasting requires 10+ decisions with recorded outcomes."
            )
        # Sufficient data path — compute trajectory
        trend = self._compute_trend(domain_data)
        direction = self._classify_direction(trend)
        confidence_score = self._compute_trajectory_confidence(domain_data)
        confidence_level = self._score_to_confidence_level(confidence_score)
        points = [
            self._project_horizon(
                horizon_days=h,
                now=now,
                domain=domain,
                domain_data=domain_data,
                trend=trend,
                confidence_score=confidence_score,
                context=context or {}
            )
            for h in horizons
        ]
        return TrajectoryForecast(
            domain=domain,
            generated_at=generated_at,
            current_state_summary=self._summarize_current_state(domain_data),
            trajectory_direction=direction,
            points=points,
            overall_confidence=confidence_level,
            data_points_used=with_outcomes,
            recommendation=self._generate_trajectory_recommendation(
                direction, confidence_level, domain, points
            ),
            caveat="" if confidence_score > 0.5 else
                "Low confidence — trajectory improves with more logged outcomes."
        )
    # ------------------------------------------------------------------
    # Internal trajectory computation helpers
    # ------------------------------------------------------------------
    def _get_domain_data_for_trajectory(self, domain: str) -> dict:
        """
        Pull domain history from FlywheelLogger.
        Falls back gracefully if logger not available.
        """
        try:
            if hasattr(self, "_flywheel_logger") and self._flywheel_logger:
                return self._flywheel_logger.get_domain_intelligence(domain)
        except Exception:
            pass
        return {
            "total": 0, "with_outcomes": 0,
            "avg_confidence": 0.0, "avg_valence": None,
            "first_decision": None, "latest_decision": None
        }
    def _compute_trend(self, domain_data: dict) -> float:
        """
        Compute trend slope from domain data.
        Positive = improving, negative = declining, 0 = stable.
        Returns value in range -1.0 to +1.0.
        """
        avg_valence = domain_data.get("avg_valence")
        if avg_valence is None:
            return 0.0
        # Normalize: avg_valence is in -1 to +1, use directly as trend
        return float(avg_valence)
    def _classify_direction(self, trend: float) -> str:
        if trend > 0.3:
            return "improving"
        elif trend < -0.3:
            return "declining"
        elif abs(trend) <= 0.1:
            return "stable"
        else:
            return "volatile"
    def _compute_trajectory_confidence(self, domain_data: dict) -> float:
        """Confidence based on data volume and recency."""
        with_outcomes = domain_data.get("with_outcomes", 0)
        # Saturates at 50 decisions → 1.0 max contribution from volume
        volume_score = min(with_outcomes / 50, 1.0)
        # Weight with avg_confidence from decisions
        avg_conf = float(domain_data.get("avg_confidence") or 0.0)
        return round((volume_score * 0.6) + (avg_conf * 0.4), 4)
    def _score_to_confidence_level(self, score: float) -> TrajectoryConfidence:
        if score >= 0.75:
            return TrajectoryConfidence.HIGH
        elif score >= 0.50:
            return TrajectoryConfidence.MEDIUM
        elif score >= 0.25:
            return TrajectoryConfidence.LOW
        else:
            return TrajectoryConfidence.UNKNOWN
    def _project_horizon(
        self,
        horizon_days: int,
        now: datetime,
        domain: str,
        domain_data: dict,
        trend: float,
        confidence_score: float,
        context: dict
    ) -> TrajectoryPoint:
        """Project state at a specific horizon."""
        projected_date = (now + timedelta(days=horizon_days)).date().isoformat()
        # Confidence degrades at longer horizons
        horizon_confidence = confidence_score * (1.0 - (horizon_days / 180))
        horizon_confidence = max(0.0, round(horizon_confidence, 4))
        confidence_level = self._score_to_confidence_level(horizon_confidence)
        # Project trend forward (simplified linear — F1.6 will add causal refinement)
        projected_valence = max(-1.0, min(1.0, trend * (horizon_days / 30)))
        predicted_state = {
            "projected_outcome_valence": round(projected_valence, 3),
            "trend_direction": self._classify_direction(trend),
            "horizon_days": horizon_days,
            "estimated_decision_count": int(
                domain_data.get("with_outcomes", 0) * (1 + horizon_days / 90)
            )
        }
        # Key drivers (placeholder — F1.6 will provide causal drivers)
        key_drivers = ["historical_outcome_trend", "decision_confidence_pattern"]
        if context:
            key_drivers = list(context.keys())[:3] + key_drivers
        risks = []
        opportunities = []
        if trend < 0:
            risks.append(f"Declining {domain} outcomes — pattern continues without intervention")
            opportunities.append("Identify root cause via Causal Inference Engine")
        elif trend > 0:
            opportunities.append(f"Strong {domain} momentum — compound by increasing decision frequency")
            risks.append("Overconfidence from positive trend — maintain 4-Gate discipline")
        if horizon_days >= 60:
            risks.append("Longer horizons subject to unmodeled disruptions")
        return TrajectoryPoint(
            horizon_days=horizon_days,
            projected_date=projected_date,
            predicted_state=predicted_state,
            confidence=confidence_level,
            confidence_score=horizon_confidence,
            key_drivers=key_drivers,
            risks=risks,
            opportunities=opportunities
        )
    def _summarize_current_state(self, domain_data: dict) -> str:
        total = domain_data.get("total", 0)
        with_outcomes = domain_data.get("with_outcomes", 0)
        avg_valence = domain_data.get("avg_valence")
        valence_str = (
            f"avg outcome {avg_valence:+.2f}" if avg_valence is not None else "no outcomes yet"
        )
        return (
            f"{total} decisions logged ({with_outcomes} with outcomes), {valence_str}."
        )
    def _generate_trajectory_recommendation(
        self,
        direction: str,
        confidence: TrajectoryConfidence,
        domain: str,
        points: list[TrajectoryPoint]
    ) -> str:
        if confidence == TrajectoryConfidence.UNKNOWN:
            return f"Log more {domain} decisions with outcomes to generate reliable forecasts."
        if direction == "improving":
            return (
                f"{domain.title()} trajectory is positive. "
                "Maintain decision discipline. "
                "Compound by increasing frequency of high-confidence decisions."
            )
        elif direction == "declining":
            return (
                f"{domain.title()} trajectory is declining. "
                "Review recent decisions for pattern. "
                "Consider Causal Inference analysis to identify root cause."
            )
        elif direction == "stable":
            return (
                f"{domain.title()} is stable. "
                "Identify highest-leverage variable to shift trajectory upward. "
                "Use Causal Inference Engine once sufficient data accumulates."
            )
        else:  # volatile
            return (
                f"{domain.title()} shows volatility. "
                "Increase decision logging frequency to identify pattern. "
                "Focus on reducing variance before optimizing for growth."
            )
