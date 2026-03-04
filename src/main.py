"""
aeOS FastAPI entry point.
Run: uvicorn src.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, Query, Path, Body
from pydantic import BaseModel, Field

from src.cognitive.aeos_core import AeOSCore
from src.api.unified_router import (
    UnifiedRouter,
    QueryRequest,
    DecisionRequest,
    ROUTE_DEFINITIONS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic request models (mirror unified_router dataclasses for FastAPI)
# ---------------------------------------------------------------------------


class QueryBody(BaseModel):
    text: str
    mode: str = "balanced"
    context: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None


class DecisionBody(BaseModel):
    description: str
    domain: str
    confidence: float
    context: Optional[str] = None
    options: Optional[Dict[str, Any]] = None


class ApproveProposalBody(BaseModel):
    proposal_id: str


class BackupBody(BaseModel):
    passphrase: Optional[str] = None


class RestoreBody(BaseModel):
    backup_path: str
    passphrase: Optional[str] = None


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
core = AeOSCore()
router = UnifiedRouter(aeos_core=core)


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("aeOS starting up …")
    core.initialize()
    yield
    logger.info("aeOS shutting down …")
    core.shutdown()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="aeOS",
    description="aeOS Cognitive Operating System API",
    version=AeOSCore.VERSION,
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Root endpoint
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    """Root endpoint — returns aeOS version and status."""
    health = core.health_check() if core._initialized else {
        "status": "starting",
        "initialized": False,
    }
    return {
        "name": "aeOS",
        "version": AeOSCore.VERSION,
        **health,
    }


# ---------------------------------------------------------------------------
# 19 API routes wired to UnifiedRouter handlers
# ---------------------------------------------------------------------------

# 1. POST /api/v1/query
@app.post("/api/v1/query")
def api_query(body: QueryBody):
    return router.handle_query(QueryRequest(
        text=body.text,
        mode=body.mode,
        context=body.context,
        session_id=body.session_id,
    ))


# 2. GET /api/v1/status
@app.get("/api/v1/status")
def api_status():
    return router.handle_status()


# 3. GET /api/v1/health
@app.get("/api/v1/health")
def api_health():
    return router.handle_health()


# 4. GET /api/v1/cartridges
@app.get("/api/v1/cartridges")
def api_list_cartridges(domain: Optional[str] = Query(None)):
    return router.handle_list_cartridges(domain=domain)


# 5. GET /api/v1/cartridges/{id}
@app.get("/api/v1/cartridges/{cartridge_id}")
def api_get_cartridge(cartridge_id: str = Path(...)):
    return router.handle_get_cartridge(cartridge_id)


# 6. POST /api/v1/cartridges/reload
@app.post("/api/v1/cartridges/reload")
def api_reload_cartridges():
    return router.handle_reload_cartridges()


# 7. POST /api/v1/decisions
@app.post("/api/v1/decisions")
def api_log_decision(body: DecisionBody):
    return router.handle_log_decision(DecisionRequest(
        description=body.description,
        domain=body.domain,
        confidence=body.confidence,
        context=body.context,
        options=body.options,
    ))


# 8. GET /api/v1/decisions
@app.get("/api/v1/decisions")
def api_list_decisions(limit: int = Query(20, ge=1, le=500)):
    return router.handle_list_decisions(limit=limit)


# 9. GET /api/v1/decisions/patterns
@app.get("/api/v1/decisions/patterns")
def api_decision_patterns():
    return router.handle_decision_patterns()


# 10. POST /api/v1/pain-scan
@app.post("/api/v1/pain-scan")
def api_pain_scan(body: QueryBody):
    return router.handle_pain_scan(QueryRequest(
        text=body.text,
        mode=body.mode,
        context=body.context,
        session_id=body.session_id,
    ))


# 11. POST /api/v1/causal-inference
@app.post("/api/v1/causal-inference")
def api_causal_inference(body: QueryBody):
    return router.handle_causal_inference(QueryRequest(
        text=body.text,
        mode=body.mode,
        context=body.context,
        session_id=body.session_id,
    ))


# 12. GET /api/v1/flywheel/metrics
@app.get("/api/v1/flywheel/metrics")
def api_flywheel_metrics():
    return router.handle_flywheel_metrics()


# 13. GET /api/v1/evolution/proposals
@app.get("/api/v1/evolution/proposals")
def api_evolution_proposals():
    return router.handle_evolution_proposals()


# 14. POST /api/v1/evolution/approve
@app.post("/api/v1/evolution/approve")
def api_approve_proposal(body: ApproveProposalBody):
    return router.handle_approve_proposal(body.proposal_id)


# 15. GET /api/v1/events/recent
@app.get("/api/v1/events/recent")
def api_recent_events(
    limit: int = Query(50, ge=1, le=1000),
    topic: Optional[str] = Query(None),
):
    return router.handle_recent_events(limit=limit, topic=topic)


# 16. GET /api/v1/audit
@app.get("/api/v1/audit")
def api_audit_report(days: int = Query(30, ge=1, le=365)):
    return router.handle_audit_report(days=days)


# 17. POST /api/v1/backup
@app.post("/api/v1/backup")
def api_backup(body: BackupBody = Body(BackupBody())):
    return router.handle_backup(passphrase=body.passphrase)


# 18. POST /api/v1/restore
@app.post("/api/v1/restore")
def api_restore(body: RestoreBody):
    return router.handle_restore(
        backup_path=body.backup_path,
        passphrase=body.passphrase,
    )


# 19. GET /api/v1/verify
@app.get("/api/v1/verify")
def api_verify_integrity():
    return router.handle_verify_integrity()
