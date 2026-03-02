"""
AeOSCore — Central wiring class for aeOS COGNITIVE_CORE.
Phase 4 fills in the implementations. This file defines the interface contract.
Single entry point: AeOSCore.query() routes all intelligence requests.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
class QueryMode(str, Enum):
    FAST = "fast"           # Single cartridge, minimal synthesis
    BALANCED = "balanced"   # 3-5 cartridges, standard synthesis
    QUALITY = "quality"     # All relevant cartridges, full 8-consciousness pass
    MAXIMUM = "maximum"     # Quality + causal inference + twin simulation


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"           # Gate not applicable for this query type


@dataclass
class FourGateResult:
    """4-Gate validation result (Blueprint v9.0 F0.1)."""
    gate_1_safe: GateStatus = GateStatus.SKIP
    gate_2_true: GateStatus = GateStatus.SKIP
    gate_3_leverage: GateStatus = GateStatus.SKIP
    gate_4_aligned: GateStatus = GateStatus.SKIP
    notes: List[str] = field(default_factory=list)

    @property
    def all_pass(self) -> bool:
        return all(
            g in (GateStatus.PASS, GateStatus.SKIP)
            for g in [self.gate_1_safe, self.gate_2_true, self.gate_3_leverage, self.gate_4_aligned]
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_1_safe": self.gate_1_safe.value,
            "gate_2_true": self.gate_2_true.value,
            "gate_3_leverage": self.gate_3_leverage.value,
            "gate_4_aligned": self.gate_4_aligned.value,
            "all_pass": self.all_pass,
            "notes": self.notes,
        }


@dataclass
class ConsciousnessOutput:
    """Output from one of the 8 consciousnesses."""
    consciousness_id: str   # C1–C8
    name: str               # e.g. "The Economist"
    notes: str
    confidence: float       # 0.0–1.0
    relevant_cartridges: List[str] = field(default_factory=list)


@dataclass
class QueryResponse:
    """Full response from AeOSCore.query()."""
    query_id: str
    query: str
    mode: QueryMode
    synthesis: str                          # Final synthesized answer
    consciousness_outputs: List[ConsciousnessOutput] = field(default_factory=list)
    cartridges_used: List[str] = field(default_factory=list)
    four_gate: FourGateResult = field(default_factory=FourGateResult)
    pain_score: Optional[float] = None
    qbest_moves_score: Optional[float] = None
    causal_inference: Optional[Dict] = None     # Populated when mode=MAXIMUM
    twin_simulation: Optional[Dict] = None      # Populated when mode=MAXIMUM
    adversarial_flags: List[str] = field(default_factory=list)
    flywheel_logged: bool = False
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and self.four_gate.all_pass

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_id": self.query_id,
            "query": self.query,
            "mode": self.mode.value,
            "synthesis": self.synthesis,
            "cartridges_used": self.cartridges_used,
            "four_gate": self.four_gate.to_dict(),
            "pain_score": self.pain_score,
            "qbest_moves_score": self.qbest_moves_score,
            "flywheel_logged": self.flywheel_logged,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "error": self.error,
        }


@dataclass
class CoreStatus:
    """Health status of AeOSCore and all wired modules."""
    initialized: bool
    cartridges_loaded: int
    cartridges_target: int
    modules_wired: List[str]
    modules_missing: List[str]
    flywheel_decisions: int
    causal_ready: bool          # True when 30+ decisions logged
    twin_ready: bool            # True when 3+ months data
    four_gate_active: bool
    event_bus_active: bool
    last_query_at: Optional[datetime]
    uptime_seconds: float
    total_queries: int
    errors_total: int

    @property
    def health_score(self) -> float:
        """0.0–1.0 health score."""
        if not self.initialized:
            return 0.0
        score = 0.0
        score += 0.3 * min(1.0, self.cartridges_loaded / max(self.cartridges_target, 1))
        score += 0.2 if self.four_gate_active else 0.0
        score += 0.2 if self.event_bus_active else 0.0
        score += 0.15 if self.causal_ready else 0.05
        score += 0.15 if self.twin_ready else 0.05
        return round(score, 3)


# ---------------------------------------------------------------------------
# AeOSCore
# ---------------------------------------------------------------------------
class AeOSCore:
    """
    Central intelligence hub. Wires all Phase 3 engines together.
    Single public entry point: query().
    Wires:
    - CartridgeLoader (21→45 cartridges)
    - 8 Consciousnesses (C1–C8)
    - DecisionEngine
    - MLEngine
    - PatternRecognitionEngine
    - AdaptiveThresholdEngine
    - ProactiveAlertEngine
    - FlywheelLogger
    - CausalInferenceEngine
    - CognitiveTwin (stub)
    - AdversarialFirewall
    - CartridgeEvolutionEngine
    - ClaudeAPIBridge
    - EventBus
    - KBCognitiveBridge
    """

    VERSION = "9.0.0"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        self._initialized = False
        self._start_time = datetime.utcnow()
        self._total_queries = 0
        self._errors_total = 0
        self._last_query_at: Optional[datetime] = None

        # Module references (set during initialize())
        self._cartridge_loader = None
        self._decision_engine = None
        self._ml_engine = None
        self._pattern_engine = None
        self._adaptive_threshold = None
        self._proactive_alert = None
        self._flywheel_logger = None
        self._causal_engine = None
        self._cognitive_twin = None
        self._adversarial_firewall = None
        self._evolution_engine = None
        self._claude_bridge = None
        self._event_bus = None
        self._kb_bridge = None

        # Phase 4B modules
        self._contradiction_detector = None
        self._cartridge_arbitrator = None
        self._offline_mode = None
        self._nlq_parser = None
        self._audit_trail = None
        self._identity_continuity = None

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------
    def initialize(self) -> bool:
        """
        Wire all modules. Returns True if core is operational.
        Partial initialization is allowed — missing modules degrade gracefully.
        """
        logger.info(f"AeOSCore v{self.VERSION} initializing...")
        errors = []

        # EventBus first — everything publishes to it
        try:
            from src.core.event_bus import get_event_bus
            self._event_bus = get_event_bus()
            logger.info("  ✓ EventBus")
        except Exception as e:
            errors.append(f"EventBus: {e}")
            logger.warning(f"  ✗ EventBus: {e}")

        # Cartridge loader
        try:
            from src.cognitive.cartridge_loader import CartridgeLoader
            self._cartridge_loader = CartridgeLoader(self._config.get("cartridge_dir", "src/cartridges"))
            self._cartridge_loader.load_all()
            count = len(self._cartridge_loader.get_all())
            logger.info(f"  ✓ CartridgeLoader ({count} cartridges)")
        except Exception as e:
            errors.append(f"CartridgeLoader: {e}")
            logger.warning(f"  ✗ CartridgeLoader: {e}")

        # Decision engine
        try:
            from src.cognitive.decision_engine import DecisionEngine
            self._decision_engine = DecisionEngine()
            logger.info("  ✓ DecisionEngine")
        except Exception as e:
            errors.append(f"DecisionEngine: {e}")
            logger.warning(f"  ✗ DecisionEngine: {e}")

        # ML engine
        try:
            from src.cognitive.ml_engine import MLEngine
            self._ml_engine = MLEngine()
            logger.info("  ✓ MLEngine")
        except Exception as e:
            errors.append(f"MLEngine: {e}")
            logger.warning(f"  ✗ MLEngine: {e}")

        # Pattern recognition
        try:
            from src.cognitive.pattern_recognition_engine import PatternRecognitionEngine
            self._pattern_engine = PatternRecognitionEngine()
            logger.info("  ✓ PatternRecognitionEngine")
        except Exception as e:
            errors.append(f"PatternEngine: {e}")
            logger.warning(f"  ✗ PatternEngine: {e}")

        # Adaptive threshold
        try:
            from src.cognitive.adaptive_threshold_engine import AdaptiveThresholdEngine
            self._adaptive_threshold = AdaptiveThresholdEngine()
            logger.info("  ✓ AdaptiveThresholdEngine")
        except Exception as e:
            errors.append(f"AdaptiveThreshold: {e}")
            logger.warning(f"  ✗ AdaptiveThreshold: {e}")

        # Proactive alert
        try:
            from src.cognitive.proactive_alert_engine import ProactiveAlertEngine
            self._proactive_alert = ProactiveAlertEngine()
            logger.info("  ✓ ProactiveAlertEngine")
        except Exception as e:
            errors.append(f"ProactiveAlert: {e}")
            logger.warning(f"  ✗ ProactiveAlert: {e}")

        # FlywheelLogger (v9.0)
        try:
            from src.cognitive.flywheel_logger import FlywheelLogger
            self._flywheel_logger = FlywheelLogger()
            logger.info("  ✓ FlywheelLogger")
        except Exception as e:
            errors.append(f"FlywheelLogger: {e}")
            logger.warning(f"  ✗ FlywheelLogger: {e}")

        # CausalInferenceEngine (v9.0 stub)
        try:
            from src.cognitive.causal_inference_engine import CausalInferenceEngine
            self._causal_engine = CausalInferenceEngine()
            logger.info("  ✓ CausalInferenceEngine (stub)")
        except Exception as e:
            errors.append(f"CausalEngine: {e}")
            logger.warning(f"  ✗ CausalEngine: {e}")

        # CognitiveTwin (v9.0 stub)
        try:
            from src.cognitive.cognitive_twin import CognitiveTwin
            self._cognitive_twin = CognitiveTwin()
            logger.info("  ✓ CognitiveTwin (stub)")
        except Exception as e:
            logger.debug(f"  - CognitiveTwin not yet available: {e}")

        # AdversarialFirewall (v9.0 stub)
        try:
            from src.cognitive.adversarial_firewall import AdversarialFirewall
            self._adversarial_firewall = AdversarialFirewall()
            logger.info("  ✓ AdversarialFirewall (stub)")
        except Exception as e:
            logger.debug(f"  - AdversarialFirewall not yet available: {e}")

        # CartridgeEvolutionEngine (v9.0 stub)
        try:
            from src.cognitive.cartridge_evolution_engine import CartridgeEvolutionEngine
            self._evolution_engine = CartridgeEvolutionEngine()
            logger.info("  ✓ CartridgeEvolutionEngine (stub)")
        except Exception as e:
            logger.debug(f"  - CartridgeEvolutionEngine not yet available: {e}")

        # Claude API Bridge
        try:
            from src.api.claude_api_bridge import ClaudeAPIBridge
            self._claude_bridge = ClaudeAPIBridge()
            logger.info("  ✓ ClaudeAPIBridge")
        except Exception as e:
            errors.append(f"ClaudeAPIBridge: {e}")
            logger.warning(f"  ✗ ClaudeAPIBridge: {e}")

        # KB<->Cognitive Bridge
        try:
            from src.kb.cognitive_bridge import KBCognitiveBridge
            self._kb_bridge = KBCognitiveBridge(aeos_core=self)
            logger.info("  ✓ KBCognitiveBridge")
        except Exception as e:
            logger.debug(f"  - KBCognitiveBridge not yet available: {e}")

        # Phase 4B: ContradictionDetector
        try:
            from src.cognitive.contradiction_detector import ContradictionDetector
            self._contradiction_detector = ContradictionDetector(flywheel_logger=self._flywheel_logger)
            logger.info("  ✓ ContradictionDetector")
        except Exception as e:
            logger.debug(f"  - ContradictionDetector not yet available: {e}")

        # Phase 4B: CartridgeArbitrator
        try:
            from src.cognitive.cartridge_arbitrator import CartridgeArbitrator
            self._cartridge_arbitrator = CartridgeArbitrator(contradiction_detector=self._contradiction_detector)
            logger.info("  ✓ CartridgeArbitrator")
        except Exception as e:
            logger.debug(f"  - CartridgeArbitrator not yet available: {e}")

        # Phase 4B: OfflineMode
        try:
            from src.core.offline_mode import OfflineMode
            self._offline_mode = OfflineMode()
            logger.info("  ✓ OfflineMode")
        except Exception as e:
            logger.debug(f"  - OfflineMode not yet available: {e}")

        # Phase 4B: NLQParser
        try:
            from src.core.nlq_parser import NLQParser
            self._nlq_parser = NLQParser()
            logger.info("  ✓ NLQParser")
        except Exception as e:
            logger.debug(f"  - NLQParser not yet available: {e}")

        # Phase 4B: AuditTrail
        try:
            from src.core.audit_trail import AuditTrail
            self._audit_trail = AuditTrail(
                flywheel_logger=self._flywheel_logger,
                event_bus=self._event_bus,
                contradiction_detector=self._contradiction_detector,
                cartridge_arbitrator=self._cartridge_arbitrator,
                offline_mode=self._offline_mode,
            )
            logger.info("  ✓ AuditTrail")
        except Exception as e:
            logger.debug(f"  - AuditTrail not yet available: {e}")

        # Phase 4B: IdentityContinuityProtocol
        try:
            from src.core.identity_continuity import IdentityContinuityProtocol
            self._identity_continuity = IdentityContinuityProtocol(
                flywheel_logger=self._flywheel_logger,
            )
            logger.info("  ✓ IdentityContinuityProtocol")
        except Exception as e:
            logger.debug(f"  - IdentityContinuityProtocol not yet available: {e}")

        self._initialized = True
        status = self.get_status()
        logger.info(
            f"AeOSCore initialized. Health: {status.health_score:.0%}. "
            f"Errors: {len(errors)}. Cartridges: {status.cartridges_loaded}/{status.cartridges_target}"
        )

        return len(errors) == 0

    def shutdown(self) -> None:
        """Graceful shutdown."""
        logger.info("AeOSCore shutting down...")
        if self._event_bus:
            self._event_bus.emit("system.shutdown", {}, source="aeos_core")
        self._initialized = False

    # -------------------------------------------------------------------------
    # Core Query Interface
    # -------------------------------------------------------------------------
    def query(
        self,
        text: str,
        mode: QueryMode = QueryMode.BALANCED,
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> QueryResponse:
        """
        Main entry point. Routes query through full intelligence pipeline.
        Pipeline:
        1. Adversarial scan (gate 1 safety)
        2. Pain scan (Phase 0)
        3. Cartridge selection (relevant domains)
        3.5. Contradiction check (Phase 4B)
        3.8. Cartridge arbitration (Phase 4B)
        4. 8-consciousness pass
        5. Synthesis
        6. 4-Gate validation
        7. Flywheel logging
        8. EventBus publish
        """
        import uuid, time

        query_id = str(uuid.uuid4())
        start = time.time()
        self._total_queries += 1
        self._last_query_at = datetime.utcnow()

        if not self._initialized:
            return QueryResponse(
                query_id=query_id,
                query=text,
                mode=mode,
                synthesis="",
                error="AeOSCore not initialized. Call initialize() first.",
            )

        try:
            response = self._run_pipeline(query_id, text, mode, context or {}, session_id)
            response.duration_ms = (time.time() - start) * 1000

            if self._event_bus:
                self._event_bus.emit(
                    "query.completed",
                    {"query_id": query_id, "success": response.success, "mode": mode.value},
                    source="aeos_core",
                )
            return response

        except Exception as e:
            self._errors_total += 1
            logger.error(f"AeOSCore.query() error: {e}", exc_info=True)
            if self._event_bus:
                self._event_bus.emit("system.error", {"query_id": query_id, "error": str(e)}, source="aeos_core")
            return QueryResponse(
                query_id=query_id,
                query=text,
                mode=mode,
                synthesis="",
                duration_ms=(time.time() - start) * 1000,
                error=str(e),
            )

    def _run_pipeline(
        self,
        query_id: str,
        text: str,
        mode: QueryMode,
        context: Dict,
        session_id: Optional[str],
    ) -> QueryResponse:
        """Internal pipeline. Phase 4 implements each step fully."""
        response = QueryResponse(query_id=query_id, query=text, mode=mode, synthesis="")

        # Step 1: Adversarial scan
        if self._adversarial_firewall:
            flags = self._adversarial_firewall.scan(text)
            response.adversarial_flags = flags
            if flags:
                response.four_gate.gate_1_safe = GateStatus.FAIL
                response.four_gate.notes.append(f"Adversarial flags: {flags}")
                response.synthesis = "[Query blocked by adversarial firewall]"
                return response
        response.four_gate.gate_1_safe = GateStatus.PASS

        # Step 2: Select cartridges
        cartridges = []
        if self._cartridge_loader:
            cartridges = self._cartridge_loader.select_relevant(text, mode=mode.value)
            response.cartridges_used = [c.get("cartridge_id", "") for c in cartridges]

        # Step 3.5: Contradiction check (Phase 4B)
        if self._contradiction_detector:
            contradiction = self._contradiction_detector.check_decision(text, "general", context)
            if contradiction.severity in ("critical", "high"):
                response.adversarial_flags.append(f"Contradiction: {contradiction.explanation}")

        # Step 3.8: Cartridge arbitration (Phase 4B)
        if self._cartridge_arbitrator and cartridges:
            cartridges, arbitrations = self._cartridge_arbitrator.arbitrate_all(
                [c.get("cartridge_id") for c in cartridges],
                cartridges
            )

        # Step 3: Route to Claude API Bridge (primary synthesis)
        if self._claude_bridge:
            synthesis = self._claude_bridge.synthesize(
                query=text,
                cartridges=cartridges,
                mode=mode.value,
                context=context,
            )
            response.synthesis = synthesis
            response.four_gate.gate_2_true = GateStatus.PASS
        else:
            # Fallback: local synthesis stub
            response.synthesis = f"[Local synthesis — cartridges: {len(cartridges)}] Query received: {text[:100]}"
            response.four_gate.gate_2_true = GateStatus.PASS

        # Step 4: Pain scan
        if self._decision_engine:
            pain = self._decision_engine.compute_pain_score(text, context)
            response.pain_score = pain

        # Step 5: 4-Gate leverage check
        response.four_gate.gate_3_leverage = GateStatus.PASS  # Phase 4 implements ROI filter
        response.four_gate.gate_4_aligned = GateStatus.PASS   # Phase 4 implements G1 check

        # Step 6: Causal inference (MAXIMUM mode only)
        if mode == QueryMode.MAXIMUM and self._causal_engine:
            causal = self._causal_engine.infer(text, context)
            response.causal_inference = causal

        # Step 7: Twin simulation (MAXIMUM mode only, when ready)
        if mode == QueryMode.MAXIMUM and self._cognitive_twin:
            twin = self._cognitive_twin.simulate(text, context)
            response.twin_simulation = twin

        # Step 8: Flywheel log
        if self._flywheel_logger:
            self._flywheel_logger.log_query(query_id, text, response.to_dict())
            response.flywheel_logged = True

        return response

    # -------------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------------
    def get_status(self) -> CoreStatus:
        import time as _time

        cartridges_loaded = 0
        if self._cartridge_loader:
            try:
                cartridges_loaded = len(self._cartridge_loader.get_all())
            except Exception:
                pass

        flywheel_decisions = 0
        if self._flywheel_logger:
            try:
                flywheel_decisions = self._flywheel_logger.count()
            except Exception:
                pass

        modules_wired = []
        modules_missing = []
        module_map = {
            "CartridgeLoader": self._cartridge_loader,
            "DecisionEngine": self._decision_engine,
            "MLEngine": self._ml_engine,
            "PatternEngine": self._pattern_engine,
            "AdaptiveThreshold": self._adaptive_threshold,
            "ProactiveAlert": self._proactive_alert,
            "FlywheelLogger": self._flywheel_logger,
            "CausalEngine": self._causal_engine,
            "ClaudeAPIBridge": self._claude_bridge,
            "EventBus": self._event_bus,
            "CognitiveTwin": self._cognitive_twin,
            "AdversarialFirewall": self._adversarial_firewall,
            "EvolutionEngine": self._evolution_engine,
            "KBBridge": self._kb_bridge,
            "ContradictionDetector": self._contradiction_detector,
            "CartridgeArbitrator": self._cartridge_arbitrator,
            "OfflineMode": self._offline_mode,
            "NLQParser": self._nlq_parser,
            "AuditTrail": self._audit_trail,
            "IdentityContinuity": self._identity_continuity,
        }
        for name, mod in module_map.items():
            (modules_wired if mod is not None else modules_missing).append(name)

        uptime = (_time.time() - self._start_time.timestamp()) if self._initialized else 0.0

        return CoreStatus(
            initialized=self._initialized,
            cartridges_loaded=cartridges_loaded,
            cartridges_target=45,
            modules_wired=modules_wired,
            modules_missing=modules_missing,
            flywheel_decisions=flywheel_decisions,
            causal_ready=flywheel_decisions >= 30,
            twin_ready=False,  # Phase 4: check months of data
            four_gate_active=True,
            event_bus_active=self._event_bus is not None,
            last_query_at=self._last_query_at,
            uptime_seconds=uptime,
            total_queries=self._total_queries,
            errors_total=self._errors_total,
        )

    def health_check(self) -> Dict[str, Any]:
        """Quick health dict for API endpoint."""
        s = self.get_status()
        return {
            "status": "healthy" if s.health_score > 0.7 else "degraded" if s.health_score > 0.3 else "critical",
            "health_score": s.health_score,
            "initialized": s.initialized,
            "cartridges": f"{s.cartridges_loaded}/{s.cartridges_target}",
            "modules_wired": len(s.modules_wired),
            "modules_missing": s.modules_missing,
            "causal_ready": s.causal_ready,
            "twin_ready": s.twin_ready,
            "total_queries": s.total_queries,
            "version": self.VERSION,
        }
