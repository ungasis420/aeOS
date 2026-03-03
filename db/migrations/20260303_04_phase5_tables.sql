-- aeOS Phase 5 — Addendum A Tables Migration (A7-A8)
-- File: db/migrations/20260303_04_phase5_tables.sql
-- Run AFTER: 20260303_03_phase4_tables.sql
--
-- Creates 2 tables required by Phase 5 Addendum A modules (A7-A8).
-- Zero breaking changes to existing schema.
--
-- Tables:
--   1. Reflection_Log   — Reflection_Engine (A7)
--   2. BlindSpot_Log    — Blind_Spot_Mapper (A8)
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- 1. Reflection_Log
-- Reflection_Engine (A7). Stores scheduled and ad-hoc reflection reports.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS Reflection_Log (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    period                  TEXT NOT NULL DEFAULT 'adhoc' CHECK (period IN ('weekly', 'monthly', 'adhoc')),
    report_json             TEXT NOT NULL DEFAULT '{}',    -- JSON: full ReflectionReport
    compound_score_at_time  REAL NOT NULL DEFAULT 0.0,
    decisions_reviewed      INTEGER NOT NULL DEFAULT 0,
    top_patterns            TEXT NOT NULL DEFAULT '[]',    -- JSON array of pattern strings
    failed_outcomes         TEXT NOT NULL DEFAULT '[]',    -- JSON array of FailureItem dicts
    cartridges_most_fired   TEXT NOT NULL DEFAULT '[]',    -- JSON array of cartridge IDs
    recommended_focus       TEXT,
    generated_at            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rl_period
    ON Reflection_Log (period);
CREATE INDEX IF NOT EXISTS idx_rl_generated
    ON Reflection_Log (generated_at DESC);

-- ---------------------------------------------------------------------------
-- 2. BlindSpot_Log
-- Blind_Spot_Mapper (A8). Tracks blind spot analyses over time.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS BlindSpot_Log (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_date           TEXT NOT NULL,
    underweighted_domains   TEXT NOT NULL DEFAULT '[]',    -- JSON array of domain strings
    avoided_patterns        TEXT NOT NULL DEFAULT '[]',    -- JSON array of pattern strings
    cartridges_never_fired  TEXT NOT NULL DEFAULT '[]',    -- JSON array of cartridge IDs
    suggested_focus         TEXT NOT NULL DEFAULT '[]',    -- JSON array of focus strings
    acknowledged            INTEGER NOT NULL DEFAULT 0     -- boolean: 0/1
);

CREATE INDEX IF NOT EXISTS idx_bsl_date
    ON BlindSpot_Log (analysis_date DESC);
CREATE INDEX IF NOT EXISTS idx_bsl_acknowledged
    ON BlindSpot_Log (acknowledged);
