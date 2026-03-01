-- 20260301_01_cognitive_core_tables.sql  (v2 — patched)
-- Fixes: (1) migrations table guard, (2) FK constraint on wisdom_application_log
PRAGMA foreign_keys = OFF;
BEGIN TRANSACTION;
-- migrations guard (required by final INSERT)
CREATE TABLE IF NOT EXISTS migrations (
    schema_version INTEGER PRIMARY KEY
);
-- 1) Tracks loaded cartridges
CREATE TABLE IF NOT EXISTS cognitive_cartridge_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    cartridge_id TEXT NOT NULL UNIQUE,
    domain TEXT NOT NULL,
    version TEXT NOT NULL,
    rule_count INTEGER NOT NULL DEFAULT 0,
    last_loaded_at DATETIME,
    is_active BOOLEAN NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_cognitive_cartridge_registry_domain
    ON cognitive_cartridge_registry(domain);
CREATE INDEX IF NOT EXISTS idx_cognitive_cartridge_registry_is_active
    ON cognitive_cartridge_registry(is_active);
-- 2) Psychological snapshot
CREATE TABLE IF NOT EXISTS sovereign_model_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    session_id TEXT NOT NULL,
    need_name TEXT NOT NULL,
    intensity_score REAL NOT NULL,
    evidence TEXT,
    updated_at DATETIME
);
CREATE INDEX IF NOT EXISTS idx_sovereign_model_state_session_id
    ON sovereign_model_state(session_id);
CREATE INDEX IF NOT EXISTS idx_sovereign_model_state_need_name
    ON sovereign_model_state(need_name);
-- 3) Logs every triggered insight
CREATE TABLE IF NOT EXISTS insight_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    session_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    cartridge_id TEXT NOT NULL,
    insight_text TEXT NOT NULL,
    confidence REAL,
    sovereign_need TEXT,
    tags TEXT
);
CREATE INDEX IF NOT EXISTS idx_insight_journal_session_id
    ON insight_journal(session_id);
CREATE INDEX IF NOT EXISTS idx_insight_journal_cartridge_id
    ON insight_journal(cartridge_id);
CREATE INDEX IF NOT EXISTS idx_insight_journal_rule_id
    ON insight_journal(rule_id);
CREATE INDEX IF NOT EXISTS idx_insight_journal_created_at
    ON insight_journal(created_at);
-- 4) Tracks which insights led to action
--    FK added: insight_journal_id → insight_journal(id)
CREATE TABLE IF NOT EXISTS wisdom_application_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    insight_journal_id INTEGER NOT NULL
        REFERENCES insight_journal(id) ON DELETE CASCADE,
    action_taken TEXT NOT NULL,
    outcome_rating INTEGER,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_wisdom_application_log_insight_journal_id
    ON wisdom_application_log(insight_journal_id);
-- 5) Creative output tracking
CREATE TABLE IF NOT EXISTS idea_generation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    session_id TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    generated_idea TEXT NOT NULL,
    cartridge_sources TEXT,
    quality_score REAL
);
CREATE INDEX IF NOT EXISTS idx_idea_generation_log_session_id
    ON idea_generation_log(session_id);
CREATE INDEX IF NOT EXISTS idx_idea_generation_log_created_at
    ON idea_generation_log(created_at);
-- 6) End-of-session synthesis
CREATE TABLE IF NOT EXISTS reflection_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    session_id TEXT NOT NULL,
    synthesis_summary TEXT NOT NULL,
    needs_served TEXT,
    tensions_identified TEXT,
    recommended_followup TEXT
);
CREATE INDEX IF NOT EXISTS idx_reflection_journal_session_id
    ON reflection_journal(session_id);
CREATE INDEX IF NOT EXISTS idx_reflection_journal_created_at
    ON reflection_journal(created_at);
-- Record schema version
INSERT INTO migrations (schema_version)
VALUES ((SELECT COALESCE(MAX(schema_version), 0) + 1 FROM migrations));
COMMIT;
