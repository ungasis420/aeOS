-- aeOS_PERSIST_v1.0.sql
-- SQLite-only persistence layer for aeOS v8.4 (Blueprint A.1–A.17) + Code Tables (Appendix B).
-- Confirmed read: aeOS_Master_Blueprint_v8.4_FINAL.docx (schemas/validations/code tables) + aeOS_Build_Spec_v2.0.md (phase registry/conventions).
-- NOTE: Schemas A.14–A.17 are defined in this file but commented out for activation deferral (per Blueprint Module 10.14.5).
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL; -- safer concurrent reads/writes for PWA-style local usage
PRAGMA synchronous = NORMAL;
BEGIN TRANSACTION;
-- Idempotent reset (drop in dependency-safe order)
DROP VIEW IF EXISTS "Portfolio_Health";
DROP TABLE IF EXISTS "Project_Execution_Log";
DROP TABLE IF EXISTS "Calibration_Ledger";
DROP TABLE IF EXISTS "Mental_Models_Registry";
DROP TABLE IF EXISTS "Synergy_Map";
DROP TABLE IF EXISTS "Decision_Tree_Log";
DROP TABLE IF EXISTS "Scenario_Map";
DROP TABLE IF EXISTS "Bias_Audit_Log";
DROP TABLE IF EXISTS "Prediction_Registry";
DROP TABLE IF EXISTS "Non_Monetary_Ledger";
DROP TABLE IF EXISTS "Solution_Design";
DROP TABLE IF EXISTS "Pain_Point_Register";
DROP TABLE IF EXISTS "MoneyScan_Records";
DROP TABLE IF EXISTS "CT_Suggestion_Type";
DROP TABLE IF EXISTS "CT_Exec_Status";
DROP TABLE IF EXISTS "CT_Reversibility";
DROP TABLE IF EXISTS "CT_Loop_Speed";
DROP TABLE IF EXISTS "CT_Loop_Polarity";
DROP TABLE IF EXISTS "CT_Feedback_Type";
DROP TABLE IF EXISTS "CT_MM_Category";
DROP TABLE IF EXISTS "CT_Bias";
DROP TABLE IF EXISTS "CT_NM_Type";
DROP TABLE IF EXISTS "CT_Pain_Status";
DROP TABLE IF EXISTS "CT_Sol_Status";
DROP TABLE IF EXISTS "CT_Sol_Type";
DROP TABLE IF EXISTS "CT_Scenario";
DROP TABLE IF EXISTS "CT_Cog_State";
DROP TABLE IF EXISTS "CT_Outcome";
DROP TABLE IF EXISTS "CT_Horizon";
DROP TABLE IF EXISTS "CT_Complexity";
DROP TABLE IF EXISTS "CT_Impact";
DROP TABLE IF EXISTS "CT_Phase";
DROP TABLE IF EXISTS "CT_Freq";
DROP TABLE IF EXISTS "CT_Priority";
DROP TABLE IF EXISTS "CT_Source";
DROP TABLE IF EXISTS "CT_Rev_Model";
DROP TABLE IF EXISTS "CT_Category";
DROP TABLE IF EXISTS "CT_Stage";
-- ----------------------------------------------
-- Code Tables (Appendix B) — seeded reference data
-- ----------------------------------------------
CREATE TABLE "CT_Stage" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Category" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Rev_Model" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Source" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Priority" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Freq" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Phase" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Impact" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Complexity" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Horizon" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Outcome" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Cog_State" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Scenario" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Sol_Type" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Sol_Status" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Pain_Status" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_NM_Type" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Bias" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_MM_Category" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Feedback_Type" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Loop_Polarity" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Loop_Speed" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Reversibility" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Exec_Status" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
CREATE TABLE "CT_Suggestion_Type" (
  "Value" TEXT PRIMARY KEY,
  "Description" TEXT,
  "Sort_Order" INTEGER NOT NULL,
  "Is_Active" INTEGER NOT NULL DEFAULT 1 CHECK ("Is_Active" IN (0,1)),
  "Notes" TEXT
);
-- Seed values for all CT_* tables (Blueprint Appendix B)
INSERT INTO "CT_Stage" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Idea', NULL, 1, 1, NULL),
  ('Research', NULL, 2, 1, NULL),
  ('Validation', NULL, 3, 1, NULL),
  ('Build', NULL, 4, 1, NULL),
  ('Launch', NULL, 5, 1, NULL),
  ('Scale', NULL, 6, 1, NULL),
  ('Kill', NULL, 7, 1, NULL),
  ('Paused', NULL, 8, 1, NULL);
INSERT INTO "CT_Category" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('SaaS', NULL, 1, 1, NULL),
  ('Service', NULL, 2, 1, NULL),
  ('Content', NULL, 3, 1, NULL),
  ('Community', NULL, 4, 1, NULL),
  ('Physical', NULL, 5, 1, NULL),
  ('Marketplace', NULL, 6, 1, NULL),
  ('Tool', NULL, 7, 1, NULL),
  ('Framework', NULL, 8, 1, NULL),
  ('Other', NULL, 9, 1, NULL);
INSERT INTO "CT_Rev_Model" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Subscription', NULL, 1, 1, NULL),
  ('One_Time', NULL, 2, 1, NULL),
  ('Usage', NULL, 3, 1, NULL),
  ('Freemium', NULL, 4, 1, NULL),
  ('Marketplace', NULL, 5, 1, NULL),
  ('Sponsorship', NULL, 6, 1, NULL),
  ('Licensing', NULL, 7, 1, NULL),
  ('Hybrid', NULL, 8, 1, NULL),
  ('None', NULL, 9, 1, NULL);
INSERT INTO "CT_Source" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Personal_Pain', NULL, 1, 1, NULL),
  ('Market_Signal', NULL, 2, 1, NULL),
  ('User_Interview', NULL, 3, 1, NULL),
  ('Competitor', NULL, 4, 1, NULL),
  ('AI_Suggestion', NULL, 5, 1, NULL),
  ('Serendipity', NULL, 6, 1, NULL),
  ('Other', NULL, 7, 1, NULL);
INSERT INTO "CT_Priority" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('P1_Critical', NULL, 1, 1, NULL),
  ('P2_High', NULL, 2, 1, NULL),
  ('P3_Medium', NULL, 3, 1, NULL),
  ('P4_Low', NULL, 4, 1, NULL);
INSERT INTO "CT_Freq" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Daily', NULL, 1, 1, NULL),
  ('Weekly', NULL, 2, 1, NULL),
  ('Monthly', NULL, 3, 1, NULL),
  ('Occasional', NULL, 4, 1, NULL),
  ('Rare', NULL, 5, 1, NULL);
INSERT INTO "CT_Phase" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Phase_0', NULL, 1, 1, NULL),
  ('Phase_1', NULL, 2, 1, NULL),
  ('Phase_2', NULL, 3, 1, NULL),
  ('Phase_3', NULL, 4, 1, NULL),
  ('Phase_4', NULL, 5, 1, NULL),
  ('Phase_5', NULL, 6, 1, NULL),
  ('Phase_6', NULL, 7, 1, NULL);
INSERT INTO "CT_Impact" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Low', NULL, 1, 1, NULL),
  ('Medium', NULL, 2, 1, NULL),
  ('High', NULL, 3, 1, NULL),
  ('Transformative', NULL, 4, 1, NULL);
INSERT INTO "CT_Complexity" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Low', NULL, 1, 1, NULL),
  ('Medium', NULL, 2, 1, NULL),
  ('High', NULL, 3, 1, NULL),
  ('Very_High', NULL, 4, 1, NULL);
INSERT INTO "CT_Horizon" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('30d', NULL, 1, 1, NULL),
  ('90d', NULL, 2, 1, NULL),
  ('6m', NULL, 3, 1, NULL),
  ('1y', NULL, 4, 1, NULL),
  ('2y+', NULL, 5, 1, NULL);
INSERT INTO "CT_Outcome" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Correct', NULL, 1, 1, NULL),
  ('Incorrect', NULL, 2, 1, NULL),
  ('Partial', NULL, 3, 1, NULL),
  ('Unresolved', NULL, 4, 1, NULL);
INSERT INTO "CT_Cog_State" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Focused', NULL, 1, 1, NULL),
  ('Fatigued', NULL, 2, 1, NULL),
  ('Stressed', NULL, 3, 1, NULL),
  ('Euphoric', NULL, 4, 1, NULL),
  ('Neutral', NULL, 5, 1, NULL),
  ('Anxious', NULL, 6, 1, NULL);
INSERT INTO "CT_Scenario" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Best', NULL, 1, 1, NULL),
  ('Base', NULL, 2, 1, NULL),
  ('Worst', NULL, 3, 1, NULL),
  ('BlackSwan', NULL, 4, 1, NULL);
INSERT INTO "CT_Sol_Type" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Product', NULL, 1, 1, NULL),
  ('Service', NULL, 2, 1, NULL),
  ('Content', NULL, 3, 1, NULL),
  ('System', NULL, 4, 1, NULL),
  ('Community', NULL, 5, 1, NULL),
  ('Tool', NULL, 6, 1, NULL),
  ('Framework', NULL, 7, 1, NULL);
INSERT INTO "CT_Sol_Status" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Concept', NULL, 1, 1, NULL),
  ('Designing', NULL, 2, 1, NULL),
  ('Validated', NULL, 3, 1, NULL),
  ('Building', NULL, 4, 1, NULL),
  ('Live', NULL, 5, 1, NULL),
  ('Shelved', NULL, 6, 1, NULL);
INSERT INTO "CT_Pain_Status" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Active', NULL, 1, 1, NULL),
  ('Solved', NULL, 2, 1, NULL),
  ('Abandoned', NULL, 3, 1, NULL),
  ('Monitoring', NULL, 4, 1, NULL);
INSERT INTO "CT_NM_Type" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Skill', NULL, 1, 1, NULL),
  ('Relationship', NULL, 2, 1, NULL),
  ('Knowledge', NULL, 3, 1, NULL),
  ('Reputation', NULL, 4, 1, NULL),
  ('Optionality', NULL, 5, 1, NULL),
  ('Confidence', NULL, 6, 1, NULL),
  ('Other', NULL, 7, 1, NULL);
INSERT INTO "CT_Bias" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Confirmation_Bias', NULL, 1, 1, NULL),
  ('Availability_Heuristic', NULL, 2, 1, NULL),
  ('Survivorship_Bias', NULL, 3, 1, NULL),
  ('Sunk_Cost_Fallacy', NULL, 4, 1, NULL),
  ('Dunning_Kruger', NULL, 5, 1, NULL),
  ('Loss_Aversion', NULL, 6, 1, NULL),
  ('Optimism_Bias', NULL, 7, 1, NULL),
  ('Anchoring', NULL, 8, 1, NULL),
  ('Recency_Bias', NULL, 9, 1, NULL),
  ('Planning_Fallacy', NULL, 10, 1, NULL),
  ('Hindsight_Bias', NULL, 11, 1, NULL),
  ('Status_Quo_Bias', NULL, 12, 1, NULL),
  ('Narrative_Fallacy', NULL, 13, 1, NULL),
  ('Overconfidence', NULL, 14, 1, NULL),
  ('Other', NULL, 15, 1, NULL);
INSERT INTO "CT_MM_Category" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Systems', NULL, 1, 1, NULL),
  ('Thinking', NULL, 2, 1, NULL),
  ('Decision', NULL, 3, 1, NULL),
  ('Psychology', NULL, 4, 1, NULL),
  ('Economics', NULL, 5, 1, NULL),
  ('Science', NULL, 6, 1, NULL),
  ('Other', NULL, 7, 1, NULL);
INSERT INTO "CT_Feedback_Type" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Reinforcing', NULL, 1, 1, NULL),
  ('Balancing', NULL, 2, 1, NULL),
  ('None', NULL, 3, 1, NULL);
INSERT INTO "CT_Loop_Polarity" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Positive', NULL, 1, 1, NULL),
  ('Negative', NULL, 2, 1, NULL),
  ('Neutral', NULL, 3, 1, NULL);
INSERT INTO "CT_Loop_Speed" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Immediate', NULL, 1, 1, NULL),
  ('Days', NULL, 2, 1, NULL),
  ('Weeks', NULL, 3, 1, NULL),
  ('Months', NULL, 4, 1, NULL),
  ('Years', NULL, 5, 1, NULL);
INSERT INTO "CT_Reversibility" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Type1_Irreversible', NULL, 1, 1, NULL),
  ('Type2_Reversible', NULL, 2, 1, NULL);
INSERT INTO "CT_Exec_Status" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Not_Started', 'Task created but work has not begun', 1, 1, NULL),
  ('In_Progress', 'Task is actively being worked on', 2, 1, NULL),
  ('Blocked', 'Work cannot proceed due to an impediment', 3, 1, NULL),
  ('Completed', 'Task fully done', 4, 1, NULL),
  ('Cancelled', 'Task will not be completed', 5, 1, NULL),
  ('Deferred', 'Task intentionally postponed', 6, 1, NULL);
INSERT INTO "CT_Suggestion_Type" ("Value", "Description", "Sort_Order", "Is_Active", "Notes") VALUES
  ('Schema_Change', 'Structural modification to an existing schema (add/remove/rename field)', 1, 1, NULL),
  ('Field_Addition', 'Add a new field to an existing schema', 2, 1, NULL),
  ('Validation_Rule', 'Add or modify a validation rule (V-series)', 3, 1, NULL),
  ('Query_Enhancement', 'Improve or add to query specifications (D-series)', 4, 1, NULL),
  ('Code_Table_Update', 'Add values to an existing code table or create new code table', 5, 1, NULL),
  ('Other', 'All other suggestion types', 6, 1, NULL);
-- ----------------------------------------------
-- Core Schemas (A.1–A.13) — active
-- ----------------------------------------------
-- A.2 Pain_Point_Register (NEW v7.5)
CREATE TABLE "Pain_Point_Register" (
  "Pain_ID" TEXT PRIMARY KEY CHECK ("Pain_ID" GLOB 'PAIN-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9]'),
  "Pain_Name" TEXT NOT NULL CHECK (length(trim("Pain_Name")) >= 1),
  "Description" TEXT NOT NULL CHECK (length(trim("Description")) >= 20),
  "Root_Cause" TEXT,
  "Affected_Population" TEXT NOT NULL,
  "Frequency" TEXT NOT NULL REFERENCES "CT_Freq"("Value"),
  "Severity" INTEGER NOT NULL CHECK ("Severity" BETWEEN 1 AND 10),
  "Impact_Score" INTEGER NOT NULL CHECK ("Impact_Score" BETWEEN 1 AND 10),
  "Monetizability_Flag" INTEGER NOT NULL CHECK ("Monetizability_Flag" IN (0,1)),
  "WTP_Estimate" REAL CHECK ("WTP_Estimate" IS NULL OR "WTP_Estimate" > 0),
  "Evidence" TEXT NOT NULL CHECK (length(trim("Evidence")) >= 10),
  "Pain_Score" REAL CHECK ("Pain_Score" IS NULL OR ("Pain_Score" BETWEEN 0 AND 100)),
  "Linked_Idea_IDs" TEXT, -- Text list (Blueprint). Keep as-is; normalize later if needed.
  "Phase_Created" TEXT NOT NULL REFERENCES "CT_Phase"("Value"),
  "Date_Identified" TEXT NOT NULL CHECK (julianday("Date_Identified") IS NOT NULL),
  "Status" TEXT NOT NULL REFERENCES "CT_Pain_Status"("Value"),
  "Validated_By" TEXT,
  "Validation_Date" TEXT CHECK ("Validation_Date" IS NULL OR (julianday("Validation_Date") IS NOT NULL AND julianday("Validation_Date") >= julianday("Date_Identified"))),
  "Notes" TEXT,
  "Created_By" TEXT,
  "Last_Updated" TEXT NOT NULL CHECK (julianday("Last_Updated") IS NOT NULL)
);
-- A.1 MoneyScan_Records (v7.0 base; full ~260 fields defined in Master Scanner)
-- Key decision: We keep ALL columns (exact names) but apply strict constraints only to core scoring + ID fields.
CREATE TABLE "MoneyScan_Records" (
  "Idea_ID" TEXT PRIMARY KEY CHECK ("Idea_ID" GLOB 'MSR-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9]'),
  "Idea_Name" TEXT NOT NULL CHECK (length(trim("Idea_Name")) >= 3),
  "Category" TEXT NOT NULL REFERENCES "CT_Category"("Value"),
  "Stage" TEXT NOT NULL REFERENCES "CT_Stage"("Value"),
  "Stage_Entry_Date" TEXT,
  "Entry_Date" TEXT NOT NULL CHECK (julianday("Entry_Date") IS NOT NULL),
  "Last_Updated" TEXT NOT NULL CHECK (julianday("Last_Updated") IS NOT NULL AND julianday("Last_Updated") >= julianday("Entry_Date")),
  "Source" TEXT NOT NULL REFERENCES "CT_Source"("Value"),
  "Revenue_Model" TEXT NOT NULL REFERENCES "CT_Rev_Model"("Value"),
  "Market_Size_Est" REAL CHECK ("Market_Size_Est" IS NULL OR "Market_Size_Est" > 0),
  "Demand_Score" REAL CHECK ("Demand_Score" IS NULL OR ("Demand_Score" BETWEEN 0 AND 100)),
  "Viability_Score" REAL CHECK ("Viability_Score" IS NULL OR ("Viability_Score" BETWEEN 0 AND 100)),
  "Interest_Score" REAL CHECK ("Interest_Score" IS NULL OR ("Interest_Score" BETWEEN 0 AND 100)),
  "Pain_ID" TEXT REFERENCES "Pain_Point_Register"("Pain_ID") ON DELETE SET NULL,
  "Pain_Score" REAL CHECK ("Pain_Score" IS NULL OR ("Pain_Score" BETWEEN 0 AND 100)),
  "Bias_Score" REAL CHECK ("Bias_Score" IS NULL OR ("Bias_Score" BETWEEN 0 AND 100)),
  "Days_Stale" INTEGER CHECK ("Days_Stale" IS NULL OR "Days_Stale" >= 0),
  "qBestMoves_v70" REAL,
  "PainM" REAL,
  "BiasM" REAL,
  "FreshM" REAL,
  "qBestMoves_v75" REAL,
  "Rank_v75" INTEGER,
  "Kill_Flag" INTEGER NOT NULL DEFAULT 0 CHECK ("Kill_Flag" IN (0,1)),
  "Kill_Rationale" TEXT,
  "Evidence_Chain" TEXT,
  "Notes" TEXT,
  "Idea_Domain_1" REAL,
  "Idea_Domain_2" REAL,
  "Idea_Domain_3" REAL,
  "Pattern_Class_1" TEXT,
  "Pattern_Class_2" TEXT,
  "Pattern_Class_3" TEXT,
  "User_Type_1" TEXT,
  "User_Type_2" TEXT,
  "User_Type_3" TEXT,
  "User_Context" TEXT,
  "Trigger_Mode" TEXT,
  "Job_Title_1" TEXT,
  "Job_Title_2" TEXT,
  "Job_Title_3" TEXT,
  "Job_Classifier" TEXT,
  "Problem_Type_1" TEXT,
  "Problem_Type_2" TEXT,
  "Problem_Type_3" TEXT,
  "Work_Context" TEXT,
  "Urgency" TEXT,
  "Current_Solution" TEXT,
  "Willingness_To_Pay" REAL,
  "Time_Saved_Hours" REAL,
  "Money_Saved" REAL,
  "Emotional_Relief" REAL,
  "Switching_Costs" REAL,
  "Competitor_1" TEXT,
  "Competitor_2" TEXT,
  "Competitor_3" TEXT,
  "Differentiation_1" TEXT,
  "Differentiation_2" TEXT,
  "Differentiation_3" TEXT,
  "Distribution_Channel_1" TEXT,
  "Distribution_Channel_2" TEXT,
  "Distribution_Channel_3" TEXT,
  "Pricing_Model_1" TEXT,
  "Pricing_Model_2" TEXT,
  "Pricing_Model_3" TEXT,
  "MVP_Feature_1" TEXT,
  "MVP_Feature_2" TEXT,
  "MVP_Feature_3" TEXT,
  "MVP_Feature_4" TEXT,
  "MVP_Feature_5" TEXT,
  "MVP_Feature_6" TEXT,
  "MVP_Feature_7" TEXT,
  "MVP_Feature_8" TEXT,
  "MVP_Feature_9" TEXT,
  "MVP_Feature_10" TEXT,
  "MVP_Feature_11" TEXT,
  "MVP_Feature_12" TEXT,
  "MVP_Feature_13" TEXT,
  "MVP_Feature_14" TEXT,
  "MVP_Feature_15" TEXT,
  "MVP_Feature_16" TEXT,
  "MVP_Feature_17" TEXT,
  "MVP_Feature_18" TEXT,
  "MVP_Feature_19" TEXT,
  "MVP_Feature_20" TEXT,
  "MVP_Feature_21" TEXT,
  "MVP_Feature_22" TEXT,
  "MVP_Feature_23" TEXT,
  "MVP_Feature_24" TEXT,
  "MVP_Feature_25" TEXT,
  "MVP_Feature_26" TEXT,
  "MVP_Feature_27" TEXT,
  "MVP_Feature_28" TEXT,
  "MVP_Feature_29" TEXT,
  "MVP_Feature_30" TEXT,
  "MVP_Feature_31" TEXT,
  "MVP_Feature_32" TEXT,
  "MVP_Feature_33" TEXT,
  "MVP_Feature_34" TEXT,
  "MVP_Feature_35" TEXT,
  "MVP_Feature_36" TEXT,
  "MVP_Feature_37" TEXT,
  "MVP_Feature_38" TEXT,
  "MVP_Feature_39" TEXT,
  "MVP_Feature_40" TEXT,
  "MVP_Feature_41" TEXT,
  "MVP_Feature_42" TEXT,
  "MVP_Feature_43" TEXT,
  "MVP_Feature_44" TEXT,
  "MVP_Feature_45" TEXT,
  "MVP_Feature_46" TEXT,
  "MVP_Feature_47" TEXT,
  "MVP_Feature_48" TEXT,
  "MVP_Feature_49" TEXT,
  "MVP_Feature_50" TEXT,
  "Market_Timing" TEXT,
  "Macro_Trend" TEXT,
  "Industry_Tailwind" TEXT,
  "Regulatory_Risk" TEXT,
  "Supply_Chain_Risk" TEXT,
  "Tech_Risk" TEXT,
  "Execution_Risk" TEXT,
  "Founder_Fit" TEXT,
  "Unique_Insight" TEXT,
  "Moat_Type_1" TEXT,
  "Moat_Type_2" TEXT,
  "Moat_Type_3" TEXT,
  "Network_Effects" TEXT,
  "Switching_Costs_Moat" TEXT,
  "Brand_Moat" TEXT,
  "Data_Moat" TEXT,
  "Scale_Economies" TEXT,
  "Distribution_Moat" TEXT,
  "Legal_Moat" TEXT,
  "Community_Moat" TEXT,
  "Operational_Moat" TEXT,
  "Time_To_MVP" TEXT,
  "Complexity_Est" REAL,
  "Time_Cost_Est" REAL,
  "Cash_Cost_Est" REAL,
  "Team_Size_Est" REAL,
  "Required_Skills" TEXT,
  "Key_Risks" TEXT,
  "Key_Assumptions" TEXT,
  "Validation_Plan" TEXT,
  "Traction_Signal" TEXT,
  "Traction_Metric_1" TEXT,
  "Traction_Metric_2" TEXT,
  "Traction_Metric_3" TEXT,
  "Traction_Metric_4" TEXT,
  "Traction_Metric_5" TEXT,
  "Traction_Metric_6" TEXT,
  "Traction_Metric_7" TEXT,
  "Traction_Metric_8" TEXT,
  "Traction_Metric_9" TEXT,
  "Traction_Metric_10" TEXT,
  "Audience_Size_Est" REAL,
  "Audience_Growth_Rate" REAL,
  "Conversion_Rate_Est" REAL,
  "Retention_Rate_Est" REAL,
  "Churn_Rate_Est" REAL,
  "ARPU_Est" REAL,
  "CAC_Est" REAL,
  "LTV_Est" REAL,
  "Margin_Est" REAL,
  "Payback_Period_Est" REAL,
  "Sales_Cycle_Est" REAL,
  "Lead_Source_1" TEXT,
  "Lead_Source_2" TEXT,
  "Lead_Source_3" TEXT,
  "Lead_Source_4" TEXT,
  "Lead_Source_5" TEXT,
  "Lead_Source_6" TEXT,
  "Lead_Source_7" TEXT,
  "Lead_Source_8" TEXT,
  "Lead_Source_9" TEXT,
  "Lead_Source_10" TEXT,
  "User_Pain_Quote_1" TEXT,
  "User_Pain_Quote_2" TEXT,
  "User_Pain_Quote_3" TEXT,
  "User_Pain_Quote_4" TEXT,
  "User_Pain_Quote_5" TEXT,
  "User_Pain_Quote_6" TEXT,
  "User_Pain_Quote_7" TEXT,
  "User_Pain_Quote_8" TEXT,
  "User_Pain_Quote_9" TEXT,
  "User_Pain_Quote_10" TEXT,
  "Customer_Segment_1" TEXT,
  "Customer_Segment_2" TEXT,
  "Customer_Segment_3" TEXT,
  "Customer_Segment_4" TEXT,
  "Customer_Segment_5" TEXT,
  "Customer_Segment_6" TEXT,
  "Customer_Segment_7" TEXT,
  "Customer_Segment_8" TEXT,
  "Customer_Segment_9" TEXT,
  "Customer_Segment_10" TEXT,
  "Pricing_Tier_1" TEXT,
  "Pricing_Tier_2" TEXT,
  "Pricing_Tier_3" TEXT,
  "Pricing_Tier_4" TEXT,
  "Pricing_Tier_5" TEXT,
  "Pricing_Tier_6" TEXT,
  "Pricing_Tier_7" TEXT,
  "Pricing_Tier_8" TEXT,
  "Pricing_Tier_9" TEXT,
  "Pricing_Tier_10" TEXT,
  "Channel_Risk" TEXT,
  "Competitive_Intensity" TEXT,
  "Market_Signal_Score" REAL,
  "Market_Signal_Score_PH" REAL,
  "Confidence_Score" REAL,
  "Differentiation_Score" REAL,
  "Freshness_Score" REAL,
  "Client_Effort_Score" REAL,
  "Layer_Synergy_Score" REAL,
  "Attractiveness_Alternative_Score" REAL,
  "Effort_Level_Alternative_Score" REAL,
  "Risk_Level_Alternative_Score" REAL,
  "Confidence_Score_Evidence" REAL,
  "Confidence_Score_Field_Confidence" REAL,
  "Confidence_Score_Alternative_Score" REAL,
  "ROI_Tier_Alternative_Score" REAL,
  "Skill_Level_Alternative_Score" REAL,
  "Energy_Cost_Alternative_Score" REAL,
  "Pain_Score_Evidence" REAL,
  "Pain_Score_Field_Confidence" REAL,
  "Pain_Score_Alternative_Score" REAL,
  "Pleasure_Score_Evidence" REAL,
  "Pleasure_Score_Field_Confidence" REAL,
  "Pleasure_Score_Alternative_Score" REAL,
  "Alignment_Score_Evidence" REAL,
  "Alignment_Score_Field_Confidence" REAL,
  "Alignment_Score_Alternative_Score" REAL,
  "Data_Quality_Score" REAL,
  "Ethics_Flag" INTEGER NOT NULL DEFAULT 0 CHECK ("Ethics_Flag" IN (0,1)),
  "PH_Relevance_Flag" INTEGER NOT NULL DEFAULT 0 CHECK ("PH_Relevance_Flag" IN (0,1)),
  "Asset_Building_Flag" INTEGER NOT NULL DEFAULT 0 CHECK ("Asset_Building_Flag" IN (0,1)),
  "Unknown_Unknowns_Flag" INTEGER NOT NULL DEFAULT 0 CHECK ("Unknown_Unknowns_Flag" IN (0,1)),
  "PH_Notes" TEXT,
  "Asset_Building_Notes" TEXT,
  "Unknown_Unknowns_Notes" TEXT,
  "Risk_Register" TEXT,
  "Mitigation_Plan" TEXT,
  "Stage_Gate_Notes" TEXT,
  "Stage_Gate_Result" TEXT,
  "Stage_Gate_Date" TEXT,
  "Stage_Gate_Reviewer" TEXT,
  "Feynman_Summary" TEXT,
  "Feynman_OneLiner" TEXT,
  "5W1H_Frame" TEXT,
  "Assumption_Map" TEXT,
  "Pre_Mortem" TEXT,
  "Bias_Checklist" TEXT,
  "Scenario_Map_Ref" TEXT,
  "Decision_Tree_Ref" TEXT,
  "Synergy_Map_Ref" TEXT,
  "NonMon_Value_Trail_Ref" TEXT,
  "Execution_Log_Ref" TEXT,
  "Evidence_Link_1" TEXT,
  "Evidence_Link_2" TEXT,
  "Evidence_Link_3" TEXT,
  "Evidence_Link_4" TEXT,
  "Evidence_Link_5" TEXT,
  "Evidence_Link_6" TEXT,
  "Evidence_Link_7" TEXT,
  "Evidence_Link_8" TEXT,
  "Evidence_Link_9" TEXT,
  "Evidence_Link_10" TEXT,
  "Critical_Mass_Estimate" INTEGER,
  "First_Mover_Advantage" REAL,
  "Competitor_Response" TEXT,
  "Value_Chain_Position" TEXT,
  "Margin_Capture_Potential" REAL,
  "Narrative_Coherence" REAL,
  "Counter_Narrative" TEXT,
  "Key_Stakeholders" TEXT,
  "Stakeholder_Alignment" REAL,
  "Cognitive_State_At_Score" REAL,
  "Excitement_Correction" REAL,
  "Fear_Correction" REAL,
  "Pre_Mortem_Notes" TEXT,
  "Devil_Advocate_Notes" TEXT,
  "Inversion_Check" TEXT,
  "Second_Order_Effects" TEXT,
  "Non_Monetary_Value_Sum" REAL,
  "Prediction_Count" INTEGER,
  "Assumptions" TEXT,
  "Constraints" TEXT,
  "Game_Theory_Notes" TEXT,
  "Value_Chain_Notes" TEXT,
  "Narrative_Notes" TEXT,
  "Opportunity_Cost_Notes" TEXT,
  "Optionality_Notes" TEXT,
  "Information_Asymmetry" TEXT,
  "Lock_In_Risk" TEXT,
  "Diminishing_Returns_Flag" INTEGER NOT NULL DEFAULT 0 CHECK ("Diminishing_Returns_Flag" IN (0,1)),
  "NonMon_Summary" TEXT,
  "NonMon_Impact" REAL,
  CHECK ("Stage_Entry_Date" IS NULL OR julianday("Stage_Entry_Date") IS NOT NULL)
);
-- A.3 Solution_Design (NEW v7.5)
CREATE TABLE "Solution_Design" (
  "Solution_ID" TEXT PRIMARY KEY CHECK ("Solution_ID" GLOB 'SOL-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9]'),
  "Pain_ID" TEXT NOT NULL REFERENCES "Pain_Point_Register"("Pain_ID") ON DELETE CASCADE,
  "Solution_Name" TEXT NOT NULL,
  "Solution_Type" TEXT NOT NULL REFERENCES "CT_Sol_Type"("Value"),
  "Description" TEXT NOT NULL CHECK (length(trim("Description")) >= 20),
  "Delivery_Mechanism" TEXT NOT NULL,
  "Complexity" TEXT NOT NULL REFERENCES "CT_Complexity"("Value"),
  "Time_To_MVP" TEXT NOT NULL,
  "Monetization_Path" TEXT REFERENCES "CT_Rev_Model"("Value"),
  "Pain_Fit_Score" REAL CHECK ("Pain_Fit_Score" IS NULL OR ("Pain_Fit_Score" BETWEEN 0 AND 10)),
  "Linked_Idea_ID" TEXT REFERENCES "MoneyScan_Records"("Idea_ID") ON DELETE SET NULL,
  "Date_Created" TEXT NOT NULL CHECK (julianday("Date_Created") IS NOT NULL),
  "Status" TEXT NOT NULL REFERENCES "CT_Sol_Status"("Value"),
  "Notes" TEXT,
  "Last_Updated" TEXT NOT NULL CHECK (julianday("Last_Updated") IS NOT NULL)
);
-- A.4 Non_Monetary_Ledger (NEW v7.5)
CREATE TABLE "Non_Monetary_Ledger" (
  "NM_ID" TEXT PRIMARY KEY CHECK ("NM_ID" GLOB 'NML-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9]'),
  "Idea_ID" TEXT REFERENCES "MoneyScan_Records"("Idea_ID") ON DELETE SET NULL,
  "Session_Date" TEXT NOT NULL CHECK (julianday("Session_Date") IS NOT NULL),
  "NM_Type" TEXT NOT NULL REFERENCES "CT_NM_Type"("Value"),
  "Description" TEXT NOT NULL CHECK (length(trim("Description")) >= 10),
  "Impact_Level" TEXT NOT NULL REFERENCES "CT_Impact"("Value"),
  "Monetization_Potential" INTEGER CHECK ("Monetization_Potential" IS NULL OR "Monetization_Potential" IN (0,1)),
  "Evidence" TEXT,
  "Notes" TEXT
);
-- A.5 Prediction_Registry (NEW v7.5)
CREATE TABLE "Prediction_Registry" (
  "Pred_ID" TEXT PRIMARY KEY CHECK ("Pred_ID" GLOB 'PRED-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9]'),
  "Idea_ID" TEXT REFERENCES "MoneyScan_Records"("Idea_ID") ON DELETE SET NULL,
  "Prediction_Text" TEXT NOT NULL,
  "Horizon" TEXT NOT NULL REFERENCES "CT_Horizon"("Value"),
  "Confidence_Pct" REAL NOT NULL CHECK ("Confidence_Pct" BETWEEN 0 AND 100),
  "Base_Rate" REAL CHECK ("Base_Rate" IS NULL OR ("Base_Rate" BETWEEN 0 AND 100)),
  "Evidence_For" TEXT NOT NULL,
  "Evidence_Against" TEXT,
  "Resolution_Criteria" TEXT NOT NULL,
  "Outcome" TEXT REFERENCES "CT_Outcome"("Value"),
  "Resolution_Date" TEXT CHECK ("Resolution_Date" IS NULL OR julianday("Resolution_Date") IS NOT NULL),
  "Calibration_Delta" REAL
);
-- A.6 Bias_Audit_Log (NEW v7.5)
CREATE TABLE "Bias_Audit_Log" (
  "Bias_ID" TEXT PRIMARY KEY,
  "Idea_ID" TEXT REFERENCES "MoneyScan_Records"("Idea_ID") ON DELETE SET NULL,
  "Session_Date" TEXT NOT NULL CHECK (julianday("Session_Date") IS NOT NULL),
  "Cognitive_State" TEXT NOT NULL REFERENCES "CT_Cog_State"("Value"),
  "Biases_Detected" TEXT NOT NULL, -- Text list (Blueprint). Store as CSV/JSON; normalize later if needed.
  "Pre_Bias_Score" REAL NOT NULL CHECK ("Pre_Bias_Score" BETWEEN 0 AND 100),
  "Bias_Score" REAL NOT NULL CHECK ("Bias_Score" BETWEEN 0 AND 100),
  "Post_Debiasing_Score" REAL CHECK ("Post_Debiasing_Score" IS NULL OR ("Post_Debiasing_Score" BETWEEN 0 AND 100)),
  "Debiasing_Actions" TEXT,
  "Recommendation" TEXT,
  "Reviewed_By" TEXT,
  "Last_Updated" TEXT NOT NULL CHECK (julianday("Last_Updated") IS NOT NULL)
);
-- A.7 Scenario_Map (NEW v7.5)
CREATE TABLE "Scenario_Map" (
  "Scenario_ID" TEXT PRIMARY KEY,
  "Idea_ID" TEXT NOT NULL REFERENCES "MoneyScan_Records"("Idea_ID") ON DELETE CASCADE,
  "Scenario_Type" TEXT NOT NULL REFERENCES "CT_Scenario"("Value"),
  "Description" TEXT NOT NULL,
  "Probability_Pct" REAL NOT NULL CHECK ("Probability_Pct" BETWEEN 0 AND 100),
  "Revenue_Impact" REAL,
  "Key_Triggers" TEXT NOT NULL,
  "Early_Signals" TEXT,
  "Strategy" TEXT NOT NULL,
  "Last_Updated" TEXT NOT NULL CHECK (julianday("Last_Updated") IS NOT NULL)
);
-- A.8 Decision_Tree_Log (v7.5 Extended — 20 fields)
CREATE TABLE "Decision_Tree_Log" (
  "Decision_ID" TEXT PRIMARY KEY,
  "Idea_ID" TEXT REFERENCES "MoneyScan_Records"("Idea_ID") ON DELETE SET NULL,
  "Decision_Date" TEXT CHECK ("Decision_Date" IS NULL OR julianday("Decision_Date") IS NOT NULL),
  "Decision_Type" TEXT NOT NULL, -- Blueprint marks as Code but does not define CT_* list in Appendix B; keep as Text.
  "Options_Considered" TEXT,
  "Selected_Option" TEXT,
  "Rationale" TEXT,
  "Confidence_Pct" REAL CHECK ("Confidence_Pct" IS NULL OR ("Confidence_Pct" BETWEEN 0 AND 100)),
  "Evidence" TEXT,
  "Assumptions" TEXT,
  "Risks" TEXT,
  "Reversibility" TEXT REFERENCES "CT_Reversibility"("Value"),
  "Stage_At_Decision" TEXT REFERENCES "CT_Stage"("Value"),
  "Outcome" TEXT,
  "Last_Updated" TEXT CHECK ("Last_Updated" IS NULL OR julianday("Last_Updated") IS NOT NULL),
  "Opportunity_Cost_Notes" TEXT,
  "Regret_Minimization_Check" INTEGER CHECK ("Regret_Minimization_Check" IS NULL OR "Regret_Minimization_Check" IN (0,1)),
  "Cognitive_State_At_Decision" TEXT REFERENCES "CT_Cog_State"("Value"),
  "Biases_Present" TEXT,
  "Counterfactual_Notes" TEXT
);
-- A.9 Synergy_Map (v7.5 Extended — 14 fields)
CREATE TABLE "Synergy_Map" (
  "Synergy_ID" TEXT PRIMARY KEY,
  "Idea_A" TEXT NOT NULL REFERENCES "MoneyScan_Records"("Idea_ID") ON DELETE CASCADE,
  "Idea_B" TEXT NOT NULL REFERENCES "MoneyScan_Records"("Idea_ID") ON DELETE CASCADE,
  "Relationship_Type" TEXT NOT NULL CHECK ("Relationship_Type" IN ('Amplifier','Blocker','Complementary','Prerequisite')), -- V40
  "Strength" TEXT NOT NULL CHECK ("Strength" IN ('Low','Medium','High')), -- Blueprint valid list
  "Direction" TEXT NOT NULL CHECK ("Direction" IN ('AtoB','BtoA','Bidirectional')), -- Blueprint valid list
  "Notes" TEXT,
  "Feedback_Type" TEXT REFERENCES "CT_Feedback_Type"("Value"),
  "Feedback_Description" TEXT,
  "Loop_Polarity" TEXT REFERENCES "CT_Loop_Polarity"("Value"),
  "Date_Identified" TEXT CHECK ("Date_Identified" IS NULL OR julianday("Date_Identified") IS NOT NULL),
  "Loop_Speed" TEXT REFERENCES "CT_Loop_Speed"("Value"),
  "Delay_Estimate" TEXT,
  "Tipping_Point_Flag" INTEGER CHECK ("Tipping_Point_Flag" IS NULL OR "Tipping_Point_Flag" IN (0,1)),
  CHECK ("Idea_A" <> "Idea_B") -- V39 self-synergy block
);
-- A.10 Mental_Models_Registry (NEW v7.5)
CREATE TABLE "Mental_Models_Registry" (
  "Model_ID" TEXT PRIMARY KEY CHECK ("Model_ID" GLOB 'MM-[0-9][0-9][0-9]'),
  "Model_Name" TEXT NOT NULL,
  "Category" TEXT NOT NULL REFERENCES "CT_MM_Category"("Value"),
  "Description" TEXT NOT NULL,
  "Inversion" TEXT,
  "Scanner_Application" TEXT NOT NULL,
  "Usage_Count" INTEGER NOT NULL DEFAULT 0 CHECK ("Usage_Count" >= 0)
);
-- A.12 Calibration_Ledger
CREATE TABLE "Calibration_Ledger" (
  "Cal_ID" TEXT PRIMARY KEY,
  "Pred_ID" TEXT NOT NULL REFERENCES "Prediction_Registry"("Pred_ID") ON DELETE CASCADE,
  "Resolution_Date" TEXT NOT NULL CHECK (julianday("Resolution_Date") IS NOT NULL),
  "Predicted_Confidence" REAL NOT NULL CHECK ("Predicted_Confidence" BETWEEN 0 AND 100),
  "Actual_Outcome" INTEGER NOT NULL CHECK ("Actual_Outcome" IN (0,1)),
  "Calibration_Error" REAL NOT NULL CHECK ("Calibration_Error" BETWEEN 0 AND 1), -- V42
  "Running_Brier_Score" REAL,
  "Notes" TEXT
);
-- A.13 Project_Execution_Log (NEW v8.3)
-- Key decision: Node_ID is retained as TEXT (Decision Mesh schema not part of the 17 persist schemas). Index it for joins.
CREATE TABLE "Project_Execution_Log" (
  "Exec_ID" TEXT PRIMARY KEY CHECK ("Exec_ID" GLOB 'EXEC-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9]'),
  "Node_ID" TEXT,
  "Idea_ID" TEXT REFERENCES "MoneyScan_Records"("Idea_ID") ON DELETE SET NULL,
  "Task_Name" TEXT NOT NULL CHECK (length(trim("Task_Name")) >= 5),
  "Exec_Status" TEXT NOT NULL DEFAULT 'Not_Started' REFERENCES "CT_Exec_Status"("Value"),
  "Completion_Pct" REAL NOT NULL CHECK ("Completion_Pct" BETWEEN 0 AND 100),
  "Priority_Tier" TEXT REFERENCES "CT_Priority"("Value"),
  "Start_Date" TEXT CHECK ("Start_Date" IS NULL OR julianday("Start_Date") IS NOT NULL),
  "Target_Completion" TEXT CHECK ("Target_Completion" IS NULL OR julianday("Target_Completion") IS NOT NULL),
  "Actual_Completion" TEXT CHECK ("Actual_Completion" IS NULL OR julianday("Actual_Completion") IS NOT NULL),
  "Time_Invested_Hours" REAL NOT NULL CHECK ("Time_Invested_Hours" >= 0),
  "Time_Estimate_Hours" REAL CHECK ("Time_Estimate_Hours" IS NULL OR "Time_Estimate_Hours" >= 0),
  "Blocker_Description" TEXT,
  "Blocker_Owner" TEXT,
  "Blocker_Escalation_Date" TEXT CHECK ("Blocker_Escalation_Date" IS NULL OR julianday("Blocker_Escalation_Date") IS NOT NULL),
  "Next_Action" TEXT,
  "Next_Action_Owner" TEXT,
  "Next_Action_Due" TEXT CHECK ("Next_Action_Due" IS NULL OR julianday("Next_Action_Due") IS NOT NULL),
  "Revenue_Generated" REAL CHECK ("Revenue_Generated" IS NULL OR "Revenue_Generated" >= 0),
  "Non_Monetary_Value_Notes" TEXT,
  "Unlock_IDs_Fired" TEXT,
  "Linked_Feynman_Guide" TEXT, -- FK to template tab (A.10h) is not modeled in this persist file
  "Linked_5W1H_Frame" TEXT,    -- FK to template tab (A.10i) is not modeled in this persist file
  "Quality_Gate_Passed" INTEGER CHECK ("Quality_Gate_Passed" IS NULL OR "Quality_Gate_Passed" IN (0,1)),
  "Iteration_Number" INTEGER NOT NULL DEFAULT 1 CHECK ("Iteration_Number" >= 1),
  "Parent_Exec_ID" TEXT REFERENCES "Project_Execution_Log"("Exec_ID") ON DELETE SET NULL,
  "Session_Notes" TEXT,
  "Last_Updated" TEXT NOT NULL CHECK (julianday("Last_Updated") IS NOT NULL),
  CHECK (
    -- V50: at least one of Node_ID or Idea_ID must be present
    (trim(COALESCE("Node_ID",'')) <> '' OR trim(COALESCE("Idea_ID",'')) <> '')
  ),
  CHECK (
    -- V47: when Completed, Completion_Pct must be 100 and Actual_Completion must be provided
    ("Exec_Status" <> 'Completed') OR ("Completion_Pct" = 100 AND "Actual_Completion" IS NOT NULL)
  ),
  CHECK (
    -- V48: when Blocked, Blocker_Description must be present (non-empty)
    ("Exec_Status" <> 'Blocked') OR (trim(COALESCE("Blocker_Description",'')) <> '')
  ),
  CHECK (
    -- Temporal sanity: if both present, Target_Completion >= Start_Date; Last_Updated >= Start_Date
    ("Start_Date" IS NULL OR "Target_Completion" IS NULL OR julianday("Target_Completion") >= julianday("Start_Date"))
  ),
  CHECK (
    ("Start_Date" IS NULL OR julianday("Last_Updated") >= julianday("Start_Date"))
  )
);
-- V49 (partial): enforce monotonic Time_Invested_Hours on UPDATE of the same Exec_ID
CREATE TRIGGER trg_ProjectExec_TimeInvested_NonDecreasing
BEFORE UPDATE OF "Time_Invested_Hours" ON "Project_Execution_Log"
FOR EACH ROW
WHEN NEW."Time_Invested_Hours" < OLD."Time_Invested_Hours"
BEGIN
  SELECT RAISE(ABORT, 'V49: Time_Invested_Hours cannot decrease');
END;
-- A.11 Portfolio_Health (v7.5 — derived)
-- Key decision: Implemented as a VIEW (Blueprint defines as derived metrics).
CREATE VIEW "Portfolio_Health" AS
SELECT
  (SELECT COUNT(*) FROM "MoneyScan_Records") AS "Total_Ideas",
  (SELECT group_concat(Stage || ':' || cnt, ';')
     FROM (SELECT Stage, COUNT(*) AS cnt FROM "MoneyScan_Records" GROUP BY Stage)
  ) AS "Ideas_By_Stage",
  (SELECT AVG(Demand_Score) FROM "MoneyScan_Records") AS "Avg_Demand_Score",
  (SELECT AVG(Viability_Score) FROM "MoneyScan_Records") AS "Avg_Viability_Score",
  (SELECT COUNT(*) FROM "MoneyScan_Records" WHERE Kill_Flag = 1) AS "Kill_Candidates",
  (SELECT COUNT(*) FROM "MoneyScan_Records" WHERE Pain_Score >= 70) AS "High_Pain_Ideas",
  (SELECT COUNT(DISTINCT Session_Date) FROM "Non_Monetary_Ledger") AS "Non_Monetary_Sessions",
  (SELECT COUNT(*) FROM "MoneyScan_Records" WHERE Days_Stale > 90) AS "Stale_Scores"
;
-- ----------------------------------------------
-- Indexes (frequently queried columns / join keys)
-- ----------------------------------------------
CREATE INDEX idx_MoneyScan_Stage ON "MoneyScan_Records"("Stage");
CREATE INDEX idx_MoneyScan_Category ON "MoneyScan_Records"("Category");
CREATE INDEX idx_MoneyScan_RevModel ON "MoneyScan_Records"("Revenue_Model");
CREATE INDEX idx_MoneyScan_Source ON "MoneyScan_Records"("Source");
CREATE INDEX idx_MoneyScan_LastUpdated ON "MoneyScan_Records"("Last_Updated");
CREATE INDEX idx_MoneyScan_Rank ON "MoneyScan_Records"("Rank_v75");
CREATE INDEX idx_MoneyScan_KillFlag ON "MoneyScan_Records"("Kill_Flag");
CREATE INDEX idx_MoneyScan_PainID ON "MoneyScan_Records"("Pain_ID");
CREATE INDEX idx_Pain_Status ON "Pain_Point_Register"("Status");
CREATE INDEX idx_Pain_Score ON "Pain_Point_Register"("Pain_Score");
CREATE INDEX idx_Pain_DateIdentified ON "Pain_Point_Register"("Date_Identified");
CREATE INDEX idx_Solution_PainID ON "Solution_Design"("Pain_ID");
CREATE INDEX idx_Solution_Status ON "Solution_Design"("Status");
CREATE INDEX idx_Solution_MonetizationPath ON "Solution_Design"("Monetization_Path");
CREATE INDEX idx_Solution_LinkedIdea ON "Solution_Design"("Linked_Idea_ID");
CREATE INDEX idx_NonMon_IdeaID ON "Non_Monetary_Ledger"("Idea_ID");
CREATE INDEX idx_NonMon_SessionDate ON "Non_Monetary_Ledger"("Session_Date");
CREATE INDEX idx_NonMon_Type ON "Non_Monetary_Ledger"("NM_Type");
CREATE INDEX idx_Pred_IdeaID ON "Prediction_Registry"("Idea_ID");
CREATE INDEX idx_Pred_Horizon ON "Prediction_Registry"("Horizon");
CREATE INDEX idx_Pred_Outcome ON "Prediction_Registry"("Outcome");
CREATE INDEX idx_Pred_ResolutionDate ON "Prediction_Registry"("Resolution_Date");
CREATE INDEX idx_Bias_IdeaID ON "Bias_Audit_Log"("Idea_ID");
CREATE INDEX idx_Bias_SessionDate ON "Bias_Audit_Log"("Session_Date");
CREATE INDEX idx_Bias_Score ON "Bias_Audit_Log"("Bias_Score");
CREATE INDEX idx_Scenario_IdeaID ON "Scenario_Map"("Idea_ID");
CREATE INDEX idx_Scenario_Type ON "Scenario_Map"("Scenario_Type");
CREATE INDEX idx_Decision_IdeaID ON "Decision_Tree_Log"("Idea_ID");
CREATE INDEX idx_Decision_Date ON "Decision_Tree_Log"("Decision_Date");
CREATE INDEX idx_Decision_Stage ON "Decision_Tree_Log"("Stage_At_Decision");
CREATE INDEX idx_Synergy_IdeaA ON "Synergy_Map"("Idea_A");
CREATE INDEX idx_Synergy_IdeaB ON "Synergy_Map"("Idea_B");
CREATE INDEX idx_Synergy_RelType ON "Synergy_Map"("Relationship_Type");
CREATE INDEX idx_MM_Category ON "Mental_Models_Registry"("Category");
CREATE INDEX idx_MM_UsageCount ON "Mental_Models_Registry"("Usage_Count");
CREATE INDEX idx_Cal_PredID ON "Calibration_Ledger"("Pred_ID");
CREATE INDEX idx_Cal_ResolutionDate ON "Calibration_Ledger"("Resolution_Date");
CREATE INDEX idx_Exec_NodeID ON "Project_Execution_Log"("Node_ID");
CREATE INDEX idx_Exec_IdeaID ON "Project_Execution_Log"("Idea_ID");
CREATE INDEX idx_Exec_Status ON "Project_Execution_Log"("Exec_Status");
CREATE INDEX idx_Exec_Priority ON "Project_Execution_Log"("Priority_Tier");
CREATE INDEX idx_Exec_TargetCompletion ON "Project_Execution_Log"("Target_Completion");
CREATE INDEX idx_Exec_NextActionDue ON "Project_Execution_Log"("Next_Action_Due");
CREATE INDEX idx_Exec_ParentExec ON "Project_Execution_Log"("Parent_Exec_ID");
COMMIT;
-- ==============================================
-- Activation-deferred schemas (A.14–A.17) — NEW v8.4
-- IMPORTANT: Keep commented until Local AI Layer is operational (Blueprint Module 10.14.5).
-- To activate: remove the /* ... */ wrapper below and execute the statements.
-- ==============================================
/*
-- A.14 Calibration_Feedback_Loop (NEW v8.4) — 11 fields
CREATE TABLE "Calibration_Feedback_Loop" (
  "Cal_Feedback_ID" TEXT PRIMARY KEY,
  "Pred_ID" TEXT NOT NULL REFERENCES "Prediction_Registry"("Pred_ID") ON DELETE CASCADE, -- V53
  "Idea_ID" TEXT NOT NULL REFERENCES "MoneyScan_Records"("Idea_ID") ON DELETE CASCADE,
  "Predicted_Value" REAL NOT NULL,
  "Actual_Value" REAL,
  "Delta" REAL, -- Derived: Actual_Value - Predicted_Value
  "Calibration_Score" REAL CHECK ("Calibration_Score" IS NULL OR ("Calibration_Score" BETWEEN 0 AND 1)),
  "Brier_Score_Running" REAL, -- Derived running brier score
  "Feedback_Date" TEXT NOT NULL CHECK (julianday("Feedback_Date") IS NOT NULL),
  "AI_Tier_Used" TEXT REFERENCES "AI_Routing_Registry"("Route_ID") ON DELETE SET NULL,
  "Notes" TEXT
);
CREATE INDEX idx_CalFeedback_PredID ON "Calibration_Feedback_Loop"("Pred_ID");
CREATE INDEX idx_CalFeedback_IdeaID ON "Calibration_Feedback_Loop"("Idea_ID");
CREATE INDEX idx_CalFeedback_Date ON "Calibration_Feedback_Loop"("Feedback_Date");
-- A.15 Evolution_Suggestions_Log (NEW v8.4) — 12 fields
CREATE TABLE "Evolution_Suggestions_Log" (
  "Evo_ID" TEXT PRIMARY KEY,
  "Suggestion_Date" TEXT NOT NULL CHECK (julianday("Suggestion_Date") IS NOT NULL),
  "Trigger_Event" TEXT NOT NULL,
  "Suggestion_Type" TEXT NOT NULL REFERENCES "CT_Suggestion_Type"("Value"), -- V54
  "Suggestion_Text" TEXT NOT NULL,
  "Affected_Schema" TEXT NOT NULL,
  "Affected_Field" TEXT,
  "Priority" TEXT NOT NULL CHECK ("Priority" IN ('High','Medium','Low')),
  "Status" TEXT NOT NULL CHECK ("Status" IN ('Pending','Approved','Rejected','Implemented')),
  "Approved_By" TEXT,
  "Implementation_Date" TEXT CHECK ("Implementation_Date" IS NULL OR julianday("Implementation_Date") IS NOT NULL),
  "Notes" TEXT
);
CREATE INDEX idx_Evo_Status ON "Evolution_Suggestions_Log"("Status");
CREATE INDEX idx_Evo_Priority ON "Evolution_Suggestions_Log"("Priority");
CREATE INDEX idx_Evo_SuggestionDate ON "Evolution_Suggestions_Log"("Suggestion_Date");
-- A.16 AI_Routing_Registry (NEW v8.4) — 13 fields
CREATE TABLE "AI_Routing_Registry" (
  "Route_ID" TEXT PRIMARY KEY,
  "Scan_ID" TEXT NOT NULL,
  "Idea_ID" TEXT REFERENCES "MoneyScan_Records"("Idea_ID") ON DELETE SET NULL,
  "Timestamp" TEXT NOT NULL CHECK (julianday("Timestamp") IS NOT NULL),
  "Input_Complexity_Score" REAL CHECK ("Input_Complexity_Score" IS NULL OR ("Input_Complexity_Score" BETWEEN 0 AND 100)),
  "Tier_Selected" INTEGER NOT NULL CHECK ("Tier_Selected" BETWEEN 1 AND 4), -- V51
  "Tier_Reason" TEXT NOT NULL,
  "Model_Used" TEXT NOT NULL,
  "Tokens_Used" INTEGER NOT NULL CHECK ("Tokens_Used" > 0), -- V52
  "Latency_Ms" INTEGER NOT NULL CHECK ("Latency_Ms" > 0), -- V52
  "Output_Quality_Score" REAL CHECK ("Output_Quality_Score" IS NULL OR ("Output_Quality_Score" BETWEEN 0 AND 1)),
  "Fallback_Triggered" INTEGER NOT NULL DEFAULT 0 CHECK ("Fallback_Triggered" IN (0,1)),
  "Notes" TEXT
);
CREATE INDEX idx_Route_IdeaID ON "AI_Routing_Registry"("Idea_ID");
CREATE INDEX idx_Route_Timestamp ON "AI_Routing_Registry"("Timestamp");
CREATE INDEX idx_Route_Tier ON "AI_Routing_Registry"("Tier_Selected");
-- A.17 AI_Performance_Log (NEW v8.4) — 13 fields
CREATE TABLE "AI_Performance_Log" (
  "Perf_ID" TEXT PRIMARY KEY,
  "Route_ID" TEXT NOT NULL REFERENCES "AI_Routing_Registry"("Route_ID") ON DELETE CASCADE,
  "Idea_ID" TEXT REFERENCES "MoneyScan_Records"("Idea_ID") ON DELETE SET NULL,
  "Session_Date" TEXT NOT NULL CHECK (julianday("Session_Date") IS NOT NULL),
  "AI_Tier" INTEGER NOT NULL CHECK ("AI_Tier" BETWEEN 1 AND 4),
  "Model_Version" TEXT NOT NULL,
  "Task_Type" TEXT NOT NULL,
  "Accuracy_Score" REAL CHECK ("Accuracy_Score" IS NULL OR ("Accuracy_Score" BETWEEN 0 AND 1)),
  "Confidence_Avg" REAL CHECK ("Confidence_Avg" IS NULL OR ("Confidence_Avg" BETWEEN 0 AND 1)),
  "Fields_Extracted" INTEGER NOT NULL CHECK ("Fields_Extracted" >= 0),
  "Fields_Overridden" INTEGER NOT NULL CHECK ("Fields_Overridden" >= 0),
  "Override_Reason" TEXT,
  "Notes" TEXT
);
CREATE INDEX idx_Perf_RouteID ON "AI_Performance_Log"("Route_ID");
CREATE INDEX idx_Perf_SessionDate ON "AI_Performance_Log"("Session_Date");
CREATE INDEX idx_Perf_IdeaID ON "AI_Performance_Log"("Idea_ID");
*/
-- End of aeOS_PERSIST_v1.0.sql
