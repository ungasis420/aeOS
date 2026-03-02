-- aeOS v9.0 — New Tables Migration
-- File: db/migrations/20260302_02_v9_foundation_tables.sql
-- Run AFTER: 20260301_01_cognitive_core_tables_fixed.sql
--
-- Creates 4 new tables required by v9.0 initializations.
-- Data starts accumulating immediately — schema must exist before first write.
-- These tables are empty on creation; they fill as aeOS is used.
--
-- Tables:
--   1. Compound_Intelligence_Log     — Flywheel Logger (F3.6) — decisions + outcomes
--   2. Cartridge_Performance_Log     — per-cartridge effectiveness tracking
--   3. Cognitive_Twin_State          — Cognitive Digital Twin (F2.5) — longitudinal model
--   4. Causal_Graph_Log              — Causal Inference Engine (F1.6) — causal edges
--   5. Cartridge_Evolution_Proposals — Autonomous Cartridge Gen (F3.7) — gap drafts
-- ---------------------------------------------------------------------------
-- ---------------------------------------------------------------------------
-- 1. Compound_Intelligence_Log
-- The flywheel. Every decision + outcome = raw material for compounding.
-- Append-only (no UPDATE except outcome fields). Never DELETE.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS Compound_Intelligence_Log (
    id                  SERIAL          PRIMARY KEY,
    decision_id         UUID            NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    event_type          VARCHAR(50)     NOT NULL DEFAULT 'DECISION_MADE',
    -- Decision fields (set at creation)
    timestamp           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    context             TEXT            NOT NULL,
    cartridges_fired    JSONB           NOT NULL DEFAULT '[]',
    cartridge_count     INTEGER         NOT NULL DEFAULT 0,
    reasoning_summary   TEXT,
    confidence          NUMERIC(5,4)    NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    domain              VARCHAR(50)     NOT NULL DEFAULT 'unknown',
    session_id          UUID,
    metadata            JSONB           NOT NULL DEFAULT '{}',
    -- Outcome fields (updated when outcome known — only these fields)
    outcome_recorded    BOOLEAN         NOT NULL DEFAULT FALSE,
    outcome_description TEXT,
    outcome_valence     SMALLINT        CHECK (outcome_valence IN (-1, 0, 1)),
    outcome_magnitude   NUMERIC(4,3)    CHECK (outcome_magnitude BETWEEN 0 AND 1),
    outcome_timestamp   TIMESTAMPTZ,
    -- Encryption (F0.3 — CryptoGuard encrypts sensitive fields)
    is_encrypted        BOOLEAN         NOT NULL DEFAULT FALSE,
    -- Constraints
    CONSTRAINT valid_domain CHECK (domain IN (
        'business', 'finance', 'health', 'relationships',
        'career', 'creative', 'learning', 'personal', 'unknown'
    )),
    CONSTRAINT outcome_consistency CHECK (
        (outcome_recorded = FALSE) OR
        (outcome_recorded = TRUE AND outcome_valence IS NOT NULL)
    )
);
-- Indexes for FlywheelLogger queries
CREATE INDEX IF NOT EXISTS idx_cil_domain
    ON Compound_Intelligence_Log (domain);
CREATE INDEX IF NOT EXISTS idx_cil_timestamp
    ON Compound_Intelligence_Log (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_cil_outcome_recorded
    ON Compound_Intelligence_Log (outcome_recorded)
    WHERE outcome_recorded = TRUE;
CREATE INDEX IF NOT EXISTS idx_cil_session
    ON Compound_Intelligence_Log (session_id)
    WHERE session_id IS NOT NULL;
COMMENT ON TABLE Compound_Intelligence_Log IS
    'Flywheel Logger (F3.6). Append-only log of decisions and outcomes. '
    'Never delete records — they compound. '
    'Feeds: Causal Inference (F1.6), Cognitive Twin (F2.5), Predictive Life Engine (F1.1).';
-- ---------------------------------------------------------------------------
-- 2. Cartridge_Performance_Log
-- Per-cartridge effectiveness tracking for gap detection (F3.7).
-- Linked to Compound_Intelligence_Log via decision_id.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS Cartridge_Performance_Log (
    id              SERIAL          PRIMARY KEY,
    event_type      VARCHAR(50)     NOT NULL DEFAULT 'CARTRIDGE_PERFORMANCE',
    timestamp       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    cartridge_id    VARCHAR(200)    NOT NULL,
    decision_id     UUID            REFERENCES Compound_Intelligence_Log(decision_id) ON DELETE SET NULL,
    relevance_score NUMERIC(4,3)    NOT NULL CHECK (relevance_score BETWEEN 0 AND 1),
    was_accepted    BOOLEAN         NOT NULL,
    domain          VARCHAR(50)     NOT NULL DEFAULT 'unknown',
    CONSTRAINT valid_domain CHECK (domain IN (
        'business', 'finance', 'health', 'relationships',
        'career', 'creative', 'learning', 'personal', 'unknown'
    ))
);
CREATE INDEX IF NOT EXISTS idx_cpl_cartridge_id
    ON Cartridge_Performance_Log (cartridge_id);
CREATE INDEX IF NOT EXISTS idx_cpl_domain
    ON Cartridge_Performance_Log (domain);
CREATE INDEX IF NOT EXISTS idx_cpl_was_accepted
    ON Cartridge_Performance_Log (was_accepted);
COMMENT ON TABLE Cartridge_Performance_Log IS
    'Per-cartridge effectiveness log. '
    'Feeds Autonomous Cartridge Generation (F3.7) gap detection. '
    'Linked to Compound_Intelligence_Log for outcome correlation.';
-- ---------------------------------------------------------------------------
-- 3. Cognitive_Twin_State
-- The running model of your reasoning patterns.
-- Populated by Cognitive Digital Twin (F2.5) — Month 2.
-- Table must exist now so early decision data can be structured for it.
-- One row per domain per snapshot period (updated, not appended).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS Cognitive_Twin_State (
    id                      SERIAL          PRIMARY KEY,
    snapshot_timestamp      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    domain                  VARCHAR(50)     NOT NULL DEFAULT 'global',
    -- Reasoning pattern model (JSON — schema evolves with F2.5 implementation)
    decision_tendencies     JSONB           NOT NULL DEFAULT '{}',
    risk_tolerance          JSONB           NOT NULL DEFAULT '{}',
    energy_decision_map     JSONB           NOT NULL DEFAULT '{}',
    blind_spots             JSONB           NOT NULL DEFAULT '{}',
    strengths               JSONB           NOT NULL DEFAULT '{}',
    cognitive_biases        JSONB           NOT NULL DEFAULT '{}',
    -- Model quality metrics
    data_points_used        INTEGER         NOT NULL DEFAULT 0,
    model_confidence        NUMERIC(4,3)    CHECK (model_confidence BETWEEN 0 AND 1),
    training_horizon_days   INTEGER         NOT NULL DEFAULT 0,
    -- Encryption (F0.3 — cognitive model is most sensitive data)
    is_encrypted            BOOLEAN         NOT NULL DEFAULT FALSE,
    encryption_key_hash     VARCHAR(64),     -- hash of key used (never the key itself)
    -- Versioning
    model_version           VARCHAR(20)     NOT NULL DEFAULT 'v0.0.0',
    superseded_by           INTEGER         REFERENCES Cognitive_Twin_State(id)
);
CREATE INDEX IF NOT EXISTS idx_cts_domain
    ON Cognitive_Twin_State (domain);
CREATE INDEX IF NOT EXISTS idx_cts_snapshot
    ON Cognitive_Twin_State (snapshot_timestamp DESC);
COMMENT ON TABLE Cognitive_Twin_State IS
    'Cognitive Digital Twin (F2.5) state snapshots. '
    'Running model of Sovereign reasoning patterns. '
    'Populated Month 2+. Schema must exist now for data contracts. '
    'This is the most sensitive table — always encrypted (F0.3).';
-- ---------------------------------------------------------------------------
-- 4. Causal_Graph_Log
-- Causal edges identified by Causal Inference Engine (F1.6).
-- Populated Month 1+ after sufficient decision data accumulates.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS Causal_Graph_Log (
    id                      SERIAL          PRIMARY KEY,
    detected_timestamp      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    -- Causal edge
    cause_variable          VARCHAR(200)    NOT NULL,
    effect_variable         VARCHAR(200)    NOT NULL,
    domain                  VARCHAR(50)     NOT NULL DEFAULT 'unknown',
    -- Statistical evidence
    effect_size             NUMERIC(6,4),
    confidence              NUMERIC(4,3)    CHECK (confidence BETWEEN 0 AND 1),
    sample_count            INTEGER         NOT NULL DEFAULT 0,
    causal_strength         VARCHAR(20)     NOT NULL DEFAULT 'unknown'
                            CHECK (causal_strength IN ('strong', 'moderate', 'weak', 'unknown')),
    -- Evidence chain
    supporting_decision_ids JSONB           NOT NULL DEFAULT '[]',
    statistical_method      VARCHAR(100),
    confounders_controlled  JSONB           NOT NULL DEFAULT '[]',
    -- Versioning (edges update as more data arrives)
    is_current              BOOLEAN         NOT NULL DEFAULT TRUE,
    superseded_at           TIMESTAMPTZ,
    CONSTRAINT valid_domain CHECK (domain IN (
        'business', 'finance', 'health', 'relationships',
        'career', 'creative', 'learning', 'personal', 'unknown'
    ))
);
CREATE INDEX IF NOT EXISTS idx_cgl_cause
    ON Causal_Graph_Log (cause_variable);
CREATE INDEX IF NOT EXISTS idx_cgl_effect
    ON Causal_Graph_Log (effect_variable);
CREATE INDEX IF NOT EXISTS idx_cgl_domain
    ON Causal_Graph_Log (domain);
CREATE INDEX IF NOT EXISTS idx_cgl_current
    ON Causal_Graph_Log (is_current)
    WHERE is_current = TRUE;
COMMENT ON TABLE Causal_Graph_Log IS
    'Causal edges from Causal Inference Engine (F1.6). '
    'Not correlation — actual causal relationships in YOUR data. '
    'Populated after 30+ decisions with outcomes. '
    'Feeds Cognitive Twin (F2.5) and Predictive Life Engine (F1.1).';
-- ---------------------------------------------------------------------------
-- 5. Cartridge_Evolution_Proposals
-- Draft cartridges proposed by Autonomous Cartridge Generation (F3.7).
-- Human review required before deployment (never auto-deploy).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS Cartridge_Evolution_Proposals (
    id                      SERIAL          PRIMARY KEY,
    proposed_timestamp      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    -- Proposal identity
    cartridge_id            VARCHAR(200)    NOT NULL UNIQUE,
    cartridge_name          VARCHAR(200)    NOT NULL,
    domain                  VARCHAR(50)     NOT NULL DEFAULT 'unknown',
    -- Gap that triggered this proposal
    gap_description         TEXT            NOT NULL,
    gap_frequency           INTEGER         NOT NULL DEFAULT 0,
    gap_estimated_impact    NUMERIC(4,3)    CHECK (gap_estimated_impact BETWEEN 0 AND 1),
    -- Draft content (JSON — matches cartridge schema)
    draft_content           JSONB           NOT NULL DEFAULT '{}',
    core_principles         JSONB           NOT NULL DEFAULT '[]',
    decision_heuristics     JSONB           NOT NULL DEFAULT '[]',
    -- Generation metadata
    generated_from_decisions JSONB          NOT NULL DEFAULT '[]',
    generation_confidence   NUMERIC(4,3)    CHECK (generation_confidence BETWEEN 0 AND 1),
    generation_method       VARCHAR(100)    NOT NULL DEFAULT 'gap_analysis_v1',
    -- 4-Gate validation results
    gate_1_safe             BOOLEAN,
    gate_2_true             BOOLEAN,
    gate_3_leverage         BOOLEAN,
    gate_4_aligned          BOOLEAN,
    validation_notes        TEXT,
    -- Status workflow
    status                  VARCHAR(20)     NOT NULL DEFAULT 'draft'
                            CHECK (status IN ('draft', 'validated', 'deployed', 'rejected', 'deprecated')),
    reviewed_at             TIMESTAMPTZ,
    reviewed_by             VARCHAR(100),
    deployed_at             TIMESTAMPTZ,
    rejection_reason        TEXT,
    human_review_required   BOOLEAN         NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_cep_status
    ON Cartridge_Evolution_Proposals (status);
CREATE INDEX IF NOT EXISTS idx_cep_domain
    ON Cartridge_Evolution_Proposals (domain);
CREATE INDEX IF NOT EXISTS idx_cep_pending
    ON Cartridge_Evolution_Proposals (status)
    WHERE status IN ('draft', 'validated');
COMMENT ON TABLE Cartridge_Evolution_Proposals IS
    'Autonomous Cartridge Generation (F3.7) proposals. '
    'Never auto-deploy — human_review_required always TRUE. '
    'This table enables the self-improving loop: '
    'gap detected → draft → 4-Gate → human review → deploy → better reasoning.';
-- ---------------------------------------------------------------------------
-- Verification query — run after migration to confirm tables exist
-- ---------------------------------------------------------------------------
SELECT
    table_name,
    (SELECT COUNT(*) FROM information_schema.columns
     WHERE table_name = t.table_name
     AND table_schema = 'public') as column_count
FROM (VALUES
    ('Compound_Intelligence_Log'),
    ('Cartridge_Performance_Log'),
    ('Cognitive_Twin_State'),
    ('Causal_Graph_Log'),
    ('Cartridge_Evolution_Proposals')
) AS t(table_name)
ORDER BY table_name;
