"""
import_founding_decisions.py — Bulk-import founding decisions into Compound_Intelligence_Log.

Inserts 10 founding decisions (with outcomes) via FlywheelLogger.
Adapts FlywheelLogger's PostgreSQL-flavored SQL to SQLite for local execution.

Usage:
    python -m scripts.import_founding_decisions
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo root is importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.db.db_connect import get_connection

# ---------------------------------------------------------------------------
# Founding decisions data
# ---------------------------------------------------------------------------

FOUNDING_DECISIONS = [
    {
        "context": "Recognized fixed mindset as the root constraint on growth",
        "domain": "personal",
        "decision": "Paradigm shift to growth mindset",
        "reasoning_summary": "Identified that beliefs about capability were self-imposed constraints, not reality. Chose to treat every failure as data.",
        "confidence": 0.95,
        "outcome": "Unlocked capacity to learn anything. Foundation for all subsequent decisions.",
        "outcome_valence": "positive",
        "outcome_magnitude": 10,
    },
    {
        "context": "Realized knowledge retention and speed of learning were bottlenecks",
        "domain": "personal",
        "decision": "Learned how to learn — meta-learning as a skill",
        "reasoning_summary": "Invested in learning methodology before content. Spaced repetition, first principles, teaching as retention.",
        "confidence": 0.90,
        "outcome": "Compression of skill acquisition timelines significantly. Able to pick up complex domains faster.",
        "outcome_valence": "positive",
        "outcome_magnitude": 9,
    },
    {
        "context": "Ego protection was blocking honest assessment and growth",
        "domain": "personal",
        "decision": "Adopted 'I don't know' as default posture",
        "reasoning_summary": "Chose intellectual honesty over appearance of competence. Removed ego from the learning equation.",
        "confidence": 0.92,
        "outcome": "Dramatically improved signal quality in conversations and decisions. Others trust the outputs more.",
        "outcome_valence": "positive",
        "outcome_magnitude": 8,
    },
    {
        "context": "Identity structures no longer matched actual reality or trajectory",
        "domain": "personal",
        "decision": "Allowed existential crisis to complete rather than suppress it",
        "reasoning_summary": "Recognized crisis as identity shedding, not collapse. Let old frameworks dissolve consciously.",
        "confidence": 0.70,
        "outcome": "Emerged with clearer values, higher tolerance for uncertainty, more authentic decision-making.",
        "outcome_valence": "positive",
        "outcome_magnitude": 10,
    },
    {
        "context": "AI wave identified as the highest-leverage technology shift of the decade",
        "domain": "business",
        "decision": "Decided to invest in AI — time, attention, and capital",
        "reasoning_summary": "Module 33 (wave timing): Early growth phase. Asymmetric bet — downside is time spent, upside is decade-long leverage.",
        "confidence": 0.88,
        "outcome": "Currently building aeOS — a sovereign cognitive operating system. ROI still compounding.",
        "outcome_valence": "positive",
        "outcome_magnitude": 9,
    },
    {
        "context": "Recognized that using AI without understanding prompting is like driving blind",
        "domain": "learning",
        "decision": "Purchased prompt engineering courses",
        "reasoning_summary": "Upstream skill — better prompts multiply output quality across every downstream AI interaction.",
        "confidence": 0.85,
        "outcome": "Dramatically improved Claude output quality. Enabled complex multi-session builds like aeOS.",
        "outcome_valence": "positive",
        "outcome_magnitude": 8,
    },
    {
        "context": "Free tier limiting depth and session length on critical builds",
        "domain": "business",
        "decision": "Subscribed to Claude Pro then upgraded to Claude Max 5x",
        "reasoning_summary": "Tool quality directly limits output quality. Removing the constraint was asymmetric — low cost, high leverage.",
        "confidence": 0.95,
        "outcome": "Unlocked extended context, faster iteration, deeper builds. aeOS would not exist at this fidelity otherwise.",
        "outcome_valence": "positive",
        "outcome_magnitude": 9,
    },
    {
        "context": "Ideas were accumulating without execution — becoming intellectual debt",
        "domain": "personal",
        "decision": "Committed to executing all ideas rather than collecting them",
        "reasoning_summary": "Law 21: knowledge without execution is vanity. Shifted identity from thinker to builder.",
        "confidence": 0.88,
        "outcome": "aeOS phases 0\u20133 complete, 341 tests passing, v9 architecture in progress.",
        "outcome_valence": "positive",
        "outcome_magnitude": 10,
    },
    {
        "context": "No existing tool matched the cognitive architecture needed",
        "domain": "business",
        "decision": "Built a custom cognitive OS rather than buying off-the-shelf",
        "reasoning_summary": "Off-the-shelf tools optimize for average users. Sovereign system optimizes for one — the builder.",
        "confidence": 0.80,
        "outcome": "In progress. 341 tests, v9 foundation laid, Phase 4 scoped. Compound value accelerating.",
        "outcome_valence": "positive",
        "outcome_magnitude": 10,
    },
    {
        "context": "Single AI dependency creates fragility and blind spots",
        "domain": "business",
        "decision": "Adopted multi-AI orchestration (Claude + ChatGPT + Claude Code in parallel)",
        "reasoning_summary": "Different models have different strengths. Parallel windows compress time. No single point of failure.",
        "confidence": 0.87,
        "outcome": "Blueprint synthesis, build specs, cartridge generation, and code execution running simultaneously.",
        "outcome_valence": "positive",
        "outcome_magnitude": 8,
    },
]

# ---------------------------------------------------------------------------
# Valence / magnitude normalizers
# ---------------------------------------------------------------------------

_VALENCE_MAP = {"positive": 1, "neutral": 0, "negative": -1}


def _normalize_valence(raw: str | int) -> int:
    if isinstance(raw, int) and raw in (-1, 0, 1):
        return raw
    return _VALENCE_MAP.get(str(raw).lower(), 0)


def _normalize_magnitude(raw: float | int) -> float:
    """Scale 0-10 magnitude to 0.0-1.0 range expected by FlywheelLogger."""
    if raw > 1.0:
        return round(min(raw / 10.0, 1.0), 4)
    return round(raw, 4)


# ---------------------------------------------------------------------------
# SQLite-compatible table creation
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS Compound_Intelligence_Log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id     TEXT    NOT NULL UNIQUE,
    event_type      TEXT    NOT NULL DEFAULT 'DECISION_MADE',
    timestamp       TEXT    NOT NULL,
    context         TEXT,
    cartridges_fired TEXT   DEFAULT '[]',
    cartridge_count  INTEGER DEFAULT 0,
    reasoning_summary TEXT,
    confidence      REAL,
    domain          TEXT    DEFAULT 'unknown',
    session_id      TEXT,
    outcome_recorded INTEGER DEFAULT 0,
    outcome_valence  INTEGER,
    outcome_magnitude REAL,
    outcome_description TEXT,
    outcome_timestamp TEXT,
    metadata        TEXT    DEFAULT '{}'
);
"""

_INSERT_DECISION_SQL = """
INSERT INTO Compound_Intelligence_Log (
    decision_id, event_type, timestamp, context,
    cartridges_fired, cartridge_count, reasoning_summary,
    confidence, domain, session_id, outcome_recorded,
    outcome_valence, outcome_magnitude, outcome_description,
    outcome_timestamp, metadata
) VALUES (
    :decision_id, :event_type, :timestamp, :context,
    :cartridges_fired, :cartridge_count, :reasoning_summary,
    :confidence, :domain, :session_id, :outcome_recorded,
    :outcome_valence, :outcome_magnitude, :outcome_description,
    :outcome_timestamp, :metadata
)
"""

_UPDATE_OUTCOME_SQL = """
UPDATE Compound_Intelligence_Log
SET outcome_recorded    = 1,
    outcome_description = :outcome_description,
    outcome_valence     = :outcome_valence,
    outcome_magnitude   = :outcome_magnitude,
    outcome_timestamp   = :outcome_timestamp
WHERE decision_id = :decision_id
"""

# ---------------------------------------------------------------------------
# Import logic
# ---------------------------------------------------------------------------

# FlywheelLogger VALID_DOMAINS (keep in sync)
VALID_DOMAINS = {
    "business", "finance", "health", "relationships",
    "career", "creative", "learning", "personal", "unknown",
}


def import_founding_decisions() -> list[str]:
    """Insert all founding decisions and their outcomes. Returns list of decision_ids."""
    conn = get_connection()
    conn.execute(_CREATE_TABLE_SQL)
    conn.commit()

    decision_ids: list[str] = []
    session_id = "founding-decisions-import"
    now = datetime.now(timezone.utc).isoformat()

    for entry in FOUNDING_DECISIONS:
        domain = entry["domain"] if entry["domain"] in VALID_DOMAINS else "unknown"
        decision_id = str(uuid.uuid4())
        confidence = entry["confidence"]
        context = entry["context"]
        decision_label = entry["decision"]
        reasoning = entry["reasoning_summary"]

        # --- log decision ---
        conn.execute(_INSERT_DECISION_SQL, {
            "decision_id": decision_id,
            "event_type": "DECISION_MADE",
            "timestamp": now,
            "context": context[:2000],
            "cartridges_fired": json.dumps([]),
            "cartridge_count": 0,
            "reasoning_summary": reasoning[:1000],
            "confidence": round(confidence, 4),
            "domain": domain,
            "session_id": session_id,
            "outcome_recorded": 0,
            "outcome_valence": None,
            "outcome_magnitude": None,
            "outcome_description": None,
            "outcome_timestamp": None,
            "metadata": json.dumps({"decision_label": decision_label}),
        })

        # --- log outcome ---
        valence = _normalize_valence(entry["outcome_valence"])
        magnitude = _normalize_magnitude(entry["outcome_magnitude"])

        conn.execute(_UPDATE_OUTCOME_SQL, {
            "decision_id": decision_id,
            "outcome_description": entry["outcome"][:1000],
            "outcome_valence": valence,
            "outcome_magnitude": magnitude,
            "outcome_timestamp": now,
        })

        decision_ids.append(decision_id)
        print(f"  [{domain:10s}] {decision_label}")

    conn.commit()
    return decision_ids


def verify_records(expected: int) -> None:
    """Read back and print summary of inserted records."""
    conn = get_connection()
    cur = conn.execute(
        "SELECT COUNT(*) FROM Compound_Intelligence_Log WHERE session_id = 'founding-decisions-import'"
    )
    count = cur.fetchone()[0]
    print(f"\nVerification: {count} records in Compound_Intelligence_Log (expected {expected})")

    cur = conn.execute(
        "SELECT COUNT(*) FROM Compound_Intelligence_Log "
        "WHERE session_id = 'founding-decisions-import' AND outcome_recorded = 1"
    )
    with_outcomes = cur.fetchone()[0]
    print(f"  With outcomes: {with_outcomes}/{count}")

    cur = conn.execute(
        "SELECT domain, COUNT(*) as n FROM Compound_Intelligence_Log "
        "WHERE session_id = 'founding-decisions-import' "
        "GROUP BY domain ORDER BY n DESC"
    )
    print("  By domain:")
    for row in cur.fetchall():
        print(f"    {row[0]:12s}: {row[1]}")

    if count != expected:
        print(f"\nERROR: Expected {expected} records, found {count}")
        sys.exit(1)
    print("\nAll founding decisions imported successfully.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Importing 10 founding decisions into Compound_Intelligence_Log...\n")
    ids = import_founding_decisions()
    verify_records(expected=len(FOUNDING_DECISIONS))
