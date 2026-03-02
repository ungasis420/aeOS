"""
safety.py — Safety enforcement layer for aeOS.
This module provides:
- Rate limiting (requests/minute)
- Cost guarding (daily/monthly USD caps)
- PII detection + redaction (PH-first patterns)
- A single SafetyGate that composes the above and emits stub "BUS events"
  to stdout (JSON) for later wiring.
Dependencies: stdlib only (re, time, datetime, json, typing)
"""
from __future__ import annotations
import json
import re
import time
from datetime import datetime, date
from typing import Any, Callable, Dict, List, Pattern, Tuple, Union
# =========================
# Constants
# =========================
MAX_REQUESTS_PER_MINUTE: int = 20
MAX_COST_PER_DAY_USD: float = 5.00
MAX_COST_PER_MONTH_USD: float = 50.00
# =========================
# PII Patterns (compiled at module load time)
# =========================
RedactionReplacement = Union[str, Callable[[re.Match[str]], str]]
def _keep_label_redact(match: re.Match[str]) -> str:
    """
    Helper redactor that preserves the label in group(1) and replaces the value.
    Expected regex structure: (label)(value)
    """
    label = (match.group(1) or "").strip()
    # Normalize to "Label: [REDACTED]" even if original used "=" or "-" etc.
    return f"{label}: [REDACTED]" if label else "[REDACTED]"
# Philippine-specific patterns first, then general.
_PII_RULES: List[Tuple[str, Pattern[str], RedactionReplacement]] = [
    # Philippine mobile numbers (09XX-XXX-XXXX)
    (
        "PH_MOBILE_09XX_XXX_XXXX",
        re.compile(r"(?<!\d)09\d{2}-\d{3}-\d{4}(?!\d)"),
        "[REDACTED]",
    ),
    # SSS (commonly: 34-1234567-8 OR 10 digits)
    (
        "PH_SSS_NUMBER",
        re.compile(
            r"(?i)\b(SSS(?:\s*(?:No\.?|#|Number)?)?)\s*[:\-]?\s*(\d{2}-\d{7}-\d{1}|\d{10})\b"
        ),
        _keep_label_redact,
    ),
    # TIN (commonly: 123-456-789 OR 9-12 digits)
    (
        "PH_TIN_NUMBER",
        re.compile(
            r"(?i)\b(TIN(?:\s*(?:No\.?|#|Number)?)?)\s*[:\-]?\s*(\d{3}-\d{3}-\d{3}(?:-\d{3,4})?|\d{9,12})\b"
        ),
        _keep_label_redact,
    ),
    # PhilHealth PIN (commonly: 00-000000000-0 OR 12 digits)
    (
        "PH_PHILHEALTH_NUMBER",
        re.compile(
            r"(?i)\b(PhilHealth(?:\s*(?:No\.?|#|Number|PIN)?)?)\s*[:\-]?\s*(\d{2}-\d{9}-\d{1}|\d{12})\b"
        ),
        _keep_label_redact,
    ),
    # UMID / CRN (commonly: 0000-0000000-0 OR 12 digits)
    (
        "PH_UMID_CRN_NUMBER",
        re.compile(
            r"(?i)\b((?:UMID|CRN|Common\s+Reference\s+Number)(?:\s*(?:No\.?|#|Number)?)?)\s*[:\-]?\s*(\d{4}-\d{7}-\d{1}|\d{12})\b"
        ),
        _keep_label_redact,
    ),
    # Email addresses
    (
        "EMAIL_ADDRESS",
        re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b"),
        "[REDACTED]",
    ),
    # Credit card numbers (basic 16-digit; allows 4-4-4-4 with spaces/hyphens)
    (
        "CREDIT_CARD_16_DIGIT",
        re.compile(r"(?<!\d)(?:\d{4}[- ]?){3}\d{4}(?!\d)"),
        "[REDACTED]",
    ),
    # Passwords (anything following password:/pass:/pwd:)
    (
        "PASSWORD_FIELD",
        re.compile(r"(?im)\b(password|pass|pwd)\s*[:=]\s*([^\s]+)"),
        _keep_label_redact,
    ),
]
# Per spec: list of compiled regex patterns (compiled at module load time).
PII_PATTERNS: List[Pattern[str]] = [rule[1] for rule in _PII_RULES]
# =========================
# RateLimiter
# =========================
class RateLimiter:
    """
    Fixed-window rate limiter using stdlib time only.
    - Tracks requests in a 60-second window.
    - Resets automatically when window expires.
    """
    def __init__(self, max_per_minute: int = MAX_REQUESTS_PER_MINUTE) -> None:
        if int(max_per_minute) <= 0:
            raise ValueError("max_per_minute must be a positive integer.")
        self._max_per_minute: int = int(max_per_minute)
        self._window_start_ts: float = time.time()
        self._count: int = 0
    def _rollover_if_needed(self) -> None:
        now = time.time()
        if (now - self._window_start_ts) >= 60.0:
            self._window_start_ts = now
            self._count = 0
    def check_and_increment(self) -> Tuple[bool, str]:
        """
        Returns:
            (allowed, reason_if_blocked)
        """
        self._rollover_if_needed()
        if self._count >= self._max_per_minute:
            return False, f"Rate limit exceeded: {self._max_per_minute} requests per minute."
        self._count += 1
        return True, ""
    def reset_window(self) -> None:
        """Manually reset the current window and count."""
        self._window_start_ts = time.time()
        self._count = 0
    def get_current_count(self) -> int:
        """Return current request count for the active window."""
        self._rollover_if_needed()
        return self._count
# =========================
# CostGuard
# =========================
class CostGuard:
    """
    In-memory cost guard (daily + monthly).
    Notes:
    - Totals are stored in memory only (persistence is deferred to PERSIST layer).
    - Day/month rollovers are handled automatically on any call.
    """
    def __init__(
        self,
        daily_limit: float = MAX_COST_PER_DAY_USD,
        monthly_limit: float = MAX_COST_PER_MONTH_USD,
    ) -> None:
        daily_limit_f = float(daily_limit)
        monthly_limit_f = float(monthly_limit)
        if daily_limit_f < 0 or monthly_limit_f < 0:
            raise ValueError("Cost limits must be >= 0.")
        self._daily_limit: float = daily_limit_f
        self._monthly_limit: float = monthly_limit_f
        self._daily_total: float = 0.0
        self._monthly_total: float = 0.0
        today = date.today()
        self._current_day: date = today
        self._current_month: Tuple[int, int] = (today.year, today.month)
    def _rollover_if_needed(self) -> None:
        today = date.today()
        # Day rollover
        if today != self._current_day:
            self._current_day = today
            self._daily_total = 0.0
        # Month rollover
        month_key = (today.year, today.month)
        if month_key != self._current_month:
            self._current_month = month_key
            self._monthly_total = 0.0
    def add_cost(self, amount_usd: float) -> None:
        """
        Add cost to running totals.
        Args:
            amount_usd: Non-negative float cost to add.
        """
        self._rollover_if_needed()
        amount = float(amount_usd)
        if amount < 0:
            raise ValueError("amount_usd must be >= 0.")
        self._daily_total += amount
        self._monthly_total += amount
    def check_limits(self) -> Tuple[bool, str]:
        """
        Returns:
            (within_limits, reason_if_exceeded)
        """
        self._rollover_if_needed()
        if self._daily_total > self._daily_limit:
            return (
                False,
                f"Daily cost limit exceeded: ${self._daily_total:.2f} > ${self._daily_limit:.2f}.",
            )
        if self._monthly_total > self._monthly_limit:
            return (
                False,
                f"Monthly cost limit exceeded: ${self._monthly_total:.2f} > ${self._monthly_limit:.2f}.",
            )
        return True, ""
    def get_daily_total(self) -> float:
        """Return today's running total."""
        self._rollover_if_needed()
        return float(self._daily_total)
    def get_monthly_total(self) -> float:
        """Return this month's running total."""
        self._rollover_if_needed()
        return float(self._monthly_total)
    def reset_daily(self) -> None:
        """Manual reset of today's total."""
        self._current_day = date.today()
        self._daily_total = 0.0
# =========================
# PIIDetector
# =========================
class PIIDetector:
    """
    PII detection and redaction.
    Uses module-level compiled regex rules (PH-first).
    """
    def __init__(self) -> None:
        self._rules = _PII_RULES  # name + compiled pattern + replacement
    def scan(self, text: str) -> Tuple[bool, List[str]]:
        """
        Scan text for PII.
        Args:
            text: Input text.
        Returns:
            (found_pii, pattern_names_matched)
        """
        haystack = text or ""
        matched: List[str] = []
        for name, pattern, _replacement in self._rules:
            if pattern.search(haystack):
                matched.append(name)
        # Deduplicate while preserving order
        seen = set()
        deduped = [n for n in matched if not (n in seen or seen.add(n))]
        return (len(deduped) > 0), deduped
    def redact(self, text: str) -> str:
        """
        Replace detected PII with [REDACTED].
        Args:
            text: Input text.
        Returns:
            Redacted text.
        """
        if not text:
            return ""
        redacted = text
        for _name, pattern, replacement in self._rules:
            redacted = pattern.sub(replacement, redacted)
        return redacted
    def get_patterns(self) -> List[str]:
        """Return list of pattern names being checked."""
        return [name for name, _pattern, _replacement in self._rules]
# =========================
# SafetyGate
# =========================
class SafetyGate:
    """
    Composes RateLimiter + CostGuard + PIIDetector.
    check_request() produces a single decision dict suitable for later routing,
    logging, and BUS publishing.
    """
    def __init__(self) -> None:
        self.rate_limiter = RateLimiter()
        self.cost_guard = CostGuard()
        self.pii_detector = PIIDetector()
    def check_request(self, text: str, estimated_cost_usd: float = 0.0) -> Dict[str, Any]:
        """
        Evaluate a request against:
        - PII detection + redaction (does not block by default)
        - Rate limiting (blocks when exceeded)
        - Cost limits (blocks when projected totals exceed)
        Args:
            text: The raw input text.
            estimated_cost_usd: Expected incremental cost for this request.
        Returns:
            {
                "allowed": bool,
                "pii_detected": bool,
                "pii_patterns": list,
                "rate_limited": bool,
                "cost_exceeded": bool,
                "reason": str,
                "safe_text": str
            }
        """
        raw_text = text or ""
        # 1) PII scan + redact (always done; PH-first patterns).
        pii_detected, pii_patterns = self.pii_detector.scan(raw_text)
        safe_text = self.pii_detector.redact(raw_text) if pii_detected else raw_text
        if pii_detected:
            self._publish_event(
                "PII_DETECTED",
                {"patterns": pii_patterns},
            )
        # 2) Rate limit check (blocking).
        allowed_rl, rl_reason = self.rate_limiter.check_and_increment()
        if not allowed_rl:
            self._publish_event(
                "RATE_LIMIT_BLOCK",
                {
                    "reason": rl_reason,
                    "count": self.rate_limiter.get_current_count(),
                    "max_per_minute": MAX_REQUESTS_PER_MINUTE,
                },
            )
            return {
                "allowed": False,
                "pii_detected": pii_detected,
                "pii_patterns": pii_patterns,
                "rate_limited": True,
                "cost_exceeded": False,
                "reason": rl_reason,
                "safe_text": safe_text,
            }
        # 3) Cost check (blocking) — evaluate projected totals before adding.
        try:
            est_cost = float(estimated_cost_usd)
        except (TypeError, ValueError):
            est_cost = 0.0
            self._publish_event(
                "COST_ESTIMATE_INVALID",
                {"provided": estimated_cost_usd, "used": est_cost},
            )
        if est_cost < 0:
            # Don't crash the pipeline; treat as 0 and log.
            self._publish_event(
                "COST_ESTIMATE_NEGATIVE",
                {"provided": est_cost, "used": 0.0},
            )
            est_cost = 0.0
        daily_total = self.cost_guard.get_daily_total()
        monthly_total = self.cost_guard.get_monthly_total()
        projected_daily = daily_total + est_cost
        projected_monthly = monthly_total + est_cost
        if projected_daily > MAX_COST_PER_DAY_USD:
            reason = (
                f"Daily cost limit would be exceeded: "
                f"${projected_daily:.2f} > ${MAX_COST_PER_DAY_USD:.2f}."
            )
            self._publish_event(
                "COST_LIMIT_BLOCK",
                {"scope": "daily", "projected": projected_daily, "limit": MAX_COST_PER_DAY_USD},
            )
            return {
                "allowed": False,
                "pii_detected": pii_detected,
                "pii_patterns": pii_patterns,
                "rate_limited": False,
                "cost_exceeded": True,
                "reason": reason,
                "safe_text": safe_text,
            }
        if projected_monthly > MAX_COST_PER_MONTH_USD:
            reason = (
                f"Monthly cost limit would be exceeded: "
                f"${projected_monthly:.2f} > ${MAX_COST_PER_MONTH_USD:.2f}."
            )
            self._publish_event(
                "COST_LIMIT_BLOCK",
                {
                    "scope": "monthly",
                    "projected": projected_monthly,
                    "limit": MAX_COST_PER_MONTH_USD,
                },
            )
            return {
                "allowed": False,
                "pii_detected": pii_detected,
                "pii_patterns": pii_patterns,
                "rate_limited": False,
                "cost_exceeded": True,
                "reason": reason,
                "safe_text": safe_text,
            }
        # If within limits, commit the estimated cost.
        if est_cost > 0:
            self.cost_guard.add_cost(est_cost)
        # Final allow decision.
        reason = "OK (PII redacted)" if pii_detected else "OK"
        return {
            "allowed": True,
            "pii_detected": pii_detected,
            "pii_patterns": pii_patterns,
            "rate_limited": False,
            "cost_exceeded": False,
            "reason": reason,
            "safe_text": safe_text,
        }
    def _publish_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        BUS publish stub — prints to stdout for now.
        Real BUS wiring will replace this later.
        Args:
            event_type: Event type string.
            data: Event payload.
        """
        event = {
            "event_type": event_type,
            "timestamp_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "data": data,
        }
        print(json.dumps(event, ensure_ascii=False, sort_keys=True))


# =========================
# SafetyGuard (Phase 3 extension)
# =========================

class SafetyGuard:
    """Operational guardrails for aeOS.

    Rate limiting, PII detection, cost caps. Extends the existing
    safety primitives (RateLimiter, CostGuard, PIIDetector) into
    a unified guard with structured return dicts.
    """

    def __init__(
        self,
        rate_limit: int = 10,
        daily_cap: float = 10.0,
        monthly_cap: float = 100.0,
    ) -> None:
        self._rate_limiters: Dict[str, List[float]] = {}
        self._default_rate_limit = int(rate_limit)
        self._pii_detector = PIIDetector()
        self._daily_cap = float(daily_cap)
        self._monthly_cap = float(monthly_cap)
        self._daily_spend: float = 0.0
        self._monthly_spend: float = 0.0
        self._current_day: date = date.today()
        self._current_month: int = date.today().month
        self._safety_events: List[Dict[str, Any]] = []

    def _rollover(self) -> None:
        today = date.today()
        if today != self._current_day:
            self._current_day = today
            self._daily_spend = 0.0
        if today.month != self._current_month:
            self._current_month = today.month
            self._monthly_spend = 0.0

    def check_rate_limit(
        self, endpoint: str, window_seconds: int = 60
    ) -> Dict[str, Any]:
        """Check rate limit for an endpoint.

        Returns:
            {allowed: bool, remaining: int, reset_at: float}
        Default: 10 calls/minute per endpoint.
        """
        now = time.time()
        if endpoint not in self._rate_limiters:
            self._rate_limiters[endpoint] = []

        # Prune expired timestamps
        cutoff = now - window_seconds
        self._rate_limiters[endpoint] = [
            ts for ts in self._rate_limiters[endpoint] if ts > cutoff
        ]

        current_count = len(self._rate_limiters[endpoint])
        allowed = current_count < self._default_rate_limit

        if allowed:
            self._rate_limiters[endpoint].append(now)
            remaining = self._default_rate_limit - current_count - 1
        else:
            remaining = 0

        oldest = (
            self._rate_limiters[endpoint][0]
            if self._rate_limiters[endpoint]
            else now
        )
        reset_at = oldest + window_seconds

        return {
            "allowed": allowed,
            "remaining": max(remaining, 0),
            "reset_at": reset_at,
        }

    def detect_pii(self, text: str) -> Dict[str, Any]:
        """Scan text for PII before external transmission.

        Detects: email, phone, SSN, credit card, API keys.

        Returns:
            {has_pii: bool, detected_types: list[str], sanitized: str}
        Replaces detected PII with [REDACTED_TYPE].
        """
        if not isinstance(text, str):
            return {
                "has_pii": False,
                "detected_types": [],
                "sanitized": str(text),
            }
        has_pii, types = self._pii_detector.scan(text)
        sanitized = self._pii_detector.redact(text) if has_pii else text
        return {
            "has_pii": has_pii,
            "detected_types": types,
            "sanitized": sanitized,
        }

    def check_cost_guard(
        self, model: str, estimated_tokens: int
    ) -> Dict[str, Any]:
        """Validate AI call against daily/monthly cost caps.

        Returns:
            {approved: bool, reason: str, daily_remaining: float,
             monthly_remaining: float}
        Caps configurable in config. Defaults: $10/day, $100/month.
        """
        self._rollover()
        # Cost estimation: rough $0.003 per 1K tokens for sonnet, $0.015 for opus
        rate_per_1k = 0.015 if "opus" in str(model).lower() else 0.003
        estimated_cost = (int(estimated_tokens) / 1000.0) * rate_per_1k

        daily_remaining = self._daily_cap - self._daily_spend
        monthly_remaining = self._monthly_cap - self._monthly_spend

        if estimated_cost > daily_remaining:
            return {
                "approved": False,
                "reason": f"Daily cap exceeded: ${self._daily_spend:.2f} + ${estimated_cost:.4f} > ${self._daily_cap:.2f}",
                "daily_remaining": max(daily_remaining, 0.0),
                "monthly_remaining": max(monthly_remaining, 0.0),
            }
        if estimated_cost > monthly_remaining:
            return {
                "approved": False,
                "reason": f"Monthly cap exceeded: ${self._monthly_spend:.2f} + ${estimated_cost:.4f} > ${self._monthly_cap:.2f}",
                "daily_remaining": max(daily_remaining, 0.0),
                "monthly_remaining": max(monthly_remaining, 0.0),
            }

        self._daily_spend += estimated_cost
        self._monthly_spend += estimated_cost

        return {
            "approved": True,
            "reason": "Within budget",
            "daily_remaining": max(self._daily_cap - self._daily_spend, 0.0),
            "monthly_remaining": max(
                self._monthly_cap - self._monthly_spend, 0.0
            ),
        }

    def log_safety_event(
        self, event_type: str, details: Dict[str, Any]
    ) -> None:
        """Write safety event to internal log."""
        self._safety_events.append(
            {
                "event_type": str(event_type),
                "details": dict(details) if isinstance(details, dict) else {},
                "timestamp": time.time(),
            }
        )

    def get_safety_events(self) -> List[Dict[str, Any]]:
        """Return all logged safety events."""
        return list(self._safety_events)
