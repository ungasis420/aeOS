"""
tests/test_daemon_scheduler.py

Unit tests for the DaemonScheduler background job system.

Stamp: S✅ T✅ L✅ A✅
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.core.daemon_scheduler import DaemonScheduler, ScheduledJob, JobResult


class TestRegistration:
    def test_register_interval(self):
        s = DaemonScheduler()
        jid = s.register_interval("test_job", 60, lambda: "ok")
        assert jid.startswith("int_")
        jobs = s.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["name"] == "test_job"
        assert jobs[0]["job_type"] == "interval"
        assert jobs[0]["interval_seconds"] == 60

    def test_register_cron(self):
        s = DaemonScheduler()
        jid = s.register_cron("weekly", {"day_of_week": 6, "hour": 9, "minute": 0}, lambda: None)
        assert jid.startswith("cron_")
        jobs = s.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["cron_spec"]["day_of_week"] == 6

    def test_register_once(self):
        s = DaemonScheduler()
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        jid = s.register_once("one_time", future, lambda: "done")
        assert jid.startswith("once_")
        jobs = s.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["job_type"] == "once"

    def test_register_multiple_jobs(self):
        s = DaemonScheduler()
        s.register_interval("a", 10, lambda: None)
        s.register_interval("b", 20, lambda: None)
        s.register_cron("c", {"hour": 1}, lambda: None)
        assert len(s.list_jobs()) == 3

    def test_unregister_job(self):
        s = DaemonScheduler()
        jid = s.register_interval("tmp", 10, lambda: None)
        assert s.unregister(jid) is True
        assert len(s.list_jobs()) == 0

    def test_unregister_nonexistent(self):
        s = DaemonScheduler()
        assert s.unregister("fake_id") is False

    def test_enable_disable(self):
        s = DaemonScheduler()
        jid = s.register_interval("x", 10, lambda: None, enabled=False)
        job_info = s.get_job(jid)
        assert job_info["enabled"] is False
        s.enable(jid)
        assert s.get_job(jid)["enabled"] is True
        s.disable(jid)
        assert s.get_job(jid)["enabled"] is False


class TestIntervalExecution:
    def test_interval_job_runs_immediately(self):
        s = DaemonScheduler()
        results = []
        s.register_interval("imm", 0.01, lambda: results.append(1))
        # First tick should fire (last_tick_time starts at 0).
        tick_results = s.tick()
        assert len(tick_results) == 1
        assert tick_results[0].success is True
        assert len(results) == 1

    def test_interval_job_respects_interval(self):
        s = DaemonScheduler()
        count = []
        jid = s.register_interval("slow", 0.01, lambda: count.append(1))
        s.tick()  # first tick — fires because interval elapsed since 0
        assert len(count) >= 1
        # Now set a long interval so it won't fire again.
        s._jobs[jid].interval_seconds = 9999
        s.tick()  # second tick — should NOT fire (9999s not elapsed)
        assert len(count) == 1

    def test_disabled_job_not_run(self):
        s = DaemonScheduler()
        count = []
        jid = s.register_interval("dis", 0.01, lambda: count.append(1), enabled=False)
        s.tick()
        assert len(count) == 0


class TestCronExecution:
    def test_cron_job_matching_time(self):
        s = DaemonScheduler()
        results = []
        now = datetime.now(timezone.utc)
        spec = {"hour": now.hour, "minute": now.minute}
        s.register_cron("now_job", spec, lambda: results.append(1))
        s.tick()
        assert len(results) == 1

    def test_cron_job_non_matching_hour(self):
        s = DaemonScheduler()
        results = []
        now = datetime.now(timezone.utc)
        wrong_hour = (now.hour + 5) % 24
        spec = {"hour": wrong_hour, "minute": now.minute}
        s.register_cron("wrong_hour", spec, lambda: results.append(1))
        s.tick()
        assert len(results) == 0

    def test_cron_job_day_of_week(self):
        s = DaemonScheduler()
        results = []
        now = datetime.now(timezone.utc)
        spec = {"day_of_week": now.weekday(), "hour": now.hour, "minute": now.minute}
        s.register_cron("today", spec, lambda: results.append(1))
        s.tick()
        assert len(results) == 1

    def test_cron_no_double_fire(self):
        s = DaemonScheduler()
        results = []
        now = datetime.now(timezone.utc)
        spec = {"hour": now.hour, "minute": now.minute}
        s.register_cron("no_dupe", spec, lambda: results.append(1))
        s.tick()
        s.tick()  # Should not fire again within 120s.
        assert len(results) == 1


class TestOnceExecution:
    def test_once_job_fires_when_due(self):
        s = DaemonScheduler()
        results = []
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        s.register_once("past_job", past, lambda: results.append(1))
        s.tick()
        assert len(results) == 1

    def test_once_job_does_not_repeat(self):
        s = DaemonScheduler()
        results = []
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        s.register_once("past_job", past, lambda: results.append(1))
        s.tick()
        s.tick()
        assert len(results) == 1

    def test_once_job_future_not_fired(self):
        s = DaemonScheduler()
        results = []
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        s.register_once("future", future, lambda: results.append(1))
        s.tick()
        assert len(results) == 0


class TestErrorHandling:
    def test_failing_job_does_not_crash_scheduler(self):
        s = DaemonScheduler()

        def bad():
            raise RuntimeError("boom")

        s.register_interval("bad", 0.01, bad)
        tick_results = s.tick()
        assert len(tick_results) == 1
        assert tick_results[0].success is False
        assert "boom" in tick_results[0].error

    def test_error_count_incremented(self):
        s = DaemonScheduler()

        def bad():
            raise ValueError("fail")

        jid = s.register_interval("bad", 0.01, bad)
        s.tick()
        job = s.get_job(jid)
        assert job["error_count"] == 1
        assert job["run_count"] == 0


class TestManualRun:
    def test_run_job_by_id(self):
        s = DaemonScheduler()
        results = []
        jid = s.register_interval("man", 9999, lambda: results.append(1))
        jr = s.run_job(jid)
        assert jr is not None
        assert jr.success is True
        assert len(results) == 1

    def test_run_nonexistent_job(self):
        s = DaemonScheduler()
        assert s.run_job("fake") is None


class TestHistory:
    def test_history_recorded(self):
        s = DaemonScheduler()
        s.register_interval("h", 0.01, lambda: "result")
        s.tick()
        hist = s.get_history()
        assert len(hist) == 1
        assert hist[0]["success"] is True
        assert hist[0]["job_name"] == "h"

    def test_history_bounded(self):
        s = DaemonScheduler()
        s._max_history = 3
        s.register_interval("h", 0.01, lambda: None)
        for _ in range(10):
            s.tick()
            # Reset tick time to allow re-firing.
            for jid in s._last_tick_times:
                s._last_tick_times[jid] = 0.0
        hist = s.get_history()
        assert len(hist) == 3


class TestBackgroundThread:
    def test_start_stop(self):
        s = DaemonScheduler(tick_interval=0.05)
        s.start()
        assert s.running is True
        time.sleep(0.15)
        s.stop()
        assert s.running is False

    def test_background_job_executes(self):
        s = DaemonScheduler(tick_interval=0.05)
        results = []
        s.register_interval("bg", 0.01, lambda: results.append(1))
        s.start()
        time.sleep(0.2)
        s.stop()
        assert len(results) >= 1


class TestScheduledJob:
    def test_to_dict(self):
        job = ScheduledJob(
            job_id="test_1",
            name="my_job",
            job_type="interval",
            callback=lambda: None,
            interval_seconds=60,
        )
        d = job.to_dict()
        assert d["job_id"] == "test_1"
        assert d["name"] == "my_job"
        assert d["interval_seconds"] == 60
        assert "callback" not in d  # Should not serialize callback.


class TestJobResult:
    def test_job_result_defaults(self):
        jr = JobResult(job_id="j1", job_name="test", success=True)
        assert jr.success is True
        assert jr.error is None
        assert jr.duration_ms == 0
        assert jr.executed_at
