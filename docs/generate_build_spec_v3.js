/**
 * generate_build_spec_v3.js — aeOS Build Spec v3.0 DOCX Generator
 *
 * Produces: aeOS_Build_Spec_v3.0.docx
 * Run:      node docs/generate_build_spec_v3.js
 */

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, WidthType, BorderStyle, ShadingType,
  PageBreak, TabStopPosition, TabStopType, Footer, Header,
  TableOfContents, PageNumber, NumberFormat,
} = require("docx");
const fs = require("fs");
const path = require("path");

// ─── Style Constants ─────────────────────────────────────────────────
const NAVY   = "1B2A4A";
const ACCENT  = "2E86AB";
const DARK    = "333333";
const LIGHT_BG = "F0F4F8";
const WHITE   = "FFFFFF";
const GREEN   = "2D6A4F";
const RED     = "D32F2F";
const ORANGE  = "E65100";

// ─── Helpers ─────────────────────────────────────────────────────────
function heading(text, level = HeadingLevel.HEADING_1) {
  return new Paragraph({ text, heading: level, spacing: { before: 300, after: 150 } });
}
function h2(text) { return heading(text, HeadingLevel.HEADING_2); }
function h3(text) { return heading(text, HeadingLevel.HEADING_3); }

function para(text, opts = {}) {
  return new Paragraph({
    children: [new TextRun({ text, size: 22, color: DARK, ...opts })],
    spacing: { after: 120 },
  });
}

function bold(text) { return para(text, { bold: true }); }

function bullet(text) {
  return new Paragraph({
    children: [new TextRun({ text, size: 22, color: DARK })],
    bullet: { level: 0 },
    spacing: { after: 60 },
  });
}

function subBullet(text) {
  return new Paragraph({
    children: [new TextRun({ text, size: 20, color: DARK })],
    bullet: { level: 1 },
    spacing: { after: 40 },
  });
}

function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

function cell(text, opts = {}) {
  const shading = opts.bg ? { type: ShadingType.SOLID, color: opts.bg, fill: opts.bg } : undefined;
  return new TableCell({
    children: [new Paragraph({
      children: [new TextRun({
        text,
        size: opts.size || 20,
        bold: opts.bold || false,
        color: opts.color || DARK,
      })],
      alignment: opts.align || AlignmentType.LEFT,
    })],
    shading,
    width: opts.width ? { size: opts.width, type: WidthType.DXA } : undefined,
    verticalAlign: "center",
  });
}

function headerCell(text, width) {
  return cell(text, { bg: NAVY, color: WHITE, bold: true, width, size: 20 });
}

function makeTable(headers, rows, colWidths) {
  const hdrRow = new TableRow({
    children: headers.map((h, i) => headerCell(h, colWidths?.[i])),
    tableHeader: true,
  });
  const dataRows = rows.map((r, ri) =>
    new TableRow({
      children: r.map((c, ci) => cell(c, {
        bg: ri % 2 === 0 ? WHITE : LIGHT_BG,
        width: colWidths?.[ci],
      })),
    })
  );
  return new Table({
    rows: [hdrRow, ...dataRows],
    width: { size: 9500, type: WidthType.DXA },
  });
}

// ─── Cover Page ──────────────────────────────────────────────────────
function coverPage() {
  return [
    new Paragraph({ spacing: { before: 3000 } }),
    new Paragraph({
      children: [new TextRun({ text: "aeOS", size: 72, bold: true, color: NAVY })],
      alignment: AlignmentType.CENTER,
    }),
    new Paragraph({
      children: [new TextRun({ text: "Build Specification v3.0", size: 44, color: ACCENT })],
      alignment: AlignmentType.CENTER,
      spacing: { after: 200 },
    }),
    new Paragraph({
      children: [new TextRun({ text: "Autonomous Entrepreneurial Operating System", size: 28, color: DARK, italics: true })],
      alignment: AlignmentType.CENTER,
      spacing: { after: 600 },
    }),
    new Paragraph({
      children: [new TextRun({ text: `Date: ${new Date().toISOString().split("T")[0]}`, size: 24, color: DARK })],
      alignment: AlignmentType.CENTER,
    }),
    new Paragraph({
      children: [new TextRun({ text: "Version: 3.0  |  Classification: Internal", size: 24, color: DARK })],
      alignment: AlignmentType.CENTER,
    }),
    new Paragraph({
      children: [new TextRun({ text: "Status: Active Development", size: 24, color: GREEN })],
      alignment: AlignmentType.CENTER,
      spacing: { after: 200 },
    }),
    pageBreak(),
  ];
}

// ─── 1. Executive Summary ────────────────────────────────────────────
function section1() {
  return [
    heading("1. Executive Summary"),
    para("aeOS (Autonomous Entrepreneurial Operating System) is a sovereign intelligence platform that combines pain-point analysis, solution design, prediction calibration, bias auditing, and knowledge management into a unified decision-support system. It is designed to operate locally with full user data sovereignty, using SQLite for persistence, ChromaDB for vector search, and Ollama-hosted local LLMs for inference."),
    para("This Build Specification (v3.0) supersedes v2.0 and documents the complete technical architecture, phase-by-phase build plan, database schemas, agent contracts, orchestration pipeline, cognitive cartridge system, and testing standards as implemented in the current codebase."),

    h2("1.1 Vision"),
    para("aeOS transforms raw entrepreneurial observations into structured, evidence-backed decisions through a multi-layered intelligence stack that progressively deepens its understanding of the user's portfolio, pain landscape, and cognitive patterns."),

    h2("1.2 Key Design Principles"),
    bullet("Sovereignty-first: All data stays local. No cloud telemetry. User owns everything."),
    bullet("Graceful degradation: Every component works without its dependencies (LLM, DB, KB)."),
    bullet("Evidence-over-intuition: Decisions are anchored by structured schemas, Brier scoring, and bias auditing."),
    bullet("Deterministic routing, AI-assisted answers: Intent classification uses keyword patterns (no LLM). Answer generation may use local LLM."),
    bullet("Cartridge-extensible: Domain knowledge is loaded from JSON cartridge files, not hard-coded."),

    h2("1.3 Technology Stack"),
    makeTable(
      ["Layer", "Technology", "Notes"],
      [
        ["Language", "Python 3.10+", "All source under src/"],
        ["Database", "SQLite 3 (WAL mode)", "db/aeOS_PERSIST_v1.0.sql — 13 active schemas + 20 code tables"],
        ["Vector Store", "ChromaDB", "Knowledge base via src/kb/"],
        ["Local LLM", "Ollama (deepseek-r1:8b default)", "Configurable via OLLAMA_HOST / OLLAMA_MODEL"],
        ["CLI", "Python argparse", "src/cli/cli_main.py entry point"],
        ["API", "FastAPI (planned)", "src/api/ — health, pain, solutions, predictions endpoints"],
        ["Docs Generator", "Node.js + docx library", "docs/ directory"],
        ["Testing", "pytest", "tests/ — 19 test files, 200+ test cases"],
      ],
      [2500, 3000, 4000]
    ),
    pageBreak(),
  ];
}

// ─── 2. Architecture Overview ────────────────────────────────────────
function section2() {
  return [
    heading("2. Architecture Overview"),
    para("aeOS is structured as a 6-layer stack. Each layer depends only on the layer below it, enabling incremental development and isolated testing."),

    h2("2.1 Layer Architecture"),
    makeTable(
      ["Layer", "Name", "Components", "Purpose"],
      [
        ["Layer 0", "Core Infrastructure", "config, logger, auth, safety, history", "Configuration, logging, authentication, safety guardrails"],
        ["Layer 1", "AI Core", "ai_connect, ai_infer, ai_context, ai_router", "LLM connectivity, inference, context building, intent routing"],
        ["Layer 2", "Agents (Phase 4)", "agent_pain, agent_solution, agent_prediction, agent_bias, agent_memory", "Domain-specific intelligence agents"],
        ["Layer 3", "Orchestrator (Phase 4)", "orchestrator.py", "Central coordinator: routes queries, dispatches agents, composes responses"],
        ["Layer 4", "Advanced Agents (Phase 5)", "agent_graph, agent_experiment, agent_synthesis, agent_report, agent_monitor", "GraphRAG, experiments, KB synthesis, reporting, system monitoring"],
        ["Layer 5", "Cognitive Core", "cartridge_loader, reasoning_substrate, orchestration/*", "Cartridge system, multi-insight synthesis, 4-gate validation"],
      ],
      [1200, 2000, 3500, 2800]
    ),

    h2("2.2 Data Flow"),
    para("The standard request lifecycle follows this path:"),
    bullet("User query enters via CLI (cli_main.py) or API endpoint"),
    bullet("ai_router.detect_intent() classifies intent using keyword/pattern matching (7 intents)"),
    bullet("Orchestrator dispatches to the appropriate Layer 2/4 agent"),
    bullet("Agent reads from SQLite (DB) and/or ChromaDB (KB) via context builders"),
    bullet("Agent may call ai_infer for LLM-assisted analysis"),
    bullet("Response flows back through Orchestrator to the caller"),
    para("For COGNITIVE_CORE queries, the path adds:"),
    bullet("Dispatcher classifies intent across 45 cartridge domains with 9 sovereign needs"),
    bullet("CartridgeConductor loads relevant cartridges, runs trigger matching via run_rules()"),
    bullet("ReasoningSynthesizer calls reasoning_substrate.synthesise() for convergence/tension/blind-spot detection"),
    bullet("OutputValidator runs 4-gate validation (SAFE, TRUE, HIGH-LEVERAGE, ALIGNED)"),
    bullet("OutputComposer formats the final ComposedOutput response"),
    pageBreak(),
  ];
}

// ─── 3. Phase Build Plan ─────────────────────────────────────────────
function section3() {
  return [
    heading("3. Phase Build Plan"),
    para("Development proceeds in 7 phases (0–6). Phases 0–5 are implemented. Phase 6 is planned."),

    h2("3.1 Phase Registry"),
    makeTable(
      ["Phase", "Name", "Status", "Key Deliverables"],
      [
        ["Phase 0", "Foundation", "Complete", "SQLite schema (20 code tables + 13 core tables), db_connect, db_init"],
        ["Phase 1", "Persistence Layer", "Complete", "Pain_Point_Register, MoneyScan_Records, Solution_Design, full CRUD operations"],
        ["Phase 2", "Knowledge Base", "Complete", "ChromaDB integration (kb_connect, kb_index, kb_ingest, kb_search)"],
        ["Phase 3", "AI Core", "Complete", "Ollama connectivity (ai_connect), inference (ai_infer), context building (ai_context), intent routing (ai_router)"],
        ["Phase 4", "Orchestration", "Complete", "5 agents (pain, solution, prediction, bias, memory), Orchestrator class, daily briefing"],
        ["Phase 5", "Advanced Agents", "Complete", "5 agents (graph, experiment, synthesis, report, monitor), 58+ tests"],
        ["Phase 6", "Cognitive Core", "Active", "Cartridge system, reasoning substrate, 5-component orchestration pipeline"],
      ],
      [1200, 2000, 1500, 4800]
    ),

    h2("3.2 Phase Completion Criteria"),
    para("Each phase must satisfy the S-T-L-A stamp before promotion:"),
    bullet("S (Spec): Module docstrings match this build spec"),
    bullet("T (Tested): All public functions have pytest coverage with passing tests"),
    bullet("L (Linted): Code passes standard Python linting (no unused imports, consistent style)"),
    bullet("A (Approved): Code review completed and merged to main"),

    h2("3.3 Phase 6 — Cognitive Core (Current)"),
    para("Phase 6 introduces the COGNITIVE_CORE intelligence layer:"),

    h3("3.3.1 Cartridge System"),
    bullet("JSON cartridge files live in src/cartridges/ (e.g., stoic.json)"),
    bullet("Schema validated by cartridge_schema.json (custom stdlib-only validator)"),
    bullet("Each cartridge contains rules with detection_triggers, insight_template, confidence_weight, sovereign_need_served, and tags"),
    bullet("cartridge_loader.py: load_schema(), load_cartridge(), load_cartridges() (parallel via ThreadPoolExecutor), run_rules()"),
    bullet("run_rules() computes proportional confidence = weight * (matched_triggers / total_triggers)"),

    h3("3.3.2 Reasoning Substrate"),
    bullet("reasoning_substrate.py: synthesise() is the main entry point"),
    bullet("Convergence detection: groups insights sharing tags, computes mean confidence"),
    bullet("Tension detection: surfaces opposing pairs (e.g., acceptance vs. discipline)"),
    bullet("Blind-spot detection: identifies 8 universal dimensions not addressed (autonomy, security, purpose, resilience, clarity, belonging, integrity, growth)"),
    bullet("Outputs SynthesisResult dataclass with primary_insight, convergences, tensions, blind_spots, recommended_action"),

    h3("3.3.3 Orchestration Pipeline (5 Components)"),
    bullet("Dispatcher: Classifies intent across 45 domains using keyword affinity scoring"),
    bullet("CartridgeConductor: Loads relevant cartridges, runs rules, returns ranked CartridgeInsight list (max 20)"),
    bullet("ReasoningSynthesizer: Bridges CartridgeInsight list to reasoning_substrate.synthesise()"),
    bullet("OutputValidator: 4-gate validation — SAFE (no PII/harmful), TRUE (confidence > 0.4), HIGH-LEVERAGE (convergence or confidence > 0.7), ALIGNED (sovereign need served)"),
    bullet("OutputComposer: Formats SynthesisResult + ValidationResult into ComposedOutput"),

    h3("3.3.4 Database Migration"),
    bullet("db/migrations/20260301_01_cognitive_core_tables.sql adds 6 tables for cognitive core persistence"),
    pageBreak(),
  ];
}

// ─── 4. Database Schema ──────────────────────────────────────────────
function section4() {
  return [
    heading("4. Database Schema"),
    para("The persistence layer is defined in db/aeOS_PERSIST_v1.0.sql. It implements SQLite with WAL mode, foreign key enforcement, and comprehensive CHECK constraints."),

    h2("4.1 Code Tables (Appendix B — 20 Tables)"),
    para("Code tables provide validated reference data for foreign key constraints. All follow the same 5-column structure: Value (PK), Description, Sort_Order, Is_Active, Notes."),
    makeTable(
      ["Code Table", "Purpose", "Sample Values"],
      [
        ["CT_Stage", "Project lifecycle stage", "Idea, Research, Validation, Build, Launch, Scale, Kill, Paused"],
        ["CT_Category", "Business category", "SaaS, Service, Content, Community, Physical, Marketplace, Tool, Framework"],
        ["CT_Rev_Model", "Revenue model", "Subscription, One_Time, Usage, Freemium, Marketplace, Sponsorship, Licensing, Hybrid"],
        ["CT_Source", "Idea source", "Personal_Pain, Market_Signal, User_Interview, Competitor, AI_Suggestion, Serendipity"],
        ["CT_Priority", "Priority tier", "P1_Critical, P2_High, P3_Medium, P4_Low"],
        ["CT_Freq", "Frequency", "Daily, Weekly, Monthly, Occasional, Rare"],
        ["CT_Phase", "Build phase", "Phase_0 through Phase_6"],
        ["CT_Impact", "Impact level", "Low, Medium, High, Transformative"],
        ["CT_Complexity", "Complexity level", "Low, Medium, High, Very_High"],
        ["CT_Horizon", "Prediction horizon", "30d, 90d, 6m, 1y, 2y+"],
        ["CT_Outcome", "Prediction outcome", "Correct, Incorrect, Partial, Unresolved"],
        ["CT_Cog_State", "Cognitive state", "Focused, Fatigued, Stressed, Euphoric, Neutral, Anxious"],
        ["CT_Scenario", "Scenario type", "Best, Base, Worst, BlackSwan"],
        ["CT_Sol_Type", "Solution type", "Product, Service, Content, System, Community, Tool, Framework"],
        ["CT_Sol_Status", "Solution status", "Concept, Designing, Validated, Building, Live, Shelved"],
        ["CT_Pain_Status", "Pain status", "Active, Solved, Abandoned, Monitoring"],
        ["CT_NM_Type", "Non-monetary type", "Skill, Relationship, Knowledge, Reputation, Optionality, Confidence"],
        ["CT_Bias", "Cognitive bias", "Confirmation_Bias, Sunk_Cost_Fallacy, Dunning_Kruger, Loss_Aversion, etc."],
        ["CT_MM_Category", "Mental model category", "Systems, Thinking, Decision, Psychology, Economics, Science"],
        ["CT_Exec_Status", "Execution status", "Not_Started, In_Progress, Blocked, Completed, Cancelled, Deferred"],
      ],
      [2500, 2500, 4500]
    ),

    h2("4.2 Core Schemas (A.1–A.13)"),
    para("13 active core tables implement the full aeOS data model:"),

    h3("A.1 MoneyScan_Records"),
    para("The master idea/venture registry with ~260 columns covering scoring, MVP features (50 slots), traction metrics (10 slots), competitive analysis, moat assessment, financial estimates, bias corrections, and evidence chains. ID format: MSR-YYYYMMDD-NNN."),

    h3("A.2 Pain_Point_Register"),
    para("Structured pain-point tracking: Pain_ID (PAIN-YYYYMMDD-NNN), severity (1-10), impact score (1-10), monetizability flag, WTP estimate, pain score (0-100), frequency, evidence, and validation workflow."),

    h3("A.3 Solution_Design"),
    para("Links solutions to pain points: SOL-YYYYMMDD-NNN, solution type, complexity, time to MVP, monetization path, pain-fit score (0-10). FK to Pain_Point_Register."),

    h3("A.4 Non_Monetary_Ledger"),
    para("Tracks non-financial value: skills, relationships, knowledge, reputation, optionality, confidence. NML-YYYYMMDD-NNN format."),

    h3("A.5 Prediction_Registry"),
    para("Bayesian prediction tracking: PRED-YYYYMMDD-NNN, confidence percentage, base rate, evidence for/against, resolution criteria, calibration delta."),

    h3("A.6 Bias_Audit_Log"),
    para("Cognitive bias auditing: detects biases, records pre-bias score, bias score, post-debiasing score, debiasing actions."),

    h3("A.7 Scenario_Map"),
    para("Best/Base/Worst/BlackSwan scenario planning per idea with probability, revenue impact, key triggers, early signals, strategy."),

    h3("A.8 Decision_Tree_Log"),
    para("20-field decision record: options considered, rationale, confidence, evidence, assumptions, reversibility (Type1_Irreversible / Type2_Reversible), cognitive state, biases present."),

    h3("A.9 Synergy_Map"),
    para("Tracks relationships between ideas: Amplifier, Blocker, Complementary, Prerequisite. Includes feedback loop analysis (polarity, speed, tipping points)."),

    h3("A.10 Mental_Models_Registry"),
    para("Catalog of mental models: MM-NNN format, category (Systems, Thinking, Decision, Psychology, Economics, Science), inversion, scanner application, usage count."),

    h3("A.12 Calibration_Ledger"),
    para("Stores prediction resolution data: predicted confidence vs. actual outcome, calibration error (0-1), running Brier score."),

    h3("A.13 Project_Execution_Log"),
    para("Execution tracking: EXEC-YYYYMMDD-NNN, status, completion percentage, time invested/estimated, blockers, next actions, revenue generated, quality gates, iteration number, parent/child relationships."),

    h2("4.3 Portfolio Health View"),
    para("Portfolio_Health is a SQL VIEW joining MoneyScan_Records with execution and prediction counts for dashboard-level visibility."),
    pageBreak(),
  ];
}

// ─── 5. Module Reference ─────────────────────────────────────────────
function section5() {
  return [
    heading("5. Module Reference"),

    h2("5.1 Core Infrastructure (src/core/)"),
    makeTable(
      ["Module", "Purpose", "Key Functions/Classes"],
      [
        ["config.py", "Central configuration (aliases db_connect.py)", "get_connection(), close_connection(), execute_query()"],
        ["logger.py", "Centralized logging", "get_logger(name)"],
        ["auth.py", "Authentication (Phase 3+)", "Token validation, session management"],
        ["safety.py", "Safety guardrails", "Input sanitization, output filtering"],
        ["history.py", "Session history tracking", "Command history, undo support"],
      ],
      [2500, 3000, 4000]
    ),

    h2("5.2 AI Core (src/ai/)"),
    makeTable(
      ["Module", "Purpose", "Key Functions"],
      [
        ["ai_connect.py", "Ollama connectivity", "ping_ollama(), check_model_available()"],
        ["ai_infer.py", "LLM inference", "infer(prompt, system_prompt), infer_json(prompt, system_prompt)"],
        ["ai_context.py", "Context building for LLM prompts", "build_pain_context(), build_portfolio_context(), build_kb_context(), assemble_full_context()"],
        ["ai_router.py", "Deterministic intent routing (no LLM)", "detect_intent(query), route_query(query, conn, kb_conn), get_routing_stats()"],
      ],
      [2500, 3000, 4000]
    ),

    h3("5.2.1 Intent Router Details"),
    para("ai_router.py classifies user queries into 7 intents using keyword/pattern matching:"),
    makeTable(
      ["Intent", "Agent", "DB Needed", "KB Needed", "Example Triggers"],
      [
        ["pain_analysis", "agent_pain", "Yes", "Yes", "pain point, root cause, diagnose, severity, frustrat, bottleneck"],
        ["solution_generation", "agent_solution", "Yes", "Yes", "solution, fix, resolve, approach, how do i, recommend"],
        ["prediction", "agent_prediction", "Yes", "Yes", "predict, forecast, probability, confidence, brier, calibration"],
        ["bias_check", "agent_bias", "Yes", "Yes", "bias, cognitive bias, fallacy, assumption, blind spot"],
        ["memory_search", "agent_memory", "No", "Yes", "search, find, look up, retrieve, what did i say"],
        ["portfolio_health", "module_portfolio_health", "Yes", "No", "portfolio, health, dashboard, runway, burn, cash"],
        ["general", "ai_infer", "No", "No", "Fallback for unmatched queries"],
      ],
      [2000, 2000, 1000, 1000, 3500]
    ),

    h2("5.3 Knowledge Base (src/kb/)"),
    makeTable(
      ["Module", "Purpose", "Key Functions"],
      [
        ["kb_connect.py", "ChromaDB connectivity", "get_kb_client(), get_collection()"],
        ["kb_index.py", "Index management", "create_index(), rebuild_index()"],
        ["kb_ingest.py", "Document ingestion", "ingest_document(), batch_ingest()"],
        ["kb_search.py", "Vector similarity search", "search(query, n_results), hybrid_search()"],
      ],
      [2500, 3000, 4000]
    ),

    h2("5.4 Agents — Phase 4 (src/agents/)"),
    makeTable(
      ["Agent", "Purpose", "Key Functions"],
      [
        ["agent_pain.py", "Pain-point analysis via LLM", "analyze_pain(conn, pain_id), detect_pain_patterns(conn), generate_pain_summary(conn)"],
        ["agent_solution.py", "Solution generation", "handle(query, conn, kb_conn), suggest_quick_wins(conn)"],
        ["agent_prediction.py", "Prediction analysis", "handle(query, conn, kb_conn), get_calibration_insight(conn)"],
        ["agent_bias.py", "Cognitive bias auditing", "handle(query, conn, kb_conn)"],
        ["agent_memory.py", "KB search and retrieval", "handle(query, conn, kb_conn)"],
      ],
      [2500, 3000, 4000]
    ),

    h2("5.5 Agents — Phase 5 (src/agents/)"),
    makeTable(
      ["Agent", "Purpose", "Key Functions"],
      [
        ["agent_graph.py", "GraphRAG knowledge graph traversal", "find_connections(conn, kb_conn, concept), build_entity_graph(conn), traverse_from_pain(conn, kb_conn, pain_id), find_root_causes_across_portfolio(), suggest_leverage_points()"],
        ["agent_experiment.py", "Micro-experiment design + tracking", "design_experiment(), track_experiment(), evaluate_experiment()"],
        ["agent_synthesis.py", "KB synthesis for emerging themes", "synthesize_themes(), generate_cross_domain_insights()"],
        ["agent_report.py", "Report generation", "generate_report(), format_findings()"],
        ["agent_monitor.py", "System monitoring", "monitor_health(), alert_anomalies()"],
      ],
      [2500, 3000, 4000]
    ),

    h2("5.6 Orchestrator (src/orchestrator/)"),
    para("orchestrator.py provides the central Orchestrator class:"),
    bullet("__init__(db_path, kb_path): Connects to DB and KB, loads all 5 Phase-4 agents"),
    bullet("process(query): Full end-to-end query processing — intent detection, agent dispatch, fallback routing"),
    bullet("run_daily_briefing(): Composes pain summary + quick wins + calibration insight"),
    bullet("get_status(): Health snapshot (DB connected, KB connected, agents loaded, Ollama connected)"),
    bullet("close(): Cleanup resources. Supports context manager protocol."),

    h2("5.7 Cognitive Core (src/cognitive/)"),
    makeTable(
      ["Module", "Purpose", "Key API"],
      [
        ["cartridge_loader.py", "Load + validate JSON cartridges, run rules", "load_schema(), load_cartridge(), load_cartridges(), run_rules(cartridge, context)"],
        ["reasoning_substrate.py", "Multi-insight synthesis engine", "synthesise(all_insights) -> SynthesisResult"],
      ],
      [2500, 3500, 3500]
    ),

    h2("5.8 Orchestration Pipeline (src/orchestration/)"),
    makeTable(
      ["Module", "Purpose", "Key API"],
      [
        ["models.py", "Shared dataclasses", "IntentClassification, OrchestratorRequest, CartridgeInsight, ValidationResult, ComposedOutput"],
        ["dispatcher.py", "Intent classification (45 domains)", "Dispatcher.classify_intent(text), Dispatcher.dispatch(text)"],
        ["cartridge_conductor.py", "Load + run cartridges by domain", "CartridgeConductor.conduct(request) -> List[CartridgeInsight]"],
        ["reasoning_synthesizer.py", "Bridge to reasoning substrate", "ReasoningSynthesizer.synthesize(insights) -> SynthesisResult"],
        ["output_validator.py", "4-gate validation", "OutputValidator.validate(result, original_text) -> ValidationResult"],
        ["output_composer.py", "Final response formatting", "OutputComposer.compose(result, validation) -> ComposedOutput"],
      ],
      [2800, 3000, 3700]
    ),

    h2("5.9 Financial Metrics (src/financial_metrics.py)"),
    para("15 pure financial calculation functions with strict input validation:"),
    makeTable(
      ["Function", "Purpose", "Formula"],
      [
        ["calc_cac()", "Customer Acquisition Cost", "total_spend / new_customers"],
        ["calc_ltv()", "Customer Lifetime Value", "(ARPC * gross_margin) / churn_rate"],
        ["calc_ltv_cac_ratio()", "LTV:CAC ratio", "LTV / CAC (healthy >= 3:1)"],
        ["calc_payback_period_months()", "CAC payback period", "CAC / (MRR_per_customer * margin)"],
        ["calc_contribution_margin()", "Contribution margin", "revenue - variable_costs"],
        ["calc_break_even_units()", "Break-even units", "fixed_costs / (price - variable_cost)"],
        ["calc_gross_margin_pct()", "Gross margin %", "((revenue - COGS) / revenue) * 100"],
        ["calc_net_margin_pct()", "Net margin %", "(net_income / revenue) * 100"],
        ["calc_mrr()", "Monthly Recurring Revenue", "active_subs * avg_monthly_price"],
        ["calc_arr()", "Annual Recurring Revenue", "MRR * 12"],
        ["calc_churn_rate()", "Churn rate", "customers_lost / customers_start"],
        ["calc_nrr()", "Net Revenue Retention", "(start + expansion - churned) / start"],
        ["calc_runway_months()", "Runway in months", "cash_balance / monthly_burn"],
        ["calc_revenue_per_hour()", "Revenue per hour worked", "revenue / hours_worked"],
        ["calc_utilization_rate()", "Billable utilization", "billable_hours / total_hours"],
      ],
      [3200, 2800, 3500]
    ),
    pageBreak(),
  ];
}

// ─── 6. Cognitive Cartridge System ───────────────────────────────────
function section6() {
  return [
    heading("6. Cognitive Cartridge System"),

    h2("6.1 Cartridge Schema"),
    para("Each cartridge is a JSON file conforming to cartridge_schema.json:"),
    bullet("cartridge_id: Unique identifier string"),
    bullet("version: Semantic version"),
    bullet("domain: Dot-notation domain (e.g., 'philosophy.stoicism')"),
    bullet("rules[]: Array of rule objects"),

    h3("6.1.1 Rule Structure"),
    bullet("rule_id: Unique rule identifier"),
    bullet("name: Human-readable rule name"),
    bullet("principle: Core principle text"),
    bullet("detection_triggers: Array of keyword strings for context matching"),
    bullet("insight_template: Template string with {variable} placeholders"),
    bullet("confidence_weight: Float weight (0.0-1.0) for confidence scoring"),
    bullet("sovereign_need_served: Which of the 9 sovereign needs this rule serves"),
    bullet("connects_to: Array of related rule IDs"),
    bullet("tags: Array of tag strings for convergence detection"),

    h2("6.2 Domain Coverage (45 Domains)"),
    para("The dispatcher covers 45 cartridge domains organized into 7 categories:"),
    makeTable(
      ["Category", "Count", "Domains"],
      [
        ["Philosophy", "10", "stoicism, existentialism, buddhism, taoism, epicureanism, pragmatism, virtue_ethics, utilitarianism, deontology, phenomenology"],
        ["Psychology", "10", "cbt, emotional_regulation, attachment_theory, positive_psychology, behavioral, depth, trauma_recovery, motivation, habit_formation, social"],
        ["Productivity", "6", "deep_work, essentialism, time_management, goal_setting, decision_making, systems_thinking"],
        ["Health", "6", "physical_wellness, mental_health, sleep, nutrition, stress_management, mindfulness"],
        ["Finance", "5", "personal_finance, investing, risk_management, wealth_building, financial_planning"],
        ["Relationships", "5", "communication, conflict_resolution, boundaries, empathy, leadership"],
        ["Career", "3", "career_development, negotiation, entrepreneurship"],
      ],
      [2000, 1000, 6500]
    ),

    h2("6.3 Sovereign Needs (9 Dimensions)"),
    para("Every insight is tagged with the sovereign need it serves. The system tracks 9 needs plus uses 8 universal dimensions for blind-spot detection:"),
    makeTable(
      ["Sovereign Need", "Keywords", "Universal Dimension"],
      [
        ["autonomy", "control, freedom, independence, choice, agency", "Yes"],
        ["security", "safe, protect, stable, certainty, reliable", "Yes"],
        ["purpose", "meaning, mission, calling, legacy, contribution", "Yes"],
        ["resilience", "endure, recover, bounce back, persevere, grit", "Yes"],
        ["clarity", "clear, insight, direction, focus, perspective", "Yes"],
        ["belonging", "connect, community, tribe, accepted, together", "Yes"],
        ["integrity", "honest, truth, authentic, values, principled", "Yes"],
        ["growth", "improve, learn, develop, evolve, mastery", "Yes"],
        ["expression", "express, create, voice, art, identity", "No (blind-spot detection only uses 8)"],
      ],
      [2000, 4000, 3500]
    ),

    h2("6.4 Reasoning Pipeline"),
    para("The full cognitive pipeline operates as follows:"),
    bullet("1. Dispatcher scores text against 45 domain keyword maps (10 keywords each)"),
    bullet("2. Top 5 domains selected; complexity classified (low/medium/high)"),
    bullet("3. CartridgeConductor filters cartridges by domain prefix match"),
    bullet("4. run_rules() matches detection_triggers against context; computes proportional confidence"),
    bullet("5. Up to 20 insights ranked by confidence descending"),
    bullet("6. ReasoningSynthesizer converts CartridgeInsight objects to raw dicts"),
    bullet("7. synthesise() runs convergence detection (shared tags), tension detection (opposing pairs), blind-spot detection (missing dimensions)"),
    bullet("8. OutputValidator checks 4 gates: SAFE, TRUE, HIGH-LEVERAGE, ALIGNED"),
    bullet("9. OutputComposer produces ComposedOutput (summary, primary insight, supporting points, tensions, blind spots, recommended action)"),
    bullet("10. If validation fails, degraded output is returned with failure explanation"),
    pageBreak(),
  ];
}

// ─── 7. Testing Standards ────────────────────────────────────────────
function section7() {
  return [
    heading("7. Testing Standards"),

    h2("7.1 Test Suite Overview"),
    para("The test suite lives in tests/ and uses pytest. All 19 test files follow consistent patterns:"),
    makeTable(
      ["Test File", "Module Under Test", "Test Count (approx)"],
      [
        ["test_persist_pain.py", "Pain_Point_Register CRUD", "15+"],
        ["test_persist_solutions.py", "Solution_Design + MoneyScan CRUD", "20+"],
        ["test_api_health.py", "API health endpoints", "10+"],
        ["test_kb_search.py", "Knowledge base search", "15+"],
        ["test_ai_connect.py", "Ollama connectivity", "8+"],
        ["test_ai_infer.py", "LLM inference", "8+"],
        ["test_orchestrator.py", "Orchestrator class", "8+"],
        ["test_agent_pain.py", "Pain analysis agent", "10+"],
        ["test_agent_graph.py", "GraphRAG agent", "10+"],
        ["test_agent_experiment.py", "Experiment agent", "12+"],
        ["test_agent_synthesis.py", "KB synthesis agent", "12+"],
        ["test_agent_report.py", "Report agent", "10+"],
        ["test_agent_monitor.py", "Monitor agent", "12+"],
        ["test_cartridge_loader.py", "Cartridge loading + rules", "15+"],
        ["test_financial_metrics.py", "15 financial calculations", "58"],
        ["test_orchestration.py", "5-component pipeline", "20+"],
        ["test_reasoning_substrate.py", "Synthesis engine", "15+"],
      ],
      [3500, 3500, 2500]
    ),

    h2("7.2 Testing Conventions"),
    bullet("All public functions must have at least one positive and one negative test case"),
    bullet("Tests use in-memory SQLite (:memory:) — no file I/O side effects"),
    bullet("LLM calls are mocked using monkeypatch or unittest.mock"),
    bullet("ChromaDB is mocked with lightweight stub classes"),
    bullet("Return shapes are validated (always dict with success key for agents)"),
    bullet("Edge cases: empty inputs, None connections, missing tables, malformed IDs"),

    h2("7.3 Running Tests"),
    bullet("Full suite: pytest tests/ -v"),
    bullet("Single file: pytest tests/test_financial_metrics.py -v"),
    bullet("With coverage: pytest tests/ --cov=src --cov-report=term-missing"),
    pageBreak(),
  ];
}

// ─── 8. API Contract ─────────────────────────────────────────────────
function section8() {
  return [
    heading("8. API & CLI Contract"),

    h2("8.1 CLI Entry Point"),
    para("src/cli/cli_main.py provides the command-line interface:"),
    bullet("cli_pain.py: Pain-related commands"),
    bullet("cli_solutions.py: Solution management commands"),
    bullet("cli_report.py: Report generation commands"),

    h2("8.2 API Endpoints (src/api/)"),
    makeTable(
      ["Endpoint Module", "Purpose", "Methods"],
      [
        ["api_health.py", "System health checks", "GET /health, GET /status"],
        ["api_pain.py", "Pain CRUD + analysis", "GET/POST /pain, GET /pain/{id}/analyze"],
        ["api_predictions.py", "Prediction management", "GET/POST /predictions, GET /calibration"],
        ["api_solutions.py", "Solution management", "GET/POST /solutions, GET /quick-wins"],
      ],
      [2500, 3000, 4000]
    ),

    h2("8.3 Agent Contract"),
    para("All Layer 2 agents must implement:"),
    bullet("handle(query: str, conn, kb_conn) -> dict with at least {success: bool, response: str}"),
    bullet("Graceful degradation: If DB or KB is None, agent should return a meaningful error, not crash"),
    bullet("All exceptions caught internally; never raise to the orchestrator"),
    pageBreak(),
  ];
}

// ─── 9. Configuration ────────────────────────────────────────────────
function section9() {
  return [
    heading("9. Configuration"),

    h2("9.1 Environment Variables"),
    makeTable(
      ["Variable", "Default", "Purpose"],
      [
        ["OLLAMA_HOST", "http://localhost:11434", "Ollama server URL"],
        ["OLLAMA_MODEL", "deepseek-r1:8b", "Default LLM model for inference"],
        ["AEOS_DB_PATH", "../db/aeOS.db", "SQLite database file path"],
        ["AEOS_KB_PATH", "", "ChromaDB persistence directory"],
      ],
      [3000, 3000, 3500]
    ),

    h2("9.2 SQLite Configuration"),
    bullet("journal_mode = WAL (Write-Ahead Logging for concurrent reads)"),
    bullet("foreign_keys = ON (strict referential integrity)"),
    bullet("synchronous = NORMAL (performance + safety balance)"),
    bullet("busy_timeout = 5000ms"),
    bullet("row_factory = sqlite3.Row (dict-like access)"),

    h2("9.3 Naming Conventions"),
    makeTable(
      ["Convention", "Pattern", "Example"],
      [
        ["Pain ID", "PAIN-YYYYMMDD-NNN", "PAIN-20260301-001"],
        ["Idea ID", "MSR-YYYYMMDD-NNN", "MSR-20260215-042"],
        ["Solution ID", "SOL-YYYYMMDD-NNN", "SOL-20260301-003"],
        ["Prediction ID", "PRED-YYYYMMDD-NNN", "PRED-20260220-007"],
        ["Execution ID", "EXEC-YYYYMMDD-NNN", "EXEC-20260301-012"],
        ["Non-Monetary ID", "NML-YYYYMMDD-NNN", "NML-20260228-005"],
        ["Mental Model ID", "MM-NNN", "MM-001"],
      ],
      [2500, 3000, 4000]
    ),
    pageBreak(),
  ];
}

// ─── 10. Appendices ──────────────────────────────────────────────────
function section10() {
  return [
    heading("10. Appendices"),

    h2("10.1 File Tree"),
    para("aeOS/"),
    bullet("src/ — Python source code"),
    subBullet("core/ — config, logger, auth, safety, history"),
    subBullet("ai/ — ai_connect, ai_infer, ai_context, ai_router"),
    subBullet("agents/ — 10 agents (pain, solution, prediction, bias, memory, graph, experiment, synthesis, report, monitor)"),
    subBullet("orchestrator/ — orchestrator.py (central coordinator)"),
    subBullet("orchestration/ — models, dispatcher, cartridge_conductor, reasoning_synthesizer, output_validator, output_composer"),
    subBullet("cognitive/ — cartridge_loader, reasoning_substrate"),
    subBullet("cartridges/ — JSON cartridge files + schema"),
    subBullet("calc/ — calc_pain, calc_brier, calc_calibration, calc_bestmoves, bias_detector, prediction_engine, solution_bridge, solution_scorer"),
    subBullet("kb/ — kb_connect, kb_index, kb_ingest, kb_search"),
    subBullet("db/ — db_connect, db_init"),
    subBullet("cli/ — cli_main, cli_pain, cli_report, cli_solutions"),
    subBullet("api/ — api_health, api_pain, api_predictions, api_solutions"),
    subBullet("profile/ — investor_profile"),
    subBullet("financial_metrics.py — 15 pure calculation functions"),
    bullet("db/ — Database files"),
    subBullet("aeOS_PERSIST_v1.0.sql — Full schema (20 CT + 13 core tables + 1 view)"),
    subBullet("migrations/ — Incremental migrations"),
    bullet("tests/ — 19 test files with 200+ test cases"),
    bullet("docs/ — Documentation generators"),

    h2("10.2 Validation Rules Summary"),
    para("The database enforces ~50 validation rules:"),
    bullet("V1-V10: ID format validation (GLOB patterns)"),
    bullet("V11-V20: Score range constraints (0-100, 1-10, 0-1)"),
    bullet("V21-V30: Referential integrity via foreign keys to code tables"),
    bullet("V31-V40: Date validation (julianday() IS NOT NULL)"),
    bullet("V41-V50: Business rules (minimum text lengths, exclusive constraints, self-reference prevention)"),

    h2("10.3 Opposing Pairs (Tension Detection)"),
    para("The reasoning substrate detects tensions between these opposing concept pairs:"),
    makeTable(
      ["Pair A", "Pair B", "Example Tension"],
      [
        ["acceptance", "discipline", "Accepting current state vs. pushing for change"],
        ["presence", "preparation", "Being in the moment vs. planning ahead"],
        ["mindfulness", "visualization", "Observing what is vs. imagining what could be"],
        ["community", "self-mastery", "Group identity vs. individual excellence"],
        ["control", "acceptance", "Taking charge vs. letting go"],
      ],
      [2500, 2500, 4500]
    ),

    h2("10.4 Revision History"),
    makeTable(
      ["Version", "Date", "Changes"],
      [
        ["1.0", "2025-12", "Initial build spec"],
        ["2.0", "2026-01", "Added Phase 4-5 agents, orchestrator, testing standards"],
        ["3.0", "2026-03", "Added Cognitive Core (cartridge system, reasoning substrate, 5-component orchestration), financial metrics, expanded database documentation"],
      ],
      [1500, 1500, 6500]
    ),
  ];
}

// ─── Document Assembly ───────────────────────────────────────────────
async function main() {
  const doc = new Document({
    creator: "aeOS Build System",
    title: "aeOS Build Specification v3.0",
    description: "Complete technical build specification for the aeOS platform",
    sections: [{
      properties: {
        page: {
          margin: { top: 1200, bottom: 1200, left: 1200, right: 1200 },
        },
      },
      children: [
        ...coverPage(),
        ...section1(),
        ...section2(),
        ...section3(),
        ...section4(),
        ...section5(),
        ...section6(),
        ...section7(),
        ...section8(),
        ...section9(),
        ...section10(),
      ],
    }],
  });

  const buffer = await Packer.toBuffer(doc);
  const outPath = path.join(__dirname, "aeOS_Build_Spec_v3.0.docx");
  fs.writeFileSync(outPath, buffer);
  console.log(`Generated: ${outPath} (${(buffer.length / 1024).toFixed(1)} KB)`);
}

main().catch(err => { console.error(err); process.exit(1); });
