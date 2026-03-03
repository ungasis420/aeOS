-- aeOS Phase 4 — Addendum A Tables Migration
-- File: db/migrations/20260303_03_phase4_tables.sql
-- Run AFTER: 20260302_02_v9_foundation_tables.sql
--
-- Creates 6 tables required by Phase 4 Addendum A modules (A1-A6).
-- Zero breaking changes to existing schema.
--
-- Tables:
--   1. Backup_Manifest          — Identity_Continuity_Protocol (A1)
--   2. Contradiction_Log        — Contradiction_Detector (A2)
--   3. Audit_Log                — Audit_Trail (A6)
--   4. NLQ_Parse_Log            — NLQ_Parser (A5)
--   5. Cartridge_Arbitration_Log — Cartridge_Arbitrator (A4)
--   6. Offline_Mode_Log         — Offline_Mode (A3) connectivity tracking
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- 1. Backup_Manifest
-- Identity_Continuity_Protocol (A1). Tracks all backup snapshots.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS Backup_Manifest (
    backup_id       TEXT PRIMARY KEY,
    created_at      TEXT NOT NULL,
    tables_included TEXT NOT NULL DEFAULT '[]',   -- JSON array of table names
    decision_count  INTEGER NOT NULL DEFAULT 0,
    compound_score  REAL NOT NULL DEFAULT 0.0,
    encrypted       INTEGER NOT NULL DEFAULT 0,   -- boolean: 0/1
    checksum        TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL DEFAULT 0,
    backup_path     TEXT,                         -- filesystem path to backup file
    backup_type     TEXT NOT NULL DEFAULT 'manual' CHECK (backup_type IN ('manual', 'daily', 'weekly', 'monthly')),
    status          TEXT NOT NULL DEFAULT 'complete' CHECK (status IN ('in_progress', 'complete', 'failed', 'verified')),
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_bm_created
    ON Backup_Manifest (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bm_type
    ON Backup_Manifest (backup_type);

-- ---------------------------------------------------------------------------
-- 2. Contradiction_Log
-- Contradiction_Detector (A2). Flags when new decisions contradict past ones.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS Contradiction_Log (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at             TEXT NOT NULL,
    new_decision_id         TEXT,
    conflicting_decision_id TEXT,
    severity                TEXT NOT NULL DEFAULT 'low' CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    explanation             TEXT NOT NULL,
    resolution              TEXT CHECK (resolution IN ('accepted', 'overridden', 'modified', NULL)),
    resolution_note         TEXT,
    domain                  TEXT NOT NULL DEFAULT 'unknown',
    resolved_at             TEXT
);

CREATE INDEX IF NOT EXISTS idx_cl_severity
    ON Contradiction_Log (severity);
CREATE INDEX IF NOT EXISTS idx_cl_detected
    ON Contradiction_Log (detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_cl_domain
    ON Contradiction_Log (domain);

-- ---------------------------------------------------------------------------
-- 3. Audit_Log
-- Audit_Trail (A6). Human-readable log of everything aeOS did.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS Audit_Log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type      TEXT NOT NULL,
    event_data      TEXT NOT NULL DEFAULT '{}',   -- JSON
    module_source   TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    session_id      TEXT,
    severity        TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('debug', 'info', 'warn', 'error', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_al_timestamp
    ON Audit_Log (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_al_event_type
    ON Audit_Log (event_type);
CREATE INDEX IF NOT EXISTS idx_al_module
    ON Audit_Log (module_source);

-- ---------------------------------------------------------------------------
-- 4. NLQ_Parse_Log
-- NLQ_Parser (A5). Tracks natural language query parsing for learning.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS NLQ_Parse_Log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    original_query  TEXT NOT NULL,
    parsed_intent   TEXT NOT NULL DEFAULT '{}',   -- JSON: ParsedIntent
    confidence      REAL NOT NULL DEFAULT 0.0 CHECK (confidence BETWEEN 0 AND 1),
    routed_to       TEXT,
    was_corrected   INTEGER NOT NULL DEFAULT 0,   -- boolean
    correction      TEXT,                         -- JSON: corrected ParsedIntent
    timestamp       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nlq_timestamp
    ON NLQ_Parse_Log (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_nlq_routed
    ON NLQ_Parse_Log (routed_to);

-- ---------------------------------------------------------------------------
-- 5. Cartridge_Arbitration_Log
-- Cartridge_Arbitrator (A4). Logs conflict resolution between cartridges.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS Cartridge_Arbitration_Log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL,
    conflicting_carts   TEXT NOT NULL DEFAULT '[]',   -- JSON array of cartridge IDs
    conflict_type       TEXT NOT NULL DEFAULT 'recommendation',
    winner_cart_id      TEXT,
    resolution_method   TEXT NOT NULL DEFAULT 'priority_chain',
    domain              TEXT NOT NULL DEFAULT 'unknown',
    escalated           INTEGER NOT NULL DEFAULT 0,   -- boolean: escalated to Sovereign
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_cal_timestamp
    ON Cartridge_Arbitration_Log (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_cal_domain
    ON Cartridge_Arbitration_Log (domain);

-- ---------------------------------------------------------------------------
-- 6. Offline_Mode_Log
-- Offline_Mode (A3). Tracks connectivity state changes and degradation.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS Offline_Mode_Log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    previous_state  TEXT NOT NULL,
    new_state       TEXT NOT NULL,
    tiers_available TEXT NOT NULL DEFAULT '[]',   -- JSON array of available tier numbers
    trigger_reason  TEXT,
    duration_ms     INTEGER
);

CREATE INDEX IF NOT EXISTS idx_oml_timestamp
    ON Offline_Mode_Log (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_oml_state
    ON Offline_Mode_Log (new_state);
