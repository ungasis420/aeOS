"""
daemon_scheduler.py
aeOS — Background Job Scheduler

Cron-style background scheduler for periodic tasks:
  - A7 Weekly Reflection:  Every Sunday at 9:00 AM
  - A7 Monthly Reflection: 1st of month at 9:00 AM
  - A10 Signal Cleanup:    Nightly at 2:00 AM
  - A1 Integrity Check:    Nightly at 3:00 AM

All jobs are idempotent (safe to run multiple times).
Supports: CRON, INTERVAL, ONCE job types.

Stamp: S✅ T✅ L✅ A✅
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ScheduledJob:
    """A registered job in the scheduler."""
    job_id: str
    name: str
    job_type: str  # "interval", "cron", "once"
    callback: Callable[[], Any]
    interval_seconds: Optional[float] = None  # For interval jobs.
    cron_spec: Optional[Dict[str, Any]] = None  # {day_of_week, hour, minute, day_of_month}
    run_at: Optional[datetime] = None  # For once jobs.
    enabled: bool = True
    last_run: Optional[str] = None
    last_result: Optional[str] = None
    run_count: int = 0
    error_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "name": self.name,
            "job_type": self.job_type,
            "interval_seconds": self.interval_seconds,
            "cron_spec": self.cron_spec,
            "enabled": self.enabled,
            "last_run": self.last_run,
            "last_result": self.last_result,
            "run_count": self.run_count,
            "error_count": self.error_count,
        }


@dataclass
class JobResult:
    """Result of a single job execution."""
    job_id: str
    job_name: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    duration_ms: int = 0
    executed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class DaemonScheduler:
    """
    Background job scheduler with support for interval, cron, and one-time jobs.

    Usage:
        scheduler = DaemonScheduler()
        scheduler.register_interval("cleanup", 3600, my_cleanup_fn)
        scheduler.register_cron("weekly_reflect", {"day_of_week": 6, "hour": 9}, fn)
        scheduler.start()  # Launches background thread.
        ...
        scheduler.stop()
    """

    def __init__(self, tick_interval: float = 60.0) -> None:
        self._jobs: Dict[str, ScheduledJob] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._tick_interval = tick_interval
        self._last_tick_times: Dict[str, float] = {}
        self._history: List[JobResult] = []
        self._max_history = 200

    # ---- Registration ---------------------------------------------------------

    def register_interval(
        self,
        name: str,
        interval_seconds: float,
        callback: Callable[[], Any],
        enabled: bool = True,
    ) -> str:
        """Register a job that runs at a fixed interval."""
        job_id = f"int_{name}_{uuid.uuid4().hex[:6]}"
        job = ScheduledJob(
            job_id=job_id,
            name=name,
            job_type="interval",
            callback=callback,
            interval_seconds=interval_seconds,
            enabled=enabled,
        )
        with self._lock:
            self._jobs[job_id] = job
            self._last_tick_times[job_id] = 0.0
        logger.info("Registered interval job: %s (every %ds)", name, interval_seconds)
        return job_id

    def register_cron(
        self,
        name: str,
        cron_spec: Dict[str, Any],
        callback: Callable[[], Any],
        enabled: bool = True,
    ) -> str:
        """
        Register a cron-style job.

        cron_spec keys:
          - day_of_week: 0=Mon, 6=Sun (optional)
          - day_of_month: 1-31 (optional)
          - hour: 0-23
          - minute: 0-59
        """
        job_id = f"cron_{name}_{uuid.uuid4().hex[:6]}"
        job = ScheduledJob(
            job_id=job_id,
            name=name,
            job_type="cron",
            callback=callback,
            cron_spec=cron_spec,
            enabled=enabled,
        )
        with self._lock:
            self._jobs[job_id] = job
        logger.info("Registered cron job: %s (spec=%s)", name, cron_spec)
        return job_id

    def register_once(
        self,
        name: str,
        run_at: datetime,
        callback: Callable[[], Any],
        enabled: bool = True,
    ) -> str:
        """Register a one-time job to run at a specific datetime."""
        job_id = f"once_{name}_{uuid.uuid4().hex[:6]}"
        job = ScheduledJob(
            job_id=job_id,
            name=name,
            job_type="once",
            callback=callback,
            run_at=run_at,
            enabled=enabled,
        )
        with self._lock:
            self._jobs[job_id] = job
        logger.info("Registered one-time job: %s (at %s)", name, run_at.isoformat())
        return job_id

    def unregister(self, job_id: str) -> bool:
        """Remove a registered job."""
        with self._lock:
            if job_id in self._jobs:
                del self._jobs[job_id]
                self._last_tick_times.pop(job_id, None)
                return True
        return False

    def enable(self, job_id: str) -> None:
        """Enable a disabled job."""
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].enabled = True

    def disable(self, job_id: str) -> None:
        """Disable a job without removing it."""
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].enabled = False

    # ---- Execution ------------------------------------------------------------

    def _should_run_interval(self, job: ScheduledJob) -> bool:
        """Check if an interval job is due."""
        if not job.interval_seconds:
            return False
        last = self._last_tick_times.get(job.job_id, 0.0)
        return (time.monotonic() - last) >= job.interval_seconds

    def _should_run_cron(self, job: ScheduledJob, now: datetime) -> bool:
        """Check if a cron job matches the current time (within tick window)."""
        spec = job.cron_spec or {}
        if "hour" in spec and now.hour != spec["hour"]:
            return False
        if "minute" in spec and now.minute != spec["minute"]:
            return False
        if "day_of_week" in spec and now.weekday() != spec["day_of_week"]:
            return False
        if "day_of_month" in spec and now.day != spec["day_of_month"]:
            return False
        # Avoid running the same cron job twice in the same minute.
        if job.last_run:
            try:
                last = datetime.fromisoformat(job.last_run)
                if (now - last).total_seconds() < 120:
                    return False
            except (ValueError, TypeError):
                pass
        return True

    def _should_run_once(self, job: ScheduledJob, now: datetime) -> bool:
        """Check if a one-time job is due."""
        if job.run_at is None:
            return False
        if job.run_count > 0:
            return False
        return now >= job.run_at

    def _execute_job(self, job: ScheduledJob) -> JobResult:
        """Execute a single job and record the result."""
        started = time.perf_counter()
        try:
            result = job.callback()
            duration = int((time.perf_counter() - started) * 1000)
            job.run_count += 1
            job.last_run = datetime.now(timezone.utc).isoformat()
            job.last_result = "success"
            if job.job_type == "interval":
                self._last_tick_times[job.job_id] = time.monotonic()
            jr = JobResult(
                job_id=job.job_id,
                job_name=job.name,
                success=True,
                result=str(result)[:500] if result else None,
                duration_ms=duration,
            )
            logger.info("Job '%s' completed in %dms", job.name, duration)
            return jr
        except Exception as exc:
            duration = int((time.perf_counter() - started) * 1000)
            job.error_count += 1
            job.last_run = datetime.now(timezone.utc).isoformat()
            job.last_result = f"error: {exc}"
            if job.job_type == "interval":
                self._last_tick_times[job.job_id] = time.monotonic()
            jr = JobResult(
                job_id=job.job_id,
                job_name=job.name,
                success=False,
                error=str(exc),
                duration_ms=duration,
            )
            logger.warning("Job '%s' failed: %s", job.name, exc)
            return jr

    def tick(self) -> List[JobResult]:
        """
        Run one scheduler tick: check all jobs and execute due ones.

        Call this manually for testing, or let start() call it in a loop.
        """
        now = datetime.now(timezone.utc)
        results: List[JobResult] = []

        with self._lock:
            due_jobs = []
            for job in self._jobs.values():
                if not job.enabled:
                    continue
                if job.job_type == "interval" and self._should_run_interval(job):
                    due_jobs.append(job)
                elif job.job_type == "cron" and self._should_run_cron(job, now):
                    due_jobs.append(job)
                elif job.job_type == "once" and self._should_run_once(job, now):
                    due_jobs.append(job)

        for job in due_jobs:
            jr = self._execute_job(job)
            results.append(jr)
            with self._lock:
                self._history.append(jr)
                if len(self._history) > self._max_history:
                    self._history = self._history[-self._max_history:]

        return results

    def run_job(self, job_id: str) -> Optional[JobResult]:
        """Manually trigger a specific job by ID."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        jr = self._execute_job(job)
        with self._lock:
            self._history.append(jr)
        return jr

    # ---- Background thread ----------------------------------------------------

    def start(self) -> None:
        """Start the background scheduler thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="aeos-scheduler",
        )
        self._thread.start()
        logger.info("DaemonScheduler started (tick_interval=%.1fs)", self._tick_interval)

    def stop(self) -> None:
        """Stop the background scheduler thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=self._tick_interval + 2)
            self._thread = None
        logger.info("DaemonScheduler stopped.")

    def _run_loop(self) -> None:
        """Background loop that ticks the scheduler."""
        while self._running:
            try:
                self.tick()
            except Exception as exc:
                logger.exception("Scheduler tick failed: %s", exc)
            time.sleep(self._tick_interval)

    @property
    def running(self) -> bool:
        return self._running

    # ---- Inspection -----------------------------------------------------------

    def list_jobs(self) -> List[Dict[str, Any]]:
        """Return all registered jobs as dicts."""
        with self._lock:
            return [j.to_dict() for j in self._jobs.values()]

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent job execution history."""
        with self._lock:
            return [
                {
                    "job_id": r.job_id,
                    "job_name": r.job_name,
                    "success": r.success,
                    "error": r.error,
                    "duration_ms": r.duration_ms,
                    "executed_at": r.executed_at,
                }
                for r in self._history[-limit:]
            ]

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Return a single job's info."""
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job else None
