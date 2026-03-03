"""
event_bus.py
aeOS — Cross-cutting EventBus

Lightweight publish/subscribe event bus for cross-module communication.
All A1-A10 modules can publish events and subscribe to events from other modules.

Event topics:
  - query_processed     — fired after Orchestrator.process() completes
  - decision_made       — fired when FlywheelLogger records a decision
  - contradiction_found — fired when ContradictionDetector finds a conflict
  - signal_ingested     — fired when SignalIngester ingests new data
  - signal_expired      — fired when signals are cleaned up
  - reflection_complete — fired when ReflectionEngine finishes a report
  - blind_spot_detected — fired when BlindSpotMapper finds gaps
  - backup_created      — fired when IdentityContinuity creates a backup
  - gate_failed         — fired when 4-Gate validation fails
  - connectivity_change — fired when OfflineMode detects tier change

Stamp: S✅ T✅ L✅ A✅
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """An event published on the bus."""
    topic: str
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


# All known event topics for validation.
KNOWN_TOPICS: Set[str] = {
    "query_processed",
    "decision_made",
    "contradiction_found",
    "signal_ingested",
    "signal_expired",
    "reflection_complete",
    "blind_spot_detected",
    "backup_created",
    "gate_failed",
    "connectivity_change",
    "arbitration_resolved",
    "audit_logged",
}

# Type alias for subscriber callbacks.
Subscriber = Callable[[Event], None]


class EventBus:
    """
    Thread-safe publish/subscribe event bus.

    Usage:
        bus = EventBus()
        sub_id = bus.subscribe("decision_made", my_handler)
        bus.publish(Event(topic="decision_made", data={...}))
        bus.unsubscribe(sub_id)
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, Dict[str, Subscriber]] = {}
        self._lock = threading.Lock()
        self._event_log: List[Event] = []
        self._max_log = 1000

    def subscribe(
        self,
        topic: str,
        callback: Subscriber,
        subscription_id: Optional[str] = None,
    ) -> str:
        """Subscribe to a topic. Returns subscription_id for unsubscribe."""
        sub_id = subscription_id or str(uuid.uuid4())[:12]
        with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = {}
            self._subscribers[topic][sub_id] = callback
        logger.info("EventBus: subscribed %s to topic '%s'", sub_id, topic)
        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription by ID. Returns True if found and removed."""
        with self._lock:
            for topic, subs in self._subscribers.items():
                if subscription_id in subs:
                    del subs[subscription_id]
                    logger.info("EventBus: unsubscribed %s from '%s'", subscription_id, topic)
                    return True
        return False

    def publish(self, event: Event) -> int:
        """
        Publish an event to all subscribers of its topic.

        Returns the number of subscribers notified.
        """
        with self._lock:
            subs = dict(self._subscribers.get(event.topic, {}))
            # Keep event log bounded.
            self._event_log.append(event)
            if len(self._event_log) > self._max_log:
                self._event_log = self._event_log[-self._max_log:]

        notified = 0
        for sub_id, callback in subs.items():
            try:
                callback(event)
                notified += 1
            except Exception as exc:
                logger.warning(
                    "EventBus: subscriber %s failed on topic '%s': %s",
                    sub_id, event.topic, exc,
                )
        return notified

    def get_subscribers(self, topic: str) -> List[str]:
        """Return list of subscription IDs for a topic."""
        with self._lock:
            return list(self._subscribers.get(topic, {}).keys())

    def get_topics(self) -> List[str]:
        """Return all topics that have at least one subscriber."""
        with self._lock:
            return [t for t, subs in self._subscribers.items() if subs]

    def get_event_log(self, topic: Optional[str] = None, limit: int = 50) -> List[Event]:
        """Return recent events, optionally filtered by topic."""
        with self._lock:
            events = list(self._event_log)
        if topic:
            events = [e for e in events if e.topic == topic]
        return events[-limit:]

    def clear(self) -> None:
        """Remove all subscriptions and clear event log."""
        with self._lock:
            self._subscribers.clear()
            self._event_log.clear()


# ---------------------------------------------------------------------------
# Singleton instance — modules import this to share a single bus.
# ---------------------------------------------------------------------------

_bus: Optional[EventBus] = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Return the singleton EventBus instance."""
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = EventBus()
    return _bus
