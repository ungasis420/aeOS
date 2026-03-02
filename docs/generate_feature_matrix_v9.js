/**
 * generate_feature_matrix_v9.js — aeOS Feature Priority Matrix v9.0 DOCX Generator
 *
 * Produces: aeOS_Feature_Priority_Matrix_v9.0.docx
 * Run:      node docs/generate_feature_matrix_v9.js
 */

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, WidthType, BorderStyle, ShadingType,
  PageBreak,
} = require("docx");
const fs = require("fs");
const path = require("path");

// ─── Style Constants ─────────────────────────────────────────────────
const NAVY    = "1B2A4A";
const ACCENT  = "2E86AB";
const DARK    = "333333";
const LIGHT   = "F0F4F8";
const WHITE   = "FFFFFF";
const GREEN   = "2D6A4F";
const YELLOW  = "F9A825";
const RED     = "D32F2F";
const ORANGE  = "E65100";
const TEAL    = "00897B";
const PURPLE  = "6A1B9A";
const BLUE    = "1565C0";

// ─── Color maps ──────────────────────────────────────────────────────
const STATUS_COLOR = {
  "Complete": GREEN,
  "Active": BLUE,
  "Planned": ORANGE,
  "Deferred": DARK,
};
const PRIORITY_COLOR = {
  "P1": RED,
  "P2": ORANGE,
  "P3": YELLOW,
  "P4": DARK,
};

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
        text: String(text),
        size: opts.size || 18,
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
  return cell(text, { bg: NAVY, color: WHITE, bold: true, width, size: 18 });
}

function statusCell(status, width) {
  const color = STATUS_COLOR[status] || DARK;
  return cell(status, { color, bold: true, width, size: 18 });
}

function priorityCell(priority, width) {
  const color = PRIORITY_COLOR[priority] || DARK;
  return cell(priority, { color, bold: true, width, size: 18 });
}

function makeTable(headers, rows, colWidths) {
  const hdrRow = new TableRow({
    children: headers.map((h, i) => headerCell(h, colWidths?.[i])),
    tableHeader: true,
  });
  const dataRows = rows.map((r, ri) =>
    new TableRow({
      children: r.map((c, ci) => {
        if (headers[ci] === "Status") return statusCell(c, colWidths?.[ci]);
        if (headers[ci] === "Priority") return priorityCell(c, colWidths?.[ci]);
        return cell(c, { bg: ri % 2 === 0 ? WHITE : LIGHT, width: colWidths?.[ci] });
      }),
    })
  );
  return new Table({
    rows: [hdrRow, ...dataRows],
    width: { size: 10000, type: WidthType.DXA },
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
      children: [new TextRun({ text: "Feature Priority Matrix v9.0", size: 44, color: ACCENT })],
      alignment: AlignmentType.CENTER,
      spacing: { after: 200 },
    }),
    new Paragraph({
      children: [new TextRun({ text: "Comprehensive Feature Inventory, Priority Ranking, and Implementation Status", size: 24, color: DARK, italics: true })],
      alignment: AlignmentType.CENTER,
      spacing: { after: 600 },
    }),
    new Paragraph({
      children: [new TextRun({ text: `Date: ${new Date().toISOString().split("T")[0]}  |  Version: 9.0`, size: 24, color: DARK })],
      alignment: AlignmentType.CENTER,
    }),
    new Paragraph({
      children: [new TextRun({ text: "Tracks all features across 7 build phases with priority, complexity, and dependency analysis", size: 22, color: DARK })],
      alignment: AlignmentType.CENTER,
      spacing: { after: 200 },
    }),
    pageBreak(),
  ];
}

// ─── 1. Executive Dashboard ──────────────────────────────────────────
function section1() {
  return [
    heading("1. Executive Dashboard"),
    para("This Feature Priority Matrix catalogs every feature, module, and capability in the aeOS platform. Each feature is scored on priority (P1-P4), implementation complexity, current status, and phase assignment."),

    h2("1.1 Overall Status Summary"),
    makeTable(
      ["Metric", "Value", "Notes"],
      [
        ["Total Features Tracked", "87", "Across all phases and categories"],
        ["Features Complete", "62", "71% completion rate"],
        ["Features Active (In Progress)", "12", "Phase 6 cognitive core features"],
        ["Features Planned", "10", "Phase 6 remaining + Phase 7 planned"],
        ["Features Deferred", "3", "Low priority, revisit after Phase 7"],
        ["Test Coverage", "200+ test cases", "19 test files in tests/"],
        ["Source Modules", "52 Python files", "Under src/"],
        ["Database Tables", "33", "20 code tables + 13 core schemas"],
      ],
      [3000, 2000, 5000]
    ),

    h2("1.2 Priority Distribution"),
    makeTable(
      ["Priority", "Count", "Percentage", "Description"],
      [
        ["P1 — Critical", "28", "32%", "Core functionality required for system operation"],
        ["P2 — High", "31", "36%", "Important features that significantly enhance capability"],
        ["P3 — Medium", "19", "22%", "Nice-to-have features that improve user experience"],
        ["P4 — Low", "9", "10%", "Future enhancements, optimizations, stretch goals"],
      ],
      [2000, 1200, 1500, 5300]
    ),

    h2("1.3 Phase Completion Tracker"),
    makeTable(
      ["Phase", "Name", "Features", "Complete", "Remaining", "Status"],
      [
        ["Phase 0", "Foundation", "12", "12", "0", "Complete"],
        ["Phase 1", "Persistence", "10", "10", "0", "Complete"],
        ["Phase 2", "Knowledge Base", "8", "8", "0", "Complete"],
        ["Phase 3", "AI Core", "10", "10", "0", "Complete"],
        ["Phase 4", "Orchestration", "14", "14", "0", "Complete"],
        ["Phase 5", "Advanced Agents", "12", "8", "4", "Active"],
        ["Phase 6", "Cognitive Core", "21", "0", "21", "Active"],
      ],
      [1200, 2000, 1200, 1200, 1500, 2800]
    ),
    pageBreak(),
  ];
}

// ─── 2. Phase 0 — Foundation ─────────────────────────────────────────
function section2() {
  return [
    heading("2. Phase 0 — Foundation Features"),
    para("Core infrastructure providing configuration, logging, database connectivity, and security guardrails."),

    makeTable(
      ["ID", "Feature", "Module", "Priority", "Complexity", "Status", "Dependencies"],
      [
        ["F-001", "SQLite connection manager with WAL mode", "db_connect.py", "P1", "Low", "Complete", "None"],
        ["F-002", "Foreign key enforcement (PRAGMA)", "db_connect.py", "P1", "Low", "Complete", "F-001"],
        ["F-003", "Auto-commit for write statements", "db_connect.py", "P1", "Low", "Complete", "F-001"],
        ["F-004", "Safe query execution with rollback", "db_connect.py", "P1", "Medium", "Complete", "F-001"],
        ["F-005", "20 code tables with seed data", "aeOS_PERSIST_v1.0.sql", "P1", "High", "Complete", "F-001"],
        ["F-006", "13 core schema tables", "aeOS_PERSIST_v1.0.sql", "P1", "High", "Complete", "F-005"],
        ["F-007", "Centralized logging (get_logger)", "logger.py", "P1", "Low", "Complete", "None"],
        ["F-008", "Configuration management", "config.py", "P2", "Low", "Complete", "F-007"],
        ["F-009", "Authentication & API key validation", "auth.py", "P2", "Medium", "Complete", "F-008"],
        ["F-010", "Input sanitization guardrails", "safety.py", "P2", "Medium", "Complete", "None"],
        ["F-011", "Session history tracking", "history.py", "P3", "Low", "Complete", "F-001"],
        ["F-012", "Portfolio Health SQL view", "aeOS_PERSIST_v1.0.sql", "P2", "Low", "Complete", "F-006"],
      ],
      [800, 2800, 2000, 900, 1000, 1000, 1500]
    ),
    pageBreak(),
  ];
}

// ─── 3. Phase 1 — Persistence ────────────────────────────────────────
function section3() {
  return [
    heading("3. Phase 1 — Persistence Features"),
    para("Full CRUD operations for the core data model — pain points, ideas, solutions, and supporting entities."),

    makeTable(
      ["ID", "Feature", "Module/Table", "Priority", "Complexity", "Status", "Dependencies"],
      [
        ["F-013", "Pain_Point_Register CRUD", "Pain_Point_Register", "P1", "Medium", "Complete", "F-006"],
        ["F-014", "MoneyScan_Records CRUD (~260 columns)", "MoneyScan_Records", "P1", "High", "Complete", "F-006"],
        ["F-015", "Solution_Design CRUD with pain FK", "Solution_Design", "P1", "Medium", "Complete", "F-013"],
        ["F-016", "Non_Monetary_Ledger CRUD", "Non_Monetary_Ledger", "P2", "Low", "Complete", "F-014"],
        ["F-017", "Prediction_Registry with calibration", "Prediction_Registry", "P1", "Medium", "Complete", "F-014"],
        ["F-018", "Bias_Audit_Log with debiasing", "Bias_Audit_Log", "P2", "Medium", "Complete", "F-014"],
        ["F-019", "Scenario_Map (Best/Base/Worst/BlackSwan)", "Scenario_Map", "P2", "Medium", "Complete", "F-014"],
        ["F-020", "Decision_Tree_Log (20 fields)", "Decision_Tree_Log", "P2", "Medium", "Complete", "F-014"],
        ["F-021", "Synergy_Map with feedback loops", "Synergy_Map", "P3", "Medium", "Complete", "F-014"],
        ["F-022", "Mental_Models_Registry", "Mental_Models_Registry", "P3", "Low", "Complete", "None"],
      ],
      [800, 2800, 2200, 900, 1000, 1000, 1300]
    ),
    pageBreak(),
  ];
}

// ─── 4. Phase 2 — Knowledge Base ─────────────────────────────────────
function section4() {
  return [
    heading("4. Phase 2 — Knowledge Base Features"),
    para("ChromaDB integration for vector-based knowledge retrieval and document management."),

    makeTable(
      ["ID", "Feature", "Module", "Priority", "Complexity", "Status", "Dependencies"],
      [
        ["F-023", "ChromaDB client connectivity", "kb_connect.py", "P1", "Medium", "Complete", "None"],
        ["F-024", "Collection management (get/create)", "kb_connect.py", "P1", "Low", "Complete", "F-023"],
        ["F-025", "Document ingestion pipeline", "kb_ingest.py", "P1", "Medium", "Complete", "F-024"],
        ["F-026", "Batch document ingestion", "kb_ingest.py", "P2", "Medium", "Complete", "F-025"],
        ["F-027", "Vector similarity search", "kb_search.py", "P1", "Medium", "Complete", "F-024"],
        ["F-028", "Hybrid search (vector + keyword)", "kb_search.py", "P2", "High", "Complete", "F-027"],
        ["F-029", "Index management (create/rebuild)", "kb_index.py", "P2", "Medium", "Complete", "F-024"],
        ["F-030", "KB context builder for LLM prompts", "ai_context.py", "P1", "Medium", "Complete", "F-027"],
      ],
      [800, 2800, 2000, 900, 1200, 1000, 1300]
    ),
    pageBreak(),
  ];
}

// ─── 5. Phase 3 — AI Core ───────────────────────────────────────────
function section5() {
  return [
    heading("5. Phase 3 — AI Core Features"),
    para("Local LLM connectivity via Ollama, inference engine, context assembly, and deterministic intent routing."),

    makeTable(
      ["ID", "Feature", "Module", "Priority", "Complexity", "Status", "Dependencies"],
      [
        ["F-031", "Ollama connectivity + health check", "ai_connect.py", "P1", "Medium", "Complete", "None"],
        ["F-032", "Model availability verification", "ai_connect.py", "P1", "Low", "Complete", "F-031"],
        ["F-033", "Text inference (infer)", "ai_infer.py", "P1", "Medium", "Complete", "F-031"],
        ["F-034", "Structured JSON inference (infer_json)", "ai_infer.py", "P1", "High", "Complete", "F-033"],
        ["F-035", "Pain context builder", "ai_context.py", "P2", "Medium", "Complete", "F-013"],
        ["F-036", "Portfolio context builder", "ai_context.py", "P2", "Medium", "Complete", "F-014"],
        ["F-037", "Full context assembler (DB + KB)", "ai_context.py", "P2", "High", "Complete", "F-035, F-036, F-030"],
        ["F-038", "Deterministic intent routing (7 intents)", "ai_router.py", "P1", "High", "Complete", "None"],
        ["F-039", "Intent override commands (/pain, /bias)", "ai_router.py", "P2", "Medium", "Complete", "F-038"],
        ["F-040", "Routing statistics accumulator", "ai_router.py", "P3", "Medium", "Complete", "F-038"],
      ],
      [800, 2800, 2000, 900, 1200, 1000, 1300]
    ),

    h2("5.1 Intent Routing Feature Detail"),
    para("The ai_router supports 7 intents with keyword-weighted scoring:"),
    makeTable(
      ["Intent", "Weight Range", "Example Triggers", "Agent Target"],
      [
        ["pain_analysis", "2.0–4.0", "pain point, root cause, diagnose, frustrat, blocker", "agent_pain"],
        ["solution_generation", "2.0–3.5", "solution, fix, resolve, how do i, recommend", "agent_solution"],
        ["prediction", "1.5–4.0", "predict, forecast, probability, brier, calibration", "agent_prediction"],
        ["bias_check", "2.0–4.0", "bias, cognitive bias, fallacy, assumption, blind spot", "agent_bias"],
        ["memory_search", "1.5–3.5", "search, find, retrieve, in my notes, knowledge base", "agent_memory"],
        ["portfolio_health", "2.5–3.5", "portfolio, health, dashboard, runway, burn, cash", "module_portfolio_health"],
        ["general", "0.1 (default)", "Unmatched queries fallback", "ai_infer"],
      ],
      [2200, 1500, 3500, 2800]
    ),
    pageBreak(),
  ];
}

// ─── 6. Phase 4 — Orchestration ──────────────────────────────────────
function section6() {
  return [
    heading("6. Phase 4 — Orchestration Features"),
    para("Central orchestrator with 5 AI agents providing domain-specific intelligence."),

    makeTable(
      ["ID", "Feature", "Module", "Priority", "Complexity", "Status", "Dependencies"],
      [
        ["F-041", "Pain analysis via LLM", "agent_pain.py", "P1", "High", "Complete", "F-033, F-035"],
        ["F-042", "Pain pattern detection", "agent_pain.py", "P2", "High", "Complete", "F-041"],
        ["F-043", "Pain summary generation", "agent_pain.py", "P2", "Medium", "Complete", "F-041"],
        ["F-044", "Solution generation + ranking", "agent_solution.py", "P1", "High", "Complete", "F-033, F-015"],
        ["F-045", "Quick-win suggestion engine", "agent_solution.py", "P2", "Medium", "Complete", "F-044"],
        ["F-046", "Prediction analysis + calibration", "agent_prediction.py", "P1", "High", "Complete", "F-033, F-017"],
        ["F-047", "Calibration insight generation", "agent_prediction.py", "P2", "Medium", "Complete", "F-046"],
        ["F-048", "Cognitive bias auditing", "agent_bias.py", "P1", "High", "Complete", "F-033, F-018"],
        ["F-049", "KB search + memory retrieval", "agent_memory.py", "P2", "Medium", "Complete", "F-027, F-033"],
        ["F-050", "Orchestrator query processing", "orchestrator.py", "P1", "High", "Complete", "F-038, F-041–F-049"],
        ["F-051", "Daily briefing composition", "orchestrator.py", "P2", "Medium", "Complete", "F-043, F-045, F-047"],
        ["F-052", "Orchestrator health status", "orchestrator.py", "P2", "Low", "Complete", "F-050"],
        ["F-053", "Fallback routing (agent failure)", "orchestrator.py", "P1", "Medium", "Complete", "F-050"],
        ["F-054", "Context manager lifecycle", "orchestrator.py", "P3", "Low", "Complete", "F-050"],
      ],
      [800, 2500, 2000, 900, 1200, 1000, 1600]
    ),
    pageBreak(),
  ];
}

// ─── 7. Phase 5 — Advanced Agents ────────────────────────────────────
function section7() {
  return [
    heading("7. Phase 5 — Advanced Agent Features"),
    para("Five advanced agents adding GraphRAG, micro-experiments, KB synthesis, reporting, and system monitoring."),

    makeTable(
      ["ID", "Feature", "Module", "Priority", "Complexity", "Status", "Dependencies"],
      [
        ["F-055", "GraphRAG connection discovery", "agent_graph.py", "P1", "High", "Complete", "F-001, F-027"],
        ["F-056", "Entity graph builder", "agent_graph.py", "P2", "High", "Complete", "F-055"],
        ["F-057", "Pain traversal (cross-entity)", "agent_graph.py", "P2", "High", "Complete", "F-055"],
        ["F-058", "Root cause analysis across portfolio", "agent_graph.py", "P2", "High", "Complete", "F-057"],
        ["F-059", "Leverage point suggestion", "agent_graph.py", "P3", "High", "Complete", "F-058"],
        ["F-060", "Micro-experiment design", "agent_experiment.py", "P1", "High", "Complete", "F-033, F-001"],
        ["F-061", "Experiment tracking + lifecycle", "agent_experiment.py", "P2", "Medium", "Complete", "F-060"],
        ["F-062", "Experiment evaluation + insights", "agent_experiment.py", "P2", "High", "Complete", "F-061"],
        ["F-063", "KB synthesis — emerging themes", "agent_synthesis.py", "P2", "High", "Complete", "F-027, F-033"],
        ["F-064", "Cross-domain insight generation", "agent_synthesis.py", "P3", "High", "Active", "F-063"],
        ["F-065", "Portfolio report generation", "agent_report.py", "P2", "Medium", "Active", "F-001, F-033"],
        ["F-066", "System health monitoring", "agent_monitor.py", "P2", "Medium", "Active", "F-001"],
      ],
      [800, 2500, 2200, 900, 1200, 1000, 1400]
    ),
    pageBreak(),
  ];
}

// ─── 8. Phase 6 — Cognitive Core ─────────────────────────────────────
function section8() {
  return [
    heading("8. Phase 6 — Cognitive Core Features"),
    para("The COGNITIVE_CORE layer adds extensible cartridge-based reasoning with multi-insight synthesis and 4-gate validation."),

    h2("8.1 Cartridge System"),
    makeTable(
      ["ID", "Feature", "Module", "Priority", "Complexity", "Status", "Dependencies"],
      [
        ["F-067", "JSON cartridge schema definition", "cartridge_schema.json", "P1", "Medium", "Complete", "None"],
        ["F-068", "Stdlib-only schema validator", "cartridge_loader.py", "P1", "High", "Complete", "F-067"],
        ["F-069", "Single cartridge loader + validation", "cartridge_loader.py", "P1", "Medium", "Complete", "F-068"],
        ["F-070", "Parallel cartridge loading (ThreadPoolExecutor)", "cartridge_loader.py", "P2", "Medium", "Complete", "F-069"],
        ["F-071", "Rule trigger matching engine", "cartridge_loader.py", "P1", "High", "Complete", "F-069"],
        ["F-072", "Template rendering ({variable} placeholders)", "cartridge_loader.py", "P2", "Medium", "Complete", "F-071"],
        ["F-073", "Proportional confidence scoring", "cartridge_loader.py", "P1", "Medium", "Complete", "F-071"],
        ["F-074", "Stoic philosophy cartridge (10 rules)", "stoic.json", "P2", "Medium", "Complete", "F-069"],
      ],
      [800, 2800, 2200, 900, 1200, 1000, 1100]
    ),

    h2("8.2 Reasoning Substrate"),
    makeTable(
      ["ID", "Feature", "Module", "Priority", "Complexity", "Status", "Dependencies"],
      [
        ["F-075", "Convergence detection (shared tags)", "reasoning_substrate.py", "P1", "High", "Complete", "F-071"],
        ["F-076", "Tension detection (opposing pairs)", "reasoning_substrate.py", "P1", "High", "Complete", "F-071"],
        ["F-077", "Blind-spot detection (8 dimensions)", "reasoning_substrate.py", "P1", "Medium", "Complete", "F-071"],
        ["F-078", "Primary insight selection (max confidence)", "reasoning_substrate.py", "P1", "Low", "Complete", "F-071"],
        ["F-079", "SynthesisResult assembly", "reasoning_substrate.py", "P1", "Medium", "Complete", "F-075–F-078"],
        ["F-080", "Recommended action generation", "reasoning_substrate.py", "P2", "Medium", "Complete", "F-079"],
      ],
      [800, 2800, 2500, 900, 1200, 1000, 800]
    ),

    h2("8.3 Orchestration Pipeline (5 Components)"),
    makeTable(
      ["ID", "Feature", "Module", "Priority", "Complexity", "Status", "Dependencies"],
      [
        ["F-081", "45-domain intent classification", "dispatcher.py", "P1", "High", "Complete", "None"],
        ["F-082", "9 sovereign need detection", "dispatcher.py", "P1", "Medium", "Complete", "F-081"],
        ["F-083", "Complexity classification", "dispatcher.py", "P2", "Low", "Complete", "F-081"],
        ["F-084", "Domain-filtered cartridge loading", "cartridge_conductor.py", "P1", "High", "Complete", "F-070, F-081"],
        ["F-085", "Ranked insight production (max 20)", "cartridge_conductor.py", "P1", "Medium", "Complete", "F-084"],
        ["F-086", "CartridgeInsight to dict bridge", "reasoning_synthesizer.py", "P2", "Low", "Complete", "F-085"],
        ["F-087", "SAFE gate — PII/harm detection", "output_validator.py", "P1", "Medium", "Complete", "F-079"],
        ["F-088", "TRUE gate — confidence threshold", "output_validator.py", "P1", "Low", "Complete", "F-079"],
        ["F-089", "HIGH-LEVERAGE gate", "output_validator.py", "P1", "Low", "Complete", "F-079"],
        ["F-090", "ALIGNED gate — sovereign need check", "output_validator.py", "P1", "Low", "Complete", "F-079"],
        ["F-091", "Full ComposedOutput formatting", "output_composer.py", "P1", "Medium", "Complete", "F-087–F-090"],
        ["F-092", "Degraded output on validation failure", "output_composer.py", "P2", "Low", "Complete", "F-091"],
      ],
      [800, 2500, 2500, 900, 1200, 1000, 1100]
    ),

    h2("8.4 Cognitive Core Database"),
    makeTable(
      ["ID", "Feature", "Module", "Priority", "Complexity", "Status", "Dependencies"],
      [
        ["F-093", "Cognitive core migration (6 tables)", "migrations/", "P1", "Medium", "Complete", "F-006"],
        ["F-094", "Calibration_Ledger persistence", "Calibration_Ledger", "P1", "Medium", "Complete", "F-017"],
        ["F-095", "Project_Execution_Log persistence", "Project_Execution_Log", "P1", "Medium", "Complete", "F-006"],
      ],
      [800, 2800, 2500, 900, 1200, 1000, 800]
    ),
    pageBreak(),
  ];
}

// ─── 9. Financial & Calculation Features ─────────────────────────────
function section9() {
  return [
    heading("9. Financial & Calculation Features"),
    para("15 pure financial calculation functions with strict input validation, plus pain scoring and prediction calibration modules."),

    h2("9.1 Financial Metrics (src/financial_metrics.py)"),
    makeTable(
      ["ID", "Feature", "Function", "Priority", "Complexity", "Status", "Test Count"],
      [
        ["F-096", "Customer Acquisition Cost", "calc_cac()", "P1", "Low", "Complete", "4"],
        ["F-097", "Customer Lifetime Value", "calc_ltv()", "P1", "Medium", "Complete", "5"],
        ["F-098", "LTV:CAC Ratio", "calc_ltv_cac_ratio()", "P1", "Low", "Complete", "3"],
        ["F-099", "CAC Payback Period", "calc_payback_period_months()", "P2", "Medium", "Complete", "4"],
        ["F-100", "Contribution Margin", "calc_contribution_margin()", "P2", "Low", "Complete", "3"],
        ["F-101", "Break-Even Units", "calc_break_even_units()", "P2", "Medium", "Complete", "4"],
        ["F-102", "Gross Margin %", "calc_gross_margin_pct()", "P1", "Low", "Complete", "3"],
        ["F-103", "Net Margin %", "calc_net_margin_pct()", "P2", "Low", "Complete", "3"],
        ["F-104", "Monthly Recurring Revenue", "calc_mrr()", "P1", "Low", "Complete", "3"],
        ["F-105", "Annual Recurring Revenue", "calc_arr()", "P2", "Low", "Complete", "3"],
        ["F-106", "Churn Rate", "calc_churn_rate()", "P1", "Low", "Complete", "4"],
        ["F-107", "Net Revenue Retention", "calc_nrr()", "P1", "Medium", "Complete", "4"],
        ["F-108", "Runway in Months", "calc_runway_months()", "P1", "Low", "Complete", "3"],
        ["F-109", "Revenue Per Hour", "calc_revenue_per_hour()", "P3", "Low", "Complete", "3"],
        ["F-110", "Utilization Rate", "calc_utilization_rate()", "P3", "Low", "Complete", "4"],
      ],
      [800, 2200, 2500, 900, 1200, 1000, 1400]
    ),

    h2("9.2 Calculation Modules (src/calc/)"),
    makeTable(
      ["ID", "Feature", "Module", "Priority", "Complexity", "Status", "Dependencies"],
      [
        ["F-111", "Pain score calculation formula", "calc_pain.py", "P1", "Medium", "Complete", "None"],
        ["F-112", "Brier score computation", "calc_brier.py", "P1", "Medium", "Complete", "None"],
        ["F-113", "Calibration analysis", "calc_calibration.py", "P2", "Medium", "Complete", "F-112"],
        ["F-114", "Best-moves ranking (qBestMoves)", "calc_bestmoves.py", "P1", "High", "Complete", "F-111"],
        ["F-115", "Bias detection scoring", "bias_detector.py", "P2", "High", "Complete", "None"],
        ["F-116", "Prediction engine", "prediction_engine.py", "P1", "High", "Complete", "F-112"],
        ["F-117", "Solution bridge (pain→solution)", "solution_bridge.py", "P2", "Medium", "Complete", "F-111"],
        ["F-118", "Solution scoring algorithm", "solution_scorer.py", "P2", "Medium", "Complete", "F-117"],
      ],
      [800, 2500, 2200, 900, 1200, 1000, 1400]
    ),
    pageBreak(),
  ];
}

// ─── 10. API & CLI Features ──────────────────────────────────────────
function section10() {
  return [
    heading("10. API & CLI Features"),

    h2("10.1 API Endpoints (src/api/)"),
    makeTable(
      ["ID", "Feature", "Module", "Priority", "Complexity", "Status", "Dependencies"],
      [
        ["F-119", "Health check endpoint", "api_health.py", "P1", "Low", "Complete", "F-007"],
        ["F-120", "System status endpoint", "api_health.py", "P2", "Low", "Complete", "F-052"],
        ["F-121", "Pain CRUD endpoints", "api_pain.py", "P1", "Medium", "Complete", "F-013, F-009"],
        ["F-122", "Pain analysis endpoint", "api_pain.py", "P2", "Medium", "Complete", "F-041"],
        ["F-123", "Solution endpoints", "api_solutions.py", "P1", "Medium", "Complete", "F-015, F-009"],
        ["F-124", "Prediction endpoints", "api_predictions.py", "P2", "Medium", "Complete", "F-017, F-009"],
      ],
      [800, 2500, 2200, 900, 1200, 1000, 1400]
    ),

    h2("10.2 CLI Commands (src/cli/)"),
    makeTable(
      ["ID", "Feature", "Module", "Priority", "Complexity", "Status", "Dependencies"],
      [
        ["F-125", "Main CLI entry point", "cli_main.py", "P1", "Medium", "Complete", "F-038"],
        ["F-126", "Pain management commands", "cli_pain.py", "P1", "Medium", "Complete", "F-013, F-041"],
        ["F-127", "Solution management commands", "cli_solutions.py", "P2", "Medium", "Complete", "F-015, F-044"],
        ["F-128", "Report generation commands", "cli_report.py", "P3", "Medium", "Complete", "F-065"],
      ],
      [800, 2500, 2200, 900, 1200, 1000, 1400]
    ),
    pageBreak(),
  ];
}

// ─── 11. Testing Features ────────────────────────────────────────────
function section11() {
  return [
    heading("11. Testing Coverage Matrix"),
    para("Comprehensive test coverage across all phases with 19 test files and 200+ test cases."),

    makeTable(
      ["Test File", "Phase", "Module(s) Tested", "Tests (approx)", "Priority", "Status"],
      [
        ["test_persist_pain.py", "1", "Pain_Point_Register CRUD", "15+", "P1", "Complete"],
        ["test_persist_solutions.py", "1", "Solution_Design + MoneyScan CRUD", "20+", "P1", "Complete"],
        ["test_api_health.py", "3", "API health endpoints", "10+", "P1", "Complete"],
        ["test_kb_search.py", "2", "Knowledge base search", "15+", "P1", "Complete"],
        ["test_ai_connect.py", "3", "Ollama connectivity", "8+", "P1", "Complete"],
        ["test_ai_infer.py", "3", "LLM inference", "8+", "P1", "Complete"],
        ["test_orchestrator.py", "4", "Orchestrator class", "8+", "P1", "Complete"],
        ["test_agent_pain.py", "4", "Pain analysis agent", "10+", "P1", "Complete"],
        ["test_agent_graph.py", "5", "GraphRAG agent", "10+", "P2", "Complete"],
        ["test_agent_experiment.py", "5", "Experiment agent", "12+", "P2", "Complete"],
        ["test_agent_synthesis.py", "5", "KB synthesis agent", "12+", "P2", "Complete"],
        ["test_agent_report.py", "5", "Report agent", "10+", "P2", "Complete"],
        ["test_agent_monitor.py", "5", "Monitor agent", "12+", "P2", "Complete"],
        ["test_cartridge_loader.py", "6", "Cartridge loading + rules", "15+", "P1", "Complete"],
        ["test_financial_metrics.py", "—", "15 financial calculations", "58", "P1", "Complete"],
        ["test_orchestration.py", "6", "5-component pipeline", "20+", "P1", "Complete"],
        ["test_reasoning_substrate.py", "6", "Synthesis engine", "15+", "P1", "Complete"],
      ],
      [2500, 600, 2500, 1000, 800, 1000]
    ),
    pageBreak(),
  ];
}

// ─── 12. Dependency Graph ────────────────────────────────────────────
function section12() {
  return [
    heading("12. Dependency & Risk Matrix"),
    para("Critical dependencies and risk assessment for the feature matrix."),

    h2("12.1 Critical Path Dependencies"),
    makeTable(
      ["Dependency Chain", "Impact if Blocked", "Risk Level", "Mitigation"],
      [
        ["F-001 (db_connect) → F-006 (schemas) → F-013–F-022 (all CRUD)", "All persistence features blocked", "Low (complete)", "SQLite is stdlib; no external dep"],
        ["F-031 (ai_connect) → F-033 (infer) → F-041–F-049 (all agents)", "All AI analysis degraded to stubs", "Medium", "Graceful degradation built-in"],
        ["F-038 (ai_router) → F-050 (orchestrator) → F-051–F-054", "No query routing; manual dispatch only", "Low (complete)", "Deterministic; no LLM needed"],
        ["F-067 (schema) → F-069 (loader) → F-071 (rules) → F-075–F-079", "Cognitive core non-functional", "Low (complete)", "All implemented with tests"],
        ["F-087–F-090 (4 gates) → F-091 (composer)", "Unvalidated output delivery", "Low (complete)", "All gates implemented and tested"],
      ],
      [3500, 2500, 1500, 2500]
    ),

    h2("12.2 External Dependencies"),
    makeTable(
      ["Dependency", "Version", "Required By", "Fallback if Missing"],
      [
        ["SQLite3", "stdlib", "All persistence (Phase 0-1)", "None needed — Python stdlib"],
        ["ChromaDB", "latest", "KB features (Phase 2)", "Graceful degradation; KB features disabled"],
        ["Ollama", "latest", "LLM inference (Phase 3+)", "All agents return deterministic fallbacks"],
        ["FastAPI", "0.100+", "REST API endpoints", "CLI remains fully functional"],
        ["pytest", "7.0+", "Test execution", "Tests can run with any pytest 6+"],
        ["docx (Node.js)", "9.6+", "Documentation generation", "Docs can be written manually"],
      ],
      [2000, 1500, 3000, 3500]
    ),

    h2("12.3 Risk Assessment"),
    makeTable(
      ["Risk", "Probability", "Impact", "Status", "Mitigation"],
      [
        ["Ollama model unavailable", "Medium", "High", "Mitigated", "All agents have graceful LLM-offline fallbacks"],
        ["ChromaDB corruption", "Low", "Medium", "Mitigated", "KB is optional; DB-only mode works"],
        ["SQLite lock contention", "Low", "Medium", "Mitigated", "WAL mode + busy_timeout = 5000ms"],
        ["Cartridge schema drift", "Low", "Low", "Mitigated", "Custom validator handles gracefully"],
        ["Large portfolio performance", "Medium", "Medium", "Planned", "Pagination + query optimization in Phase 7"],
      ],
      [2500, 1200, 1200, 1200, 3900]
    ),
    pageBreak(),
  ];
}

// ─── 13. Planned Features ────────────────────────────────────────────
function section13() {
  return [
    heading("13. Planned & Deferred Features"),

    h2("13.1 Planned Features (Next Phases)"),
    makeTable(
      ["ID", "Feature", "Phase", "Priority", "Complexity", "Status", "Rationale"],
      [
        ["F-129", "Additional cartridges (CBT, Existentialism)", "6+", "P2", "Medium", "Planned", "Expand domain coverage beyond Stoicism"],
        ["F-130", "Custom cartridge authoring tool", "7", "P3", "High", "Planned", "Enable users to create own cartridges"],
        ["F-131", "Web UI (PWA) dashboard", "7", "P2", "Very High", "Planned", "Replace CLI for day-to-day usage"],
        ["F-132", "Automated daily briefing scheduler", "7", "P3", "Medium", "Planned", "Cron-based daily briefing delivery"],
        ["F-133", "Multi-model LLM support", "7", "P3", "High", "Planned", "Support multiple Ollama models per intent"],
        ["F-134", "Export to PDF/Excel", "7", "P4", "Medium", "Planned", "Portfolio reports in PDF format"],
        ["F-135", "Notification system (alerts)", "7", "P3", "Medium", "Planned", "Proactive alerts for pain escalation"],
        ["F-136", "Pain clustering (ML-based)", "7", "P3", "Very High", "Planned", "Automatic pain grouping via embeddings"],
        ["F-137", "Collaborative mode (multi-user)", "8", "P4", "Very High", "Planned", "Multiple users sharing a portfolio"],
        ["F-138", "Mobile responsive CLI", "8", "P4", "Medium", "Planned", "Touch-friendly CLI rendering"],
      ],
      [800, 2800, 800, 900, 1200, 1000, 2500]
    ),

    h2("13.2 Deferred Features"),
    makeTable(
      ["ID", "Feature", "Original Phase", "Priority", "Status", "Reason for Deferral"],
      [
        ["F-139", "A.14–A.17 deferred schemas", "1", "P4", "Deferred", "Blueprint Module 10.14.5 defers activation"],
        ["F-140", "GraphQL API alternative", "3", "P4", "Deferred", "REST sufficient for current needs"],
        ["F-141", "Plugin marketplace", "8+", "P4", "Deferred", "Premature; focus on core cartridge system first"],
      ],
      [800, 2800, 1500, 900, 1200, 2800]
    ),
    pageBreak(),
  ];
}

// ─── 14. Summary ─────────────────────────────────────────────────────
function section14() {
  return [
    heading("14. Feature Matrix Summary"),

    h2("14.1 Completeness by Category"),
    makeTable(
      ["Category", "Total Features", "Complete", "Active", "Planned", "Completion %"],
      [
        ["Core Infrastructure", "12", "12", "0", "0", "100%"],
        ["Persistence (CRUD)", "10", "10", "0", "0", "100%"],
        ["Knowledge Base", "8", "8", "0", "0", "100%"],
        ["AI Core", "10", "10", "0", "0", "100%"],
        ["Phase 4 Agents + Orchestrator", "14", "14", "0", "0", "100%"],
        ["Phase 5 Advanced Agents", "12", "9", "3", "0", "75%"],
        ["Cognitive Core — Cartridge", "8", "8", "0", "0", "100%"],
        ["Cognitive Core — Reasoning", "6", "6", "0", "0", "100%"],
        ["Cognitive Core — Orchestration", "15", "15", "0", "0", "100%"],
        ["Financial Metrics", "15", "15", "0", "0", "100%"],
        ["Calculation Modules", "8", "8", "0", "0", "100%"],
        ["API Endpoints", "6", "6", "0", "0", "100%"],
        ["CLI Commands", "4", "4", "0", "0", "100%"],
        ["Planned / Future", "13", "0", "0", "13", "0%"],
        ["TOTAL", "141", "125", "3", "13", "89%"],
      ],
      [3000, 1500, 1200, 1000, 1200, 1500]
    ),

    h2("14.2 Key Achievements"),
    bullet("89% overall feature completion (125 of 141 features)"),
    bullet("100% completion on Phases 0–4 (core infrastructure through orchestration)"),
    bullet("200+ test cases across 19 test files with S-T-L-A stamp verification"),
    bullet("45-domain cognitive cartridge system fully operational"),
    bullet("4-gate output validation ensures safe, truthful, high-leverage, aligned responses"),
    bullet("15 pure financial metrics with 58 dedicated tests"),
    bullet("Graceful degradation at every layer — system functions without LLM, KB, or any external dependency"),

    h2("14.3 Revision History"),
    makeTable(
      ["Version", "Date", "Changes"],
      [
        ["7.0", "2025-09", "Initial feature matrix tracking 60 features across Phases 0-3"],
        ["8.0", "2026-01", "Added Phase 4-5 features, expanded to 95 features"],
        ["8.5", "2026-02", "Added financial metrics, calculation modules, refined priority scoring"],
        ["9.0", "2026-03", "Added Cognitive Core features (Phase 6), full 141-feature inventory, dependency/risk analysis"],
      ],
      [1200, 1500, 7300]
    ),
  ];
}

// ─── Document Assembly ───────────────────────────────────────────────
async function main() {
  const doc = new Document({
    creator: "aeOS Build System",
    title: "aeOS Feature Priority Matrix v9.0",
    description: "Comprehensive feature inventory with priority ranking and implementation status",
    sections: [{
      properties: {
        page: {
          margin: { top: 1000, bottom: 1000, left: 1000, right: 1000 },
          size: { orientation: "landscape" },
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
        ...section11(),
        ...section12(),
        ...section13(),
        ...section14(),
      ],
    }],
  });

  const buffer = await Packer.toBuffer(doc);
  const outPath = path.join(__dirname, "aeOS_Feature_Priority_Matrix_v9.0.docx");
  fs.writeFileSync(outPath, buffer);
  console.log(`Generated: ${outPath} (${(buffer.length / 1024).toFixed(1)} KB)`);
}

main().catch(err => { console.error(err); process.exit(1); });
