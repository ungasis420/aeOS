-- v9.0 Foundation Tables
-- Creates 5 tables for compound intelligence, cartridge performance,
-- cognitive twin state, causal graph, and cartridge evolution proposals.

PRAGMA foreign_keys = OFF;

BEGIN TRANSACTION;

-- Guard: use existing migrations table schema (schema_version INTEGER PK)
-- Schema version 2 = v9.0 foundation tables
INSERT OR IGNORE INTO migrations (schema_version) VALUES (2);

-- 1. Compound_Intelligence_Log
CREATE TABLE IF NOT EXISTS compound_intelligence_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL,
    context TEXT,
    cartridges_fired TEXT,
    reasoning_summary TEXT,
    confidence REAL,
    domain TEXT,
    outcome TEXT,
    feedback_score REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cil_decision_id ON compound_intelligence_log(decision_id);
CREATE INDEX IF NOT EXISTS idx_cil_domain ON compound_intelligence_log(domain);
CREATE INDEX IF NOT EXISTS idx_cil_created_at ON compound_intelligence_log(created_at);

-- 2. Cartridge_Performance_Log
CREATE TABLE IF NOT EXISTS cartridge_performance_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cartridge_id TEXT NOT NULL,
    domain TEXT,
    invocation_count INTEGER NOT NULL DEFAULT 0,
    avg_confidence REAL,
    avg_latency_ms REAL,
    success_rate REAL,
    last_invoked_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cpl_cartridge_id ON cartridge_performance_log(cartridge_id);
CREATE INDEX IF NOT EXISTS idx_cpl_domain ON cartridge_performance_log(domain);

-- 3. Cognitive_Twin_State
CREATE TABLE IF NOT EXISTS cognitive_twin_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    state_blob TEXT NOT NULL,
    encrypted INTEGER NOT NULL DEFAULT 0,
    checksum TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cts_session_id ON cognitive_twin_state(session_id);

-- 4. Causal_Graph_Log
CREATE TABLE IF NOT EXISTS causal_graph_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cause_node TEXT NOT NULL,
    effect_node TEXT NOT NULL,
    edge_weight REAL NOT NULL DEFAULT 0.0,
    evidence TEXT,
    domain TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cgl_cause ON causal_graph_log(cause_node);
CREATE INDEX IF NOT EXISTS idx_cgl_effect ON causal_graph_log(effect_node);

-- 5. Cartridge_Evolution_Proposals
CREATE TABLE IF NOT EXISTS cartridge_evolution_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cartridge_id TEXT NOT NULL,
    proposal_type TEXT NOT NULL,
    description TEXT,
    proposed_change TEXT,
    impact_estimate TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cep_cartridge_id ON cartridge_evolution_proposals(cartridge_id);
CREATE INDEX IF NOT EXISTS idx_cep_status ON cartridge_evolution_proposals(status);

COMMIT;

PRAGMA foreign_keys = ON;
