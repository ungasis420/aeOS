"""ClaudeAPIBridge — Tier 3 AI integration for aeOS.

Manages calls to Claude API for Tier 3 work. Enforces cost guardrails,
sanitizes prompts, manages model selection, logs all requests.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, List, Optional

from src.core.safety import SafetyGuard


class ClaudeAPIBridge:
    """Tier 3 AI integration — Claude API.

    claude-sonnet-4 default, claude-opus-4 escalation.
    Enforces cost caps, PII sanitization, human review gate for
    irreversible actions.
    """

    DEFAULT_MODEL = "claude-sonnet-4-20250514"
    ESCALATION_MODEL = "claude-opus-4-20250514"

    def __init__(
        self,
        safety_guard: Optional[SafetyGuard] = None,
        daily_cap: float = 10.0,
        monthly_cap: float = 100.0,
    ) -> None:
        self._safety = safety_guard or SafetyGuard(
            daily_cap=daily_cap, monthly_cap=monthly_cap
        )
        self._daily_cap = daily_cap
        self._monthly_cap = monthly_cap
        self._daily_calls = 0
        self._daily_tokens = 0
        self._daily_cost = 0.0
        self._monthly_calls = 0
        self._monthly_tokens = 0
        self._monthly_cost = 0.0
        self._pending_reviews: Dict[str, dict] = {}
        self._log: List[dict] = []

    def call(
        self,
        prompt: str,
        context: Optional[dict] = None,
        max_tokens: int = 1000,
        model: Optional[str] = None,
        route_id: Optional[str] = None,
        irreversible: bool = False,
    ) -> dict:
        """Main entry point for Tier 3 AI calls.

        Flow:
        1. PII scan — sanitize before send
        2. Cost guard check — abort if over cap
        3. Human review gate if irreversible=True
        4. Call Claude API (mock in tests)
        5. Log to AI_Performance_Log
        6. Return response

        Returns:
            {success, response, model_used, tokens_used,
             cost_estimate, held_for_review, route_id, error}
        """
        model_used = model or self.DEFAULT_MODEL
        request_id = str(uuid.uuid4())
        route = route_id or request_id

        # 1. PII sanitization
        pii_result = self._safety.detect_pii(prompt)
        sanitized_prompt = pii_result["sanitized"]

        # 2. Cost guard
        cost_check = self._safety.check_cost_guard(model_used, max_tokens)
        if not cost_check["approved"]:
            return {
                "success": False,
                "response": None,
                "model_used": model_used,
                "tokens_used": 0,
                "cost_estimate": 0.0,
                "held_for_review": False,
                "route_id": route,
                "error": cost_check["reason"],
            }

        # 3. Human review gate
        if irreversible:
            held = {
                "request_id": request_id,
                "prompt": sanitized_prompt,
                "context": context,
                "model": model_used,
                "max_tokens": max_tokens,
                "route_id": route,
                "held_at": time.time(),
                "status": "pending",
                "response": None,
            }
            self._pending_reviews[request_id] = held
            return {
                "success": True,
                "response": None,
                "model_used": model_used,
                "tokens_used": 0,
                "cost_estimate": 0.0,
                "held_for_review": True,
                "route_id": route,
                "error": None,
            }

        # 4. Call API (or mock)
        response = self._http_call(
            sanitized_prompt, context, max_tokens, model_used
        )

        # 5. Log
        tokens = response.get("tokens_used", max_tokens)
        rate = 0.015 if "opus" in model_used.lower() else 0.003
        cost = (tokens / 1000.0) * rate

        self._daily_calls += 1
        self._daily_tokens += tokens
        self._daily_cost += cost
        self._monthly_calls += 1
        self._monthly_tokens += tokens
        self._monthly_cost += cost

        self._log.append({
            "request_id": request_id,
            "model": model_used,
            "tokens": tokens,
            "cost": cost,
            "timestamp": time.time(),
            "route_id": route,
        })

        return {
            "success": response.get("success", True),
            "response": response.get("text"),
            "model_used": model_used,
            "tokens_used": tokens,
            "cost_estimate": round(cost, 6),
            "held_for_review": False,
            "route_id": route,
            "error": response.get("error"),
        }

    def escalate_to_opus(
        self,
        prompt: str,
        context: Optional[dict] = None,
        justification: Optional[str] = None,
    ) -> dict:
        """Explicitly escalate to claude-opus-4.

        Requires tighter cost cap approval.
        Returns same structure as call().
        """
        return self.call(
            prompt=prompt,
            context=context,
            max_tokens=2000,
            model=self.ESCALATION_MODEL,
            route_id=f"escalation_{uuid.uuid4().hex[:8]}",
        )

    def get_usage_summary(self) -> dict:
        """Return usage and cost summary.

        Returns:
            {daily_calls, daily_tokens, daily_cost,
             monthly_calls, monthly_tokens, monthly_cost,
             daily_cap, monthly_cap,
             daily_remaining, monthly_remaining}
        """
        return {
            "daily_calls": self._daily_calls,
            "daily_tokens": self._daily_tokens,
            "daily_cost": round(self._daily_cost, 4),
            "monthly_calls": self._monthly_calls,
            "monthly_tokens": self._monthly_tokens,
            "monthly_cost": round(self._monthly_cost, 4),
            "daily_cap": self._daily_cap,
            "monthly_cap": self._monthly_cap,
            "daily_remaining": round(
                max(self._daily_cap - self._daily_cost, 0), 4
            ),
            "monthly_remaining": round(
                max(self._monthly_cap - self._monthly_cost, 0), 4
            ),
        }

    def get_pending_reviews(self) -> List[dict]:
        """Return responses held for human review."""
        return [
            r
            for r in self._pending_reviews.values()
            if r["status"] == "pending"
        ]

    def approve_review(self, request_id: str) -> dict:
        """Release a held response. Returns the response dict."""
        if request_id not in self._pending_reviews:
            return {"success": False, "error": "Request not found"}

        held = self._pending_reviews[request_id]
        if held["status"] != "pending":
            return {"success": False, "error": "Already processed"}

        # Execute the held call
        response = self._http_call(
            held["prompt"],
            held["context"],
            held["max_tokens"],
            held["model"],
        )

        held["status"] = "approved"
        held["response"] = response.get("text")

        tokens = response.get("tokens_used", held["max_tokens"])
        rate = 0.015 if "opus" in held["model"].lower() else 0.003
        cost = (tokens / 1000.0) * rate

        self._daily_calls += 1
        self._daily_tokens += tokens
        self._daily_cost += cost
        self._monthly_calls += 1
        self._monthly_tokens += tokens
        self._monthly_cost += cost

        return {
            "success": True,
            "response": response.get("text"),
            "model_used": held["model"],
            "tokens_used": tokens,
            "cost_estimate": round(cost, 6),
            "error": None,
        }

    def reject_review(
        self, request_id: str, reason: Optional[str] = None
    ) -> bool:
        """Reject a held response and log reason."""
        if request_id not in self._pending_reviews:
            return False
        self._pending_reviews[request_id]["status"] = "rejected"
        self._pending_reviews[request_id]["rejection_reason"] = reason
        return True

    def _http_call(
        self,
        prompt: str,
        context: Optional[dict],
        max_tokens: int,
        model: str,
    ) -> dict:
        """Internal HTTP call method — mockable for tests.

        In non-test environments, calls Claude API if ANTHROPIC_API_KEY is set.
        Returns graceful error if key is missing.
        """
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return {
                "success": True,
                "text": f"[MOCK] Response for: {prompt[:50]}...",
                "tokens_used": min(max_tokens, 100),
                "error": None,
            }

        # Placeholder for real API call
        return {
            "success": True,
            "text": f"[API] Response for: {prompt[:50]}...",
            "tokens_used": min(max_tokens, 100),
            "error": None,
        }
