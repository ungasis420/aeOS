"""
agent_solution.py
aeOS Phase 4 — Layer 2 (AI Agents)

AI agent that generates solution candidates for pain points.

Responsibilities:
- Generate solution candidates for a pain point using local LLM inference (Ollama).
- Re-rank existing solutions for a pain point using LLM reasoning beyond numeric scores.
- Produce one-paragraph solution summaries for CLI display.
- Suggest quick wins (high impact + low effort) across the portfolio.

Stamp: S✅ T✅ L✅ A✅
"""

from __future__ import annotations

import json
import re
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
    from src.ai.ai_context import build_pain_context  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    from ai.ai_context import build_pain_context  # type: ignore


# ---- Optional: persistence helpers (best-effort) -----------------------------
# NOTE: agent_solution does NOT require persistence to operate. If the persistence
# module exists, callers may choose to write returned candidates separately.

try:
    from src.db import pain_persist  # type: ignore
except Exception:  # pragma: no cover
    pain_persist = None  # type: ignore

try:
    from src.db import solution_persist  # type: ignore
except Exception:  # pragma: no cover
    solution_persist = None  # type: ignore


# ---------------------------------------------------------------------------
# Internal helpers (DB + parsing)
# ---------------------------------------------------------------------------


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
    # Conservative contains fallback for schema drift
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


def _to_float(v: Any, default: Optional[float] = None) -> Optional[float]:
    if v is None:
        return default
    try:
        return float(v)
    except Exception:
        return default


def _clamp(v: Any, lo: float, hi: float, default: float) -> float:
    x = _to_float(v, default=default)
    if x is None:
        return float(default)
    if x < lo:
        return float(lo)
    if x > hi:
        return float(hi)
    return float(x)


def _fetch_pain_record(conn, pain_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a pain record by ID (best-effort).

    Preference:
    1) Try pain_persist helper if present (duck-typed).
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
            if not callable(fn):
                continue
            try:
                res = fn(conn, pain_id)  # type: ignore[misc]
            except TypeError:
                try:
                    res = fn(pain_id)  # type: ignore[misc]
                except Exception:
                    continue
            except Exception:
                continue
            if isinstance(res, dict):
                return res
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


# ---- Solution table helpers --------------------------------------------------

_SOL_COL_CACHE: Dict[str, Dict[str, Optional[str]]] = {}


def _solution_table(conn) -> Optional[str]:
    return _find_table(conn, ("Solution_Design", "solution_design", "solutions", "solution"))


def _get_solution_cols(conn, table: str) -> Dict[str, Optional[str]]:
    """
    Cache solution column selections per table to avoid repeated PRAGMA calls
    when iterating over many solution rows.
    """
    cached = _SOL_COL_CACHE.get(table)
    if cached is not None:
        return cached
    cols: Dict[str, Optional[str]] = {
        "solution_id": _pick_column(conn, table, ("Solution_ID", "solution_id", "id", "ID")),
        "pain_id": _pick_column(conn, table, ("Pain_ID", "pain_id", "linked_pain_id", "source_pain_id", "painId")),
        "title": _pick_column(conn, table, ("Solution_Name", "solution_name", "title", "name", "Solution_Title")),
        "description": _pick_column(
            conn,
            table,
            ("Description", "description", "Summary", "summary", "Solution_Description", "Solution_Summary", "notes"),
        ),
        "effort": _pick_column(
            conn,
            table,
            (
                "Effort_Score",
                "effort_score",
                "Effort",
                "effort",
                "Complexity_Score",
                "complexity_score",
                "Complexity",
                "complexity",
                "Implementation_Effort",
                "implementation_effort",
            ),
        ),
        "impact": _pick_column(
            conn,
            table,
            (
                "Impact_Score",
                "impact_score",
                "Impact",
                "impact",
                "Expected_Impact",
                "expected_impact",
                "Value_Score",
                "value_score",
                "Benefit_Score",
                "benefit_score",
            ),
        ),
        "status": _pick_column(conn, table, ("Status", "status", "Exec_Status", "exec_status")),
        "order": _pick_column(conn, table, ("Last_Updated", "updated_at", "updatedAt", "created_at", "createdAt", "timestamp")),
    }
    _SOL_COL_CACHE[table] = cols
    return cols


def _fetch_solutions_for_pain(conn, pain_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch solutions linked to a pain_id (best-effort)."""
    if conn is None:
        return []
    table = _solution_table(conn)
    if not table:
        return []
    cols = _get_solution_cols(conn, table)
    pain_col = cols.get("pain_id")
    if not pain_col:
        return []
    order_col = cols.get("order")
    sql = f"SELECT * FROM {_qi(table)} WHERE {_qi(pain_col)} = ?"
    if order_col:
        sql += f" ORDER BY {_qi(order_col)} DESC"
    sql += f" LIMIT {int(max(1, limit))};"
    return _fetchall_dict(conn, sql, (pain_id,))


def _fetch_solution_record(conn, solution_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a solution record by ID (best-effort)."""
    solution_id = (solution_id or "").strip()
    if not solution_id or conn is None:
        return None

    # 1) Persistence helper (best-effort).
    if solution_persist is not None:
        for fn_name in (
            "get_solution",
            "read_solution",
            "fetch_solution",
            "get_solution_by_id",
            "get_solution_record",
            "load_solution",
        ):
            fn = getattr(solution_persist, fn_name, None)
            if not callable(fn):
                continue
            try:
                res = fn(conn, solution_id)  # type: ignore[misc]
            except TypeError:
                try:
                    res = fn(solution_id)  # type: ignore[misc]
                except Exception:
                    continue
            except Exception:
                continue
            if isinstance(res, dict):
                return res
            if hasattr(res, "keys"):
                try:
                    return {k: res[k] for k in res.keys()}  # type: ignore[index]
                except Exception:
                    pass

    # 2) Direct SQL.
    table = _solution_table(conn)
    if not table:
        return None
    cols = _get_solution_cols(conn, table)
    id_col = cols.get("solution_id") or _pick_column(conn, table, ("Solution_ID", "solution_id", "id", "ID"))
    if not id_col:
        return None
    return _fetchone_dict(conn, f"SELECT * FROM {_qi(table)} WHERE {_qi(id_col)} = ? LIMIT 1;", (solution_id,))


def _fetch_solution_rows(conn, limit: int = 250) -> List[Dict[str, Any]]:
    """Fetch solution rows across the portfolio (best-effort)."""
    if conn is None:
        return []
    table = _solution_table(conn)
    if not table:
        return []
    cols = _get_solution_cols(conn, table)
    order_col = cols.get("order")
    sql = f"SELECT * FROM {_qi(table)}"
    if order_col:
        sql += f" ORDER BY {_qi(order_col)} DESC"
    sql += f" LIMIT {int(max(1, limit))};"
    return _fetchall_dict(conn, sql, ())


def _extract_solution_fields(conn, table: str, row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a Solution_Design row to a compact dict used by this agent.

    Returns keys:
      - solution_id
      - pain_id
      - title
      - description
      - effort_score (1..10, lower is easier)
      - impact_score (1..10, higher is better)
      - status (optional)
    """
    cols = _get_solution_cols(conn, table)
    id_col = cols.get("solution_id") or "Solution_ID"
    pain_col = cols.get("pain_id") or "Pain_ID"
    title_col = cols.get("title") or "title"
    desc_col = cols.get("description") or "description"
    effort_col = cols.get("effort")
    impact_col = cols.get("impact")
    status_col = cols.get("status")
    return {
        "solution_id": _safe_str(row.get(id_col) or _get_ci(row, id_col), 40),
        "pain_id": _safe_str(row.get(pain_col) or _get_ci(row, pain_col), 40),
        "title": _safe_str(row.get(title_col) or _get_ci(row, title_col), 120),
        "description": _safe_str(row.get(desc_col) or _get_ci(row, desc_col), 1200),
        "effort_score": _clamp(row.get(effort_col) if effort_col else None, 1.0, 10.0, default=5.0)
        if effort_col
        else None,
        "impact_score": _clamp(row.get(impact_col) if impact_col else None, 1.0, 10.0, default=5.0)
        if impact_col
        else None,
        "status": _safe_str(row.get(status_col) if status_col else "", 40) if status_col else "",
    }


def _fallback_solutions_from_pain(pain: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deterministic fallback when the local LLM is unavailable.
    Important: These are generic "candidate templates" so callers can still proceed.
    """
    pain_name = _safe_str(_get_ci(pain or {}, "Pain_Name") or _get_ci(pain or {}, "title") or _get_ci(pain or {}, "name"), 80)
    pain_desc = _safe_str(_get_ci(pain or {}, "Description") or _get_ci(pain or {}, "summary") or "", 240)
    base = f" for: {pain_name}" if pain_name else ""
    context_hint = f" (context: {pain_desc})" if pain_desc else ""
    return [
        {
            "title": f"Clarify the pain definition{base}",
            "description": f"Write a crisp 1–2 sentence problem statement, list who is affected, and add one concrete evidence line.{context_hint}",
            "effort_score": 2.0,
            "impact_score": 6.0,
            "confidence": 0.45,
            "reasoning": "Most solution failures come from vague problem definition; tightening scope improves downstream decisions.",
        },
        {
            "title": f"Instrument + measure the bottleneck{base}",
            "description": "Add a minimal measurement: time-to-complete, error rate, or cost. Track it for 3–7 days to quantify baseline.",
            "effort_score": 4.0,
            "impact_score": 7.0,
            "confidence": 0.40,
            "reasoning": "Measurement makes the pain falsifiable and reveals whether a fix actually works.",
        },
        {
            "title": f"Implement a low-risk workaround{base}",
            "description": "Create a simple workaround that reduces frequency or severity immediately (even if imperfect). Iterate after first win.",
            "effort_score": 5.0,
            "impact_score": 6.0,
            "confidence": 0.35,
            "reasoning": "A reversible v1 reduces pain now and buys learning for a better long-term solution.",
        },
    ]


def _normalize_solution_candidates(items: Any) -> List[Dict[str, Any]]:
    """Normalize LLM-produced items into the contract shape."""
    if not isinstance(items, list):
        return []
    out: List[Dict[str, Any]] = []
    seen_titles = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        title = _safe_str(raw.get("title") or raw.get("name") or raw.get("solution") or "", 120)
        desc = _safe_str(raw.get("description") or raw.get("summary") or raw.get("details") or "", 1400)
        effort = _clamp(raw.get("effort_score") or raw.get("effort") or raw.get("complexity"), 1.0, 10.0, default=5.0)
        impact = _clamp(raw.get("impact_score") or raw.get("impact") or raw.get("value"), 1.0, 10.0, default=5.0)
        conf = _clamp(raw.get("confidence"), 0.0, 1.0, default=0.4)
        reasoning = _safe_str(raw.get("reasoning") or raw.get("rationale") or "", 900)
        if not title:
            continue
        key = title.lower().strip()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        out.append(
            {
                "title": title,
                "description": desc,
                "effort_score": float(effort),
                "impact_score": float(impact),
                "confidence": float(conf),
                "reasoning": reasoning or "No reasoning provided.",
            }
        )
    return out


def _format_solution_list_for_cli(solutions: List[Dict[str, Any]], max_items: int = 10) -> str:
    if not solutions:
        return "No solutions found."
    lines: List[str] = []
    for i, s in enumerate(solutions[: max(0, int(max_items))], start=1):
        title = _safe_str(s.get("title"), 80)
        eff = s.get("effort_score")
        imp = s.get("impact_score")
        conf = s.get("confidence")
        line = f"{i}. {title}"
        meta: List[str] = []
        if isinstance(imp, (int, float)):
            meta.append(f"impact={float(imp):.1f}/10")
        if isinstance(eff, (int, float)):
            meta.append(f"effort={float(eff):.1f}/10")
        if isinstance(conf, (int, float)):
            meta.append(f"conf={float(conf):.2f}")
        if meta:
            line += " (" + ", ".join(meta) + ")"
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_solutions(conn, pain_id: str) -> List[Dict[str, Any]]:
    """
    Generate solution candidates for a pain point using DB context + local LLM.

    Args:
        conn: sqlite3.Connection (from src/db/db_connect.get_connection()).
        pain_id: Pain_ID (PAIN-YYYYMMDD-NNN).

    Returns:
        list[dict]: [
          {title, description, effort_score, impact_score, confidence, reasoning}, ...
        ]
    """
    pain_id = (pain_id or "").strip()
    pain = _fetch_pain_record(conn, pain_id)
    if not pain:
        return [
            {
                "title": "Verify pain record exists",
                "description": f"Pain record not found for Pain_ID={pain_id}. Confirm the ID and that Pain_Point_Register contains the record.",
                "effort_score": 1.0,
                "impact_score": 3.0,
                "confidence": 0.9,
                "reasoning": "Cannot generate solutions without a valid pain definition.",
            }
        ]

    # Build DB context pack (includes pain + linked solutions/predictions).
    try:
        ctx = build_pain_context(conn, pain_id)
    except Exception as e:  # pragma: no cover
        _LOG.warning("build_pain_context failed: %s", e)
        ctx = "PAIN_CONTEXT: (failed to build)"

    prompt = (
        "You are aeOS Solution Designer.\n"
        "Goal: generate a small set of high-quality Solution_Design candidates for the pain point.\n"
        "Rules:\n"
        "- Use ONLY what is in CONTEXT. Do NOT invent new facts.\n"
        "- Each solution must be concrete and testable.\n"
        "- Prefer reversible (two-way door) actions when uncertain.\n"
        "- Effort_Score: 1..10 (1 = easiest). Impact_Score: 1..10 (10 = biggest).\n"
        "- Confidence: 0..1 based on how well the solution matches the context.\n"
        "- Keep reasoning to 1–3 sentences.\n\n"
        "<CONTEXT>\n"
        f"{_truncate(ctx, 6000)}\n"
        "</CONTEXT>\n\n"
        "Return 5 to 7 solutions as JSON now."
    )

    schema_hint = (
        "[\n"
        "  {\n"
        '    "title": "string",\n'
        '    "description": "string",\n'
        '    "effort_score": 1,\n'
        '    "impact_score": 1,\n'
        '    "confidence": 0.0,\n'
        '    "reasoning": "string"\n'
        "  }\n"
        "]"
    )

    out = infer_json(prompt=prompt, schema_hint=schema_hint)
    if out.get("success"):
        candidates = _normalize_solution_candidates(out.get("data"))
        if candidates:
            return candidates

    # Fallback: no AI / parse failed.
    return _fallback_solutions_from_pain(pain)


def rank_solutions_with_ai(conn, pain_id: str) -> List[Dict[str, Any]]:
    """
    Re-rank existing solutions for a pain point using local LLM reasoning.

    This is intended to surface the best next action beyond numeric impact/effort:
    - dependencies
    - reversibility
    - evidence fit
    - sequencing / prerequisites

    Args:
        conn: sqlite3.Connection
        pain_id: Pain_ID (PAIN-YYYYMMDD-NNN)

    Returns:
        list[dict]: solutions in AI-ranked order, with extra fields:
          - ai_rank
          - ai_reasoning
    """
    pain_id = (pain_id or "").strip()
    if not pain_id or conn is None:
        return []

    table = _solution_table(conn)
    if not table:
        return []

    rows = _fetch_solutions_for_pain(conn, pain_id, limit=50)
    if not rows:
        return []

    sols: List[Dict[str, Any]] = []
    for r in rows:
        s = _extract_solution_fields(conn, table, r)
        s["description"] = _truncate(s.get("description") or "", 600)
        sols.append(s)

    pain = _fetch_pain_record(conn, pain_id) or {}
    pain_compact = {
        "Pain_ID": _get_ci(pain, "Pain_ID") or pain_id,
        "Pain_Name": _get_ci(pain, "Pain_Name") or _get_ci(pain, "title") or _get_ci(pain, "name"),
        "Description": _truncate(_safe_str(_get_ci(pain, "Description") or "", 900), 900),
        "Root_Cause": _truncate(_safe_str(_get_ci(pain, "Root_Cause") or "", 500), 500),
        "Frequency": _get_ci(pain, "Frequency"),
        "Severity": _get_ci(pain, "Severity"),
        "Impact_Score": _get_ci(pain, "Impact_Score"),
        "Monetizability_Flag": _get_ci(pain, "Monetizability_Flag"),
    }

    prompt = (
        "You are aeOS Solution Ranking Agent.\n"
        "Task: re-rank the candidate solutions for the given pain point.\n"
        "Rules:\n"
        "- Use ONLY the provided pain + solution list.\n"
        "- Do NOT invent dependencies, costs, or constraints.\n"
        "- Prefer solutions that are high impact, low effort, and reversible.\n"
        "- If two solutions have similar scores, prefer the one that creates learning or unlocks other solutions.\n"
        "- Output JSON only.\n\n"
        "<PAIN>\n"
        f"{json.dumps(pain_compact, ensure_ascii=False)}\n"
        "</PAIN>\n\n"
        "<SOLUTIONS>\n"
        f"{json.dumps(sols, ensure_ascii=False)}\n"
        "</SOLUTIONS>\n\n"
        "Return a JSON array ranking the solutions by best next move (rank=1 is best)."
    )

    schema_hint = (
        "[\n"
        "  {\n"
        '    "solution_id": "string",\n'
        '    "rank": 1,\n'
        '    "reasoning": "string (1-3 sentences)"\n'
        "  }\n"
        "]"
    )

    out = infer_json(prompt=prompt, schema_hint=schema_hint)
    if out.get("success") and isinstance(out.get("data"), list):
        ranking = out["data"]
        id_to_rank: Dict[str, Tuple[int, str]] = {}
        for item in ranking:
            if not isinstance(item, dict):
                continue
            sid = _safe_str(item.get("solution_id"), 60)
            if not sid:
                continue
            r = int(_clamp(item.get("rank"), 1.0, 999.0, default=999.0))
            reason = _safe_str(item.get("reasoning"), 800)
            id_to_rank[sid] = (r, reason or "No reasoning provided.")

        def sort_key(s: Dict[str, Any]) -> Tuple[int, float, float, str]:
            sid = _safe_str(s.get("solution_id"), 60)
            ai_rank = id_to_rank.get(sid, (999, ""))[0]
            imp = _to_float(s.get("impact_score"), default=0.0) or 0.0
            eff = _to_float(s.get("effort_score"), default=10.0) or 10.0
            return (ai_rank, -imp, eff, _safe_str(s.get("title"), 120).lower())

        sols_sorted = sorted(sols, key=sort_key)
        for s in sols_sorted:
            sid = _safe_str(s.get("solution_id"), 60)
            r, reason = id_to_rank.get(sid, (999, ""))
            s["ai_rank"] = r if r != 999 else None
            s["ai_reasoning"] = reason or None
        return sols_sorted

    # Fallback: numeric-first heuristic.
    def fallback_key(s: Dict[str, Any]) -> Tuple[float, float, str]:
        imp = _to_float(s.get("impact_score"), default=0.0) or 0.0
        eff = _to_float(s.get("effort_score"), default=10.0) or 10.0
        return (-imp, eff, _safe_str(s.get("title"), 120).lower())

    return sorted(sols, key=fallback_key)


def generate_solution_summary(conn, solution_id: str) -> str:
    """
    Produce a one-paragraph summary for CLI display.

    Args:
        conn: sqlite3.Connection
        solution_id: Solution_ID (SOL-YYYYMMDD-NNN)

    Returns:
        str: one-paragraph summary
    """
    solution_id = (solution_id or "").strip()
    rec = _fetch_solution_record(conn, solution_id)
    if not rec:
        return f"Solution Summary: (no record found for Solution_ID={solution_id})"

    table = _solution_table(conn) or ""
    norm = _extract_solution_fields(conn, table, rec) if table else {
        "solution_id": solution_id,
        "title": _safe_str(_get_ci(rec, "Solution_Name") or _get_ci(rec, "title") or _get_ci(rec, "name"), 120),
        "description": _safe_str(_get_ci(rec, "Description") or _get_ci(rec, "summary") or "", 1200),
        "effort_score": _to_float(_get_ci(rec, "Effort_Score") or _get_ci(rec, "effort_score")),
        "impact_score": _to_float(_get_ci(rec, "Impact_Score") or _get_ci(rec, "impact_score")),
        "pain_id": _safe_str(_get_ci(rec, "Pain_ID") or _get_ci(rec, "pain_id") or "", 40),
    }

    compact = {
        "solution_id": norm.get("solution_id") or solution_id,
        "pain_id": norm.get("pain_id") or "",
        "title": norm.get("title") or "",
        "description": _truncate(norm.get("description") or "", 900),
        "effort_score": norm.get("effort_score"),
        "impact_score": norm.get("impact_score"),
    }

    prompt = (
        "You are aeOS Solution Summarizer.\n"
        "Write ONE paragraph (max ~90 words) summarizing the solution for CLI display.\n"
        "Include: what it is, expected impact, effort, and the next concrete step.\n"
        "No markdown. No bullets.\n\n"
        f"{json.dumps(compact, ensure_ascii=False)}"
    )

    out = infer(prompt=prompt, system_prompt=None)
    if out.get("success") and isinstance(out.get("response"), str) and out["response"].strip():
        return _truncate(out["response"].strip(), 900)

    # Fallback: deterministic summary.
    title = _safe_str(compact.get("title") or "Untitled solution", 120)
    desc = _safe_str(compact.get("description") or "", 500)
    eff = compact.get("effort_score")
    imp = compact.get("impact_score")
    meta: List[str] = []
    if isinstance(imp, (int, float)):
        meta.append(f"impact {float(imp):.1f}/10")
    if isinstance(eff, (int, float)):
        meta.append(f"effort {float(eff):.1f}/10")
    meta_s = (" (" + ", ".join(meta) + ")") if meta else ""
    next_step = "Next: define a tiny v1 experiment and measure baseline vs. after."
    return f"{title}{meta_s}: {desc} {next_step}".strip()


def suggest_quick_wins(conn) -> List[Dict[str, Any]]:
    """
    Find quick wins across the portfolio.

    Definition:
      - high impact AND low effort
      - based on stored numeric scores (if present)

    Args:
        conn: sqlite3.Connection

    Returns:
        list[dict]: quick win solutions (sorted), each dict includes:
          - solution_id
          - pain_id
          - title
          - effort_score
          - impact_score
          - quick_win_score
    """
    if conn is None:
        return []
    table = _solution_table(conn)
    if not table:
        return []
    rows = _fetch_solution_rows(conn, limit=300)
    if not rows:
        return []

    candidates: List[Dict[str, Any]] = []
    for r in rows:
        s = _extract_solution_fields(conn, table, r)
        if not isinstance(s.get("impact_score"), (int, float)) or not isinstance(s.get("effort_score"), (int, float)):
            continue
        impact = float(s["impact_score"])
        effort = float(s["effort_score"])
        # Quick-win threshold (tunable): high impact + low effort.
        if impact < 7.0 or effort > 4.0:
            continue
        # Score: weight impact more; lower effort better.
        qscore = (impact * 2.0) - effort
        candidates.append(
            {
                "solution_id": s.get("solution_id"),
                "pain_id": s.get("pain_id"),
                "title": s.get("title"),
                "effort_score": effort,
                "impact_score": impact,
                "quick_win_score": float(qscore),
            }
        )

    candidates.sort(
        key=lambda d: (
            -(d.get("quick_win_score") or 0.0),
            -(d.get("impact_score") or 0.0),
            d.get("effort_score") or 999.0,
        )
    )
    return candidates[:25]


# ---------------------------------------------------------------------------
# Optional Router entry point (for ai_router integration)
# ---------------------------------------------------------------------------

_PAIN_ID_RE = re.compile(r"\bPAIN-\d{8}-\d{3}\b", re.I)
_SOL_ID_RE = re.compile(r"\bSOL-\d{8}-\d{3}\b", re.I)


def handle(query: str, conn, kb_conn=None) -> Dict[str, Any]:
    """
    Router-compatible handler for ai_router.py.

    This is a thin wrapper over the public functions in this module.
    Supported patterns:
      - "quick wins" -> suggest_quick_wins()
      - contains PAIN-YYYYMMDD-NNN -> generate_solutions()
      - "rank" + pain id -> rank_solutions_with_ai()
      - "summary" + SOL-YYYYMMDD-NNN -> generate_solution_summary()
    """
    q = (query or "").strip()
    if not q:
        return {"success": False, "response": "", "error": "empty_query"}

    if re.search(r"\bquick\s*wins?\b", q, re.I):
        wins = suggest_quick_wins(conn)
        resp = (
            "Quick Wins:\n"
            + "\n".join(
                [
                    f"- {w.get('solution_id')}: {w.get('title')} (impact={w.get('impact_score')}, effort={w.get('effort_score')})"
                    for w in wins[:10]
                ]
            )
            if wins
            else "Quick Wins: (none found)"
        )
        return {"success": True, "response": resp, "data": wins}

    m_pain = _PAIN_ID_RE.search(q)
    if m_pain:
        pain_id = m_pain.group(0).upper()
        if re.search(r"\b(rank|rerank|re-rank)\b", q, re.I):
            ranked = rank_solutions_with_ai(conn, pain_id)
            resp = "AI Ranked Solutions:\n" + _format_solution_list_for_cli(ranked, max_items=10)
            return {"success": True, "response": resp, "data": ranked}
        sols = generate_solutions(conn, pain_id)
        resp = "Generated Solutions:\n" + _format_solution_list_for_cli(sols, max_items=10)
        return {"success": True, "response": resp, "data": sols}

    m_sol = _SOL_ID_RE.search(q)
    if m_sol and re.search(r"\b(summary|summarize)\b", q, re.I):
        sid = m_sol.group(0).upper()
        summary = generate_solution_summary(conn, sid)
        return {"success": True, "response": summary, "data": {"solution_id": sid}}

    return {
        "success": True,
        "response": (
            "agent_solution: provide a PAIN-YYYYMMDD-NNN to generate solutions, "
            "'rank PAIN-...' to re-rank existing solutions, 'summary SOL-...' for a one-paragraph summary, "
            "or 'quick wins' to list high-impact low-effort solutions."
        ),
    }
