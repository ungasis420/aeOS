"""
agent_bias.py
aeOS Phase 4 — Layer 2 (AI Agents)

AI agent that detects cognitive bias in reasoning chains and decisions.

Responsibilities:
- Scan arbitrary text for cognitive biases using the local LLM (Ollama via ai_infer).
- Audit a Decision_Tree_Log record, run bias scan, and persist result to Bias_Audit_Log.
- Produce a plain-English monthly bias report from Bias_Audit_Log.
- Provide targeted debiasing prompts per CT_Bias type.

Stamp: S✅ T✅ L✅ A✅
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ---- Logging (centralized) ---------------------------------------------------
try:
    from src.core.logger import get_logger  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    # Fallback for dev runs where `src/` is on PYTHONPATH.
    from core.logger import get_logger  # type: ignore

_LOG = get_logger(__name__)


# ---- AI primitives -----------------------------------------------------------
try:
    from src.ai.ai_infer import infer_json  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    from ai.ai_infer import infer_json  # type: ignore


# ---- Optional helpers (best-effort) ------------------------------------------
try:
    from src.db import bias_persist  # type: ignore
except Exception:  # pragma: no cover
    bias_persist = None  # type: ignore

try:
    from src.calc import bias_detector  # type: ignore
except Exception:  # pragma: no cover
    bias_detector = None  # type: ignore


# -----------------------------------------------------------------------------
# Constants / code tables (from Blueprint v8.4)
# -----------------------------------------------------------------------------

# Valid CT_Cog_State values
_CT_COG_STATES = {"Focused", "Fatigued", "Stressed", "Euphoric", "Neutral", "Anxious"}

# Valid CT_Bias values
_CT_BIASES = {
    "Confirmation_Bias",
    "Availability_Heuristic",
    "Survivorship_Bias",
    "Sunk_Cost_Fallacy",
    "Dunning_Kruger",
    "Loss_Aversion",
    "Optimism_Bias",
    "Anchoring",
    "Recency_Bias",
    "Planning_Fallacy",
    "Hindsight_Bias",
    "Status_Quo_Bias",
    "Narrative_Fallacy",
    "Overconfidence",
    "Other",
}


# Severity mapping used consistently across scans
def _severity_from_score(score: Any) -> str:
    try:
        s = float(score)
    except Exception:
        return "L"
    if s >= 70.0:
        return "H"
    if s >= 40.0:
        return "M"
    return "L"


# -----------------------------------------------------------------------------
# Small internal helpers (DB + parsing)
# -----------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _today_iso() -> str:
    return _dt.date.today().isoformat()


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    s = (text or "").strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 12].rstrip() + "…(truncated)"


def _safe_str(v: Any, max_len: int = 600) -> str:
    if v is None:
        return ""
    s = re.sub(r"\s+", " ", str(v)).strip()
    return _truncate(s, max_len)


def _qi(name: str) -> str:
    """Quote SQL identifier defensively (SQLite)."""
    return '"' + (name or "").replace('"', '""') + '"'


def _fetchall_dict(conn, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    """Execute SQL and return rows as dicts (cursor.description keys)."""
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cols = [c[0] for c in cur.description] if cur.description else []
        out: List[Dict[str, Any]] = []
        for r in rows:
            if hasattr(r, "keys"):
                out.append({k: r[k] for k in r.keys()})  # sqlite3.Row
            elif cols:
                out.append({cols[i]: r[i] for i in range(len(cols))})
            else:
                out.append({})
        return out
    except Exception as e:
        _LOG.warning("DB query failed: %s | sql=%s", e, _truncate(sql, 240))
        return []


def _fetchone_dict(conn, sql: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
    rows = _fetchall_dict(conn, sql, params)
    return rows[0] if rows else None


def _list_tables(conn) -> List[str]:
    rows = _fetchall_dict(
        conn,
        "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%';",
        (),
    )
    return [str(r.get("name")) for r in rows if r.get("name")]


def _find_table(conn, candidates: Sequence[str]) -> Optional[str]:
    existing = _list_tables(conn)
    if not existing:
        return None
    by_lower = {t.lower(): t for t in existing}
    for c in candidates:
        hit = by_lower.get(str(c).lower())
        if hit:
            return hit
    # Conservative contains fallback
    for c in candidates:
        cl = str(c).lower()
        for tl, orig in by_lower.items():
            if cl in tl:
                return orig
    return None


def _list_columns(conn, table: str) -> List[str]:
    rows = _fetchall_dict(conn, f"PRAGMA table_info({_qi(table)});", ())
    return [str(r.get("name")) for r in rows if r.get("name")]


def _pick_column(conn, table: str, candidates: Sequence[str]) -> Optional[str]:
    cols = _list_columns(conn, table)
    if not cols:
        return None
    cols_l = {c.lower(): c for c in cols}
    for c in candidates:
        hit = cols_l.get(str(c).lower())
        if hit:
            return hit
    return None


def _get_ci(d: Dict[str, Any], key: str) -> Any:
    """Case-insensitive dict lookup."""
    kl = (key or "").lower()
    for k, v in d.items():
        if str(k).lower() == kl:
            return v
    return None


def _coerce_bias_list(v: Any) -> List[str]:
    """Accept list, JSON text list, or comma-separated text list."""
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    s = str(v).strip()
    if not s:
        return []
    # Try JSON array first.
    if s.startswith("[") and s.endswith("]"):
        try:
            arr = json.loads(s)
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            pass
    # Fallback: comma/semicolon separated.
    parts = re.split(r"[;,/]\s*", s)
    return [p.strip() for p in parts if p.strip()]


def _normalize_bias_name(raw: str) -> str:
    """
    Normalize a bias label into CT_Bias-like format where possible.
    We accept user-friendly variants like "confirmation bias" -> Confirmation_Bias.
    """
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (raw or "").strip())
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        return "Other"
    # Title-case tokens except known abbreviations; then join with underscores.
    toks = [t for t in s.split("_") if t]
    norm = "_".join([t[:1].upper() + t[1:].lower() if t else "" for t in toks])

    # Common aliasing
    alias = {
        "Confirmationbias": "Confirmation_Bias",
        "Confirmation_Bias": "Confirmation_Bias",
        "Availabilityheuristic": "Availability_Heuristic",
        "Availability_Heuristic": "Availability_Heuristic",
        "Survivorshipbias": "Survivorship_Bias",
        "Survivorship_Bias": "Survivorship_Bias",
        "Sunkcostfallacy": "Sunk_Cost_Fallacy",
        "Sunk_Cost_Fallacy": "Sunk_Cost_Fallacy",
        "Dunningkruger": "Dunning_Kruger",
        "Dunning_Kruger": "Dunning_Kruger",
        "Lossaversion": "Loss_Aversion",
        "Loss_Aversion": "Loss_Aversion",
        "Optimismbias": "Optimism_Bias",
        "Optimism_Bias": "Optimism_Bias",
        "Anchoring": "Anchoring",
        "Recencybias": "Recency_Bias",
        "Recency_Bias": "Recency_Bias",
        "Planningfallacy": "Planning_Fallacy",
        "Planning_Fallacy": "Planning_Fallacy",
        "Hindsightbias": "Hindsight_Bias",
        "Hindsight_Bias": "Hindsight_Bias",
        "Statusquobias": "Status_Quo_Bias",
        "Status_Quo_Bias": "Status_Quo_Bias",
        "Narrativefallacy": "Narrative_Fallacy",
        "Narrative_Fallacy": "Narrative_Fallacy",
        "Overconfidence": "Overconfidence",
        "Other": "Other",
    }
    norm = alias.get(norm.replace("_", ""), alias.get(norm, norm))
    return norm if norm in _CT_BIASES else "Other"


def _validate_cog_state(v: Any) -> str:
    s = _safe_str(v, 40)
    if s in _CT_COG_STATES:
        return s
    # Try normalized capitalization.
    s2 = s[:1].upper() + s[1:].lower() if s else ""
    return s2 if s2 in _CT_COG_STATES else "Neutral"


def _heuristic_bias_hints(text: str) -> List[str]:
    """
    Lightweight keyword heuristics to provide *hints* when the LLM is down
    or when we want to nudge the prompt. Keep conservative to avoid noise.
    """
    t = (text or "").lower()
    hits: List[str] = []

    def hit(pat: str) -> bool:
        return re.search(pat, t) is not None

    if hit(r"\b(always|never|guaranteed|certain|no doubt)\b"):
        hits.append("Overconfidence")
    if hit(r"\b(recently|lately|this week|yesterday|today)\b"):
        hits.append("Recency_Bias")
    if hit(r"\b(already (spent|invested)|too much invested|can't waste)\b"):
        hits.append("Sunk_Cost_Fallacy")
    if hit(r"\b(quick|easy|no problem|won't take long|by (tomorrow|next week))\b"):
        hits.append("Planning_Fallacy")
    if hit(r"\b(first number|starting point|anchor)\b"):
        hits.append("Anchoring")
    if hit(r"\b(stick with|keep doing|status quo|as usual)\b"):
        hits.append("Status_Quo_Bias")

    # Dedup + validate
    out = []
    for b in hits:
        nb = _normalize_bias_name(b)
        if nb not in out:
            out.append(nb)
    return out


def _bias_detector_hints(text: str) -> List[str]:
    """
    If src/calc/bias_detector.py exists, try to use it for additional hints.
    We don't assume an interface; we probe common function names.
    """
    if bias_detector is None:
        return []
    for fn_name in ("detect_biases", "scan_biases", "scan", "classify_biases", "find_biases"):
        fn = getattr(bias_detector, fn_name, None)
        if not callable(fn):
            continue
        try:
            res = fn(text)  # type: ignore[misc]
        except Exception:
            continue
        # Accept common shapes: list[str], dict with 'biases'/'biases_found'
        if isinstance(res, list):
            return [_normalize_bias_name(x) for x in res]
        if isinstance(res, dict):
            v = res.get("biases") or res.get("biases_found") or res.get("found")
            if isinstance(v, list):
                return [_normalize_bias_name(x) for x in v]
            if isinstance(v, str):
                return [_normalize_bias_name(x) for x in _coerce_bias_list(v)]
    return []


def _next_bias_id(conn) -> str:
    """
    Generate Bias_ID in PREFIX-YYYYMMDD-NNN format.
    Uses existing Bias_Audit_Log if available to increment NNN safely.
    """
    prefix = "BIAS"
    ymd = _dt.date.today().strftime("%Y%m%d")
    base = f"{prefix}-{ymd}-"
    table = _find_table(conn, ("Bias_Audit_Log", "bias_audit_log", "bias_audit", "bias"))
    if conn is None or not table:
        return f"{base}001"
    col = _pick_column(conn, table, ("Bias_ID", "bias_id", "id", "ID"))
    if not col:
        return f"{base}001"
    try:
        row = _fetchone_dict(
            conn,
            f"SELECT {_qi(col)} AS bias_id FROM {_qi(table)} WHERE {_qi(col)} LIKE ? "
            f"ORDER BY {_qi(col)} DESC LIMIT 1;",
            (base + "%",),
        )
        last = (row or {}).get("bias_id") if row else None
        if not last:
            return f"{base}001"
        m = re.search(rf"{re.escape(base)}(\d+)$", str(last))
        n = int(m.group(1)) if m else 0
        return f"{base}{n + 1:03d}"
    except Exception:
        return f"{base}001"


def _insert_bias_audit(conn, record: Dict[str, Any]) -> bool:
    """
    Insert into Bias_Audit_Log (best-effort, robust to schema drift).
    Returns True on insert+commit, False otherwise.
    """
    if conn is None:
        return False
    table = _find_table(conn, ("Bias_Audit_Log", "bias_audit_log", "bias_audit", "bias"))
    if not table:
        return False
    cols = _list_columns(conn, table)
    cols_l = {c.lower(): c for c in cols}

    # Build an insert payload using columns that actually exist.
    insert_cols: List[str] = []
    insert_vals: List[Any] = []
    for k, v in record.items():
        # case-insensitive column match
        col = cols_l.get(str(k).lower())
        if not col:
            continue
        insert_cols.append(col)
        insert_vals.append(v)
    if not insert_cols:
        return False
    ph = ", ".join(["?"] * len(insert_cols))
    sql = f"INSERT INTO {_qi(table)} ({', '.join(_qi(c) for c in insert_cols)}) VALUES ({ph});"
    try:
        cur = conn.cursor()
        cur.execute(sql, tuple(insert_vals))
        conn.commit()
        return True
    except Exception as e:
        _LOG.warning("Insert Bias_Audit_Log failed: %s", e)
        return False


def _persist_bias_audit_best_effort(conn, record: Dict[str, Any]) -> bool:
    """
    Preference order:
    1) Use src/db/bias_persist helper if present (duck-typed).
    2) Direct SQL insert into Bias_Audit_Log.
    """
    # 1) Persistence helper (best-effort).
    if bias_persist is not None:
        for fn_name in (
            "insert_bias_audit",
            "log_bias_audit",
            "create_bias_audit",
            "save_bias_audit",
            "upsert_bias_audit",
        ):
            fn = getattr(bias_persist, fn_name, None)
            if not callable(fn):
                continue
            try:
                # Common signatures: (conn, record) or (record) (module manages conn)
                try:
                    res = fn(conn, record)  # type: ignore[misc]
                except TypeError:
                    res = fn(record)  # type: ignore[misc]
                if isinstance(res, bool):
                    return res
                # If no explicit bool, treat as success if no exception.
                return True
            except Exception:
                continue

    # 2) Direct SQL.
    return _insert_bias_audit(conn, record)


def _fetch_decision_record(conn, decision_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a decision record by Decision_ID (best-effort, robust to schema drift).
    """
    decision_id = (decision_id or "").strip()
    if not decision_id or conn is None:
        return None
    table = _find_table(conn, ("Decision_Tree_Log", "decision_tree_log", "decisions", "decision_log", "decision"))
    if not table:
        return None
    id_col = _pick_column(conn, table, ("Decision_ID", "decision_id", "id", "ID"))
    if not id_col:
        return None
    return _fetchone_dict(conn, f"SELECT * FROM {_qi(table)} WHERE {_qi(id_col)} = ? LIMIT 1;", (decision_id,))


def _decision_to_text(dec: Dict[str, Any]) -> str:
    """
    Turn a Decision_Tree_Log record into a bounded reasoning-text block for bias scanning.

    We deliberately include the "chain": options -> selection -> rationale -> assumptions/evidence/risks.
    """
    if not dec:
        return ""

    def pick(*keys: str, max_len: int = 1200) -> str:
        for k in keys:
            v = _get_ci(dec, k)
            if v not in (None, ""):
                return _safe_str(v, max_len)
        return ""

    parts: List[str] = []
    parts.append("BEGIN_DECISION_RECORD")
    parts.append(f"Decision_ID: {pick('Decision_ID', 'decision_id', max_len=60)}")
    parts.append(f"Idea_ID: {pick('Idea_ID', 'idea_id', max_len=60)}")
    parts.append(f"Decision_Date: {pick('Decision_Date', 'decision_date', 'Date', max_len=40)}")
    parts.append(f"Decision_Type: {pick('Decision_Type', 'decision_type', max_len=60)}")
    parts.append(f"Stage_At_Decision: {pick('Stage_At_Decision', 'stage_at_decision', max_len=40)}")
    parts.append("")
    parts.append("Options_Considered:")
    parts.append(pick("Options_Considered", "options_considered", max_len=2000) or "(missing)")
    parts.append("")
    parts.append("Selected_Option:")
    parts.append(pick("Selected_Option", "selected_option", max_len=800) or "(missing)")
    parts.append("")
    parts.append("Rationale:")
    parts.append(pick("Rationale", "rationale", max_len=2500) or "(missing)")
    parts.append("")
    parts.append("Evidence:")
    parts.append(pick("Evidence", "evidence", max_len=2000) or "(missing)")
    parts.append("")
    parts.append("Assumptions:")
    parts.append(pick("Assumptions", "assumptions", max_len=2000) or "(missing)")
    parts.append("")
    parts.append("Risks:")
    parts.append(pick("Risks", "risks", max_len=2000) or "(missing)")
    parts.append("")
    parts.append("Opportunity_Cost_Notes:")
    parts.append(pick("Opportunity_Cost_Notes", "opportunity_cost_notes", max_len=2000) or "(missing)")
    parts.append("")
    parts.append("Regret_Minimization_Check:")
    parts.append(pick("Regret_Minimization_Check", "regret_minimization_check", max_len=1000) or "(missing)")
    parts.append("")
    parts.append("Counterfactual_Notes:")
    parts.append(pick("Counterfactual_Notes", "counterfactual_notes", max_len=1500) or "(missing)")
    parts.append("")
    parts.append("Biases_Present (if any):")
    parts.append(pick("Biases_Present", "biases_present", max_len=800) or "(missing)")
    parts.append("END_DECISION_RECORD")

    # Keep bounded for prompt safety.
    return _truncate("\n".join(parts), 9000)


# -----------------------------------------------------------------------------
# Debiasing prompt library (targeted questions)
# -----------------------------------------------------------------------------

_DEBIASING_QUESTIONS: Dict[str, str] = {
    "Confirmation_Bias": "What evidence would change my mind? What would prove this decision wrong?",
    "Availability_Heuristic": "Am I overweighting vivid/recent examples? What do base rates or broader data say?",
    "Survivorship_Bias": "Who failed and is missing from my sample? What does the full denominator look like?",
    "Sunk_Cost_Fallacy": "If I had invested nothing so far, would I still choose this today?",
    "Dunning_Kruger": "What might I be missing due to limited expertise? What would a domain expert challenge?",
    "Loss_Aversion": "Am I avoiding losses more than pursuing value? If upside/downside were flipped, what would I do?",
    "Optimism_Bias": "What are the most likely failure modes? What's the realistic base rate for success here?",
    "Anchoring": "What is my anchor? If I had no starting number/idea, what independent estimate would I make?",
    "Recency_Bias": "Am I over-weighting the latest information? What does the longer-term trend say?",
    "Planning_Fallacy": "How long have similar tasks taken historically? What is the 80th percentile timeline with buffers?",
    "Hindsight_Bias": "Am I rewriting the past as predictable? What did I *actually* believe at the time?",
    "Status_Quo_Bias": "If this were a new choice today, would I pick the same default? What is the cost of doing nothing?",
    "Narrative_Fallacy": "Is my story too neat? What disconfirming evidence or alternative causal model fits the facts?",
    "Overconfidence": "What's my confidence interval? What could surprise me? What quick test would falsify my belief?",
    "Other": "What assumption, if wrong, would most damage this decision? How can I test it quickly?",
}


def suggest_debiasing_prompt(bias_type: str) -> str:
    """
    Returns a targeted question to counter a specific bias type.

    Args:
        bias_type: Bias label (prefer CT_Bias values, but flexible).

    Returns:
        str: A short debiasing question/prompt.
    """
    b = _normalize_bias_name(bias_type)
    return _DEBIASING_QUESTIONS.get(b, _DEBIASING_QUESTIONS["Other"])


# -----------------------------------------------------------------------------
# Public API (required)
# -----------------------------------------------------------------------------


def scan_for_bias(text: str) -> Dict[str, Any]:
    """
    Send text to the local LLM with a bias detection prompt.

    Args:
        text: The reasoning chain / decision narrative to analyze.

    Returns:
        dict: {
          biases_found: list,
          severity: H/M/L,
          explanation: str,
          debiased_version: str
        }
        Note: Additional fields may be included (bias_score, recommendation, post_debiasing_score, etc.).
    """
    raw_text = (text or "").strip()
    if not raw_text:
        return {
            "biases_found": [],
            "severity": "L",
            "explanation": "No text provided for bias scanning.",
            "debiased_version": "",
        }

    # Hints (non-authoritative): allow calc heuristic + local keyword heuristic.
    hints = []
    try:
        hints.extend(_bias_detector_hints(raw_text))
    except Exception:
        pass
    try:
        hints.extend(_heuristic_bias_hints(raw_text))
    except Exception:
        pass

    # Deduplicate, keep only valid CT_Bias values
    hints_dedup: List[str] = []
    for h in hints:
        nh = _normalize_bias_name(h)
        if nh not in hints_dedup:
            hints_dedup.append(nh)

    allowed_biases = sorted(_CT_BIASES)

    schema_hint = json.dumps(
        {
            "biases_found": ["Confirmation_Bias"],
            "bias_score": 55,
            "severity": "M",
            "explanation": "Short explanation of where bias shows up and why it matters.",
            "debiased_version": "Rewritten reasoning with explicit assumptions, base rates, and falsification tests.",
            "recommendation": "1-3 concrete steps to reduce bias before committing.",
            "post_debiasing_score": 35,
            "debiasing_questions": ["What evidence would change my mind?"],
        },
        indent=2,
    )

    prompt = (
        "You are aeOS Bias Auditor.\n"
        "Task: identify cognitive biases in the DECISION_TEXT and produce a debiased rewrite.\n"
        "Allowed bias labels (CT_Bias):\n"
        f"{', '.join(allowed_biases)}\n\n"
        "Rules:\n"
        "- Output JSON only.\n"
        "- biases_found must be a list of CT_Bias values; if none, use an empty list.\n"
        "- bias_score: 0-100 (higher = more bias risk / more distorted reasoning).\n"
        "- severity must be one of: H/M/L.\n"
        "- explanation: 3-6 sentences, concrete.\n"
        "- debiased_version: rewrite the reasoning with (a) explicit assumptions, (b) base rates where possible, "
        "(c) a falsification test, and (d) a quick next step.\n"
        "- recommendation: if bias_score >= 40, give 1-3 actionable steps.\n"
        "- post_debiasing_score: expected score after following recommendation; must be <= bias_score.\n"
        "- debiasing_questions: list targeted questions (1 per bias found).\n\n"
        f"Non-authoritative hints (may be empty): {json.dumps(hints_dedup)}\n\n"
        "<DECISION_TEXT>\n"
        f"{_truncate(raw_text, 9000)}\n"
        "</DECISION_TEXT>\n"
    )

    out = infer_json(prompt=prompt, schema_hint=schema_hint)
    data = out.get("data") if isinstance(out, dict) else None

    # If model call or JSON parse fails, fall back to heuristics (never crash callers).
    if not isinstance(data, dict):
        fallback_biases = hints_dedup
        # Conservative fallback score: small bump per bias hint.
        bias_score = min(100, 15 * len(fallback_biases)) if fallback_biases else 10
        sev = _severity_from_score(bias_score)
        explanation = (
            "LLM bias scan unavailable; using conservative heuristic hints only. "
            "Treat this as a *signal to review*, not a definitive diagnosis."
        )
        questions = [suggest_debiasing_prompt(b) for b in fallback_biases] or [suggest_debiasing_prompt("Other")]
        return {
            "biases_found": fallback_biases,
            "severity": sev,
            "explanation": explanation,
            "debiased_version": raw_text,
            "bias_score": bias_score,
            "recommendation": "Answer the debiasing questions before committing.",
            "post_debiasing_score": max(0, bias_score - 10),
            "debiasing_questions": questions,
            "model": out.get("model") if isinstance(out, dict) else "",
            "tokens_used": out.get("tokens_used") if isinstance(out, dict) else 0,
            "latency_ms": out.get("latency_ms") if isinstance(out, dict) else 0,
            "success": False,
        }

    # Normalize + validate model output.
    biases_raw = data.get("biases_found")
    biases_list = _coerce_bias_list(biases_raw)
    biases_norm = []
    for b in biases_list:
        nb = _normalize_bias_name(b)
        if nb != "Other" and nb not in biases_norm:
            biases_norm.append(nb)

    bias_score = data.get("bias_score")
    sev = data.get("severity") or _severity_from_score(bias_score)
    sev = str(sev).strip().upper()
    if sev not in {"H", "M", "L"}:
        sev = _severity_from_score(bias_score)

    explanation = _safe_str(data.get("explanation") or "", 2000)
    debiased = _safe_str(data.get("debiased_version") or "", 8000)

    # Ensure debiasing questions exist (even if model omitted).
    dq = data.get("debiasing_questions")
    dq_list = _coerce_bias_list(dq)
    if not dq_list:
        dq_list = [suggest_debiasing_prompt(b) for b in biases_norm] if biases_norm else [suggest_debiasing_prompt("Other")]

    # Post score must not exceed pre score (Blueprint warns on this).
    post_score = data.get("post_debiasing_score")
    try:
        pre_f = float(bias_score) if bias_score is not None else None
        post_f = float(post_score) if post_score is not None else None
        if pre_f is not None and post_f is not None and post_f > pre_f:
            post_score = pre_f
    except Exception:
        pass

    # Return required fields + useful extras (safe for downstream).
    return {
        "biases_found": biases_norm,
        "severity": sev,
        "explanation": explanation,
        "debiased_version": debiased,
        "bias_score": bias_score,
        "recommendation": _safe_str(data.get("recommendation") or "", 1200),
        "post_debiasing_score": post_score,
        "debiasing_questions": dq_list,
        "model": out.get("model"),
        "tokens_used": out.get("tokens_used"),
        "latency_ms": out.get("latency_ms"),
        "success": bool(out.get("success")),
    }


def audit_decision(conn, decision_id: str) -> Dict[str, Any]:
    """
    Fetch a Decision_Tree_Log record, run bias scan, and log result to Bias_Audit_Log.

    Args:
        conn: sqlite3.Connection (duck-typed; may be None).
        decision_id: Decision_ID (PREFIX-YYYYMMDD-NNN per aeOS ID pattern).

    Returns:
        dict: {
          success: bool,
          decision_id: str,
          bias_id: str|None,
          scan: dict,
          persisted: bool,
          error: str|None
        }
    """
    decision_id = (decision_id or "").strip()
    if conn is None:
        return {
            "success": False,
            "decision_id": decision_id,
            "bias_id": None,
            "scan": {},
            "persisted": False,
            "error": "db_connection_unavailable",
        }
    if not decision_id:
        return {
            "success": False,
            "decision_id": "",
            "bias_id": None,
            "scan": {},
            "persisted": False,
            "error": "missing_decision_id",
        }

    dec = _fetch_decision_record(conn, decision_id)
    if not dec:
        return {
            "success": False,
            "decision_id": decision_id,
            "bias_id": None,
            "scan": {},
            "persisted": False,
            "error": "decision_not_found",
        }

    # Prefer cognitive state from the decision record if present; otherwise default.
    cog_state = _validate_cog_state(_get_ci(dec, "Cognitive_State_At_Decision") or _get_ci(dec, "Cognitive_State"))
    idea_id = _safe_str(_get_ci(dec, "Idea_ID") or "", 60)

    scan_text = _decision_to_text(dec)
    scan = scan_for_bias(scan_text)

    bias_id = _next_bias_id(conn)
    biases_found = scan.get("biases_found") or []
    bias_score = scan.get("bias_score")
    recommendation = scan.get("recommendation") or ""

    # Keep required + useful fields aligned with Bias_Audit_Log schema.
    # Note: Biases_Detected is stored as a JSON text list for unambiguous parsing later.
    pre_score = bias_score
    post_score = scan.get("post_debiasing_score")
    try:
        if pre_score is not None and post_score is None:
            # Conservative estimate if model omitted it.
            post_score = max(0, float(pre_score) - 15.0)
    except Exception:
        post_score = post_score

    # Recommendation is required when score >= 40 (Blueprint V33 warns otherwise).
    try:
        if recommendation and isinstance(recommendation, str):
            rec_s = recommendation.strip()
        else:
            rec_s = ""
        if rec_s == "":
            if _severity_from_score(pre_score) in {"M", "H"}:
                # Construct a minimal actionable recommendation from debiasing questions.
                qs = scan.get("debiasing_questions") or []
                qs_list = qs if isinstance(qs, list) else _coerce_bias_list(qs)
                take = qs_list[:2] if qs_list else [suggest_debiasing_prompt("Other")]
                rec_s = "Before committing: " + " | ".join([_safe_str(q, 220) for q in take])
        recommendation = rec_s
    except Exception:
        pass

    notes = (
        f"Decision_ID={decision_id}. "
        f"ScanAtUTC={_utc_now_iso()}. "
        f"Summary={_truncate(_safe_str(scan.get('explanation') or '', 900), 900)}"
    )

    record = {
        "Bias_ID": bias_id,
        "Idea_ID": idea_id or None,
        "Session_Date": _today_iso(),
        "Cognitive_State": cog_state,
        "Biases_Detected": json.dumps([_normalize_bias_name(b) for b in biases_found]),
        "Bias_Score": bias_score if bias_score is not None else 0,
        "Recommendation": recommendation or None,
        "Pre_Bias_Score": pre_score if pre_score is not None else 0,
        "Post_Debiasing_Score": post_score if post_score is not None else 0,
        "Notes": notes,
        "Last_Updated": _today_iso(),
    }

    persisted = _persist_bias_audit_best_effort(conn, record)
    return {
        "success": bool(persisted),
        "decision_id": decision_id,
        "bias_id": bias_id if persisted else None,
        "scan": scan,
        "persisted": bool(persisted),
        "error": None if persisted else "persist_failed",
    }


def get_bias_report(conn) -> str:
    """
    Plain-English summary of most frequent biases detected this month.

    Args:
        conn: sqlite3.Connection (duck-typed; may be None).

    Returns:
        str: Monthly summary (human-readable).
    """
    if conn is None:
        return "Bias report unavailable: DB connection is not available."

    table = _find_table(conn, ("Bias_Audit_Log", "bias_audit_log", "bias_audit", "bias"))
    if not table:
        return "Bias report unavailable: Bias_Audit_Log table not found."

    # Date window: current calendar month
    today = _dt.date.today()
    start = today.replace(day=1)
    if start.month == 12:
        end = _dt.date(start.year + 1, 1, 1)
    else:
        end = _dt.date(start.year, start.month + 1, 1)

    # Column picks (robust to casing)
    date_col = _pick_column(conn, table, ("Session_Date", "session_date", "date"))
    bias_col = _pick_column(conn, table, ("Biases_Detected", "biases_detected", "biases"))
    score_col = _pick_column(conn, table, ("Bias_Score", "bias_score"))
    pre_col = _pick_column(conn, table, ("Pre_Bias_Score", "pre_bias_score"))
    post_col = _pick_column(conn, table, ("Post_Debiasing_Score", "post_debiasing_score"))
    cog_col = _pick_column(conn, table, ("Cognitive_State", "cognitive_state"))

    if not date_col or not bias_col:
        return "Bias report unavailable: required columns missing (Session_Date and/or Biases_Detected)."

    # SQLite date() works well with ISO "YYYY-MM-DD" strings.
    sql = (
        f"SELECT {_qi(bias_col)} AS biases, "
        f"{_qi(score_col)} AS score, "
        f"{_qi(pre_col)} AS pre, "
        f"{_qi(post_col)} AS post, "
        f"{_qi(cog_col)} AS cog "
        f"FROM {_qi(table)} "
        f"WHERE date({_qi(date_col)}) >= date(?) AND date({_qi(date_col)}) < date(?);"
    )
    rows = _fetchall_dict(conn, sql, (start.isoformat(), end.isoformat()))
    if not rows:
        return f"No bias audits logged for {start.strftime('%Y-%m')} yet."

    bias_counts: Counter[str] = Counter()
    cog_counts: Counter[str] = Counter()
    scores: List[float] = []
    improvements: List[float] = []

    for r in rows:
        bl = _coerce_bias_list(r.get("biases"))
        for b in bl:
            nb = _normalize_bias_name(b)
            if nb != "Other":
                bias_counts[nb] += 1
            else:
                # Track "Other" only if nothing else exists in that record.
                bias_counts["Other"] += 1
        cog = _validate_cog_state(r.get("cog"))
        cog_counts[cog] += 1

        # Scores (best-effort)
        def to_float(x: Any) -> Optional[float]:
            try:
                return float(x)
            except Exception:
                return None

        sc = to_float(r.get("score")) or to_float(r.get("pre"))
        if sc is not None:
            scores.append(sc)
        pre = to_float(r.get("pre"))
        post = to_float(r.get("post"))
        if pre is not None and post is not None:
            improvements.append(max(0.0, pre - post))

    top_biases = bias_counts.most_common(5)
    total_audits = len(rows)
    avg_score = (sum(scores) / len(scores)) if scores else 0.0
    avg_improve = (sum(improvements) / len(improvements)) if improvements else 0.0
    month_label = start.strftime("%Y-%m")

    lines: List[str] = []
    lines.append(f"Bias Audit Report — {month_label}")
    lines.append(f"- Audits logged: {total_audits}")
    lines.append(f"- Average Bias_Score: {avg_score:.1f}/100")
    if improvements:
        lines.append(f"- Avg improvement after debiasing: {avg_improve:.1f} points")
    lines.append("")
    if top_biases:
        lines.append("Most frequent biases:")
        for b, n in top_biases:
            lines.append(f"- {b}: {n}")
    else:
        lines.append("Most frequent biases: (none detected)")
    if cog_counts:
        lines.append("")
        lines.append("Cognitive states during audits (counts):")
        for s, n in cog_counts.most_common():
            lines.append(f"- {s}: {n}")
    lines.append("")
    lines.append("Tip: For the top bias, run the targeted debiasing question before your next decision.")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Optional agent contract (router integration)
# -----------------------------------------------------------------------------

_DECISION_ID_RE = re.compile(r"\b[A-Z]{2,6}-\d{8}-\d{3}\b")


def handle(query: str, conn, kb_conn=None) -> Dict[str, Any]:
    """
    Router contract: def handle(query: str, conn, kb_conn) -> dict

    Behaviors (simple, deterministic):
    - If query asks for a monthly report -> get_bias_report()
    - If query includes a Decision_ID and keywords like 'audit' -> audit_decision()
    - If query asks for a debiasing prompt -> suggest_debiasing_prompt()
    - Else -> scan_for_bias(query)
    """
    q = (query or "").strip()
    if not q:
        return {"response": "", "success": False, "error": "empty_query"}

    ql = q.lower()

    # 1) Monthly report
    if "report" in ql and ("month" in ql or "monthly" in ql or "this month" in ql):
        rep = get_bias_report(conn)
        return {"response": rep, "success": True}

    # 2) Audit decision if a Decision_ID-like token exists
    m = _DECISION_ID_RE.search(q)
    if m and ("audit" in ql or "bias audit" in ql or "check bias" in ql):
        did = m.group(0)
        res = audit_decision(conn, did)
        if res.get("success"):
            scan = res.get("scan") or {}
            biases = scan.get("biases_found") or []
            sev = scan.get("severity") or "L"
            resp_lines = [
                f"Bias audit saved. Bias_ID={res.get('bias_id')} Decision_ID={did}",
                f"Severity: {sev}",
                f"Biases: {', '.join(biases) if biases else '(none detected)'}",
                "",
                "Debiased version:",
                _safe_str(scan.get("debiased_version") or "", 3000),
            ]
            return {"response": "\n".join(resp_lines), "success": True, "data": res}
        return {"response": "", "success": False, "error": res.get("error") or "audit_failed", "data": res}

    # 3) Suggest a debiasing prompt
    if "debias" in ql and ("prompt" in ql or "question" in ql):
        # Try to extract a bias type after keywords; else use full query as bias label.
        # Example: "debiasing prompt for confirmation bias"
        bt = q
        m2 = re.search(r"for\s+(.+)$", q, re.I)
        if m2:
            bt = m2.group(1).strip()
        prompt = suggest_debiasing_prompt(bt)
        return {"response": prompt, "success": True, "bias_type": _normalize_bias_name(bt)}

    # 4) Default: scan the query text itself (useful for quick checks)
    scan = scan_for_bias(q)
    biases = scan.get("biases_found") or []
    sev = scan.get("severity") or "L"
    resp_lines = [
        f"Severity: {sev}",
        f"Biases: {', '.join(biases) if biases else '(none detected)'}",
        "",
        "Explanation:",
        _safe_str(scan.get("explanation") or "", 1600),
        "",
        "Debiased version:",
        _safe_str(scan.get("debiased_version") or "", 3000),
    ]
    return {"response": "\n".join(resp_lines), "success": True, "data": scan}
