"""
models.py — Shared dataclasses for the aeOS orchestration layer.

All data structures that flow between the five orchestration components live
here so every module can import from a single source of truth.

Stamp: S✅ T✅ L✅ A✅
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class IntentClassification:
    """Output of the dispatcher's intent classifier."""

    domains: List[str]
    complexity: str  # "low", "medium", "high"
    sovereign_need_hint: Optional[str] = None


@dataclass
class OrchestratorRequest:
    """Full request object passed from dispatcher to downstream components."""

    raw_text: str
    intent: IntentClassification
    timestamp: str = ""


@dataclass
class CartridgeInsight:
    """Single insight produced by the cartridge conductor."""

    rule_id: str
    cartridge_id: str
    insight_text: str
    confidence: float
    sovereign_need: str
    tags: List[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Output of the 4-gate output validator."""

    passed: bool
    gates: Dict[str, bool] = field(default_factory=dict)
    failure_reason: Optional[str] = None


@dataclass
class ComposedOutput:
    """Final formatted response delivered to the caller."""

    summary: str
    primary_insight: str
    supporting_points: List[str] = field(default_factory=list)
    tensions_flagged: List[str] = field(default_factory=list)
    blind_spots: List[str] = field(default_factory=list)
    recommended_action: str = ""
    needs_served: List[str] = field(default_factory=list)
    confidence: float = 0.0
    gate_status: Dict[str, bool] = field(default_factory=dict)
