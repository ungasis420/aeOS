"""
tests/test_event_bus.py

Unit tests for the EventBus pub/sub system.

Stamp: S✅ T✅ L✅ A✅
"""

from __future__ import annotations

import os
import sys
import threading
import time

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.core.event_bus import Event, EventBus, KNOWN_TOPICS, get_event_bus


class TestEvent:
    def test_event_has_defaults(self):
        e = Event(topic="test")
        assert e.topic == "test"
        assert isinstance(e.data, dict)
        assert e.source == ""
        assert e.timestamp
        assert e.event_id

    def test_event_custom_data(self):
        e = Event(topic="decision_made", data={"id": "123"}, source="orchestrator")
        assert e.data["id"] == "123"
        assert e.source == "orchestrator"


class TestEventBus:
    def test_subscribe_returns_id(self):
        bus = EventBus()
        sid = bus.subscribe("test_topic", lambda e: None)
        assert isinstance(sid, str)
        assert len(sid) > 0

    def test_subscribe_custom_id(self):
        bus = EventBus()
        sid = bus.subscribe("test_topic", lambda e: None, subscription_id="my_sub")
        assert sid == "my_sub"

    def test_publish_notifies_subscriber(self):
        bus = EventBus()
        received = []
        bus.subscribe("test_topic", lambda e: received.append(e))
        count = bus.publish(Event(topic="test_topic", data={"msg": "hello"}))
        assert count == 1
        assert len(received) == 1
        assert received[0].data["msg"] == "hello"

    def test_publish_returns_subscriber_count(self):
        bus = EventBus()
        bus.subscribe("t", lambda e: None)
        bus.subscribe("t", lambda e: None)
        bus.subscribe("other", lambda e: None)
        assert bus.publish(Event(topic="t")) == 2
        assert bus.publish(Event(topic="other")) == 1

    def test_publish_no_subscribers_returns_zero(self):
        bus = EventBus()
        assert bus.publish(Event(topic="nobody_listens")) == 0

    def test_unsubscribe_removes_subscriber(self):
        bus = EventBus()
        received = []
        sid = bus.subscribe("t", lambda e: received.append(e))
        bus.publish(Event(topic="t"))
        assert len(received) == 1
        assert bus.unsubscribe(sid) is True
        bus.publish(Event(topic="t"))
        assert len(received) == 1  # no new events

    def test_unsubscribe_nonexistent_returns_false(self):
        bus = EventBus()
        assert bus.unsubscribe("nonexistent") is False

    def test_multiple_topics_isolated(self):
        bus = EventBus()
        a_events = []
        b_events = []
        bus.subscribe("topic_a", lambda e: a_events.append(e))
        bus.subscribe("topic_b", lambda e: b_events.append(e))
        bus.publish(Event(topic="topic_a"))
        bus.publish(Event(topic="topic_b"))
        bus.publish(Event(topic="topic_a"))
        assert len(a_events) == 2
        assert len(b_events) == 1

    def test_subscriber_error_does_not_crash_bus(self):
        bus = EventBus()
        good_events = []

        def bad_handler(e):
            raise RuntimeError("boom")

        bus.subscribe("t", bad_handler)
        bus.subscribe("t", lambda e: good_events.append(e))
        count = bus.publish(Event(topic="t"))
        # Bad handler fails, good handler succeeds.
        assert count == 1
        assert len(good_events) == 1

    def test_get_subscribers(self):
        bus = EventBus()
        sid1 = bus.subscribe("t", lambda e: None)
        sid2 = bus.subscribe("t", lambda e: None)
        subs = bus.get_subscribers("t")
        assert sid1 in subs
        assert sid2 in subs

    def test_get_topics(self):
        bus = EventBus()
        bus.subscribe("alpha", lambda e: None)
        bus.subscribe("beta", lambda e: None)
        topics = bus.get_topics()
        assert "alpha" in topics
        assert "beta" in topics

    def test_event_log(self):
        bus = EventBus()
        bus.publish(Event(topic="t1", data={"x": 1}))
        bus.publish(Event(topic="t2", data={"x": 2}))
        log = bus.get_event_log()
        assert len(log) == 2
        assert log[0].topic == "t1"
        assert log[1].topic == "t2"

    def test_event_log_filter_by_topic(self):
        bus = EventBus()
        bus.publish(Event(topic="t1"))
        bus.publish(Event(topic="t2"))
        bus.publish(Event(topic="t1"))
        log = bus.get_event_log(topic="t1")
        assert len(log) == 2

    def test_event_log_bounded(self):
        bus = EventBus()
        bus._max_log = 5
        for i in range(10):
            bus.publish(Event(topic="t", data={"i": i}))
        log = bus.get_event_log()
        assert len(log) == 5
        assert log[0].data["i"] == 5  # oldest kept

    def test_clear_removes_everything(self):
        bus = EventBus()
        bus.subscribe("t", lambda e: None)
        bus.publish(Event(topic="t"))
        bus.clear()
        assert bus.get_topics() == []
        assert bus.get_event_log() == []

    def test_thread_safety(self):
        bus = EventBus()
        results = []

        def subscriber(e):
            results.append(e.data.get("i"))

        bus.subscribe("t", subscriber)

        threads = []
        for i in range(20):
            t = threading.Thread(
                target=lambda idx=i: bus.publish(Event(topic="t", data={"i": idx})),
            )
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 20
        assert set(results) == set(range(20))


class TestKnownTopics:
    def test_known_topics_not_empty(self):
        assert len(KNOWN_TOPICS) > 0

    def test_decision_made_in_topics(self):
        assert "decision_made" in KNOWN_TOPICS

    def test_query_processed_in_topics(self):
        assert "query_processed" in KNOWN_TOPICS


class TestSingleton:
    def test_get_event_bus_returns_same_instance(self):
        # Reset singleton for test isolation.
        import src.core.event_bus as mod
        mod._bus = None
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2
        mod._bus = None  # cleanup
