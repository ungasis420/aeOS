"""DecisionEngine — Next-best-action recommendations for aeOS.

Produces ranked action recommendations by combining scoring signals,
forecasts, and analytics. Learns from outcome feedback.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional


class DecisionEngine:
    """Produces ranked action recommendations with quantified rationale.

    Combines pain scores, pipeline, runway, project health.
    Learns from outcome feedback via Calibration_Feedback_Loop.
    Wired to FlywheelLogger for compound intelligence accumulation.
    """

    def __init__(self, flywheel_logger: Any = None) -> None:
        self._history: List[dict] = []
        self._feedback: Dict[str, dict] = {}
        self._flywheel_logger = flywheel_logger

    def recommend(self, context: dict) -> dict:
        """Given current system state, return top 3 recommended actions.

        context keys: pain_scores, pipeline_value, runway_months,
                     project_health, recent_decisions, user_goals

        Returns:
            {recommendations: list[{rank, action, expected_impact,
             confidence, effort_estimate, evidence, sovereign_need,
             decision_id}],
             context_summary: str, generated_at: float}
        """
        if not isinstance(context, dict):
            context = {}

        pain = context.get("pain_scores", {})
        runway = context.get("runway_months", 12)
        pipeline = context.get("pipeline_value", 0)
        health = context.get("project_health", {})
        goals = context.get("user_goals", [])

        recommendations = []

        # Rule-based recommendation generation
        if isinstance(runway, (int, float)) and runway < 6:
            recommendations.append({
                "action": "Reduce burn rate or accelerate revenue",
                "expected_impact": "Extend runway beyond 6 months",
                "confidence": 0.85,
                "effort_estimate": "high",
                "evidence": [f"Current runway: {runway} months"],
                "sovereign_need": "security",
            })

        if isinstance(pain, dict) and pain:
            top_pain = max(pain.items(), key=lambda x: float(x[1])) if pain else None
            if top_pain and float(top_pain[1]) > 7:
                recommendations.append({
                    "action": f"Address top pain point: {top_pain[0]}",
                    "expected_impact": "Reduce pain score by 30%+",
                    "confidence": 0.75,
                    "effort_estimate": "medium",
                    "evidence": [f"Pain score: {top_pain[1]}/10"],
                    "sovereign_need": "growth",
                })

        if isinstance(pipeline, (int, float)) and pipeline > 0:
            recommendations.append({
                "action": "Focus on pipeline conversion",
                "expected_impact": f"Convert ${pipeline:,.0f} pipeline",
                "confidence": 0.70,
                "effort_estimate": "medium",
                "evidence": [f"Pipeline value: ${pipeline:,.0f}"],
                "sovereign_need": "autonomy",
            })

        # Pad to 3 if needed
        defaults = [
            {
                "action": "Review and update project priorities",
                "expected_impact": "Improved focus and velocity",
                "confidence": 0.50,
                "effort_estimate": "low",
                "evidence": ["Regular review cycle"],
                "sovereign_need": "mastery",
            },
            {
                "action": "Conduct team alignment session",
                "expected_impact": "Reduce blockers and improve collaboration",
                "confidence": 0.45,
                "effort_estimate": "low",
                "evidence": ["Proactive alignment"],
                "sovereign_need": "purpose",
            },
            {
                "action": "Update financial forecasts",
                "expected_impact": "Better planning accuracy",
                "confidence": 0.40,
                "effort_estimate": "low",
                "evidence": ["Periodic refresh"],
                "sovereign_need": "security",
            },
        ]

        while len(recommendations) < 3:
            idx = len(recommendations)
            if idx < len(defaults):
                recommendations.append(defaults[idx])
            else:
                break

        # Assign ranks and IDs
        recommendations = recommendations[:3]
        for i, rec in enumerate(recommendations):
            rec["rank"] = i + 1
            rec["decision_id"] = str(uuid.uuid4())

        generated_at = time.time()

        # Log
        entry = {
            "recommendations": recommendations,
            "context_summary": self._summarize_context(context),
            "generated_at": generated_at,
        }
        self._history.append(entry)

        # FlywheelLogger: record each recommendation as a decision
        if self._flywheel_logger:
            for rec in recommendations:
                try:
                    self._flywheel_logger.log_decision(
                        context=rec.get("action", ""),
                        cartridges_fired=[rec.get("sovereign_need", "")],
                        reasoning_summary=rec.get("expected_impact", ""),
                        confidence=rec.get("confidence", 0.5),
                        domain="business",
                    )
                except Exception:
                    pass  # don't break recommendations if logging fails

        return {
            "recommendations": recommendations,
            "context_summary": entry["context_summary"],
            "generated_at": generated_at,
        }

    def compare_options(
        self,
        options: List[dict],
        criteria: List[dict],
    ) -> dict:
        """Weighted scoring and sensitivity analysis across options.

        options: [{name, description, ...scores}]
        criteria: [{name, weight, higher_is_better}]

        Returns:
            {ranked, winner, sensitivity}
        """
        if not options or not criteria:
            return {"ranked": [], "winner": None, "sensitivity": {}}

        scored = []
        for opt in options:
            total = 0.0
            scores_by_criteria = {}
            for crit in criteria:
                crit_name = crit["name"]
                weight = float(crit.get("weight", 1.0))
                higher_better = crit.get("higher_is_better", True)
                raw = float(opt.get(crit_name, 0))
                adjusted = raw if higher_better else -raw
                weighted = adjusted * weight
                scores_by_criteria[crit_name] = round(weighted, 4)
                total += weighted

            scored.append({
                "name": opt.get("name", ""),
                "score": round(total, 4),
                "scores_by_criteria": scores_by_criteria,
            })

        ranked = sorted(scored, key=lambda s: s["score"], reverse=True)
        winner = ranked[0]["name"] if ranked else None

        # Sensitivity: which criteria flip the winner
        sensitivity = {}
        if len(ranked) >= 2:
            gap = ranked[0]["score"] - ranked[1]["score"]
            for crit in criteria:
                crit_name = crit["name"]
                weight = float(crit.get("weight", 1.0))
                if weight > 0:
                    sensitivity[crit_name] = round(gap / weight, 4)

        return {"ranked": ranked, "winner": winner, "sensitivity": sensitivity}

    def assess_risk(
        self, decision_id: str, decision_data: dict
    ) -> dict:
        """Risk matrix for a pending decision.

        Returns:
            {risks, overall_risk, mitigation_suggestions, go_no_go}
        """
        if not isinstance(decision_data, dict):
            return {
                "risks": [],
                "overall_risk": "low",
                "mitigation_suggestions": [],
                "go_no_go": "go",
            }

        risks = []
        risk_factors = decision_data.get("risk_factors", [])
        total_severity = 0

        for rf in risk_factors:
            if not isinstance(rf, dict):
                continue
            prob = float(rf.get("probability", 0.5))
            impact = float(rf.get("impact", 0.5))
            severity_score = prob * impact

            if severity_score > 0.6:
                severity = "high"
            elif severity_score > 0.3:
                severity = "medium"
            else:
                severity = "low"

            risks.append({
                "factor": rf.get("factor", "unknown"),
                "probability": round(prob, 2),
                "impact": round(impact, 2),
                "severity": severity,
            })
            total_severity += severity_score

        avg_severity = total_severity / len(risks) if risks else 0
        if avg_severity > 0.6:
            overall = "high"
        elif avg_severity > 0.3:
            overall = "medium"
        else:
            overall = "low"

        if overall == "high":
            go_no_go = "no-go"
        elif overall == "medium":
            go_no_go = "caution"
        else:
            go_no_go = "go"

        mitigations = []
        for r in risks:
            if r["severity"] in ("high", "medium"):
                mitigations.append(
                    f"Mitigate '{r['factor']}': reduce probability or impact"
                )

        return {
            "risks": risks,
            "overall_risk": overall,
            "mitigation_suggestions": mitigations,
            "go_no_go": go_no_go,
        }

    def record_feedback(
        self,
        decision_id: str,
        outcome: str,
        notes: Optional[str] = None,
    ) -> bool:
        """Record outcome feedback for a decision.

        Returns True if recorded successfully.
        """
        if not isinstance(decision_id, str) or not decision_id.strip():
            return False
        if not isinstance(outcome, str) or not outcome.strip():
            return False

        self._feedback[decision_id] = {
            "decision_id": decision_id,
            "outcome": outcome,
            "notes": notes,
            "recorded_at": time.time(),
        }
        return True

    def get_recommendation_history(self, limit: int = 20) -> List[dict]:
        """Return past recommendations with outcomes where known."""
        history = list(reversed(self._history))[:limit]

        # Enrich with feedback
        for entry in history:
            for rec in entry.get("recommendations", []):
                did = rec.get("decision_id")
                if did and did in self._feedback:
                    rec["outcome"] = self._feedback[did]["outcome"]

        return history

    @staticmethod
    def _summarize_context(context: dict) -> str:
        """Generate a brief context summary."""
        parts = []
        if "runway_months" in context:
            parts.append(f"Runway: {context['runway_months']}mo")
        if "pipeline_value" in context:
            parts.append(f"Pipeline: ${context['pipeline_value']:,.0f}")
        if "pain_scores" in context and context["pain_scores"]:
            top = max(context["pain_scores"].values())
            parts.append(f"Top pain: {top}/10")
        return "; ".join(parts) if parts else "No context provided"
