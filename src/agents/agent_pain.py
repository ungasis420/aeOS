"""
agent_pain.py
aeOS Phase 4 — Layer 2 (AI Agents)

AI agent that analyzes pain points using local LLM inference (Ollama).

Responsibilities:
- Analyze a specific pain record (root cause, severity, recommended actions).
- Validate / adjust numeric Pain_Score using the local LLM.
- Produce a daily portfolio-level pain summary for briefings.
- Detect recurring patterns/themes across pain points.

Stamp: S✅ T✅ L✅ A✅
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
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
    from src.ai.ai_infer import infer, infer_json  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    from ai.ai_infer import infer, infer_json  # type: ignore

try:
    from src.ai.ai_context import build_pain_context, build_portfolio_context  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    from ai.ai_context import build_pain_context, build_portfolio_context  # type: ignore


# ---- Optional: persistence helpers (best-effort) ------------------------------
try:
    from src.db import pain_persist  # type: ignore
except Exception:  # pragma: no cover
    pain_persist = None  # type: ignore


# ---- Calc: canonical pain score ----------------------------------------------
try:
    from src.calc.calc_pain import calculate_pain_score  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    try:
        from calc.calc_pain import calculate_pain_score  # type: ignore
    except Exception:  # pragma: no cover
        calculate_pain_score = None  # type: ignore


# -----------------------------------------------------------------------------
# Internal helpers (DB + parsing)
# -----------------------------------------------------------------------------

_STOPWORDS = {
    "the",
    "and",
    "that",
    "this",
    "with",
    "from",
    "into",
    "your",
    "youre",
    "have",
    "has",
    "been",
    "were",
    "they",
    "them",
    "then",
    "than",
    "also",
    "just",
    "like",
    "more",
    "most",
    "some",
    "need",
    "needs",
    "want",
    "wants",
    "when",
    "where",
    "what",
    "why",
    "how",
    "over",
    "under",
    "between",
    "within",
    "without",
    "very",
    "much",
    "many",
    "make",
    "makes",
    "made",
    "using",
    "use",
    "used",
    "work",
    "works",
    "working",
    "issue",
    "issues",
    "problem",
    "problems",
    "pain",
    "pains",
    "time",
    "data",
    "process",
    "system",
}


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    s = (text or "").strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 12].rstrip() + "…(truncated)"


def _safe_str(v: Any, max_len: int = 400) -> str:
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
                # sqlite3.Row
                out.append({k: r[k] for k in r.keys()})
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
        hit = by_lower.get(c.lower())
        if hit:
            return hit
    # Conservative contains fallback
    for c in candidates:
        cl = c.lower()
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
        hit = cols_l.get(c.lower())
        if hit:
            return hit
    return None


def _get_ci(d: Dict[str, Any], key: str) -> Any:
    """Case-insensitive lookup for a dict."""
    kl = (key or "").lower()
    for k, v in d.items():
        if str(k).lower() == kl:
            return v
    return None


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(int(v))
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y", "t"}:
        return True
    return False


_FREQ_TO_SLIDER: Dict[str, int] = {
    "daily": 10,
    "weekly": 7,
    "monthly": 4,
    "occasional": 2,
    "rare": 1,
}


def _frequency_to_num(freq_value: Any) -> Optional[int]:
    """Map CT_Freq value -> slider-style 1–10 numeric frequency."""
    if freq_value is None:
        return None
    if isinstance(freq_value, (int, float)) and not isinstance(freq_value, bool):
        i = int(freq_value)
        return i if 0 <= i <= 10 else None
    key = str(freq_value).strip().lower()
    if not key:
        return None
    return _FREQ_TO_SLIDER.get(key)


def _calculate_score_from_record(pain: Dict[str, Any]) -> Optional[float]:
    """
    Compute canonical Pain_Score from a pain record (best-effort).
    Uses src/calc/calc_pain.calculate_pain_score when available.
    Falls back to a conservative local implementation if calc module is missing.
    """
    if not isinstance(pain, dict) or not pain:
        return None
    sev = _get_ci(pain, "Severity")
    imp = _get_ci(pain, "Impact_Score")
    freq = _get_ci(pain, "Frequency")
    monet = _get_ci(pain, "Monetizability_Flag")
    freq_num = _frequency_to_num(freq)
    monet_b = _as_bool(monet)
    try:
        sev_f = float(sev) if sev is not None else None
        imp_f = float(imp) if imp is not None else None
    except Exception:
        sev_f, imp_f = None, None
    if sev_f is None or imp_f is None or freq_num is None:
        return None
    if callable(calculate_pain_score):
        try:
            return float(calculate_pain_score(sev_f, float(freq_num), monet_b, imp_f))
        except Exception as e:
            _LOG.debug("calculate_pain_score failed: %s", e)
    # Fallback (mirrors Blueprint formula; expects 1–10 sliders).
    sev_u = max(0.0, min(10.0, sev_f)) / 10.0
    freq_u = max(0.0, min(10.0, float(freq_num))) / 10.0
    imp_u = max(0.0, min(10.0, imp_f)) / 10.0
    monet_u = 1.0 if monet_b else 0.0
    score = (sev_u * 40.0) + (freq_u * 30.0) + (monet_u * 20.0) + (imp_u * 10.0)
    return float(max(0.0, min(100.0, score)))


def _fetch_pain_record(conn, pain_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a pain record by ID.

    Preference order:
    1) Use pain_persist helper if present (duck-typed).
    2) Direct SQL against Pain_Point_Register (robust to casing and schema drift).
    """
    pain_id = (pain_id or "").strip()
    if not pain_id or conn is None:
        return None

    # 1) Persistence helper (best-effort).
    if pain_persist is not None:
        for fn_name in (
            "get_pain",
            "read_pain",
            "fetch_pain",
            "get_pain_by_id",
            "get_pain_record",
            "load_pain",
        ):
            fn = getattr(pain_persist, fn_name, None)
            if callable(fn):
                try:
                    # Common signature: (conn, pain_id)
                    res = fn(conn, pain_id)  # type: ignore[misc]
                except TypeError:
                    try:
                        # Alternate signature: (pain_id) and module opens its own conn
                        res = fn(pain_id)  # type: ignore[misc]
                    except Exception:
                        continue
                except Exception:
                    continue
                if isinstance(res, dict):
                    return res
                # Some persist modules return sqlite3.Row-like objects.
                if hasattr(res, "keys"):
                    try:
                        return {k: res[k] for k in res.keys()}  # type: ignore[index]
                    except Exception:
                        pass

    # 2) Direct SQL.
    table = _find_table(conn, ("Pain_Point_Register", "pain_point_register", "pain_points", "pains", "pain"))
    if not table:
        return None
    id_col = _pick_column(conn, table, ("Pain_ID", "pain_id", "id", "ID"))
    if not id_col:
        return None
    return _fetchone_dict(conn, f"SELECT * FROM {_qi(table)} WHERE {_qi(id_col)} = ? LIMIT 1;", (pain_id,))


def _fetch_pain_rows(conn, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Fetch pain rows (best-effort), newest first when an updated/created column exists.

    Note: schema uses Last_Updated and Date_Identified; we prefer Last_Updated if present.
    """
    if conn is None:
        return []
    table = _find_table(conn, ("Pain_Point_Register", "pain_point_register", "pain_points", "pains", "pain"))
    if not table:
        return []
    cols = _list_columns(conn, table)
    cols_l = {c.lower(): c for c in cols}
    order_col = cols_l.get("last_updated") or cols_l.get("date_identified")
    sql = f"SELECT * FROM {_qi(table)}"
    if order_col:
        sql += f" ORDER BY {_qi(order_col)} DESC"
    sql += f" LIMIT {int(max(1, limit))};"
    return _fetchall_dict(conn, sql, ())


def _summarize_pain_rows_for_prompt(pains: List[Dict[str, Any]], max_items: int = 20) -> str:
    """Compact summary of pain rows for prompt use (bounded)."""
    lines: List[str] = []
    for p in pains[: max(0, int(max_items))]:
        pid = _safe_str(_get_ci(p, "Pain_ID") or _get_ci(p, "pain_id"), 40)
        name = _safe_str(_get_ci(p, "Pain_Name") or _get_ci(p, "name") or _get_ci(p, "title"), 70)
        status = _safe_str(_get_ci(p, "Status") or "", 24)
        score = _get_ci(p, "Pain_Score")
        score_s = _safe_str(score, 8) if score is not None else ""
        desc = _safe_str(_get_ci(p, "Description") or "", 180)
        lines.append(f"- {pid} | {name} | score={score_s or 'NA'} | status={status or 'NA'} | {desc}")
    return "\n".join(lines) if lines else "(none)"


def _clamp01(x: Any, default: float = 0.25) -> float:
    try:
        v = float(x)
    except Exception:
        return float(default)
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _coerce_actions(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [_safe_str(x, 240) for x in v if _safe_str(x, 240)]
    if isinstance(v, str):
        # Split bullets/lines lightly.
        parts = [p.strip("-• \t") for p in v.splitlines()]
        return [p for p in parts if p]
    return [_safe_str(v, 240)] if _safe_str(v, 240) else []


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def analyze_pain(conn, pain_id: str) -> Dict[str, Any]:
    """
    Analyze a pain point using DB context + local LLM.

    Args:
        conn: sqlite3.Connection (from src/db/db_connect.get_connection()).
        pain_id: Pain_ID (PAIN-YYYYMMDD-NNN).

    Returns:
        dict: {
            "root_cause": str,
            "severity_assessment": dict,
            "recommended_actions": list[str],
            "confidence": float  # 0..1
        }
    """
    pain = _fetch_pain_record(conn, pain_id)
    if not pain:
        return {
            "root_cause": "",
            "severity_assessment": {"label": "Unknown", "score_estimate": None, "rationale": "Pain record not found."},
            "recommended_actions": ["Verify the Pain_ID and ensure the record exists in Pain_Point_Register."],
            "confidence": 0.1,
        }

    calc_score = _calculate_score_from_record(pain)
    stored_score = _get_ci(pain, "Pain_Score")

    # Build context pack (DB-level; includes linked solutions/predictions).
    try:
        ctx = build_pain_context(conn, pain_id)
    except Exception as e:  # pragma: no cover
        _LOG.warning("build_pain_context failed: %s", e)
        ctx = "PAIN_CONTEXT: (failed to build)"

    prompt = (
        "You are aeOS Pain Analyst.\n"
        "Goal: produce a structured diagnosis of a single pain point.\n"
        "Rules:\n"
        "- Use ONLY what is in CONTEXT + the numeric scores provided.\n"
        "- If info is missing, say so explicitly in the rationale.\n"
        "- Recommended actions must be concrete, short, and ordered (1..N).\n"
        "- Keep actions aligned with aeOS phases: Phase_0 refine evidence, Phase_1 solution bridge, "
        "Phase_2 monetize only if justified.\n\n"
        "<CONTEXT>\n"
        f"{ctx}\n"
        "</CONTEXT>\n\n"
        "Known numeric signals:\n"
        f"- calc_pain_score: {calc_score if calc_score is not None else 'NA'}\n"
        f"- stored_pain_score: {stored_score if stored_score is not None else 'NA'}\n\n"
        "Return JSON now."
    )

    schema_hint = (
        "{\n"
        '  "root_cause": "string (best guess from context; may be empty if unknown)",\n'
        '  "severity_assessment": {\n'
        '    "label": "Low|Medium|High|Critical|Unknown",\n'
        '    "score_estimate": "number 0-100 or null",\n'
        '    "rationale": "string (1-3 sentences)"\n'
        "  },\n"
        '  "recommended_actions": ["string", "string"],\n'
        '  "confidence": "number 0-1"\n'
        "}"
    )

    out = infer_json(prompt=prompt, schema_hint=schema_hint)

    if out.get("success") and isinstance(out.get("data"), dict):
        data = out["data"]
        # Normalize and harden output.
        root = _safe_str(data.get("root_cause") or _get_ci(pain, "Root_Cause"), 600)
        sev = data.get("severity_assessment") if isinstance(data.get("severity_assessment"), dict) else {}
        label = _safe_str(sev.get("label") or "Unknown", 24) if isinstance(sev, dict) else "Unknown"
        score_est = sev.get("score_estimate") if isinstance(sev, dict) else None
        try:
            score_est_f = float(score_est) if score_est is not None else None
            if score_est_f is not None:
                score_est_f = max(0.0, min(100.0, score_est_f))
        except Exception:
            score_est_f = None
        rationale = _safe_str(sev.get("rationale") if isinstance(sev, dict) else "", 600)
        actions = _coerce_actions(data.get("recommended_actions"))
        conf = _clamp01(data.get("confidence"), default=0.5)

        # If model omitted actions, provide a minimal sane default.
        if not actions:
            actions = [
                "Confirm frequency/severity/impact inputs and add one concrete evidence line.",
                "If Pain_Score >= 60: draft 1-2 Solution_Design options (Phase_1).",
            ]
            if _as_bool(_get_ci(pain, "Monetizability_Flag")):
                actions.append("If solution has a monetization path: spawn a MoneyScan record (Phase_2).")

        return {
            "root_cause": root,
            "severity_assessment": {"label": label, "score_estimate": score_est_f, "rationale": rationale},
            "recommended_actions": actions,
            "confidence": conf,
        }

    # Fallback (no AI / parse failed).
    label = "Unknown"
    if isinstance(calc_score, (int, float)):
        if calc_score >= 80:
            label = "Critical"
        elif calc_score >= 60:
            label = "High"
        elif calc_score >= 40:
            label = "Medium"
        else:
            label = "Low"

    actions = [
        "Add/refresh evidence and ensure the pain definition is specific (who/what/when/where).",
        "If Pain_Score >= 60: proceed to Solution Bridge (create Solution_Design drafts).",
    ]
    if _as_bool(_get_ci(pain, "Monetizability_Flag")):
        actions.append("If the solution can be monetized credibly: spawn MoneyScan (Phase_2).")

    return {
        "root_cause": _safe_str(_get_ci(pain, "Root_Cause"), 600),
        "severity_assessment": {
            "label": label,
            "score_estimate": float(calc_score) if isinstance(calc_score, (int, float)) else None,
            "rationale": "AI analysis unavailable; using baseline score heuristics.",
        },
        "recommended_actions": actions,
        "confidence": 0.25,
    }


def score_pain_with_ai(conn, pain_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate/adjust a numeric pain score using the local LLM.

    This is intended to sanity-check the canonical calc score against the
    narrative context (evidence, population, root cause). The AI should not
    invent new evidence; it can only flag inconsistencies or propose a small
    correction.

    Args:
        conn: sqlite3.Connection (optional; used only to build portfolio context).
        pain_dict: pain record dict (ideally from Pain_Point_Register).

    Returns:
        dict: {
            "ai_score": float | None,
            "reasoning": str,
            "agreement_with_calc": bool
        }
    """
    if not isinstance(pain_dict, dict) or not pain_dict:
        return {"ai_score": None, "reasoning": "No pain data provided.", "agreement_with_calc": False}

    calc_score = _calculate_score_from_record(pain_dict)
    if calc_score is None:
        return {"ai_score": None, "reasoning": "Insufficient fields to compute calc score.", "agreement_with_calc": False}

    # Context: include portfolio context only as a mild calibration signal (optional).
    port_ctx = ""
    try:
        port_ctx = build_portfolio_context(conn) if conn is not None else ""
    except Exception:
        port_ctx = ""

    compact_pain = {
        "Pain_ID": _get_ci(pain_dict, "Pain_ID"),
        "Pain_Name": _get_ci(pain_dict, "Pain_Name"),
        "Description": _truncate(_safe_str(_get_ci(pain_dict, "Description"), 800), 800),
        "Root_Cause": _truncate(_safe_str(_get_ci(pain_dict, "Root_Cause"), 400), 400),
        "Affected_Population": _safe_str(_get_ci(pain_dict, "Affected_Population"), 240),
        "Frequency": _get_ci(pain_dict, "Frequency"),
        "Severity": _get_ci(pain_dict, "Severity"),
        "Impact_Score": _get_ci(pain_dict, "Impact_Score"),
        "Monetizability_Flag": _get_ci(pain_dict, "Monetizability_Flag"),
        "Evidence": _truncate(_safe_str(_get_ci(pain_dict, "Evidence"), 800), 800),
        "Stored_Pain_Score": _get_ci(pain_dict, "Pain_Score"),
    }

    prompt = (
        "You are aeOS Pain Scoring Validator.\n"
        "Task: validate the numeric Pain_Score computed by calc_pain.\n"
        "Rules:\n"
        "- Do NOT invent new evidence.\n"
        "- Only adjust the score if there is a clear mismatch between narrative severity/frequency/impact and the inputs.\n"
        "- If you adjust, keep it conservative (usually within ±10 points unless evidence is extremely strong/weak).\n"
        "- Return JSON only.\n\n"
        "<PORTFOLIO_CONTEXT>\n"
        f"{_truncate(port_ctx, 1500)}\n"
        "</PORTFOLIO_CONTEXT>\n\n"
        "<PAIN_RECORD>\n"
        f"{json.dumps(compact_pain, ensure_ascii=False)}\n"
        "</PAIN_RECORD>\n\n"
        f"calc_pain_score={calc_score:.2f}\n"
    )

    schema_hint = (
        "{\n"
        '  "ai_score": "number 0-100",\n'
        '  "reasoning": "string (2-5 sentences)",\n'
        '  "agreement_with_calc": "boolean"\n'
        "}"
    )

    out = infer_json(prompt=prompt, schema_hint=schema_hint)
    if out.get("success") and isinstance(out.get("data"), dict):
        data = out["data"]
        try:
            ai_score = float(data.get("ai_score"))
            ai_score = max(0.0, min(100.0, ai_score))
        except Exception:
            ai_score = float(calc_score)
        reasoning = _safe_str(data.get("reasoning"), 1200) or "No reasoning provided."
        agreement = bool(data.get("agreement_with_calc"))
        return {"ai_score": ai_score, "reasoning": reasoning, "agreement_with_calc": agreement}

    # Fallback: no AI -> default to calc score.
    return {
        "ai_score": float(calc_score),
        "reasoning": "AI scoring validator unavailable or returned invalid JSON; using calc_pain score.",
        "agreement_with_calc": True,
    }


def generate_pain_summary(conn) -> str:
    """
    Produce a portfolio-level pain summary for a daily briefing.

    Strategy:
    - Pull top pains by Pain_Score (stored or computed).
    - Include status distribution.
    - Ask local LLM to produce a concise, actionable briefing.
    - If LLM unavailable, return a deterministic fallback summary.

    Returns:
        str: Briefing text.
    """
    pains = _fetch_pain_rows(conn, limit=50)
    if not pains:
        return "Pain Summary: (no pain records found)"

    # Ensure we have numeric scores for ranking (prefer stored, else computed).
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for p in pains:
        s = _get_ci(p, "Pain_Score")
        score = None
        try:
            score = float(s) if s is not None else None
        except Exception:
            score = None
        if score is None:
            score = _calculate_score_from_record(p)
        if score is None:
            score = 0.0
        scored.append((float(score), p))
    scored.sort(key=lambda t: t[0], reverse=True)

    top = [p for _, p in scored[:10]]

    status_counts: Counter[str] = Counter()
    for _, p in scored:
        status = _safe_str(_get_ci(p, "Status"), 40) or "Unknown"
        status_counts[status] += 1

    avg = sum(s for s, _ in scored) / max(1, len(scored))

    # Optional pattern hints (cheap, local).
    patterns = detect_pain_patterns(conn)
    pattern_lines: List[str] = []
    for t in patterns[:3]:
        if isinstance(t, dict):
            theme = _safe_str(t.get("theme"), 60)
            count = t.get("count")
            if theme:
                pattern_lines.append(f"- {theme} ({count})" if count is not None else f"- {theme}")

    port_ctx = ""
    try:
        port_ctx = build_portfolio_context(conn)
    except Exception:
        port_ctx = ""

    prompt = (
        "You are aeOS Daily Briefing Writer.\n"
        "Write a concise pain-focused briefing for today.\n"
        "Constraints:\n"
        "- Keep under ~200 words.\n"
        "- Highlight the top 3 pains and what to do next.\n"
        "- Mention any obvious recurring themes.\n"
        "- Use bullet points sparingly.\n\n"
        "<PORTFOLIO_CONTEXT>\n"
        f"{_truncate(port_ctx, 2000)}\n"
        "</PORTFOLIO_CONTEXT>\n\n"
        "<PAIN_STATS>\n"
        f"total_pains={len(scored)}\n"
        f"avg_pain_score={avg:.1f}\n"
        f"status_counts={dict(status_counts)}\n"
        "</PAIN_STATS>\n\n"
        "<TOP_PAINS>\n"
        f"{_summarize_pain_rows_for_prompt(top, max_items=10)}\n"
        "</TOP_PAINS>\n\n"
        "<PATTERN_HINTS>\n"
        f"{chr(10).join(pattern_lines) if pattern_lines else '(none)'}\n"
        "</PATTERN_HINTS>\n"
    )

    out = infer(prompt=prompt, system_prompt=None)
    if out.get("success") and isinstance(out.get("response"), str) and out.get("response").strip():
        return out["response"].strip()

    # Fallback (deterministic).
    top3 = top[:3]
    lines = [
        f"Pain Summary: {len(scored)} pain(s) tracked | avg score ~{avg:.1f}",
        "Top pains:",
    ]
    for p in top3:
        pid = _safe_str(_get_ci(p, "Pain_ID"), 40)
        name = _safe_str(_get_ci(p, "Pain_Name"), 70)
        score = _get_ci(p, "Pain_Score")
        score_s = _safe_str(score, 8) if score is not None else "NA"
        lines.append(f"- {pid}: {name} (score={score_s})")
    if pattern_lines:
        lines.append("Themes:")
        lines.extend(pattern_lines[:3])
    return "\n".join(lines)


def detect_pain_patterns(conn) -> List[Dict[str, Any]]:
    """
    Find recurring themes across pain points.

    Returns:
        list[dict]: Each item is a theme cluster like:
          {"theme": str, "count": int, "keywords": [..], "sample_pain_ids": [..], "sample_pain_names": [..]}

    Notes:
        - Uses a cheap keyword-frequency baseline.
        - If local LLM is available, attempts to refine into human-friendly themes.
    """
    pains = _fetch_pain_rows(conn, limit=120)
    if not pains:
        return []

    # Build a token index: keyword -> list of pain indices.
    token_to_idxs: Dict[str, List[int]] = defaultdict(list)
    pain_ids: List[str] = []
    pain_names: List[str] = []
    joined_texts: List[str] = []

    for i, p in enumerate(pains):
        pid = _safe_str(_get_ci(p, "Pain_ID"), 40)
        name = _safe_str(_get_ci(p, "Pain_Name"), 80)
        desc = _safe_str(_get_ci(p, "Description"), 800)
        rc = _safe_str(_get_ci(p, "Root_Cause"), 400)
        pain_ids.append(pid)
        pain_names.append(name)
        text = f"{name} {desc} {rc}".lower()
        joined_texts.append(text)
        toks = re.findall(r"[a-z0-9]{4,}", text)
        for t in toks:
            if t in _STOPWORDS:
                continue
            token_to_idxs[t].append(i)

    # Candidate themes: tokens that appear in >= 2 pains.
    candidates = [(tok, len(set(idxs))) for tok, idxs in token_to_idxs.items()]
    candidates.sort(key=lambda x: x[1], reverse=True)

    baseline: List[Dict[str, Any]] = []
    for tok, cnt in candidates[:30]:
        if cnt < 2:
            break
        idxs = list(dict.fromkeys(token_to_idxs[tok]))  # stable unique order
        sample = idxs[:5]
        baseline.append(
            {
                "theme": tok,
                "count": cnt,
                "keywords": [tok],
                "sample_pain_ids": [pain_ids[j] for j in sample if pain_ids[j]],
                "sample_pain_names": [pain_names[j] for j in sample if pain_names[j]],
            }
        )

    # If baseline is tiny, just return it.
    if len(baseline) < 3:
        return baseline

    # LLM refinement (best-effort): merge tokens into human themes.
    # Keep prompt size bounded.
    compact = []
    for p in pains[:25]:
        compact.append(
            {
                "Pain_ID": _get_ci(p, "Pain_ID"),
                "Pain_Name": _get_ci(p, "Pain_Name"),
                "Description": _truncate(_safe_str(_get_ci(p, "Description"), 400), 400),
            }
        )

    prompt = (
        "You are aeOS Pattern Detector.\n"
        "Given a list of pain points, extract 3-8 recurring themes.\n"
        "Rules:\n"
        "- Themes should be human-readable (not single tokens).\n"
        "- Provide counts and example Pain_IDs.\n"
        "- Do not invent pains that are not present.\n"
        "- Return JSON only.\n\n"
        "<PAINS>\n"
        f"{json.dumps(compact, ensure_ascii=False)}\n"
        "</PAINS>\n\n"
        "<BASELINE_KEYWORDS>\n"
        f"{json.dumps(baseline[:10], ensure_ascii=False)}\n"
        "</BASELINE_KEYWORDS>\n"
    )

    schema_hint = (
        "[\n"
        "  {\n"
        '    "theme": "string",\n'
        '    "count": "integer",\n'
        '    "keywords": ["string"],\n'
        '    "example_pain_ids": ["string"]\n'
        "  }\n"
        "]"
    )

    out = infer_json(prompt=prompt, schema_hint=schema_hint)
    if out.get("success") and isinstance(out.get("data"), list):
        cleaned: List[Dict[str, Any]] = []
        for item in out["data"]:
            if not isinstance(item, dict):
                continue
            theme = _safe_str(item.get("theme"), 80)
            if not theme:
                continue
            try:
                count = int(item.get("count"))
            except Exception:
                count = 0
            kws = item.get("keywords") if isinstance(item.get("keywords"), list) else []
            kws_s = [_safe_str(k, 24) for k in kws if _safe_str(k, 24)]
            ex_ids = item.get("example_pain_ids") if isinstance(item.get("example_pain_ids"), list) else []
            ex_ids_s = [_safe_str(x, 40) for x in ex_ids if _safe_str(x, 40)]
            cleaned.append(
                {
                    "theme": theme,
                    "count": max(0, count),
                    "keywords": kws_s[:8],
                    "sample_pain_ids": ex_ids_s[:8],
                }
            )
        if cleaned:
            cleaned.sort(key=lambda d: int(d.get("count") or 0), reverse=True)
            return cleaned

    return baseline
