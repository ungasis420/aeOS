"""
aeOS Phase 4 — Audit_Trail (A6)
=================================
Human-readable report of everything aeOS did in a time period.

Transparency guarantee: 'Show me what aeOS decided last month' should
be one command.

Layer: Cross-cutting (observability)
Dependencies: PERSIST, DB, all logging tables

Interface Contract (from Addendum A):
    generateReport(days?)       -> AuditReport
    exportCSV(days?)            -> str (filepath)
    exportJSON(days?)           -> str (filepath)
    getTimeline(days?)          -> list[TimelineEvent]

DB Table: Audit_Log (event_type, event_data JSON, module_source, timestamp)
"""
from __future__ import annotations

import csv
import io
import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TimelineEvent:
    """A single event in the audit timeline."""
    event_type: str
    module_source: str
    timestamp: str
    severity: str = "info"
    event_data: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuditReport:
    """Comprehensive audit report for a time period."""
    period_start: str
    period_end: str
    days: int
    total_events: int
    events_by_type: Dict[str, int]
    events_by_module: Dict[str, int]
    events_by_severity: Dict[str, int]
    decisions_logged: int
    alerts_triggered: int
    api_calls_made: int
    contradictions_detected: int
    system_health_score: float
    generated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# AuditTrail
# ---------------------------------------------------------------------------

class AuditTrail:
    """
    Human-readable audit trail of all aeOS activity.

    Logs events from all modules via log_event(). Generates reports,
    exports, and timelines for Sovereign transparency.

    Usage:
        audit = AuditTrail(db_path="/path/to/aeOS.db")

        # Log an event
        audit.log_event(
            event_type="DECISION_MADE",
            module_source="decision_engine",
            event_data={"decision_id": "DEC-001", "domain": "business"},
        )

        # Generate report
        report = audit.generate_report(days=30)

        # Export
        csv_path = audit.export_csv(days=7)
        json_path = audit.export_json(days=7)

        # Timeline
        timeline = audit.get_timeline(days=7)
    """

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        export_dir: Optional[Union[str, Path]] = None,
    ) -> None:
        if db_path is not None:
            self._db_path = Path(db_path).expanduser().resolve()
        else:
            self._db_path = (
                Path(__file__).resolve().parent.parent.parent / "db" / "aeOS.db"
            )

        if export_dir is not None:
            self._export_dir = Path(export_dir).expanduser().resolve()
        else:
            self._export_dir = self._db_path.parent / "exports"

    # ------------------------------------------------------------------
    # Event logging
    # ------------------------------------------------------------------

    def log_event(
        self,
        event_type: str,
        module_source: str,
        event_data: Optional[Dict[str, Any]] = None,
        severity: str = "info",
        session_id: Optional[str] = None,
    ) -> None:
        """
        Log an event to the audit trail.

        Args:
            event_type:    Type of event (e.g., DECISION_MADE, ALERT_TRIGGERED).
            module_source: Which module generated this event.
            event_data:    Optional structured event payload.
            severity:      debug, info, warn, error, critical.
            session_id:    Optional session identifier.
        """
        valid_severities = {"debug", "info", "warn", "error", "critical"}
        if severity not in valid_severities:
            severity = "info"

        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            if "Audit_Log" not in tables:
                return

            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT INTO Audit_Log
                (event_type, event_data, module_source, timestamp,
                 session_id, severity)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    event_type,
                    json.dumps(event_data or {}, default=str),
                    module_source,
                    now_iso,
                    session_id,
                    severity,
                ),
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.warning("Failed to log audit event: %s", e)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: generateReport
    # ------------------------------------------------------------------

    def generate_report(self, days: int = 30) -> AuditReport:
        """
        Generate a comprehensive audit report for the given time period.

        Args:
            days: Number of days to cover (default 30).

        Returns:
            AuditReport with aggregated statistics.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)
        cutoff_iso = cutoff.isoformat()
        now_iso = now.isoformat()

        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            if "Audit_Log" not in tables:
                return self._empty_report(cutoff_iso, now_iso, days)

            # Total events
            row = conn.execute(
                "SELECT COUNT(*) FROM Audit_Log WHERE timestamp >= ?",
                (cutoff_iso,),
            ).fetchone()
            total_events = row[0] if row else 0

            # Events by type
            events_by_type = self._count_by_column(
                conn, "Audit_Log", "event_type", cutoff_iso
            )

            # Events by module
            events_by_module = self._count_by_column(
                conn, "Audit_Log", "module_source", cutoff_iso
            )

            # Events by severity
            events_by_severity = self._count_by_column(
                conn, "Audit_Log", "severity", cutoff_iso
            )

            # Specific counts
            decisions_logged = events_by_type.get("DECISION_MADE", 0)
            alerts_triggered = sum(
                v for k, v in events_by_type.items()
                if "ALERT" in k.upper()
            )
            api_calls = sum(
                v for k, v in events_by_type.items()
                if "API" in k.upper()
            )

            # Contradictions from Contradiction_Log
            contradictions = 0
            if "Contradiction_Log" in tables:
                row = conn.execute(
                    "SELECT COUNT(*) FROM Contradiction_Log WHERE detected_at >= ?",
                    (cutoff_iso,),
                ).fetchone()
                contradictions = row[0] if row else 0

            # System health score (based on error rate)
            total_events_safe = max(total_events, 1)
            errors = events_by_severity.get("error", 0) + events_by_severity.get("critical", 0)
            health_score = max(100.0 - (errors / total_events_safe * 100), 0.0)

            return AuditReport(
                period_start=cutoff_iso,
                period_end=now_iso,
                days=days,
                total_events=total_events,
                events_by_type=events_by_type,
                events_by_module=events_by_module,
                events_by_severity=events_by_severity,
                decisions_logged=decisions_logged,
                alerts_triggered=alerts_triggered,
                api_calls_made=api_calls,
                contradictions_detected=contradictions,
                system_health_score=round(health_score, 1),
                generated_at=now_iso,
            )

        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: exportCSV
    # ------------------------------------------------------------------

    def export_csv(self, days: int = 30) -> str:
        """
        Export audit events to CSV file.

        Args:
            days: Number of days to export.

        Returns:
            Filepath of the exported CSV.
        """
        self._export_dir.mkdir(parents=True, exist_ok=True)
        events = self.get_timeline(days=days)

        filename = f"audit_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        filepath = self._export_dir / filename

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "event_type", "module_source",
                "severity", "session_id", "event_data",
            ])
            for event in events:
                writer.writerow([
                    event.timestamp,
                    event.event_type,
                    event.module_source,
                    event.severity,
                    event.session_id or "",
                    json.dumps(event.event_data, default=str),
                ])

        return str(filepath)

    # ------------------------------------------------------------------
    # Public API: exportJSON
    # ------------------------------------------------------------------

    def export_json(self, days: int = 30) -> str:
        """
        Export audit events to JSON file.

        Args:
            days: Number of days to export.

        Returns:
            Filepath of the exported JSON.
        """
        self._export_dir.mkdir(parents=True, exist_ok=True)
        events = self.get_timeline(days=days)

        filename = f"audit_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        filepath = self._export_dir / filename

        data = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "days": days,
            "total_events": len(events),
            "events": [e.to_dict() for e in events],
        }

        filepath.write_text(
            json.dumps(data, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )

        return str(filepath)

    # ------------------------------------------------------------------
    # Public API: getTimeline
    # ------------------------------------------------------------------

    def get_timeline(
        self,
        days: int = 30,
        event_type: Optional[str] = None,
        module_source: Optional[str] = None,
        limit: int = 1000,
    ) -> List[TimelineEvent]:
        """
        Get chronological event stream for the given period.

        Args:
            days:          Number of days to cover.
            event_type:    Optional filter by event type.
            module_source: Optional filter by module.
            limit:         Maximum events to return.

        Returns:
            List of TimelineEvent objects, newest first.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            if "Audit_Log" not in tables:
                return []

            where_parts = ["timestamp >= ?"]
            params: List[Any] = [cutoff]

            if event_type:
                where_parts.append("event_type = ?")
                params.append(event_type)
            if module_source:
                where_parts.append("module_source = ?")
                params.append(module_source)

            where_clause = " AND ".join(where_parts)
            params.append(limit)

            rows = conn.execute(
                f"SELECT * FROM Audit_Log WHERE {where_clause} "
                f"ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()

            events = []
            for row in rows:
                event_data = {}
                try:
                    event_data = json.loads(row["event_data"]) if row["event_data"] else {}
                except (json.JSONDecodeError, TypeError):
                    event_data = {"raw": str(row["event_data"])}

                events.append(TimelineEvent(
                    event_type=row["event_type"],
                    module_source=row["module_source"],
                    timestamp=row["timestamp"],
                    severity=row["severity"],
                    event_data=event_data,
                    session_id=row["session_id"],
                ))
            return events

        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _get_existing_tables(self, conn: sqlite3.Connection) -> set:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {row[0] for row in rows}

    def _count_by_column(
        self, conn: sqlite3.Connection, table: str,
        column: str, cutoff_iso: str,
    ) -> Dict[str, int]:
        """Count rows grouped by a column value."""
        result = {}
        try:
            rows = conn.execute(
                f'SELECT "{column}", COUNT(*) as cnt FROM "{table}" '
                f'WHERE timestamp >= ? GROUP BY "{column}"',
                (cutoff_iso,),
            ).fetchall()
            for row in rows:
                result[row[0]] = row[1]
        except sqlite3.Error:
            pass
        return result

    def _empty_report(
        self, start: str, end: str, days: int
    ) -> AuditReport:
        """Return an empty report when no data available."""
        return AuditReport(
            period_start=start,
            period_end=end,
            days=days,
            total_events=0,
            events_by_type={},
            events_by_module={},
            events_by_severity={},
            decisions_logged=0,
            alerts_triggered=0,
            api_calls_made=0,
            contradictions_detected=0,
            system_health_score=100.0,
            generated_at=end,
        )


__all__ = [
    "AuditTrail",
    "AuditReport",
    "TimelineEvent",
]
