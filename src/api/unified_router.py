"""
aeOS Unified API Router — REST endpoints via AeOSCore.
Phase 4 fills implementations. Skeleton defines full contract.
Framework: FastAPI (or Flask fallback — detected at runtime).
All endpoints route through AeOSCore.query() or AeOSCore module methods.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / Response schemas (framework-agnostic dataclasses)
# ---------------------------------------------------------------------------
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class QueryRequest:
    text: str
    mode: str = "balanced"          # fast | balanced | quality | maximum
    context: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None


@dataclass
class DecisionRequest:
    description: str
    domain: str
    confidence: float
    context: Optional[str] = None
    options: Optional[Dict] = None


@dataclass
class CartridgeRequest:
    cartridge_id: Optional[str] = None
    domain: Optional[str] = None


@dataclass
class APIResponse:
    success: bool
    data: Any
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    version: str = "9.0.0"

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "timestamp": self.timestamp,
            "version": self.version,
        }


# ---------------------------------------------------------------------------
# Route definitions (19 endpoints)
# ---------------------------------------------------------------------------
ROUTE_DEFINITIONS = [
    # Core intelligence
    {"method": "POST", "path": "/api/v1/query",              "handler": "handle_query",             "description": "Main entry point — routes text through AeOSCore.query()"},
    {"method": "GET",  "path": "/api/v1/status",             "handler": "handle_status",            "description": "AeOSCore health check + module status"},
    {"method": "GET",  "path": "/api/v1/health",             "handler": "handle_health",            "description": "Quick liveness check"},

    # Cartridges
    {"method": "GET",  "path": "/api/v1/cartridges",         "handler": "handle_list_cartridges",   "description": "List all loaded cartridges"},
    {"method": "GET",  "path": "/api/v1/cartridges/{id}",    "handler": "handle_get_cartridge",     "description": "Get single cartridge by ID"},
    {"method": "POST", "path": "/api/v1/cartridges/reload",  "handler": "handle_reload_cartridges", "description": "Hot-reload cartridges from disk"},

    # Decisions / Flywheel
    {"method": "POST", "path": "/api/v1/decisions",          "handler": "handle_log_decision",      "description": "Log a decision to Flywheel"},
    {"method": "GET",  "path": "/api/v1/decisions",          "handler": "handle_list_decisions",    "description": "List flywheel decisions"},
    {"method": "GET",  "path": "/api/v1/decisions/patterns", "handler": "handle_decision_patterns", "description": "Pattern analysis over decision log"},

    # Intelligence
    {"method": "POST", "path": "/api/v1/pain-scan",          "handler": "handle_pain_scan",         "description": "Pain_Score computation on text"},
    {"method": "POST", "path": "/api/v1/causal-inference",   "handler": "handle_causal_inference",  "description": "Causal inference query (needs 30+ decisions)"},
    {"method": "GET",  "path": "/api/v1/flywheel/metrics",   "handler": "handle_flywheel_metrics",  "description": "Compound Intelligence Flywheel stats"},

    # Evolution / Self-learning
    {"method": "GET",  "path": "/api/v1/evolution/proposals","handler": "handle_evolution_proposals","description": "Pending cartridge evolution proposals"},
    {"method": "POST", "path": "/api/v1/evolution/approve",  "handler": "handle_approve_proposal",  "description": "Approve an evolution proposal"},

    # Events
    {"method": "GET",  "path": "/api/v1/events/recent",      "handler": "handle_recent_events",     "description": "Recent EventBus events"},

    # Phase 4B: Integrity layer
    {"method": "GET",  "path": "/api/v1/audit",              "handler": "handle_audit_report",      "description": "Audit trail report"},
    {"method": "POST", "path": "/api/v1/backup",             "handler": "handle_backup",            "description": "Create sovereign backup"},
    {"method": "POST", "path": "/api/v1/restore",            "handler": "handle_restore",           "description": "Restore from backup"},
    {"method": "GET",  "path": "/api/v1/verify",             "handler": "handle_verify_integrity",  "description": "Verify data integrity"},
]


# ---------------------------------------------------------------------------
# Handler implementations
# ---------------------------------------------------------------------------
class UnifiedRouter:
    """
    Framework-agnostic router. Phase 4 mounts this under FastAPI or Flask.
    Each handle_* method returns APIResponse.to_dict().
    """

    def __init__(self, aeos_core=None):
        self._core = aeos_core

    def _require_core(self) -> Optional[Dict]:
        if self._core is None or not self._core._initialized:
            return APIResponse(success=False, error="AeOSCore not initialized", data=None).to_dict()
        return None

    # --- Core intelligence ---

    def handle_query(self, req: QueryRequest) -> Dict:
        err = self._require_core()
        if err:
            return err
        from src.cognitive.aeos_core import QueryMode
        mode = QueryMode(req.mode) if req.mode in QueryMode._value2member_map_ else QueryMode.BALANCED
        response = self._core.query(text=req.text, mode=mode, context=req.context, session_id=req.session_id)
        return APIResponse(success=response.success, data=response.to_dict(), error=response.error).to_dict()

    def handle_status(self) -> Dict:
        err = self._require_core()
        if err:
            return err
        status = self._core.get_status()
        return APIResponse(success=True, data={
            "health_score": status.health_score,
            "cartridges": f"{status.cartridges_loaded}/{status.cartridges_target}",
            "modules_wired": status.modules_wired,
            "modules_missing": status.modules_missing,
            "flywheel_decisions": status.flywheel_decisions,
            "causal_ready": status.causal_ready,
            "twin_ready": status.twin_ready,
            "total_queries": status.total_queries,
            "uptime_seconds": status.uptime_seconds,
        }).to_dict()

    def handle_health(self) -> Dict:
        if self._core:
            return APIResponse(success=True, data=self._core.health_check()).to_dict()
        return APIResponse(success=True, data={"status": "starting", "initialized": False}).to_dict()

    # --- Cartridges ---

    def handle_list_cartridges(self, domain: Optional[str] = None) -> Dict:
        err = self._require_core()
        if err:
            return err
        loader = self._core._cartridge_loader
        if not loader:
            return APIResponse(success=False, error="CartridgeLoader not available", data=None).to_dict()
        all_c = loader.get_all()
        if domain:
            all_c = [c for c in all_c if c.get("domain") == domain]
        return APIResponse(success=True, data={"cartridges": all_c, "count": len(all_c)}).to_dict()

    def handle_get_cartridge(self, cartridge_id: str) -> Dict:
        err = self._require_core()
        if err:
            return err
        loader = self._core._cartridge_loader
        if not loader:
            return APIResponse(success=False, error="CartridgeLoader not available", data=None).to_dict()
        c = loader.get_by_id(cartridge_id)
        if not c:
            return APIResponse(success=False, error=f"Cartridge '{cartridge_id}' not found", data=None).to_dict()
        return APIResponse(success=True, data=c).to_dict()

    def handle_reload_cartridges(self) -> Dict:
        err = self._require_core()
        if err:
            return err
        loader = self._core._cartridge_loader
        if not loader:
            return APIResponse(success=False, error="CartridgeLoader not available", data=None).to_dict()
        count = loader.load_all()
        return APIResponse(success=True, data={"loaded": count}).to_dict()

    # --- Decisions ---

    def handle_log_decision(self, req: DecisionRequest) -> Dict:
        err = self._require_core()
        if err:
            return err
        # Phase 4: wire to FlywheelLogger
        return APIResponse(success=False, error="Not yet implemented — Phase 4", data=None).to_dict()

    def handle_list_decisions(self, limit: int = 20) -> Dict:
        err = self._require_core()
        if err:
            return err
        fl = self._core._flywheel_logger
        if not fl:
            return APIResponse(success=False, error="FlywheelLogger not available", data=None).to_dict()
        # Phase 4: fl.get_recent(limit)
        return APIResponse(success=True, data={"decisions": [], "count": 0, "note": "Phase 4 implements"}).to_dict()

    def handle_decision_patterns(self) -> Dict:
        err = self._require_core()
        if err:
            return err
        pe = self._core._pattern_engine
        if not pe:
            return APIResponse(success=False, error="PatternEngine not available", data=None).to_dict()
        # Phase 4: pe.get_decision_patterns()
        return APIResponse(success=True, data={"patterns": [], "note": "Phase 4 implements"}).to_dict()

    # --- Intelligence ---

    def handle_pain_scan(self, req: QueryRequest) -> Dict:
        err = self._require_core()
        if err:
            return err
        de = self._core._decision_engine
        if not de:
            return APIResponse(success=False, error="DecisionEngine not available", data=None).to_dict()
        score = de.compute_pain_score(req.text, req.context)
        return APIResponse(success=True, data={"pain_score": score, "text": req.text[:100]}).to_dict()

    def handle_causal_inference(self, req: QueryRequest) -> Dict:
        err = self._require_core()
        if err:
            return err
        ce = self._core._causal_engine
        if not ce:
            return APIResponse(success=False, error="CausalEngine not available", data=None).to_dict()
        status = self._core.get_status()
        if not status.causal_ready:
            return APIResponse(
                success=False,
                error=f"CausalEngine needs 30+ decisions. Current: {status.flywheel_decisions}",
                data={"decisions_logged": status.flywheel_decisions, "required": 30},
            ).to_dict()
        result = ce.infer(req.text, req.context)
        return APIResponse(success=True, data=result).to_dict()

    def handle_flywheel_metrics(self) -> Dict:
        err = self._require_core()
        if err:
            return err
        fl = self._core._flywheel_logger
        if not fl:
            return APIResponse(success=False, error="FlywheelLogger not available", data=None).to_dict()
        # Phase 4: fl.get_metrics()
        return APIResponse(success=True, data={"note": "Phase 4 implements full metrics"}).to_dict()

    # --- Evolution ---

    def handle_evolution_proposals(self) -> Dict:
        err = self._require_core()
        if err:
            return err
        ee = self._core._evolution_engine
        if not ee:
            return APIResponse(success=True, data={"proposals": [], "note": "EvolutionEngine not yet wired"}).to_dict()
        # Phase 4: ee.get_pending_proposals()
        return APIResponse(success=True, data={"proposals": [], "note": "Phase 4 implements"}).to_dict()

    def handle_approve_proposal(self, proposal_id: str) -> Dict:
        err = self._require_core()
        if err:
            return err
        # Phase 4: implement approval flow
        return APIResponse(success=False, error="Not yet implemented — Phase 4", data=None).to_dict()

    # --- Events ---

    def handle_recent_events(self, limit: int = 50, topic: Optional[str] = None) -> Dict:
        err = self._require_core()
        if err:
            return err
        eb = self._core._event_bus
        if not eb:
            return APIResponse(success=False, error="EventBus not available", data=None).to_dict()
        events = eb.get_recent_events(limit=limit, topic_filter=topic)
        return APIResponse(success=True, data={"events": events, "count": len(events)}).to_dict()

    # --- Phase 4B: Integrity layer endpoints ---

    def handle_audit_report(self, days: int = 30) -> Dict:
        err = self._require_core()
        if err:
            return err
        at = self._core._audit_trail
        if not at:
            return APIResponse(success=False, error="AuditTrail not available", data=None).to_dict()
        report = at.generate_report(period_days=days)
        return APIResponse(success=True, data=report.to_dict()).to_dict()

    def handle_backup(self, passphrase: Optional[str] = None) -> Dict:
        err = self._require_core()
        if err:
            return err
        icp = self._core._identity_continuity
        if not icp:
            return APIResponse(success=False, error="IdentityContinuityProtocol not available", data=None).to_dict()
        manifest = icp.create_sovereign_backup(passphrase=passphrase)
        return APIResponse(success=True, data=manifest.to_dict()).to_dict()

    def handle_restore(self, backup_path: str, passphrase: Optional[str] = None) -> Dict:
        err = self._require_core()
        if err:
            return err
        icp = self._core._identity_continuity
        if not icp:
            return APIResponse(success=False, error="IdentityContinuityProtocol not available", data=None).to_dict()
        result = icp.restore_from_backup(backup_path, passphrase=passphrase)
        return APIResponse(success=result.success, data={
            "backup_id": result.backup_id,
            "tables_restored": result.tables_restored,
            "decisions_restored": result.decisions_restored,
            "errors": result.errors,
        }, error=result.errors[0] if result.errors and not result.success else None).to_dict()

    def handle_verify_integrity(self) -> Dict:
        err = self._require_core()
        if err:
            return err
        icp = self._core._identity_continuity
        if not icp:
            return APIResponse(success=False, error="IdentityContinuityProtocol not available", data=None).to_dict()
        report = icp.verify_integrity()
        return APIResponse(success=report.healthy, data=report.to_dict()).to_dict()

    def get_route_map(self) -> Dict:
        """Return all route definitions for documentation."""
        return {"routes": ROUTE_DEFINITIONS, "total": len(ROUTE_DEFINITIONS)}
