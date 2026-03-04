"""
aeOS Phase 5 — Signal_Ingester (A10)
======================================
Feed external context into aeOS reasoning: calendar, finance,
news, market signals.

aeOS currently reasons on internal data only. Sovereign intelligence
without external context is half-blind.

Layer: Cross-cutting (input layer)
Dependencies: PERSIST, DB.

Signal Lifecycle:
    Ingest → Domain classification → Active signal pool → Auto-expire.
    Consumed signals tracked for relevance learning.

Integration Point:
    AeOSCore enriches reasoning context with getActiveSignals()
    before AI routing. Signals injected at pipeline Step 3.

Interface Contract (from Addendum A):
    ingestCalendar(events)         -> None
    ingestFinancial(data)          -> None
    ingestMarketSignal(signal)     -> None
    ingestManual(text, domain)     -> None
    getActiveSignals()             -> list[Signal]
    expire(signal_id)              -> None

DB Table: External_Signals
"""
from __future__ import annotations

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
# Constants
# ---------------------------------------------------------------------------

VALID_SOURCES = {"calendar", "finance", "market", "manual"}

# Default signal TTL by source (hours)
DEFAULT_TTL: Dict[str, int] = {
    "calendar": 168,   # 7 days
    "finance": 24,     # 1 day
    "market": 72,      # 3 days
    "manual": 720,     # 30 days
}

VALID_DOMAINS = {
    "business", "finance", "health", "relationships",
    "career", "creative", "learning", "personal", "unknown",
}

# Domain inference keywords (simple NLP enrichment)
_DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "finance": [
        "revenue", "profit", "loss", "budget", "expense", "invoice",
        "payment", "cash", "debt", "investment", "stock", "portfolio",
        "dividend", "tax", "salary", "mrr", "arr", "runway",
    ],
    "business": [
        "client", "customer", "sales", "deal", "contract", "proposal",
        "pipeline", "lead", "partner", "vendor", "supplier", "market",
        "competitor", "pricing", "growth", "strategy",
    ],
    "health": [
        "exercise", "workout", "sleep", "nutrition", "diet", "weight",
        "stress", "meditation", "doctor", "appointment", "therapy",
        "wellness", "energy", "fatigue",
    ],
    "career": [
        "job", "interview", "promotion", "skill", "resume", "hiring",
        "team", "manager", "performance", "review", "mentor",
    ],
    "relationships": [
        "meeting", "family", "friend", "colleague", "networking",
        "social", "community", "conversation",
    ],
    "creative": [
        "design", "art", "write", "content", "idea", "brainstorm",
        "prototype", "concept", "creative",
    ],
    "learning": [
        "course", "book", "study", "research", "learn", "practice",
        "training", "certification", "tutorial",
    ],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    """An external context signal for aeOS reasoning."""
    signal_id: int
    source: str
    content: str
    domain: str
    relevance_score: float
    ingested_at: str
    expires_at: Optional[str] = None
    consumed_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# SignalIngester
# ---------------------------------------------------------------------------

class SignalIngester:
    """
    Feeds external context signals into aeOS reasoning.

    Supports calendar events, financial data, market signals,
    and manual free-text input. Signals are enriched with domain
    classification and relevance scoring, then stored in
    External_Signals for consumption by the reasoning pipeline.

    Usage:
        ingester = SignalIngester(db_path="/path/to/aeOS.db")

        # Calendar events
        ingester.ingest_calendar([
            {"title": "Board meeting", "start": "2026-03-10T10:00:00"},
        ])

        # Financial data
        ingester.ingest_financial({
            "cash_balance": 50000, "monthly_burn": 8000,
        })

        # Market signal
        ingester.ingest_market_signal({
            "content": "Competitor launched new product line",
            "source_url": "https://example.com/news",
        })

        # Manual signal
        ingester.ingest_manual(
            "Client X postponed meeting to next quarter",
            domain="business",
        )

        # Get active signals for reasoning
        signals = ingester.get_active_signals()

        # Expire a signal
        ingester.expire(signal_id=42)
    """

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
    ) -> None:
        if db_path is not None:
            self._db_path = Path(db_path).expanduser().resolve()
        else:
            self._db_path = (
                Path(__file__).resolve().parent.parent.parent / "db" / "aeOS.db"
            )

    # ------------------------------------------------------------------
    # Public API: ingestCalendar
    # ------------------------------------------------------------------

    def ingest_calendar(self, events: List[Dict[str, Any]]) -> None:
        """
        Ingest calendar events as time-context signals.

        Each event becomes a signal with domain inferred from
        the event title/description and source='calendar'.

        Args:
            events: List of event dicts with at minimum 'title'.
                    Optional: 'start', 'end', 'description', 'location'.
        """
        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            if "External_Signals" not in tables:
                return

            now = datetime.now(timezone.utc)
            ttl = timedelta(hours=DEFAULT_TTL["calendar"])

            for event in events:
                title = str(event.get("title", ""))
                desc = str(event.get("description", ""))
                content = f"{title}. {desc}".strip(". ")
                if not content:
                    continue

                domain = self._infer_domain(content)
                relevance = self._compute_relevance(content, event)

                self._insert_signal(
                    conn,
                    source="calendar",
                    content=content,
                    domain=domain,
                    relevance_score=relevance,
                    expires_at=(now + ttl).isoformat(),
                    metadata={
                        k: v for k, v in event.items()
                        if k not in ("title", "description")
                    },
                )
            conn.commit()
        except sqlite3.Error as e:
            logger.warning("Failed to ingest calendar events: %s", e)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: ingestFinancial
    # ------------------------------------------------------------------

    def ingest_financial(self, data: Dict[str, Any]) -> None:
        """
        Ingest financial snapshot as money-context signal.

        Args:
            data: Financial data dict. Expected keys include
                  'cash_balance', 'monthly_burn', 'revenue',
                  'expenses', etc. All are optional.
        """
        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            if "External_Signals" not in tables:
                return

            now = datetime.now(timezone.utc)
            ttl = timedelta(hours=DEFAULT_TTL["finance"])

            # Build content summary
            parts = []
            for key, val in data.items():
                if isinstance(val, (int, float)):
                    parts.append(f"{key}: {val:,.2f}")
                elif val is not None:
                    parts.append(f"{key}: {val}")
            content = "Financial snapshot: " + "; ".join(parts) if parts else "Financial data update"

            relevance = min(1.0, 0.6 + len(data) * 0.05)

            self._insert_signal(
                conn,
                source="finance",
                content=content,
                domain="finance",
                relevance_score=round(relevance, 2),
                expires_at=(now + ttl).isoformat(),
                metadata=data,
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.warning("Failed to ingest financial data: %s", e)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: ingestMarketSignal
    # ------------------------------------------------------------------

    def ingest_market_signal(self, signal: Dict[str, Any]) -> None:
        """
        Ingest market/industry signal.

        Args:
            signal: Signal dict with at minimum 'content'.
                    Optional: 'source_url', 'domain', 'relevance'.
        """
        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            if "External_Signals" not in tables:
                return

            now = datetime.now(timezone.utc)
            ttl = timedelta(hours=DEFAULT_TTL["market"])

            content = str(signal.get("content", ""))
            if not content:
                return

            domain = signal.get("domain") or self._infer_domain(content)
            relevance = float(signal.get("relevance", 0.5))
            relevance = max(0.0, min(1.0, relevance))

            metadata = {
                k: v for k, v in signal.items()
                if k not in ("content", "domain", "relevance")
            }

            self._insert_signal(
                conn,
                source="market",
                content=content,
                domain=domain,
                relevance_score=round(relevance, 2),
                expires_at=(now + ttl).isoformat(),
                metadata=metadata,
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.warning("Failed to ingest market signal: %s", e)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: ingestManual
    # ------------------------------------------------------------------

    def ingest_manual(
        self, text: str, domain: str = "unknown"
    ) -> None:
        """
        Ingest free-text signal from the Sovereign.

        Args:
            text:   The signal content.
            domain: Life domain (business, finance, health, etc.)
        """
        if not text or not text.strip():
            return

        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            if "External_Signals" not in tables:
                return

            now = datetime.now(timezone.utc)
            ttl = timedelta(hours=DEFAULT_TTL["manual"])

            if domain not in VALID_DOMAINS:
                domain = self._infer_domain(text)

            relevance = self._compute_relevance(text)

            self._insert_signal(
                conn,
                source="manual",
                content=text.strip(),
                domain=domain,
                relevance_score=round(relevance, 2),
                expires_at=(now + ttl).isoformat(),
                metadata={},
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.warning("Failed to ingest manual signal: %s", e)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: getActiveSignals
    # ------------------------------------------------------------------

    def get_active_signals(
        self,
        domain: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 100,
    ) -> List[Signal]:
        """
        Get all non-expired signals for reasoning enrichment.

        Increments consumed_count for each returned signal.

        Args:
            domain: Optional filter by domain.
            source: Optional filter by source type.
            limit:  Maximum signals to return.

        Returns:
            List of active Signal objects sorted by relevance descending.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            if "External_Signals" not in tables:
                return []

            where_parts = [
                "(expires_at IS NULL OR expires_at > ?)"
            ]
            params: List[Any] = [now_iso]

            if domain:
                where_parts.append("domain = ?")
                params.append(domain)
            if source:
                where_parts.append("source = ?")
                params.append(source)

            where_clause = " AND ".join(where_parts)
            params.append(limit)

            rows = conn.execute(
                f"""SELECT id, source, content, domain, relevance_score,
                           ingested_at, expires_at, consumed_count, metadata
                    FROM External_Signals
                    WHERE {where_clause}
                    ORDER BY relevance_score DESC
                    LIMIT ?""",
                params,
            ).fetchall()

            signals: List[Signal] = []
            ids_to_bump: List[int] = []

            for row in rows:
                meta = {}
                try:
                    meta = json.loads(row["metadata"]) if row["metadata"] else {}
                except (json.JSONDecodeError, TypeError):
                    pass

                signals.append(Signal(
                    signal_id=row["id"],
                    source=row["source"],
                    content=row["content"],
                    domain=row["domain"],
                    relevance_score=float(row["relevance_score"]),
                    ingested_at=row["ingested_at"],
                    expires_at=row["expires_at"],
                    consumed_count=row["consumed_count"] + 1,
                    metadata=meta,
                ))
                ids_to_bump.append(row["id"])

            # Bump consumed_count
            if ids_to_bump:
                placeholders = ",".join("?" * len(ids_to_bump))
                conn.execute(
                    f"""UPDATE External_Signals
                        SET consumed_count = consumed_count + 1
                        WHERE id IN ({placeholders})""",
                    ids_to_bump,
                )
                conn.commit()

            return signals
        except sqlite3.Error as e:
            logger.warning("Failed to get active signals: %s", e)
            return []
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: expire
    # ------------------------------------------------------------------

    def expire(self, signal_id: int) -> None:
        """
        Manually expire a signal by setting expires_at to now.

        Args:
            signal_id: The signal's database ID.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            if "External_Signals" not in tables:
                return

            conn.execute(
                "UPDATE External_Signals SET expires_at = ? WHERE id = ?",
                (now_iso, signal_id),
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.warning("Failed to expire signal %d: %s", signal_id, e)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public: cleanup expired signals
    # ------------------------------------------------------------------

    def cleanup_expired(self) -> int:
        """
        Remove expired signals from database.

        Called by Daemon_Scheduler on interval.

        Returns:
            Number of signals removed.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        conn = self._get_connection()
        try:
            tables = self._get_existing_tables(conn)
            if "External_Signals" not in tables:
                return 0

            cursor = conn.execute(
                """DELETE FROM External_Signals
                   WHERE expires_at IS NOT NULL AND expires_at <= ?""",
                (now_iso,),
            )
            removed = cursor.rowcount
            conn.commit()
            return removed
        except sqlite3.Error as e:
            logger.warning("Failed to cleanup expired signals: %s", e)
            return 0
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internal: signal insertion
    # ------------------------------------------------------------------

    def _insert_signal(
        self,
        conn: sqlite3.Connection,
        source: str,
        content: str,
        domain: str,
        relevance_score: float,
        expires_at: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert a signal into External_Signals."""
        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO External_Signals
            (source, content, domain, relevance_score,
             ingested_at, expires_at, consumed_count, metadata)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)""",
            (
                source,
                content,
                domain,
                relevance_score,
                now_iso,
                expires_at,
                json.dumps(metadata or {}, default=str),
            ),
        )

    # ------------------------------------------------------------------
    # Internal: domain inference (simple NLP)
    # ------------------------------------------------------------------

    def _infer_domain(self, text: str) -> str:
        """Infer domain from text content using keyword matching."""
        text_lower = text.lower()
        scores: Dict[str, int] = {}

        for domain, keywords in _DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[domain] = score

        if not scores:
            return "unknown"

        return max(scores, key=scores.get)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Internal: relevance scoring
    # ------------------------------------------------------------------

    def _compute_relevance(
        self, content: str, metadata: Optional[Dict[str, Any]] = None
    ) -> float:
        """Compute a relevance score for a signal (0.0 to 1.0)."""
        score = 0.3  # Base relevance

        # Longer content is usually more informative
        word_count = len(content.split())
        score += min(word_count / 50, 0.3)

        # Urgency keywords boost relevance
        urgency_words = {
            "urgent", "critical", "deadline", "asap", "immediately",
            "overdue", "risk", "crisis", "emergency",
        }
        content_lower = content.lower()
        urgency_hits = sum(1 for w in urgency_words if w in content_lower)
        score += min(urgency_hits * 0.1, 0.3)

        # Metadata richness
        if metadata:
            score += min(len(metadata) * 0.02, 0.1)

        return round(min(1.0, score), 2)

    # ------------------------------------------------------------------
    # DB helpers
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


__all__ = [
    "SignalIngester",
    "Signal",
    "VALID_SOURCES",
    "VALID_DOMAINS",
    "DEFAULT_TTL",
]
