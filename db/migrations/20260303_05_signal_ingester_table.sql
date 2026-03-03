-- aeOS Phase 5 — Addendum A Tables Migration (A10)
-- File: db/migrations/20260303_05_signal_ingester_table.sql
-- Run AFTER: 20260303_04_phase5_tables.sql
--
-- Creates 1 table required by Signal_Ingester (A10).
-- Zero breaking changes to existing schema.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- 1. External_Signals
-- Signal_Ingester (A10). Stores external context signals for reasoning
-- enrichment: calendar, finance, market, manual.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS External_Signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('calendar', 'finance', 'market', 'manual')),
    content         TEXT NOT NULL,
    domain          TEXT NOT NULL DEFAULT 'unknown',
    relevance_score REAL NOT NULL DEFAULT 0.5 CHECK (relevance_score BETWEEN 0 AND 1),
    ingested_at     TEXT NOT NULL,
    expires_at      TEXT,
    consumed_count  INTEGER NOT NULL DEFAULT 0,
    metadata        TEXT NOT NULL DEFAULT '{}'    -- JSON: additional structured data
);

CREATE INDEX IF NOT EXISTS idx_es_source
    ON External_Signals (source);
CREATE INDEX IF NOT EXISTS idx_es_domain
    ON External_Signals (domain);
CREATE INDEX IF NOT EXISTS idx_es_expires
    ON External_Signals (expires_at);
CREATE INDEX IF NOT EXISTS idx_es_ingested
    ON External_Signals (ingested_at DESC);
