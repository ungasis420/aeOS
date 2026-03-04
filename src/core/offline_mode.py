"""
aeOS Phase 4 — Offline_Mode (A3)
==================================
Graceful degradation when Claude API or Groq unavailable. Ensures Tier 1
(local) and Tier 2 (analytics) always function.

A sovereign system cannot be fully dependent on external services.

Layer: 4 (AI — resilience layer)
Dependencies: CLAUDE_API_BRIDGE, GROQ_BRIDGE, LOCAL_LLM_BRIDGE,
              SMART_ROUTER, CARTRIDGE_LOADER, CACHE_LAYER

Interface Contract (from Addendum A):
    getStatus()                     -> ConnectivityStatus
    getDegradedResponse(query)      -> DegradedResponse
    getCapabilities()               -> CapabilityMap
    onConnectivityChange(callback)  -> subscription_id

Degradation Tiers (from Addendum B, 6-tier):
    FULL:                All 6 tiers available (Tiers 0-5)
    CLOUD_RESTRICTED:    Tiers 0-3 (internet but no paid APIs)
    LOCAL_ONLY:          Tiers 0-1 (no internet)
    SOVEREIGN_CORE_ONLY: Tier 0 only (no Ollama)
    EMPTY:               None (first-run only)

Response Tagging:
    Every response includes response_source tag so Sovereign always
    knows confidence level.
"""
from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class DegradationLevel:
    """Degradation levels from Addendum B."""
    FULL = "FULL"                         # All 6 tiers available
    CLOUD_RESTRICTED = "CLOUD_RESTRICTED" # Tiers 0-3 only
    LOCAL_ONLY = "LOCAL_ONLY"             # Tiers 0-1 only
    SOVEREIGN_CORE_ONLY = "SOVEREIGN_CORE_ONLY"  # Tier 0 only
    EMPTY = "EMPTY"                       # First-run, no data


TIER_NAMES = {
    0: "sovereign_core",
    1: "local_llm",
    2: "web_enriched",
    3: "full_pipeline",
    4: "free_cloud",
    5: "paid_cloud",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ConnectivityStatus:
    """Current connectivity and tier availability status."""
    level: str                    # DegradationLevel value
    tiers_available: List[int]    # Available tier numbers
    internet_available: bool
    ollama_available: bool
    groq_available: bool
    claude_available: bool
    checked_at: str
    response_source: str          # Best available response source label

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DegradedResponse:
    """Response from the best available offline-capable tier."""
    content: str
    response_source: str          # "sovereign_core" | "local_llm" | etc.
    tier_reached: int
    confidence: float
    offline_capable: bool
    degradation_level: str
    cost_incurred: float = 0.0
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilityMap:
    """What is available in the current connectivity state."""
    kb_search: bool = True        # Always available (Tier 0)
    pattern_recognition: bool = True
    cartridge_reasoning: bool = True
    local_llm: bool = False
    web_search: bool = False
    free_cloud_api: bool = False
    paid_cloud_api: bool = False
    full_synthesis: bool = False
    level: str = DegradationLevel.SOVEREIGN_CORE_ONLY

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# OfflineMode
# ---------------------------------------------------------------------------

class OfflineMode:
    """
    Manages graceful degradation when external services are unavailable.

    Monitors connectivity to Ollama, Groq, and Claude. Tags every response
    with its source tier. Sovereign always knows what level of AI
    contributed to the answer.

    Usage:
        offline = OfflineMode()
        status = offline.get_status()
        if not status.internet_available:
            response = offline.get_degraded_response("What should I focus on?")
    """

    # Connectivity check interval in seconds
    CHECK_INTERVAL = 30.0

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        ollama_url: str = "http://localhost:11434",
        groq_available: bool = False,
        claude_available: bool = False,
    ) -> None:
        if db_path is not None:
            self._db_path = Path(db_path).expanduser().resolve()
        else:
            self._db_path = (
                Path(__file__).resolve().parent.parent.parent / "db" / "aeOS.db"
            )

        self._ollama_url = ollama_url
        self._groq_available = groq_available
        self._claude_available = claude_available
        self._internet_available = False
        self._ollama_available = False

        self._last_check: float = 0.0
        self._subscribers: Dict[str, Callable] = {}
        self._current_level = DegradationLevel.SOVEREIGN_CORE_ONLY
        self._tiers_available: List[int] = [0]

        # Initial check
        self._update_status()

    # ------------------------------------------------------------------
    # Public API: getStatus
    # ------------------------------------------------------------------

    def get_status(self) -> ConnectivityStatus:
        """
        Return current connectivity and tier availability status.

        Performs a fresh check if the last check was more than CHECK_INTERVAL
        seconds ago.

        Returns:
            ConnectivityStatus with current state.
        """
        now = time.monotonic()
        if now - self._last_check > self.CHECK_INTERVAL:
            self._update_status()

        return ConnectivityStatus(
            level=self._current_level,
            tiers_available=list(self._tiers_available),
            internet_available=self._internet_available,
            ollama_available=self._ollama_available,
            groq_available=self._groq_available,
            claude_available=self._claude_available,
            checked_at=datetime.now(timezone.utc).isoformat(),
            response_source=TIER_NAMES.get(
                max(self._tiers_available) if self._tiers_available else 0,
                "sovereign_core",
            ),
        )

    # ------------------------------------------------------------------
    # Public API: getDegradedResponse
    # ------------------------------------------------------------------

    def get_degraded_response(self, query: str) -> DegradedResponse:
        """
        Get the best available response from offline-capable tiers.

        Args:
            query: The user's query.

        Returns:
            DegradedResponse with content and source metadata.
        """
        status = self.get_status()
        best_tier = max(self._tiers_available) if self._tiers_available else 0

        # Tier 0: Sovereign Core (always available)
        if best_tier == 0:
            return DegradedResponse(
                content=(
                    f"[Sovereign Core] Query received: '{query[:100]}'. "
                    "Operating in KB-only mode. Search results from local "
                    "knowledge base and cartridge reasoning are available. "
                    "Connect to Ollama or internet for enhanced responses."
                ),
                response_source="sovereign_core",
                tier_reached=0,
                confidence=0.4,
                offline_capable=True,
                degradation_level=status.level,
                notes="Tier 0 only — KB search + cartridge reasoning",
            )

        # Tier 1: Local LLM
        if best_tier >= 1 and self._ollama_available:
            return DegradedResponse(
                content=(
                    f"[Local LLM] Query: '{query[:100]}'. "
                    "Processing with local AI model. Full reasoning "
                    "available without internet connection."
                ),
                response_source="local_llm",
                tier_reached=1,
                confidence=0.65,
                offline_capable=True,
                degradation_level=status.level,
                notes="Tier 1 — Local Ollama model active",
            )

        # Tier 2+: Web enriched / full pipeline
        source = TIER_NAMES.get(best_tier, "sovereign_core")
        return DegradedResponse(
            content=f"[{source}] Processing query with available resources.",
            response_source=source,
            tier_reached=best_tier,
            confidence=0.5 + (best_tier * 0.08),
            offline_capable=best_tier <= 1,
            degradation_level=status.level,
        )

    # ------------------------------------------------------------------
    # Public API: getCapabilities
    # ------------------------------------------------------------------

    def get_capabilities(self) -> CapabilityMap:
        """
        Return what is available in the current connectivity state.

        Returns:
            CapabilityMap showing available capabilities.
        """
        return CapabilityMap(
            kb_search=True,                           # Always
            pattern_recognition=True,                  # Always
            cartridge_reasoning=True,                  # Always
            local_llm=self._ollama_available,
            web_search=self._internet_available,
            free_cloud_api=self._groq_available,
            paid_cloud_api=self._claude_available,
            full_synthesis=(
                self._ollama_available and self._internet_available
            ),
            level=self._current_level,
        )

    # ------------------------------------------------------------------
    # Public API: onConnectivityChange
    # ------------------------------------------------------------------

    def on_connectivity_change(
        self, callback: Callable[[ConnectivityStatus], None]
    ) -> str:
        """
        Subscribe to connectivity state changes.

        Args:
            callback: Function called with ConnectivityStatus on change.

        Returns:
            Subscription ID for unsubscribing.
        """
        sub_id = str(uuid.uuid4())[:8]
        self._subscribers[sub_id] = callback
        return sub_id

    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a connectivity change subscription."""
        self._subscribers.pop(subscription_id, None)

    # ------------------------------------------------------------------
    # Public API: Manual overrides for testing/configuration
    # ------------------------------------------------------------------

    def set_ollama_available(self, available: bool) -> None:
        """Manually set Ollama availability (for testing/config)."""
        self._ollama_available = available
        self._update_level()

    def set_internet_available(self, available: bool) -> None:
        """Manually set internet availability (for testing/config)."""
        self._internet_available = available
        self._update_level()

    def set_groq_available(self, available: bool) -> None:
        """Manually set Groq availability."""
        self._groq_available = available
        self._update_level()

    def set_claude_available(self, available: bool) -> None:
        """Manually set Claude availability."""
        self._claude_available = available
        self._update_level()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _update_status(self) -> None:
        """Refresh connectivity state by checking services."""
        self._check_ollama()
        self._check_internet()
        self._update_level()
        self._last_check = time.monotonic()

    def _check_ollama(self) -> None:
        """Check if Ollama is running locally."""
        try:
            import urllib.request
            req = urllib.request.Request(
                f"{self._ollama_url}/api/tags",
                method="GET",
            )
            urllib.request.urlopen(req, timeout=2)
            self._ollama_available = True
        except Exception:
            self._ollama_available = False

    def _check_internet(self) -> None:
        """Check basic internet connectivity."""
        try:
            import urllib.request
            urllib.request.urlopen("https://httpbin.org/status/200", timeout=3)
            self._internet_available = True
        except Exception:
            self._internet_available = False

    def _update_level(self) -> None:
        """Update degradation level based on current availability."""
        old_level = self._current_level

        # Build tier list
        tiers = [0]  # Tier 0 always available

        if self._ollama_available:
            tiers.append(1)

        if self._internet_available:
            tiers.append(2)  # Web search
            tiers.append(3)  # Full pipeline (0+1+2 orchestrated)

        if self._groq_available:
            tiers.append(4)

        if self._claude_available:
            tiers.append(5)

        self._tiers_available = sorted(tiers)

        # Determine level
        if self._claude_available:
            self._current_level = DegradationLevel.FULL
        elif self._internet_available:
            self._current_level = DegradationLevel.CLOUD_RESTRICTED
        elif self._ollama_available:
            self._current_level = DegradationLevel.LOCAL_ONLY
        else:
            self._current_level = DegradationLevel.SOVEREIGN_CORE_ONLY

        # Notify subscribers on change
        if old_level != self._current_level:
            self._notify_subscribers()
            self._log_state_change(old_level, self._current_level)

    def _notify_subscribers(self) -> None:
        """Notify all subscribers of connectivity change."""
        status = self.get_status()
        for sub_id, callback in list(self._subscribers.items()):
            try:
                callback(status)
            except Exception as e:
                logger.warning(
                    "Subscriber %s callback failed: %s", sub_id, e
                )

    def _log_state_change(self, old: str, new: str) -> None:
        """Log connectivity state change to database."""
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
            conn.row_factory = sqlite3.Row

            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "Offline_Mode_Log" not in tables:
                conn.close()
                return

            now_iso = datetime.now(timezone.utc).isoformat()
            import json
            conn.execute(
                """INSERT INTO Offline_Mode_Log
                (timestamp, previous_state, new_state, tiers_available, trigger_reason)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    now_iso, old, new,
                    json.dumps(self._tiers_available),
                    "connectivity_check",
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("Failed to log state change: %s", e)


__all__ = [
    "OfflineMode",
    "ConnectivityStatus",
    "DegradedResponse",
    "CapabilityMap",
    "DegradationLevel",
    "TIER_NAMES",
]
