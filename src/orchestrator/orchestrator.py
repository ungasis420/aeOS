"""
orchestrator.py
aeOS Phase 4+5 — Layer 3 (Orchestrator)

Central coordinator implementing the Addendum A 11-step pipeline:
  1. Input → 2. NLQ Parse (A5) → 3. Signal Enrichment (A10) →
  4. Cartridge Loading → 5. Reasoning → 6. Offline Fallback (A3) →
  7. Cartridge Arbitration (A4) → 8. Contradiction Check (A2) →
  9. 4-Gate Validation → 10. Compose & Deliver →
  11. Log (A6) → 12. Learn (Flywheel)

Falls back to legacy agent dispatch for agent-specific intents
(pain_analysis, solution_generation, prediction, bias_check, memory_search).

Stamp: S✅ T✅ L✅ A✅
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


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


# ---- Orchestration Pipeline (5-stage) ----------------------------------------
try:
    from src.orchestration.dispatcher import Dispatcher as _Dispatcher  # type: ignore
    from src.orchestration.cartridge_conductor import CartridgeConductor as _CartridgeConductor  # type: ignore
    from src.orchestration.reasoning_synthesizer import ReasoningSynthesizer as _ReasoningSynthesizer  # type: ignore
    from src.orchestration.output_validator import OutputValidator as _OutputValidator  # type: ignore
    from src.orchestration.output_composer import OutputComposer as _OutputComposer  # type: ignore
    from src.orchestration.models import ValidationResult as _ValidationResult  # type: ignore
except Exception:  # pragma: no cover
    _Dispatcher = None  # type: ignore
    _CartridgeConductor = None  # type: ignore
    _ReasoningSynthesizer = None  # type: ignore
    _OutputValidator = None  # type: ignore
    _OutputComposer = None  # type: ignore
    _ValidationResult = None  # type: ignore


# ---- Addendum A Modules (A2-A10) ---------------------------------------------

# A2: Contradiction Detector
try:
    from src.core.contradiction_detector import ContradictionDetector as _ContradictionDetector  # type: ignore
except Exception:  # pragma: no cover
    try:
        from core.contradiction_detector import ContradictionDetector as _ContradictionDetector  # type: ignore
    except Exception:  # pragma: no cover
        _ContradictionDetector = None  # type: ignore

# A3: Offline Mode
try:
    from src.core.offline_mode import OfflineMode as _OfflineMode  # type: ignore
except Exception:  # pragma: no cover
    try:
        from core.offline_mode import OfflineMode as _OfflineMode  # type: ignore
    except Exception:  # pragma: no cover
        _OfflineMode = None  # type: ignore

# A4: Cartridge Arbitrator
try:
    from src.core.cartridge_arbitrator import (  # type: ignore
        CartridgeArbitrator as _CartridgeArbitrator,
        CartridgeRecommendation as _CartridgeRecommendation,
    )
except Exception:  # pragma: no cover
    try:
        from core.cartridge_arbitrator import (  # type: ignore
            CartridgeArbitrator as _CartridgeArbitrator,
            CartridgeRecommendation as _CartridgeRecommendation,
        )
    except Exception:  # pragma: no cover
        _CartridgeArbitrator = None  # type: ignore
        _CartridgeRecommendation = None  # type: ignore

# A5: NLQ Parser
try:
    from src.core.nlq_parser import NLQParser as _NLQParser  # type: ignore
except Exception:  # pragma: no cover
    try:
        from core.nlq_parser import NLQParser as _NLQParser  # type: ignore
    except Exception:  # pragma: no cover
        _NLQParser = None  # type: ignore

# A6: Audit Trail
try:
    from src.core.audit_trail import AuditTrail as _AuditTrail  # type: ignore
except Exception:  # pragma: no cover
    try:
        from core.audit_trail import AuditTrail as _AuditTrail  # type: ignore
    except Exception:  # pragma: no cover
        _AuditTrail = None  # type: ignore

# A7: Reflection Engine
try:
    from src.core.reflection_engine import ReflectionEngine as _ReflectionEngine  # type: ignore
except Exception:  # pragma: no cover
    try:
        from core.reflection_engine import ReflectionEngine as _ReflectionEngine  # type: ignore
    except Exception:  # pragma: no cover
        _ReflectionEngine = None  # type: ignore

# A8: Blind Spot Mapper
try:
    from src.core.blind_spot_mapper import BlindSpotMapper as _BlindSpotMapper  # type: ignore
except Exception:  # pragma: no cover
    try:
        from core.blind_spot_mapper import BlindSpotMapper as _BlindSpotMapper  # type: ignore
    except Exception:  # pragma: no cover
        _BlindSpotMapper = None  # type: ignore

# A9: Sovereign Dashboard
try:
    from src.screens.sovereign_dashboard import SovereignDashboard as _SovereignDashboard  # type: ignore
except Exception:  # pragma: no cover
    try:
        from screens.sovereign_dashboard import SovereignDashboard as _SovereignDashboard  # type: ignore
    except Exception:  # pragma: no cover
        _SovereignDashboard = None  # type: ignore

# A10: Signal Ingester
try:
    from src.core.signal_ingester import SignalIngester as _SignalIngester  # type: ignore
except Exception:  # pragma: no cover
    try:
        from core.signal_ingester import SignalIngester as _SignalIngester  # type: ignore
    except Exception:  # pragma: no cover
        _SignalIngester = None  # type: ignore

# A1: Identity Continuity (lifecycle only — not in query pipeline)
try:
    from src.core.identity_continuity import IdentityContinuityProtocol as _IdentityContinuityProtocol  # type: ignore
except Exception:  # pragma: no cover
    try:
        from core.identity_continuity import IdentityContinuityProtocol as _IdentityContinuityProtocol  # type: ignore
    except Exception:  # pragma: no cover
        _IdentityContinuityProtocol = None  # type: ignore

# Flywheel Logger (Learn step)
try:
    from src.cognitive.flywheel_logger import FlywheelLogger as _FlywheelLogger  # type: ignore
except Exception:  # pragma: no cover
    try:
        from cognitive.flywheel_logger import FlywheelLogger as _FlywheelLogger  # type: ignore
    except Exception:  # pragma: no cover
        _FlywheelLogger = None  # type: ignore

# EventBus (cross-module communication)
try:
    from src.core.event_bus import EventBus as _EventBus, Event as _Event, get_event_bus as _get_event_bus  # type: ignore
except Exception:  # pragma: no cover
    try:
        from core.event_bus import EventBus as _EventBus, Event as _Event, get_event_bus as _get_event_bus  # type: ignore
    except Exception:  # pragma: no cover
        _EventBus = None  # type: ignore
        _Event = None  # type: ignore
        _get_event_bus = None  # type: ignore

# DaemonScheduler (background jobs)
try:
    from src.core.daemon_scheduler import DaemonScheduler as _DaemonScheduler  # type: ignore
except Exception:  # pragma: no cover
    try:
        from core.daemon_scheduler import DaemonScheduler as _DaemonScheduler  # type: ignore
    except Exception:  # pragma: no cover
        _DaemonScheduler = None  # type: ignore


__version__ = "0.2.0"

_PAIN_ID_RE = re.compile(r"\bPAIN-\d{8}-\d{3}\b", re.I)

# Intent strings that route to legacy agent dispatch instead of cartridge pipeline.
_AGENT_INTENTS = frozenset({
    "pain_analysis", "solution_generation", "prediction",
    "bias_check", "memory_search",
})


# ---------------------------------------------------------------------------
# Module-level helpers (unchanged from Phase 4)
# ---------------------------------------------------------------------------


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


def _safe_init(cls: Any, **kwargs: Any) -> Any:
    """Safely instantiate a class, returning None on failure."""
    if cls is None:
        return None
    try:
        return cls(**kwargs)
    except Exception as exc:
        name = getattr(cls, "__name__", str(cls))
        _LOG.warning("Failed to initialize %s: %s", name, exc)
        return None


# ===========================================================================
# Orchestrator
# ===========================================================================


class Orchestrator:
    """
    Central aeOS orchestrator.

    Responsibilities:
      - Connect to DB + KB
      - Run the full Addendum A 11-step pipeline for general queries
      - Dispatch to Layer 2 agents for agent-specific intents
      - Provide a daily briefing composer
      - Expose health/status via get_status()
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

        # ── Addendum A pipeline modules ──
        self._init_pipeline_modules()

    def _init_pipeline_modules(self) -> None:
        """Initialize orchestration pipeline + A1-A10 modules (all best-effort)."""
        db = self.db_path

        # Orchestration pipeline components (stateless — no DB needed).
        self._dispatcher = _safe_init(_Dispatcher)
        self._conductor = _safe_init(_CartridgeConductor)
        self._synthesizer = _safe_init(_ReasoningSynthesizer)
        self._validator = _safe_init(_OutputValidator)
        self._composer = _safe_init(_OutputComposer)

        # A5: NLQ Parser (Step 2 — intent parsing).
        self._nlq_parser = _safe_init(_NLQParser, db_path=db)

        # A10: Signal Ingester (Step 3 — context enrichment).
        self._signal_ingester = _safe_init(_SignalIngester, db_path=db)

        # A3: Offline Mode (Step 6 — degradation fallback).
        self._offline_mode = _safe_init(
            _OfflineMode, db_path=db, ollama_url=self.ollama_host,
        )

        # A4: Cartridge Arbitrator (Step 7 — conflict resolution).
        self._cartridge_arbitrator = _safe_init(_CartridgeArbitrator, db_path=db)

        # A2: Contradiction Detector (Step 8 — consistency enforcement).
        self._contradiction_detector = _safe_init(_ContradictionDetector, db_path=db)

        # A6: Audit Trail (Step 11 — transparency logging).
        self._audit_trail = _safe_init(_AuditTrail, db_path=db)

        # A7: Reflection Engine (Step 12 — backward intelligence).
        self._reflection_engine = _safe_init(_ReflectionEngine, db_path=db)

        # A8: Blind Spot Mapper (gap detection, feeds dashboard).
        self._blind_spot_mapper = _safe_init(_BlindSpotMapper, db_path=db)

        # A9: Sovereign Dashboard (aggregation screen).
        self._sovereign_dashboard = _safe_init(_SovereignDashboard, db_path=db)

        # A1: Identity Continuity (lifecycle — not in query pipeline).
        self._identity_continuity = _safe_init(
            _IdentityContinuityProtocol, db_path=db,
        )

        # Flywheel Logger (Step 12 — compound learning).
        self._flywheel: Any = None
        if _FlywheelLogger is not None:
            try:
                self._flywheel = _FlywheelLogger()
            except Exception as exc:
                _LOG.warning("FlywheelLogger init failed: %s", exc)

        loaded = sum(
            1 for m in (
                self._nlq_parser, self._signal_ingester, self._offline_mode,
                self._cartridge_arbitrator, self._contradiction_detector,
                self._audit_trail, self._reflection_engine,
                self._blind_spot_mapper, self._sovereign_dashboard,
                self._identity_continuity,
            )
            if m is not None
        )
        _LOG.info("Pipeline modules initialized: %d/10 Addendum-A modules loaded.", loaded)

        # ── EventBus ──
        self._event_bus = None
        if _get_event_bus is not None:
            try:
                self._event_bus = _get_event_bus()
                self._wire_event_subscriptions()
            except Exception as exc:
                _LOG.warning("EventBus init failed: %s", exc)

        # ── DaemonScheduler ──
        self._scheduler = None
        if _DaemonScheduler is not None:
            try:
                self._scheduler = _DaemonScheduler(tick_interval=60.0)
                self._register_scheduled_jobs()
            except Exception as exc:
                _LOG.warning("DaemonScheduler init failed: %s", exc)

    def _wire_event_subscriptions(self) -> None:
        """Wire EventBus subscriptions for cross-module communication."""
        bus = self._event_bus
        if bus is None:
            return

        # A6 Audit Trail listens to all major events.
        if self._audit_trail is not None:
            def _audit_on_event(event: Any) -> None:
                try:
                    self._audit_trail.log_event(
                        event_type=event.topic,
                        module_source=event.source or "event_bus",
                        event_data=event.data,
                        severity="info",
                    )
                except Exception:
                    pass

            for topic in (
                "decision_made", "contradiction_found", "signal_ingested",
                "reflection_complete", "blind_spot_detected", "gate_failed",
                "connectivity_change", "arbitration_resolved",
            ):
                bus.subscribe(topic, _audit_on_event, subscription_id=f"audit_{topic}")

        # A3 OfflineMode connectivity change → bus event.
        if self._offline_mode is not None and _Event is not None:
            def _on_connectivity(status: Any) -> None:
                if bus is not None and _Event is not None:
                    bus.publish(_Event(
                        topic="connectivity_change",
                        data={"level": getattr(status, "level", "unknown")},
                        source="offline_mode",
                    ))
            try:
                self._offline_mode.on_connectivity_change(_on_connectivity)
            except Exception:
                pass

        _LOG.info("EventBus: %d topic subscriptions wired.", len(bus.get_topics()))

    def _register_scheduled_jobs(self) -> None:
        """Register standard scheduled jobs in the DaemonScheduler."""
        sched = self._scheduler
        if sched is None:
            return

        # A7: Weekly reflection — Sunday at 9:00 AM (day_of_week=6).
        if self._reflection_engine is not None:
            sched.register_cron(
                "weekly_reflection",
                {"day_of_week": 6, "hour": 9, "minute": 0},
                self._job_weekly_reflection,
            )
            # A7: Monthly reflection — 1st of month at 9:00 AM.
            sched.register_cron(
                "monthly_reflection",
                {"day_of_month": 1, "hour": 9, "minute": 0},
                self._job_monthly_reflection,
            )

        # A10: Signal cleanup — nightly at 2:00 AM.
        if self._signal_ingester is not None:
            sched.register_cron(
                "signal_cleanup",
                {"hour": 2, "minute": 0},
                self._job_signal_cleanup,
            )

        # A1: Integrity check — nightly at 3:00 AM.
        if self._identity_continuity is not None:
            sched.register_cron(
                "integrity_check",
                {"hour": 3, "minute": 0},
                self._job_integrity_check,
            )

        _LOG.info("DaemonScheduler: %d jobs registered.", len(sched.list_jobs()))

    def _job_weekly_reflection(self) -> Any:
        """Execute weekly reflection (A7)."""
        if self._reflection_engine is None:
            return None
        report = self._reflection_engine.weekly_reflection()
        if self._event_bus is not None and _Event is not None:
            self._event_bus.publish(_Event(
                topic="reflection_complete",
                data={"period": "weekly"},
                source="reflection_engine",
            ))
        return report

    def _job_monthly_reflection(self) -> Any:
        """Execute monthly reflection (A7)."""
        if self._reflection_engine is None:
            return None
        report = self._reflection_engine.monthly_reflection()
        if self._event_bus is not None and _Event is not None:
            self._event_bus.publish(_Event(
                topic="reflection_complete",
                data={"period": "monthly"},
                source="reflection_engine",
            ))
        return report

    def _job_signal_cleanup(self) -> Any:
        """Clean up expired signals (A10)."""
        if self._signal_ingester is None:
            return 0
        count = self._signal_ingester.cleanup_expired()
        if count and self._event_bus is not None and _Event is not None:
            self._event_bus.publish(_Event(
                topic="signal_expired",
                data={"cleaned_count": count},
                source="signal_ingester",
            ))
        return count

    def _job_integrity_check(self) -> Any:
        """Run integrity verification (A1)."""
        if self._identity_continuity is None:
            return None
        return self._identity_continuity.verify()

    def start_scheduler(self) -> None:
        """Start the background scheduler (call after init)."""
        if self._scheduler is not None:
            self._scheduler.start()

    def stop_scheduler(self) -> None:
        """Stop the background scheduler (call before close)."""
        if self._scheduler is not None:
            self._scheduler.stop()

    # ---- Lifecycle ------------------------------------------------------------

    def close(self) -> None:
        """Close resources (best-effort; safe to call multiple times)."""
        # Stop scheduler first.
        self.stop_scheduler()
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

    # ---- Legacy agent routing (backward compat) ------------------------------

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

    def _legacy_agent_dispatch(
        self,
        query: str,
        intent: str,
        suggested: str,
    ) -> Dict[str, Any]:
        """Dispatch to Layer 2 agents for agent-specific intents."""
        agent_used = suggested
        out: Dict[str, Any] = {"success": True, "response": ""}

        try:
            if intent == "pain_analysis":
                out = self._handle_pain_intent(query)
                agent_used = "agent_pain"
            elif intent == "solution_generation" and self.agent_solution is not None:
                out = self.agent_solution.handle(query, self.conn, self.kb_conn)  # type: ignore[attr-defined]
                agent_used = "agent_solution"
            elif intent == "prediction" and self.agent_prediction is not None:
                out = self.agent_prediction.handle(query, self.conn, self.kb_conn)  # type: ignore[attr-defined]
                agent_used = "agent_prediction"
            elif intent == "bias_check" and self.agent_bias is not None:
                out = self.agent_bias.handle(query, self.conn, self.kb_conn)  # type: ignore[attr-defined]
                agent_used = "agent_bias"
            elif intent == "memory_search" and self.agent_memory is not None:
                out = self.agent_memory.handle(query, self.conn, self.kb_conn)  # type: ignore[attr-defined]
                agent_used = "agent_memory"
            else:
                routed = self._fallback_route(query)
                out = {
                    "success": bool(routed.get("success", True)),
                    "response": routed.get("response") or "",
                    "data": routed,
                }
                agent_used = str(routed.get("suggested_agent") or routed.get("agent_used") or suggested)
                intent = str(routed.get("intent") or intent)
        except Exception as e:
            _LOG.exception("Legacy agent dispatch failed: %s", e)
            out = {"success": False, "response": "An internal error occurred.", "error": str(e)}

        return {"out": out, "agent_used": agent_used, "intent": intent}

    # ---- Full 11-step pipeline -----------------------------------------------

    def process(self, query: str) -> Dict[str, Any]:
        """
        Process a user query through the Addendum A 11-step pipeline.

        Pipeline:
          1. Input validation
          2. NLQ Parse (A5)
          3. Signal Enrichment (A10)
          4. Intent routing (NLQ → agent dispatch or cartridge pipeline)
          5. Cartridge Loading (Dispatcher + Conductor)
          6. Reasoning (ReasoningSynthesizer)
          7. Offline Fallback (A3) — if reasoning produced nothing
          8. Cartridge Arbitration (A4) — resolve conflicts
          9. Contradiction Check (A2) — consistency enforcement
         10. 4-Gate Validation (OutputValidator)
         11. Compose & Deliver (OutputComposer)
         12. Log (A6 Audit Trail)
         13. Learn (Flywheel Logger)

        Returns:
            dict: {response, agent_used, intent, latency_ms, success,
                   confidence, response_source, gate_status, domain,
                   signals_used, pipeline_steps}
        """
        started = time.perf_counter()
        q = (query or "").strip()
        if not q:
            return {
                "response": "", "agent_used": "none", "intent": "general",
                "latency_ms": 0, "success": False,
            }

        pipeline_steps: List[str] = []
        domain = "unknown"
        response_source = "full_pipeline"
        signals_used = 0

        # ── Step 2: NLQ Parse (A5) ──
        parsed = None
        if self._nlq_parser is not None:
            try:
                parsed = self._nlq_parser.parse(q)
                domain = getattr(parsed, "domain", "unknown") or "unknown"
                pipeline_steps.append("nlq_parsed")
            except Exception as exc:
                _LOG.warning("NLQ parse failed: %s", exc)

        # ── Step 3: Signal Enrichment (A10) ──
        signals: List[Any] = []
        if self._signal_ingester is not None:
            try:
                signals = self._signal_ingester.get_active_signals(
                    domain=domain if domain != "unknown" else None,
                    limit=10,
                )
                signals_used = len(signals)
                if signals:
                    pipeline_steps.append(f"signals:{len(signals)}")
            except Exception as exc:
                _LOG.warning("Signal enrichment failed: %s", exc)

        # ── Step 3b: Connectivity check (A3) ──
        connectivity = None
        if self._offline_mode is not None:
            try:
                connectivity = self._offline_mode.get_status()
                response_source = getattr(connectivity, "response_source", "full_pipeline")
                pipeline_steps.append(f"connectivity:{getattr(connectivity, 'level', 'unknown')}")
            except Exception as exc:
                _LOG.warning("Connectivity check failed: %s", exc)

        # ── Step 4: Intent resolution ──
        # Try NLQ parser result first, fall back to legacy ai_router.
        nlq_intent = None
        if parsed is not None:
            raw_type = getattr(parsed, "intent_type", None) or ""
            nlq_intent = str(raw_type).lower()

        # Legacy intent detection (always runs for backward compat).
        try:
            intent_info = self.router.detect_intent(q)  # type: ignore[attr-defined]
        except Exception:
            intent_info = {"intent": "general", "confidence": 0.0, "suggested_agent": "ai_infer"}

        legacy_intent = str(intent_info.get("intent") or "general")
        suggested = str(intent_info.get("suggested_agent") or "ai_infer")

        # Prefer NLQ intent when it matches a known special intent; otherwise use legacy.
        intent = legacy_intent
        if nlq_intent and nlq_intent in _AGENT_INTENTS:
            intent = nlq_intent
        elif nlq_intent == "status":
            intent = "status"

        # ── STATUS intent → Sovereign Dashboard ──
        if intent == "status" and self._sovereign_dashboard is not None:
            try:
                snapshot = self._sovereign_dashboard.get_snapshot()
                snap_dict = snapshot.to_dict()
                # Build human-readable summary.
                lines = [
                    f"aeOS Dashboard (compound score: {snap_dict['compound_score']}, "
                    f"trend: {snap_dict['compound_trend']})",
                    f"Decisions this week: {snap_dict['decisions_this_week']}",
                    f"Outcomes this week: {snap_dict['outcomes_this_week']}",
                    f"Consistency: {snap_dict['consistency_score']}%",
                    f"Health: {snap_dict['system_health'].get('status', 'unknown')} "
                    f"(score: {snap_dict['system_health'].get('health_score', 0)})",
                    f"Reflection due: {snap_dict['reflection_due']}",
                ]
                if snap_dict["active_alerts"]:
                    lines.append(f"Active alerts: {len(snap_dict['active_alerts'])}")
                if snap_dict["blind_spots"]:
                    lines.append(f"Blind spots: {', '.join(snap_dict['blind_spots'][:3])}")
                if snap_dict["top_cartridges_firing"]:
                    lines.append(f"Top cartridges: {', '.join(snap_dict['top_cartridges_firing'][:5])}")

                pipeline_steps.append("dashboard_snapshot")
                latency_ms = int((time.perf_counter() - started) * 1000)
                result = {
                    "response": "\n".join(lines),
                    "agent_used": "sovereign_dashboard",
                    "intent": "status",
                    "latency_ms": latency_ms,
                    "success": True,
                    "response_source": "sovereign_dashboard",
                    "domain": "system",
                    "signals_used": signals_used,
                    "pipeline_steps": pipeline_steps,
                    "snapshot": snap_dict,
                }
                self._step_audit_log(q, result)
                return result
            except Exception as exc:
                _LOG.warning("Dashboard snapshot failed: %s", exc)
                pipeline_steps.append("dashboard_failed")

        # ── Agent-specific intents → legacy dispatch ──
        if intent in _AGENT_INTENTS:
            dispatch = self._legacy_agent_dispatch(q, intent, suggested)
            out = dispatch["out"]
            agent_used = dispatch["agent_used"]
            intent = dispatch["intent"]

            latency_ms = int((time.perf_counter() - started) * 1000)
            resp = out.get("response") if isinstance(out, dict) else str(out)
            success = bool(out.get("success", True)) if isinstance(out, dict) else True

            # If agent failed, try fallback routing.
            if not success:
                routed = self._fallback_route(q)
                resp = routed.get("response") or resp or ""
                success = bool(routed.get("success", False))
                agent_used = str(routed.get("suggested_agent") or "ai_router_fallback")
                intent = str(routed.get("intent") or intent)

            pipeline_steps.append(f"agent:{agent_used}")
            result = {
                "response": str(resp or ""),
                "agent_used": agent_used,
                "intent": intent,
                "latency_ms": latency_ms,
                "success": success,
                "response_source": response_source,
                "domain": domain,
                "signals_used": signals_used,
                "pipeline_steps": pipeline_steps,
            }
            self._step_audit_log(q, result)
            return result

        # ── Step 5: Cartridge Loading (Dispatcher + Conductor) ──
        pipeline_steps.append("cartridge_pipeline")
        insights: List[Any] = []
        if self._dispatcher is not None and self._conductor is not None:
            try:
                request = self._dispatcher.dispatch(q)
                insights = self._conductor.conduct(request)
                pipeline_steps.append(f"cartridges_fired:{len(insights)}")
            except Exception as exc:
                _LOG.warning("Cartridge loading failed: %s", exc)

        # ── Step 6: Reasoning (ReasoningSynthesizer) ──
        synthesis = None
        if insights and self._synthesizer is not None:
            try:
                synthesis = self._synthesizer.synthesize(insights)
                pipeline_steps.append("synthesized")
            except Exception as exc:
                _LOG.warning("Reasoning synthesis failed: %s", exc)

        # ── Step 7: Offline Fallback (A3) ──
        if synthesis is None:
            # No synthesis — try offline degraded response.
            if self._offline_mode is not None:
                try:
                    degraded = self._offline_mode.get_degraded_response(q)
                    if degraded is not None:
                        response_source = getattr(degraded, "response_source", "offline_fallback")
                        pipeline_steps.append("offline_fallback")
                        latency_ms = int((time.perf_counter() - started) * 1000)
                        result = {
                            "response": getattr(degraded, "content", str(degraded)),
                            "agent_used": "offline_mode",
                            "intent": intent,
                            "latency_ms": latency_ms,
                            "success": True,
                            "confidence": getattr(degraded, "confidence", 0.0),
                            "response_source": response_source,
                            "domain": domain,
                            "signals_used": signals_used,
                            "pipeline_steps": pipeline_steps,
                        }
                        self._step_audit_log(q, result)
                        return result
                except Exception as exc:
                    _LOG.warning("Offline fallback failed: %s", exc)

            # No offline fallback either — fall back to legacy router.
            pipeline_steps.append("legacy_fallback")
            routed = self._fallback_route(q)
            latency_ms = int((time.perf_counter() - started) * 1000)
            result = {
                "response": str(routed.get("response") or ""),
                "agent_used": str(routed.get("suggested_agent") or "ai_router_fallback"),
                "intent": str(routed.get("intent") or intent),
                "latency_ms": latency_ms,
                "success": bool(routed.get("success", False)),
                "response_source": response_source,
                "domain": domain,
                "signals_used": signals_used,
                "pipeline_steps": pipeline_steps,
            }
            self._step_audit_log(q, result)
            return result

        # ── Step 8: Cartridge Arbitration (A4) ──
        if self._cartridge_arbitrator is not None and len(insights) >= 2:
            try:
                cart_ids = list({getattr(i, "cartridge_id", "") for i in insights})
                recommendations = []
                if _CartridgeRecommendation is not None:
                    now_iso = datetime.now(timezone.utc).isoformat()
                    for i in insights:
                        recommendations.append(_CartridgeRecommendation(
                            cartridge_id=getattr(i, "cartridge_id", ""),
                            cartridge_name=getattr(i, "rule_id", ""),
                            recommendation=getattr(i, "insight_text", ""),
                            confidence=getattr(i, "confidence", 0.0),
                            domain=domain,
                            validated_at=now_iso,
                        ))
                    conflicts = self._cartridge_arbitrator.detect_conflicts(
                        cart_ids, recommendations,
                    )
                    for conflict in conflicts:
                        self._cartridge_arbitrator.arbitrate(conflict)
                    if conflicts:
                        pipeline_steps.append(f"arbitrated:{len(conflicts)}")
            except Exception as exc:
                _LOG.warning("Cartridge arbitration failed: %s", exc)

        # ── Step 9: Contradiction Check (A2) ──
        contradictions: List[Any] = []
        if self._contradiction_detector is not None and synthesis is not None:
            try:
                rec_action = getattr(synthesis, "recommended_action", "")
                if rec_action:
                    decision_dict = {
                        "recommendation": rec_action,
                        "context": q,
                        "confidence": getattr(synthesis, "overall_confidence", 0.0),
                    }
                    cr = self._contradiction_detector.check_decision(
                        decision_dict, domain=domain,
                    )
                    if getattr(cr, "has_contradiction", False):
                        contradictions.append(cr)
                        pipeline_steps.append("contradiction_found")

                    # Also check against Master Laws.
                    law_violations = self._contradiction_detector.check_against_laws(rec_action)
                    if law_violations:
                        contradictions.extend(law_violations)
                        pipeline_steps.append(f"law_violations:{len(law_violations)}")
                pipeline_steps.append("contradiction_checked")
            except Exception as exc:
                _LOG.warning("Contradiction check failed: %s", exc)

        # ── Step 10: 4-Gate Validation ──
        validation = None
        if self._validator is not None and synthesis is not None:
            try:
                validation = self._validator.validate(synthesis, q)
                gate_summary = ",".join(
                    f"{g}:{'ok' if v else 'fail'}"
                    for g, v in (validation.gates or {}).items()
                )
                pipeline_steps.append(f"gates:[{gate_summary}]")
            except Exception as exc:
                _LOG.warning("4-Gate validation failed: %s", exc)

        # ── Step 11: Compose & Deliver ──
        composed = None
        if self._composer is not None and synthesis is not None:
            try:
                if validation is None and _ValidationResult is not None:
                    validation = _ValidationResult(
                        passed=True,
                        gates={"SAFE": True, "TRUE": True, "HIGH-LEVERAGE": True, "ALIGNED": True},
                    )
                if validation is not None:
                    composed = self._composer.compose(synthesis, validation)
                    pipeline_steps.append("composed")
            except Exception as exc:
                _LOG.warning("Output composition failed: %s", exc)

        # ── Build final response ──
        latency_ms = int((time.perf_counter() - started) * 1000)

        if composed is not None:
            resp = getattr(composed, "summary", "")
            primary = getattr(composed, "primary_insight", "")
            if primary:
                resp = f"{resp}\n\n{primary}" if resp else primary
            supporting = getattr(composed, "supporting_points", [])
            if supporting:
                resp += "\n" + "\n".join(f"- {s}" for s in supporting if s)
            rec = getattr(composed, "recommended_action", "")
            if rec:
                resp += f"\n\nRecommended action: {rec}"

            confidence = getattr(composed, "confidence", 0.0)
            gate_status = getattr(composed, "gate_status", {})
        else:
            # Synthesis exists but composition failed — raw fallback.
            resp = getattr(synthesis, "recommended_action", "") if synthesis else ""
            confidence = getattr(synthesis, "overall_confidence", 0.0) if synthesis else 0.0
            gate_status = {}

        result = {
            "response": str(resp or ""),
            "agent_used": "cartridge_pipeline",
            "intent": intent,
            "latency_ms": latency_ms,
            "success": bool(resp),
            "confidence": confidence,
            "response_source": response_source,
            "gate_status": gate_status,
            "domain": domain,
            "signals_used": signals_used,
            "pipeline_steps": pipeline_steps,
        }

        # ── Step 12: Log (A6 Audit Trail) ──
        self._step_audit_log(q, result)

        # ── Step 13: Learn (Flywheel) ──
        self._step_learn(q, result, insights)

        return result

    # ---- Pipeline step helpers ------------------------------------------------

    def _step_audit_log(self, query: str, result: Dict[str, Any]) -> None:
        """Log the query+result via AuditTrail (A6) and publish bus event."""
        if self._audit_trail is not None:
            try:
                self._audit_trail.log_event(
                    event_type="query_processed",
                    module_source="orchestrator",
                    event_data={
                        "query": query[:500],
                        "intent": result.get("intent", ""),
                        "agent_used": result.get("agent_used", ""),
                        "success": result.get("success", False),
                        "latency_ms": result.get("latency_ms", 0),
                        "response_source": result.get("response_source", ""),
                        "pipeline_steps": result.get("pipeline_steps", []),
                    },
                    severity="info",
                )
            except Exception as exc:
                _LOG.warning("Audit log failed: %s", exc)

        # Publish bus event.
        if self._event_bus is not None and _Event is not None:
            try:
                self._event_bus.publish(_Event(
                    topic="query_processed",
                    data={
                        "intent": result.get("intent", ""),
                        "success": result.get("success", False),
                        "agent_used": result.get("agent_used", ""),
                    },
                    source="orchestrator",
                ))
            except Exception:
                pass

    def _step_learn(
        self,
        query: str,
        result: Dict[str, Any],
        insights: List[Any],
    ) -> None:
        """Feed the Flywheel Logger with decision data (Learn step)."""
        if self._flywheel is None:
            return
        try:
            cartridges_fired = list({
                getattr(i, "cartridge_id", "") for i in insights
            }) if insights else []
            self._flywheel.log_decision(
                context=query[:2000],
                cartridges_fired=cartridges_fired,
                reasoning_summary=result.get("response", "")[:1000],
                confidence=result.get("confidence", 0.0) if isinstance(result.get("confidence"), (int, float)) else 0.0,
                domain=result.get("domain", "unknown"),
            )
        except Exception as exc:
            _LOG.warning("Flywheel learn failed: %s", exc)

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

        # Pipeline module status.
        pipeline_modules = {
            "nlq_parser": self._nlq_parser is not None,
            "signal_ingester": self._signal_ingester is not None,
            "offline_mode": self._offline_mode is not None,
            "cartridge_arbitrator": self._cartridge_arbitrator is not None,
            "contradiction_detector": self._contradiction_detector is not None,
            "audit_trail": self._audit_trail is not None,
            "reflection_engine": self._reflection_engine is not None,
            "blind_spot_mapper": self._blind_spot_mapper is not None,
            "sovereign_dashboard": self._sovereign_dashboard is not None,
            "identity_continuity": self._identity_continuity is not None,
        }
        pipeline_ready = all([
            self._dispatcher is not None,
            self._conductor is not None,
            self._synthesizer is not None,
            self._validator is not None,
            self._composer is not None,
        ])

        return {
            "ollama_connected": bool(ollama_connected),
            "agents_loaded": bool(agents_loaded),
            "db_connected": bool(db_connected),
            "kb_connected": bool(kb_connected),
            "version": __version__,
            "pipeline_ready": pipeline_ready,
            "pipeline_modules": pipeline_modules,
            "event_bus_active": self._event_bus is not None,
            "event_bus_topics": self._event_bus.get_topics() if self._event_bus else [],
            "scheduler_active": self._scheduler is not None,
            "scheduler_jobs": len(self._scheduler.list_jobs()) if self._scheduler else 0,
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
