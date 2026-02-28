"""
aeOS Phase 4 — Layer 1 (AI Core)

ai_router.py — Intent router for local AI layer.

Purpose:
  Route a user's query to the appropriate aeOS AI agent/module using
  fast, deterministic keyword + pattern matching (no LLM used for routing).

Public API:
  - detect_intent(query: str) -> dict
  - route_query(query: str, conn, kb_conn) -> dict
  - get_routing_stats() -> dict

Intents:
  - pain_analysis
  - solution_generation
  - prediction
  - bias_check
  - memory_search
  - portfolio_health
  - general

Notes:
  - Answer generation MAY use the local LLM (via ai_infer). Only routing is non-LLM.
  - Agent modules are optional at Layer 1. If missing, router falls back to LLM prompts.
  - Routing "accuracy" is only measurable when the caller provides an explicit intent override
    (e.g., "/pain ..." or "intent:prediction ..."). Those samples are tracked.

Stamp: S✅ T✅ L✅ A✅
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from src.core.logger import get_logger
from src.ai import ai_context, ai_infer

_LOG = get_logger(__name__)


# ---------------------------------------------------------------------------
# Intent rules (deterministic, fast)
# ---------------------------------------------------------------------------

_INTENTS: Tuple[str, ...] = (
    "pain_analysis",
    "solution_generation",
    "prediction",
    "bias_check",
    "memory_search",
    "portfolio_health",
    "general",
)

# Agent/module suggestion names (used for transparency + future plug-in wiring).
_AGENT_BY_INTENT: Dict[str, str] = {
    "pain_analysis": "agent_pain",
    "solution_generation": "agent_solution",
    "prediction": "agent_prediction",
    "bias_check": "agent_bias",
    "memory_search": "agent_memory",
    "portfolio_health": "module_portfolio_health",
    "general": "ai_infer",
}

# Context needs per intent. Router builds only what's needed.
_CONTEXT_POLICY: Dict[str, Dict[str, bool]] = {
    "pain_analysis": {"db": True, "kb": True},
    "solution_generation": {"db": True, "kb": True},
    "prediction": {"db": True, "kb": True},
    "bias_check": {"db": True, "kb": True},
    "memory_search": {"db": False, "kb": True},
    "portfolio_health": {"db": True, "kb": False},
    "general": {"db": False, "kb": False},
}

# A small command vocabulary for explicit routing overrides.
# Examples:
#   "/pain what is the root cause..."
#   "intent:prediction what's the chance..."
# These provide a ground-truth label we can use for routing accuracy stats.
_INTENT_OVERRIDE_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*/(pain|solution|predict|prediction|bias|memory|portfolio)\b\s*[:\-]?\s*", re.I),
    re.compile(
        r"^\s*intent\s*[:=]\s*(pain_analysis|solution_generation|prediction|bias_check|memory_search|portfolio_health|general)\b\s*[:\-]?\s*",
        re.I,
    ),
)

# Keyword/phrase patterns per intent.
# We keep this conservative: fewer false positives beats "clever" guessing.
_RULES: Dict[str, List[Tuple[re.Pattern[str], float]]] = {
    "pain_analysis": [
        (re.compile(r"\b(pain point|root cause|diagnos(e|is)|why is|why am i)\b", re.I), 4.0),
        (re.compile(r"\b(frustrat|bottleneck|blocker|problem|issue|stuck)\b", re.I), 2.5),
        (re.compile(r"\b(severity|frequency|impact|pain score|monetiz)\b", re.I), 2.0),
    ],
    "solution_generation": [
        (re.compile(r"\b(solution|fix|resolve|mitigat|workaround)\b", re.I), 3.5),
        (re.compile(r"\b(approach|plan|roadmap|design|generate|ideas?)\b", re.I), 2.5),
        (re.compile(r"\b(how do i|what should i do|recommend)\b", re.I), 2.0),
    ],
    "prediction": [
        (re.compile(r"\b(predict|forecast|projection|estimate|probabilit|likelihood|odds|chance)\b", re.I), 4.0),
        (re.compile(r"\b(confidence|brier|calibration|scenario)\b", re.I), 2.5),
        (re.compile(r"\b(in \d+\s*(days?|weeks?|months?|years?)|by \d{4})\b", re.I), 1.5),
    ],
    "bias_check": [
        (re.compile(r"\b(bias|cognitive bias|fallac(y|ies)|debias|bias audit)\b", re.I), 4.0),
        (re.compile(r"\b(assumption|blind spot|overconfiden|anchoring|confirmation)\b", re.I), 2.0),
    ],
    "memory_search": [
        (re.compile(r"\b(search|find|look up|retrieve|recall|remember)\b", re.I), 3.0),
        (re.compile(r"\b(in (my )?(notes|kb|knowledge base)|what did i say)\b", re.I), 3.5),
        (re.compile(r"\b(transcript|meeting|recording)\b", re.I), 1.5),
    ],
    "portfolio_health": [
        (re.compile(r"\b(portfolio|health|dashboard|runway|burn|cash|net worth)\b", re.I), 3.5),
        (re.compile(r"\b(qportfolio|qbestmoves|execution|blocked tasks?|in_progress)\b", re.I), 2.5),
    ],
}


def _clean_query(query: str) -> str:
    # Keep original text, but normalize whitespace.
    return re.sub(r"\s+", " ", (query or "").strip())


def _extract_intent_override(query: str) -> Tuple[Optional[str], str]:
    """
    Extract explicit intent override (if any) and return (intent, cleaned_query).

    Supported formats:
      - /pain <query>
      - /solution <query>
      - /predict <query>
      - /bias <query>
      - /memory <query>
      - /portfolio <query>
      - intent:<intent_name> <query>
    """
    q = query or ""
    for pat in _INTENT_OVERRIDE_PATTERNS:
        m = pat.match(q)
        if not m:
            continue
        token = (m.group(1) or "").lower().strip()
        rest = q[m.end() :].strip()
        mapping = {
            "pain": "pain_analysis",
            "solution": "solution_generation",
            "predict": "prediction",
            "prediction": "prediction",
            "bias": "bias_check",
            "memory": "memory_search",
            "portfolio": "portfolio_health",
        }
        if token in mapping:
            return mapping[token], rest
        if token in _INTENTS:
            return token, rest
    return None, query


def _score_intents(q: str) -> Dict[str, float]:
    q = q or ""
    scores: Dict[str, float] = {k: 0.0 for k in _INTENTS}
    for intent, rules in _RULES.items():
        for pat, weight in rules:
            if pat.search(q):
                scores[intent] += float(weight)
    # If nothing hit, keep general as a slight default winner.
    if all(v <= 0.0 for k, v in scores.items() if k != "general"):
        scores["general"] = max(scores.get("general", 0.0), 0.1)
    return scores


def detect_intent(query: str) -> Dict[str, Any]:
    """
    Detect intent for a given query using keyword/pattern matching only.

    Args:
        query: User input string.

    Returns:
        dict: {
          intent: str,
          confidence: float (0..1),
          suggested_agent: str,
          context_needed: dict (e.g., {db: bool, kb: bool})
        }
    """
    q = _clean_query(query)
    if not q:
        return {
            "intent": "general",
            "confidence": 0.0,
            "suggested_agent": _AGENT_BY_INTENT["general"],
            "context_needed": _CONTEXT_POLICY["general"].copy(),
        }

    # If the user explicitly uses a command prefix, treat it as decisive.
    override, _rest = _extract_intent_override(q)
    if override:
        intent = override if override in _INTENTS else "general"
        return {
            "intent": intent,
            "confidence": 1.0,
            "suggested_agent": _AGENT_BY_INTENT.get(intent, "ai_infer"),
            "context_needed": _CONTEXT_POLICY.get(intent, _CONTEXT_POLICY["general"]).copy(),
        }

    scores = _score_intents(q)
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_intent, best_score = ordered[0]
    second_score = ordered[1][1] if len(ordered) > 1 else 0.0

    if best_score <= 0.0:
        best_intent = "general"
        confidence = 0.2
    else:
        margin = max(0.0, best_score - second_score)
        # Confidence: 0.50..0.95 based on separation between top two.
        confidence = 0.5 + 0.5 * (margin / (best_score + 1e-9))
        confidence = max(0.0, min(0.95, confidence))

    return {
        "intent": best_intent,
        "confidence": float(confidence),
        "suggested_agent": _AGENT_BY_INTENT.get(best_intent, "ai_infer"),
        "context_needed": _CONTEXT_POLICY.get(best_intent, _CONTEXT_POLICY["general"]).copy(),
    }


# ---------------------------------------------------------------------------
# Routing stats (process-local)
# ---------------------------------------------------------------------------


class _RoutingStats:
    """Thread-safe in-process routing statistics accumulator."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total_calls = 0
        self._intent_counts: Dict[str, int] = {k: 0 for k in _INTENTS}
        self._fallback_calls = 0
        # "Accuracy" is only measurable when a caller provides explicit intent override.
        self._accuracy_samples = 0
        self._accuracy_correct = 0
        self._total_confidence = 0.0

    def record(
        self,
        final_intent: str,
        confidence: float,
        *,
        predicted_intent: Optional[str] = None,
        ground_truth_intent: Optional[str] = None,
        fallback_used: bool = False,
    ) -> None:
        final_intent = final_intent if final_intent in _INTENTS else "general"
        predicted_intent = predicted_intent if predicted_intent in _INTENTS else None
        ground_truth_intent = ground_truth_intent if ground_truth_intent in _INTENTS else None
        with self._lock:
            self._total_calls += 1
            self._intent_counts[final_intent] = self._intent_counts.get(final_intent, 0) + 1
            self._total_confidence += float(confidence or 0.0)
            if fallback_used:
                self._fallback_calls += 1
            if ground_truth_intent is not None and predicted_intent is not None:
                self._accuracy_samples += 1
                if predicted_intent == ground_truth_intent:
                    self._accuracy_correct += 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            total = self._total_calls
            counts = dict(self._intent_counts)
            fallbacks = self._fallback_calls
            samples = self._accuracy_samples
            correct = self._accuracy_correct
            total_conf = self._total_confidence
        dist = {k: counts.get(k, 0) for k in _INTENTS}
        avg_conf = (total_conf / total) if total else 0.0
        fallback_rate = (fallbacks / total) if total else 0.0
        accuracy = (correct / samples) if samples else 0.0
        return {
            "total_calls": total,
            "intent_distribution": dist,
            "avg_confidence": avg_conf,
            "fallbacks": fallbacks,
            "fallback_rate": fallback_rate,
            "routing_accuracy": accuracy,
            "accuracy_samples": samples,
        }


_STATS = _RoutingStats()


def get_routing_stats() -> Dict[str, Any]:
    """
    Return process-local routing stats.

    Returns:
        dict: {
          total_calls,
          intent_distribution,
          routing_accuracy,
          accuracy_samples,
          fallbacks,
          fallback_rate,
          avg_confidence
        }
    """
    return _STATS.snapshot()


# ---------------------------------------------------------------------------
# Dispatch helpers
# ---------------------------------------------------------------------------


def _try_call_agent(module_path: str, fn_name: str, query: str, conn, kb_conn) -> Optional[Dict[str, Any]]:
    """
    Try importing a module and calling fn_name(query, conn, kb_conn).

    Returns:
        dict if the call succeeds, else None.
    """
    try:
        mod = __import__(module_path, fromlist=[fn_name])
    except Exception:
        return None
    fn = getattr(mod, fn_name, None)
    if not callable(fn):
        return None
    try:
        out = fn(query, conn, kb_conn)
        return out if isinstance(out, dict) else {"response": str(out)}
    except Exception as e:  # noqa: BLE001
        _LOG.exception("Agent call failed: %s.%s", module_path, fn_name)
        return {"response": "", "success": False, "error": str(e)}


def _llm_fallback(system_role: str, context: str, query: str) -> Dict[str, Any]:
    """
    Generic LLM fallback used when a specialized agent is unavailable.

    Important:
      - Routing remains deterministic (keyword/pattern based).
      - This function only generates the answer (may call the local LLM).
    """
    system_prompt = (
        "You are aeOS Local AI.\n"
        f"Role: {system_role}\n"
        "Rules:\n"
        "- Be concrete and operational.\n"
        "- If you need missing info, ask for it explicitly.\n"
        "- Prefer bullet points and short sections.\n"
    )
    prompt = (query or "").strip()
    if context:
        prompt = (
            "Use the following CONTEXT to answer the QUESTION.\n"
            "If the context is insufficient, say what is missing.\n\n"
            "<CONTEXT>\n"
            f"{context}\n"
            "</CONTEXT>\n\n"
            "<QUESTION>\n"
            f"{prompt}\n"
            "</QUESTION>\n"
        )
    return ai_infer.infer(prompt=prompt, system_prompt=system_prompt)


def _build_context(intent: str, query: str, conn, kb_conn) -> str:
    """
    Build the minimum prompt context needed for a given intent.
    """
    policy = _CONTEXT_POLICY.get(intent, _CONTEXT_POLICY["general"])
    use_db = bool(policy.get("db"))
    use_kb = bool(policy.get("kb"))
    if not (use_db or use_kb):
        return ""

    # Portfolio is a special case: DB-only snapshot.
    if intent == "portfolio_health" and use_db:
        try:
            return ai_context.build_portfolio_context(conn)
        except Exception as e:  # noqa: BLE001
            _LOG.warning("Failed to build portfolio context: %s", e)
            return ""

    # Memory search is KB-only by policy; DB not needed.
    if intent == "memory_search" and use_kb:
        try:
            return ai_context.build_kb_context(kb_conn, query)
        except Exception as e:  # noqa: BLE001
            _LOG.warning("Failed to build KB context: %s", e)
            return ""

    # Default: combined pack (portfolio → decision records → KB).
    try:
        return ai_context.assemble_full_context(conn, kb_conn, query)
    except Exception as e:  # noqa: BLE001
        _LOG.warning("Failed to build full context pack: %s", e)
        return ""


def _dispatch(intent: str, query: str, conn, kb_conn, context: str) -> Tuple[Dict[str, Any], bool]:
    """
    Dispatch to the best available handler for intent.

    Returns:
        (response_dict, fallback_used)
    """
    intent = intent if intent in _INTENTS else "general"

    # First preference: dedicated agent (Layer 2) if present.
    # Contract for agents (Layer 2): def handle(query: str, conn, kb_conn) -> dict
    agent_map: Dict[str, Tuple[str, str]] = {
        "pain_analysis": ("src.agents.agent_pain", "handle"),
        "solution_generation": ("src.agents.agent_solution", "handle"),
        "prediction": ("src.agents.agent_prediction", "handle"),
        "bias_check": ("src.agents.agent_bias", "handle"),
        "memory_search": ("src.agents.agent_memory", "handle"),
    }

    if intent in agent_map:
        mod_path, fn_name = agent_map[intent]
        agent_out = _try_call_agent(mod_path, fn_name, query, conn, kb_conn)
        if isinstance(agent_out, dict) and agent_out:
            # If the agent explicitly reports failure, fall through to fallback handlers.
            if agent_out.get("success") is False:
                _LOG.warning("Agent returned success=False for intent=%s; falling back.", intent)
            else:
                # Agent output is authoritative; ensure minimal contract keys exist.
                agent_out.setdefault("success", True)
                return agent_out, False

    # Fast deterministic handlers (no LLM) where possible.
    if intent == "memory_search":
        # If agent isn't present, return KB context directly (still useful).
        return {"response": context or ai_context.build_kb_context(kb_conn, query), "success": True}, True

    if intent == "portfolio_health":
        # Provide a short LLM narrative on top of DB snapshot (if any).
        system_role = "Portfolio Health Analyst"
        return _llm_fallback(system_role=system_role, context=context, query=query), True

    # LLM fallback by intent.
    role_map = {
        "pain_analysis": "Pain Analyst",
        "solution_generation": "Solution Designer",
        "prediction": "Prediction Analyst",
        "bias_check": "Bias Auditor",
        "general": "General Assistant",
    }
    return _llm_fallback(system_role=role_map.get(intent, "General Assistant"), context=context, query=query), True


# ---------------------------------------------------------------------------
# Public router
# ---------------------------------------------------------------------------


def route_query(query: str, conn, kb_conn) -> Dict[str, Any]:
    """
    Route a query to the correct agent/module.

    Args:
        query: User query string.
        conn: SQLite connection (duck-typed; can be None).
        kb_conn: KB connection/collection (duck-typed; can be None).

    Returns:
        dict: {
          query,
          intent,
          confidence,
          suggested_agent,
          context_needed,
          response,
          model,
          tokens_used,
          latency_ms,
          success,
          fallback_used,
        }
    """
    started = time.perf_counter()
    raw = query or ""
    override_intent, cleaned = _extract_intent_override(raw)
    cleaned = _clean_query(cleaned)

    # Empty input: return a safe, deterministic response (no dispatch).
    if not cleaned:
        out = {
            "query": "",
            "intent": "general",
            "confidence": 0.0,
            "suggested_agent": _AGENT_BY_INTENT["general"],
            "context_needed": _CONTEXT_POLICY["general"].copy(),
            "response": "",
            "success": False,
            "error": "empty_query",
            "fallback_used": False,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
        _STATS.record(final_intent="general", confidence=0.0, fallback_used=False)
        return out

    # If override is present, compute predicted intent from the cleaned query
    # for accuracy tracking, but route using the override.
    if override_intent:
        pred = detect_intent(cleaned)
        final_intent = override_intent
        confidence = 1.0
        suggested_agent = _AGENT_BY_INTENT.get(final_intent, "ai_infer")
        context_needed = _CONTEXT_POLICY.get(final_intent, _CONTEXT_POLICY["general"]).copy()
        predicted_intent = pred.get("intent")
        ground_truth_intent = override_intent
    else:
        pred = detect_intent(cleaned)
        final_intent = str(pred.get("intent") or "general")
        confidence = float(pred.get("confidence") or 0.0)
        suggested_agent = str(pred.get("suggested_agent") or _AGENT_BY_INTENT.get(final_intent, "ai_infer"))
        context_needed = dict(pred.get("context_needed") or _CONTEXT_POLICY.get(final_intent, _CONTEXT_POLICY["general"]))
        predicted_intent = None
        ground_truth_intent = None

    context = _build_context(final_intent, cleaned, conn, kb_conn)
    resp, fallback_used = _dispatch(final_intent, cleaned, conn, kb_conn, context)

    # Normalize response payload: merge in known metadata without clobbering agent outputs.
    out: Dict[str, Any] = {}
    if isinstance(resp, dict):
        out.update(resp)
    else:
        out["response"] = str(resp)
    out.setdefault("response", "")
    out.setdefault("success", True)

    # Add routing metadata.
    out["query"] = cleaned
    out["intent"] = final_intent
    out["confidence"] = confidence
    out["suggested_agent"] = suggested_agent
    out["context_needed"] = context_needed
    out["fallback_used"] = bool(fallback_used)

    # If LLM response dict contains its own latency, keep it; otherwise compute wall time.
    if "latency_ms" not in out:
        out["latency_ms"] = int((time.perf_counter() - started) * 1000)

    _STATS.record(
        final_intent=final_intent,
        confidence=confidence,
        predicted_intent=predicted_intent,
        ground_truth_intent=ground_truth_intent,
        fallback_used=fallback_used,
    )

    return out
