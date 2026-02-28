"""
orchestrator.py
aeOS Phase 4 — Layer 3 (Orchestrator)

Central coordinator that receives user queries, routes them through the correct
agent pipeline, and assembles final responses.

Stamp: S✅ T✅ L✅ A✅
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, Optional, Tuple


# ---- Logging (centralized) ---------------------------------------------------
try:
    from src.core.logger import get_logger  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    # Fallback for dev runs where `src/` is on PYTHONPATH.
    from core.logger import get_logger  # type: ignore

_LOG = get_logger(__name__)


# ---- Config (best-effort) ----------------------------------------------------
try:
    from src.core import config as _config  # type: ignore
except Exception:  # pragma: no cover
    try:
        from core import config as _config  # type: ignore
    except Exception:  # pragma: no cover
        _config = None  # type: ignore


def _cfg(name: str, default: Any = None) -> Any:
    """Read a config attribute with env var fallback (best-effort)."""
    if _config is not None and hasattr(_config, name):
        return getattr(_config, name)
    # Environment variables are stringly-typed; keep a simple fallback.
    return os.environ.get(name, default)


# ---- DB connection (required by architecture) --------------------------------
try:
    from src.db.db_connect import get_connection  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    try:
        from db.db_connect import get_connection  # type: ignore
    except Exception:  # pragma: no cover
        get_connection = None  # type: ignore


# ---- KB connection (Phase 3; best-effort) ------------------------------------
try:
    from src.kb import kb_connect as _kb_connect  # type: ignore
except Exception:  # pragma: no cover
    try:
        from kb import kb_connect as _kb_connect  # type: ignore
    except Exception:  # pragma: no cover
        _kb_connect = None  # type: ignore


# ---- AI / Router -------------------------------------------------------------
try:
    from src.ai import ai_router  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    from ai import ai_router  # type: ignore

# We use ai_connect for health checks only.
try:
    from src.ai.ai_connect import ping_ollama, check_model_available  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    try:
        from ai.ai_connect import ping_ollama, check_model_available  # type: ignore
    except Exception:  # pragma: no cover
        ping_ollama = None  # type: ignore
        check_model_available = None  # type: ignore


# ---- Agents (Layer 2) --------------------------------------------------------
# Note: agent_pain intentionally does not expose a "handle" wrapper (as of the
# current Phase 4 snapshot). Orchestrator adapts accordingly.

try:
    from src.agents import agent_pain  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    try:
        from agents import agent_pain  # type: ignore
    except Exception:  # pragma: no cover
        agent_pain = None  # type: ignore

try:
    from src.agents import agent_solution  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    try:
        from agents import agent_solution  # type: ignore
    except Exception:  # pragma: no cover
        agent_solution = None  # type: ignore

try:
    from src.agents import agent_prediction  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    try:
        from agents import agent_prediction  # type: ignore
    except Exception:  # pragma: no cover
        agent_prediction = None  # type: ignore

try:
    from src.agents import agent_bias  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    try:
        from agents import agent_bias  # type: ignore
    except Exception:  # pragma: no cover
        agent_bias = None  # type: ignore

try:
    from src.agents import agent_memory  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    try:
        from agents import agent_memory  # type: ignore
    except Exception:  # pragma: no cover
        agent_memory = None  # type: ignore


__version__ = "0.1.0"

_PAIN_ID_RE = re.compile(r"\bPAIN-\d{8}-\d{3}\b", re.I)


def _call_first_available(
    obj: Any,
    names: Tuple[str, ...],
    call_specs: Tuple[Tuple[Tuple[Any, ...], Dict[str, Any]], ...],
) -> Dict[str, Any]:
    """
    Call the first callable attribute among `names` using the first compatible arg/kw spec.

    Returns:
        dict: {"ok": bool, "value": Any, "fn": str|None, "error": str|None}
    """
    for n in names:
        fn = getattr(obj, n, None)
        if not callable(fn):
            continue
        for args, kwargs in call_specs:
            try:
                return {"ok": True, "value": fn(*args, **kwargs), "fn": n, "error": None}
            except TypeError:
                # Signature mismatch; try next call spec.
                continue
            except Exception as e:
                # Runtime failure; try next function name (some may exist but require different setup).
                return {"ok": False, "value": None, "fn": n, "error": str(e)}
    return {"ok": False, "value": None, "fn": None, "error": None}


def _is_collection_like(obj: Any) -> bool:
    """Heuristic: treat objects with a `.query()` method as a KB collection."""
    return bool(obj is not None and callable(getattr(obj, "query", None)))


def _resolve_collection_from_client(client: Any, name_candidates: Tuple[str, ...]) -> Any:
    """Try to obtain a collection object from a KB client (duck-typed)."""
    if client is None:
        return None
    # Common Chroma methods.
    for cname in name_candidates:
        res = _call_first_available(
            client,
            names=("get_or_create_collection", "get_collection", "collection"),
            call_specs=(
                ((cname,), {}),
                ((), {"name": cname}),
                ((), {"collection": cname}),
            ),
        )
        if res.get("ok") and _is_collection_like(res.get("value")):
            return res.get("value")
    return None


def _connect_db(db_path: str):
    """Connect to SQLite via src/db/db_connect.get_connection (best-effort)."""
    if get_connection is None:
        return None
    p = (db_path or "").strip()
    call_specs: Tuple[Tuple[Tuple[Any, ...], Dict[str, Any]], ...] = (
        ((p,), {}),
        ((), {"db_path": p}),
        ((), {"path": p}),
        ((), {}),
    )
    for args, kwargs in call_specs:
        try:
            conn = get_connection(*args, **kwargs)  # type: ignore[misc]
            if conn is not None:
                return conn
        except TypeError:
            continue
        except Exception as e:
            _LOG.warning("DB connect failed: %s", e)
            return None
    return None


def _db_ping(conn: Any) -> bool:
    """Quick DB sanity check without assuming schema tables."""
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.fetchone()
        return True
    except Exception:
        return False


def _connect_kb(kb_path: str) -> Any:
    """
    Connect to KB (best-effort).

    `kb_path` is treated as:
      - a collection name, OR
      - a persistence directory / connection hint

    We attempt multiple common patterns used by Chroma wrappers without hard-coding.
    """
    if _kb_connect is None:
        return None
    raw = (kb_path or "").strip()
    if not raw:
        return None

    # 1) If kb_path looks like a directory, prefer client-style connect then resolve a collection.
    looks_like_dir = False
    try:
        looks_like_dir = os.path.isdir(raw)
    except Exception:
        looks_like_dir = False

    # Candidate collection names: stable defaults; we don't want to invent too many.
    # If kb_path is *not* a directory, it is used as a candidate as well.
    base_candidates: Tuple[str, ...] = ("aeos", "default", "kb", "notes")
    name_candidates: Tuple[str, ...] = base_candidates if looks_like_dir else (raw,) + base_candidates

    # (a) Direct collection getters on the module.
    res = _call_first_available(
        _kb_connect,
        names=("get_collection", "get_or_create_collection", "connect_collection", "collection", "kb_collection"),
        call_specs=(
            ((raw,), {}),
            ((), {"collection": raw}),
            ((), {"name": raw}),
        ),
    )
    if res.get("ok") and _is_collection_like(res.get("value")):
        return res.get("value")

    # (b) Client connection on the module.
    client_res = _call_first_available(
        _kb_connect,
        names=("get_kb_client", "connect", "get_client", "kb_client", "init"),
        call_specs=(
            ((raw,), {}),
            ((), {"persist_directory": raw}),
            ((), {"path": raw}),
            ((), {"kb_path": raw}),
            ((), {}),
        ),
    )
    if client_res.get("ok"):
        client = client_res.get("value")
        # If connect returned a collection directly.
        if _is_collection_like(client):
            return client
        # If connect returned a dict-like wrapper.
        if isinstance(client, dict):
            for k in ("collection", "kb", "conn", "client"):
                if _is_collection_like(client.get(k)):
                    return client.get(k)
            # If it *is* a client dict, fall through.
        # If connect returned a tuple (client, collection) or similar.
        if isinstance(client, tuple) and client:
            for item in client:
                if _is_collection_like(item):
                    return item
        # Resolve collection from client object.
        coll = _resolve_collection_from_client(client, name_candidates)
        if coll is not None:
            return coll

    # Nothing worked; be graceful.
    return None


def _ollama_ok(model: str) -> bool:
    """Best-effort health check: ping Ollama and verify model exists when possible."""
    if not callable(ping_ollama):
        return False
    try:
        if not bool(ping_ollama()):  # type: ignore[misc]
            return False
    except Exception:
        return False
    if callable(check_model_available) and model:
        try:
            return bool(check_model_available(model))  # type: ignore[misc]
        except Exception:
            # If model-check fails but ping succeeded, treat as connected anyway.
            return True
    return True


class Orchestrator:
    """
    Central aeOS orchestrator.

    Responsibilities:
      - Connect to DB + KB
      - Detect intent using ai_router
      - Dispatch to the appropriate agent
      - Provide a small daily briefing composer
    """

    def __init__(self, db_path: str, kb_path: str):
        # Load config values (Phase 4 config contract).
        self.ollama_host: str = str(_cfg("OLLAMA_HOST", "http://localhost:11434"))
        self.ollama_model: str = str(_cfg("OLLAMA_MODEL", "deepseek-r1:8b"))
        self.db_path = (db_path or "").strip()
        self.kb_path = (kb_path or "").strip()

        # Initialize DB connection (required).
        self.conn = _connect_db(self.db_path)
        if self.conn is None:
            _LOG.warning("Orchestrator DB connection is not available (db_path=%s).", self.db_path)

        # Initialize KB connection (optional).
        self.kb_conn = _connect_kb(self.kb_path)
        if self.kb_conn is None:
            _LOG.info("Orchestrator KB connection is not available (kb_path=%s).", self.kb_path)

        # Router + agents (Layer 2).
        self.router = ai_router
        self.agent_pain = agent_pain
        self.agent_solution = agent_solution
        self.agent_prediction = agent_prediction
        self.agent_bias = agent_bias
        self.agent_memory = agent_memory

    # ---- Lifecycle ------------------------------------------------------------

    def close(self) -> None:
        """Close resources (best-effort; safe to call multiple times)."""
        # SQLite
        try:
            if self.conn is not None:
                self.conn.close()
        except Exception:
            pass
        finally:
            self.conn = None
        # KB clients vary; close/persist if exposed.
        try:
            if self.kb_conn is not None:
                if callable(getattr(self.kb_conn, "persist", None)):
                    self.kb_conn.persist()
                if callable(getattr(self.kb_conn, "close", None)):
                    self.kb_conn.close()
        except Exception:
            pass
        finally:
            self.kb_conn = None

    def __enter__(self) -> "Orchestrator":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ---- Core routing ---------------------------------------------------------

    def _fallback_route(self, query: str) -> Dict[str, Any]:
        """
        Fallback to ai_router.route_query (LLM + context builder).

        This keeps behavior usable when an agent is missing or returns success=False.
        """
        try:
            if hasattr(self.router, "route_query"):
                return self.router.route_query(query, self.conn, self.kb_conn)  # type: ignore[attr-defined]
        except Exception as e:
            _LOG.warning("ai_router.route_query failed: %s", e)

        # Absolute last resort: deterministic stub.
        return {
            "query": query,
            "intent": "general",
            "confidence": 0.0,
            "suggested_agent": "none",
            "context_needed": {"db": False, "kb": False},
            "response": "I couldn't route that request because the router pipeline is unavailable.",
            "model": None,
            "tokens_used": 0,
            "latency_ms": 0,
            "success": False,
            "fallback_used": True,
        }

    def _format_pain_analysis(self, pain_id: str, analysis: Dict[str, Any]) -> str:
        """Format agent_pain.analyze_pain() output into a human-readable string."""
        root = (analysis.get("root_cause") or "").strip()
        sev = analysis.get("severity_assessment") if isinstance(analysis.get("severity_assessment"), dict) else {}
        label = (sev.get("label") or "Unknown") if isinstance(sev, dict) else "Unknown"
        est = sev.get("score_estimate") if isinstance(sev, dict) else None
        rationale = (sev.get("rationale") or "").strip() if isinstance(sev, dict) else ""
        actions = analysis.get("recommended_actions") if isinstance(analysis.get("recommended_actions"), list) else []
        conf = analysis.get("confidence")

        lines = [f"Pain Analysis — {pain_id}"]
        lines.append(f"Root cause: {root or '(unknown)'}")
        if isinstance(est, (int, float)):
            lines.append(f"Severity: {label} (estimate={float(est):.1f}/100)")
        else:
            lines.append(f"Severity: {label} (estimate=NA)")
        if rationale:
            lines.append(f"Rationale: {rationale}")
        if actions:
            lines.append("Recommended actions:")
            for i, a in enumerate(actions[:10], start=1):
                a_s = str(a).strip()
                if a_s:
                    lines.append(f"{i}. {a_s}")
        else:
            lines.append("Recommended actions: (none provided)")
        if isinstance(conf, (int, float)):
            lines.append(f"Confidence: {float(conf):.2f}")
        return "\n".join(lines).strip()

    def _handle_pain_intent(self, query: str) -> Dict[str, Any]:
        """Route pain-related queries to agent_pain functions (no agent_pain.handle)."""
        if self.agent_pain is None:
            return {"success": False, "response": "", "error": "agent_pain_missing"}
        if self.conn is None:
            return {
                "success": False,
                "response": "Pain analysis requires a DB connection, but the DB is not connected.",
                "error": "db_not_connected",
            }

        q = (query or "").strip()
        ql = q.lower()

        # If a PAIN id is present, analyze that specific pain.
        m = _PAIN_ID_RE.search(q)
        if m and callable(getattr(self.agent_pain, "analyze_pain", None)):
            pain_id = m.group(0).upper()
            analysis = self.agent_pain.analyze_pain(self.conn, pain_id)  # type: ignore[attr-defined]
            if isinstance(analysis, dict):
                return {"success": True, "response": self._format_pain_analysis(pain_id, analysis), "data": analysis}
            return {"success": True, "response": str(analysis)}

        # Patterns/themes request.
        if (
            ("pattern" in ql or "theme" in ql or "recurr" in ql)
            and callable(getattr(self.agent_pain, "detect_pain_patterns", None))
        ):
            pats = self.agent_pain.detect_pain_patterns(self.conn)  # type: ignore[attr-defined]
            if isinstance(pats, list) and pats:
                lines = ["Pain Patterns:"]
                for t in pats[:8]:
                    if not isinstance(t, dict):
                        continue
                    theme = str(t.get("theme") or "").strip()
                    if not theme:
                        continue
                    cnt = t.get("count")
                    kws = t.get("keywords") if isinstance(t.get("keywords"), list) else []
                    ex = t.get("sample_pain_ids") if isinstance(t.get("sample_pain_ids"), list) else []
                    kw_s = ", ".join([str(x) for x in kws[:6] if str(x).strip()])
                    ex_s = ", ".join([str(x) for x in ex[:4] if str(x).strip()])
                    left = f"- {theme}"
                    if isinstance(cnt, int):
                        left += f" (count={cnt})"
                    if kw_s:
                        left += f" | keywords: {kw_s}"
                    if ex_s:
                        left += f" | examples: {ex_s}"
                    lines.append(left)
                return {"success": True, "response": "\n".join(lines).strip(), "data": pats}
            return {"success": True, "response": "Pain Patterns: (none found)", "data": pats}

        # Default: daily/portfolio pain summary.
        if callable(getattr(self.agent_pain, "generate_pain_summary", None)):
            summary = self.agent_pain.generate_pain_summary(self.conn)  # type: ignore[attr-defined]
            return {"success": True, "response": str(summary)}

        return {"success": False, "response": "", "error": "agent_pain_no_entrypoints"}

    def process(self, query: str) -> Dict[str, Any]:
        """
        Process a user query end-to-end.

        Returns:
            dict: {response, agent_used, intent, latency_ms, success}
        """
        started = time.perf_counter()
        q = (query or "").strip()
        if not q:
            return {"response": "", "agent_used": "none", "intent": "general", "latency_ms": 0, "success": False}

        # 1) Intent detection (deterministic router).
        try:
            intent_info = self.router.detect_intent(q)  # type: ignore[attr-defined]
        except Exception:
            intent_info = {"intent": "general", "confidence": 0.0, "suggested_agent": "ai_infer"}

        intent = str(intent_info.get("intent") or "general")
        suggested = str(intent_info.get("suggested_agent") or "ai_infer")

        # 2) Dispatch.
        agent_used = suggested
        out: Dict[str, Any] = {"success": True, "response": ""}

        try:
            if intent == "pain_analysis":
                out = self._handle_pain_intent(q)
                agent_used = "agent_pain"
            elif intent == "solution_generation" and self.agent_solution is not None:
                out = self.agent_solution.handle(q, self.conn, self.kb_conn)  # type: ignore[attr-defined]
                agent_used = "agent_solution"
            elif intent == "prediction" and self.agent_prediction is not None:
                out = self.agent_prediction.handle(q, self.conn, self.kb_conn)  # type: ignore[attr-defined]
                agent_used = "agent_prediction"
            elif intent == "bias_check" and self.agent_bias is not None:
                out = self.agent_bias.handle(q, self.conn, self.kb_conn)  # type: ignore[attr-defined]
                agent_used = "agent_bias"
            elif intent == "memory_search" and self.agent_memory is not None:
                out = self.agent_memory.handle(q, self.conn, self.kb_conn)  # type: ignore[attr-defined]
                agent_used = "agent_memory"
            else:
                # For general / portfolio_health / unknown intents, defer to the unified router.
                routed = self._fallback_route(q)
                out = {
                    "success": bool(routed.get("success", True)),
                    "response": routed.get("response") or "",
                    "data": routed,
                }
                # Preserve router-selected agent label if present.
                agent_used = str(routed.get("suggested_agent") or routed.get("agent_used") or suggested)
                intent = str(routed.get("intent") or intent)
        except Exception as e:
            _LOG.exception("Orchestrator.process dispatch failed: %s", e)
            out = {"success": False, "response": "An internal error occurred while processing your request.", "error": str(e)}

        # 3) Normalize result + latency.
        latency_ms = int((time.perf_counter() - started) * 1000)
        resp = out.get("response") if isinstance(out, dict) else str(out)
        success = bool(out.get("success", True)) if isinstance(out, dict) else True

        # If an agent explicitly failed, try fallback routing once.
        if not success:
            routed = self._fallback_route(q)
            resp = routed.get("response") or resp or ""
            success = bool(routed.get("success", False))
            agent_used = str(routed.get("suggested_agent") or "ai_router_fallback")
            intent = str(routed.get("intent") or intent)

        return {
            "response": str(resp or ""),
            "agent_used": agent_used,
            "intent": intent,
            "latency_ms": latency_ms,
            "success": success,
        }

    # ---- Briefing -------------------------------------------------------------

    def run_daily_briefing(self) -> str:
        """
        Compose a daily briefing string.

        Required calls:
          - agent_pain.generate_pain_summary()
          - agent_solution.suggest_quick_wins()
          - agent_prediction.get_calibration_insight()
        """
        lines = ["aeOS Daily Briefing", ""]

        # Pain summary
        if self.agent_pain is not None and callable(getattr(self.agent_pain, "generate_pain_summary", None)):
            try:
                lines.append("Pain Focus")
                lines.append(self.agent_pain.generate_pain_summary(self.conn))  # type: ignore[attr-defined]
            except Exception as e:
                _LOG.warning("generate_pain_summary failed: %s", e)
                lines.append("Pain Focus")
                lines.append("(pain summary unavailable)")
        else:
            lines.append("Pain Focus")
            lines.append("(agent_pain unavailable)")
        lines.append("")

        # Quick wins
        if self.agent_solution is not None and callable(getattr(self.agent_solution, "suggest_quick_wins", None)):
            try:
                wins = self.agent_solution.suggest_quick_wins(self.conn)  # type: ignore[attr-defined]
                lines.append("Quick Wins")
                if isinstance(wins, list) and wins:
                    for w in wins[:7]:
                        if not isinstance(w, dict):
                            continue
                        sid = w.get("solution_id") or ""
                        title = w.get("title") or ""
                        imp = w.get("impact_score")
                        eff = w.get("effort_score")
                        lines.append(f"- {sid}: {title} (impact={imp}, effort={eff})".strip())
                else:
                    lines.append("(none found)")
            except Exception as e:
                _LOG.warning("suggest_quick_wins failed: %s", e)
                lines.append("Quick Wins")
                lines.append("(quick wins unavailable)")
        else:
            lines.append("Quick Wins")
            lines.append("(agent_solution unavailable)")
        lines.append("")

        # Calibration insight
        if self.agent_prediction is not None and callable(getattr(self.agent_prediction, "get_calibration_insight", None)):
            try:
                lines.append("Prediction Calibration")
                lines.append(self.agent_prediction.get_calibration_insight(self.conn))  # type: ignore[attr-defined]
            except Exception as e:
                _LOG.warning("get_calibration_insight failed: %s", e)
                lines.append("Prediction Calibration")
                lines.append("(calibration insight unavailable)")
        else:
            lines.append("Prediction Calibration")
            lines.append("(agent_prediction unavailable)")

        return "\n".join([str(x).rstrip() for x in lines]).strip()

    # ---- Status ---------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return health/status snapshot for the orchestrator."""
        db_connected = _db_ping(self.conn)
        kb_connected = self.kb_conn is not None
        agents_loaded = all(
            m is not None
            for m in (
                self.agent_pain,
                self.agent_solution,
                self.agent_prediction,
                self.agent_bias,
                self.agent_memory,
            )
        )
        ollama_connected = _ollama_ok(self.ollama_model)

        return {
            "ollama_connected": bool(ollama_connected),
            "agents_loaded": bool(agents_loaded),
            "db_connected": bool(db_connected),
            "kb_connected": bool(kb_connected),
            "version": __version__,
        }


# ---- Convenience functions ----------------------------------------------------


def create_orchestrator(db_path: str, kb_path: str) -> Orchestrator:
    """Factory for easy instantiation."""
    return Orchestrator(db_path=db_path, kb_path=kb_path)


def run_query(query: str, db_path: str, kb_path: str) -> Dict[str, Any]:
    """One-shot query runner (no persistent connections)."""
    orch = Orchestrator(db_path=db_path, kb_path=kb_path)
    try:
        return orch.process(query)
    finally:
        orch.close()
