"""
ai_context.py — aeOS Phase 4 (Layer 1)

Purpose:
  Build rich prompt context from aeOS local SQLite DB + KB (RAG store)
  before sending prompts to the local LLM.

Design goals:
  - Robust to schema drift (tables/columns may vary).
  - Graceful failure (never crash callers; best-effort context).
  - Prompt-friendly output (bounded size, clear sectioning).

Stamp: S✅ T✅ L✅ A✅
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from typing import Any, Dict, List, Optional, Sequence


# All logging should route through src/core/logger.py.
try:
    from src.core.logger import get_logger  # type: ignore
except Exception:  # pragma: no cover
    import logging

    def get_logger(name: str):  # type: ignore
        return logging.getLogger(name)


logger = get_logger(__name__)


# -----------------------
# Small, reusable helpers
# -----------------------


def _utc_now_iso() -> str:
    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 12].rstrip() + "…(truncated)"


def _safe_str(v: Any, max_len: int = 400) -> str:
    """Convert values to prompt-safe single-line strings."""
    if v is None:
        return ""
    if isinstance(v, (int, float, bool)):
        return str(v)
    if isinstance(v, (bytes, bytearray)):
        try:
            v = v.decode("utf-8", errors="replace")
        except Exception:
            v = str(v)
    s = re.sub(r"\s+", " ", str(v)).strip()
    return _truncate(s, max_len)


def _qi(name: str) -> str:
    """Quote identifier defensively (handles spaces/dashes, prevents SQL syntax breaks)."""
    return '"' + name.replace('"', '""') + '"'


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _fetchall_dict(conn, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    """Execute SQL and return rows as dicts (cursor.description keys)."""
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cols = [c[0] for c in cur.description] if cur.description else []
        return [{cols[i]: r[i] for i in range(len(cols))} for r in rows] if cols else []
    except Exception as e:
        logger.warning("DB query failed: %s | sql=%s", e, sql)
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
    return [r.get("name", "") for r in rows if r.get("name")]


def _find_table(conn, candidates: Sequence[str]) -> Optional[str]:
    """
    Return the first existing table/view matching candidates.
    Matching is case-insensitive, plus a conservative "contains" fallback.
    """
    existing = _list_tables(conn)
    if not existing:
        return None
    by_lower = {t.lower(): t for t in existing}
    for c in candidates:
        hit = by_lower.get(c.lower())
        if hit:
            return hit
    for c in candidates:
        cl = c.lower()
        for tl, orig in by_lower.items():
            if cl in tl:
                return orig
    return None


def _list_columns(conn, table: str) -> List[str]:
    rows = _fetchall_dict(conn, f"PRAGMA table_info({_qi(table)});", ())
    return [r.get("name", "") for r in rows if r.get("name")]


def _pick_column(conn, table: str, candidates: Sequence[str]) -> Optional[str]:
    """Pick an existing column from candidates (case-insensitive, plus normalized fallback)."""
    cols = _list_columns(conn, table)
    if not cols:
        return None
    cols_l = {c.lower(): c for c in cols}
    for c in candidates:
        hit = cols_l.get(c.lower())
        if hit:
            return hit
    cols_n = {_norm(c): c for c in cols}
    for c in candidates:
        nc = _norm(c)
        hit = cols_n.get(nc)
        if hit:
            return hit
    return None


def _maybe_order_by(conn, table: str) -> Optional[str]:
    """Prefer stable temporal ordering when available; otherwise return None."""
    col = _pick_column(conn, table, ("updated_at", "updatedAt", "created_at", "createdAt", "timestamp", "as_of"))
    return col


def _format_record(record: Dict[str, Any], preferred: Sequence[str], title: str) -> str:
    if not record:
        return f"{title}: (none)"
    keys: List[str] = []
    seen = set()
    for want in preferred:
        for k in record.keys():
            if k.lower() == want.lower() and k not in seen:
                keys.append(k)
                seen.add(k)
    for k in record.keys():
        if k not in seen:
            keys.append(k)
            seen.add(k)
    lines = [title]
    for k in keys[:12]:
        lines.append(f"- {k}: {_safe_str(record.get(k), 260)}")
    if len(keys) > 12:
        lines.append(f"- … (+{len(keys) - 12} more fields)")
    return "\n".join(lines)


def _format_list(
    label: str,
    rows: List[Dict[str, Any]],
    id_keys: Sequence[str],
    text_keys: Sequence[str],
    max_items: int = 5,
) -> str:
    if not rows:
        return f"{label}: (none)"
    out = [f"{label} ({min(len(rows), max_items)}/{len(rows)}):"]
    for r in rows[:max_items]:
        rid = ""
        rtext = ""
        for k in id_keys:
            for rk in r.keys():
                if rk.lower() == k.lower():
                    rid = _safe_str(r.get(rk), 80)
                    break
            if rid:
                break
        for k in text_keys:
            for rk in r.keys():
                if rk.lower() == k.lower():
                    rtext = _safe_str(r.get(rk), 180)
                    break
            if rtext:
                break
        if not rtext:
            rtext = _truncate(json.dumps(r, ensure_ascii=False), 240)
        out.append(f"- {rid}: {rtext}" if rid else f"- {rtext}")
    return "\n".join(out)


def _recent_rows(conn, table: str, limit: int = 5) -> List[Dict[str, Any]]:
    order_by = _maybe_order_by(conn, table)
    sql = f"SELECT * FROM {_qi(table)}"
    if order_by:
        sql += f" ORDER BY {_qi(order_by)} DESC"
    sql += f" LIMIT {int(limit)};"
    return _fetchall_dict(conn, sql, ())


def _keywordize(question: str, max_keywords: int = 8) -> List[str]:
    # Deterministic keyword extraction: words >=4 chars, de-duped, basic stopwords removed.
    stop = {
        "the",
        "and",
        "that",
        "this",
        "with",
        "from",
        "into",
        "what",
        "when",
        "where",
        "which",
        "will",
        "would",
        "should",
        "could",
        "about",
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
        "help",
        "please",
    }
    toks = re.findall(r"[A-Za-z0-9_]{4,}", (question or "").lower())
    out: List[str] = []
    seen = set()
    for t in toks:
        if t in stop or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= max_keywords:
            break
    return out


def _search_table_like(conn, table: str, keywords: Sequence[str], limit: int = 5) -> List[Dict[str, Any]]:
    """LIKE-search across heuristically-chosen text columns."""
    if not table or not keywords:
        return []
    cols = _list_columns(conn, table)
    if not cols:
        return []
    text_cols = [
        c
        for c in cols
        if any(k in c.lower() for k in ("title", "name", "summary", "description", "notes", "context", "statement", "question"))
    ] or [c for c in cols if any(k in c.lower() for k in ("text", "body", "detail"))]
    if not text_cols:
        return []
    clauses: List[str] = []
    params: List[Any] = []
    for kw in keywords:
        inner = [f"{_qi(c)} LIKE ?" for c in text_cols]
        clauses.append("(" + " OR ".join(inner) + ")")
        params.extend([f"%{kw}%"] * len(text_cols))
    where = " OR ".join(clauses)
    order_by = _maybe_order_by(conn, table)
    sql = f"SELECT * FROM {_qi(table)} WHERE {where}"
    if order_by:
        sql += f" ORDER BY {_qi(order_by)} DESC"
    sql += f" LIMIT {int(limit)};"
    return _fetchall_dict(conn, sql, tuple(params))


# ----------------------------
# Public context builders (DB)
# ----------------------------


def build_pain_context(conn, pain_id: str) -> str:
    """
    Fetch pain record + linked solutions + related predictions, formatted for prompt context.
    """
    if conn is None:
        return "PAIN_CONTEXT: (db connection unavailable)"
    pain_table = _find_table(conn, ("Pain_Point_Register", "pain_point_register", "pain_points", "pains", "pain"))
    sol_table = _find_table(conn, ("Solution_Design", "solution_design", "solutions", "solution"))
    pred_table = _find_table(conn, ("Prediction_Registry", "prediction_registry", "predictions", "prediction"))
    out: List[str] = ["BEGIN_DB_CONTEXT", f"GeneratedAtUTC: {_utc_now_iso()}", f"FocusPainID: {pain_id}", ""]

    if not pain_table:
        out += ["PAIN: (table not found)", "END_DB_CONTEXT"]
        return "\n".join(out)

    pain_id_col = _pick_column(conn, pain_table, ("pain_id", "Pain_ID", "id", "ID"))
    if not pain_id_col:
        out += [f"PAIN: (id column not found in {pain_table})", "END_DB_CONTEXT"]
        return "\n".join(out)

    pain = _fetchone_dict(
        conn,
        f"SELECT * FROM {_qi(pain_table)} WHERE {_qi(pain_id_col)} = ? LIMIT 1;",
        (pain_id,),
    )
    if pain:
        out.append(
            _format_record(
                pain,
                preferred=("title", "name", "summary", "description", "severity", "frequency", "impact", "monetizability", "pain_score", "status"),
                title="PAIN:",
            )
        )
    else:
        out.append(f"PAIN [{pain_table}]: (no record found for {pain_id})")
    out.append("")

    # Linked solutions (best-effort FK lookup)
    if sol_table:
        link_col = _pick_column(conn, sol_table, ("pain_id", "Pain_ID", "linked_pain_id", "source_pain_id", "painId"))
        sol_rows: List[Dict[str, Any]] = []
        if link_col:
            order_by = _maybe_order_by(conn, sol_table)
            sql = f"SELECT * FROM {_qi(sol_table)} WHERE {_qi(link_col)} = ?"
            if order_by:
                sql += f" ORDER BY {_qi(order_by)} DESC"
            sql += " LIMIT 5;"
            sol_rows = _fetchall_dict(conn, sql, (pain_id,))
        out.append(
            _format_list(
                f"LINKED_SOLUTIONS [{sol_table}]",
                sol_rows,
                id_keys=("solution_id", "Solution_ID", "id", "ID"),
                text_keys=("title", "name", "summary", "description"),
            )
        )
    else:
        out.append("LINKED_SOLUTIONS: (table not found)")
    out.append("")

    # Related predictions
    if pred_table:
        pred_link_col = _pick_column(
            conn,
            pred_table,
            ("pain_id", "Pain_ID", "related_pain_id", "source_pain_id", "subject_id", "entity_id"),
        )
        pred_rows: List[Dict[str, Any]] = []
        if pred_link_col:
            order_by = _maybe_order_by(conn, pred_table)
            sql = f"SELECT * FROM {_qi(pred_table)} WHERE {_qi(pred_link_col)} = ?"
            if order_by:
                sql += f" ORDER BY {_qi(order_by)} DESC"
            sql += " LIMIT 5;"
            pred_rows = _fetchall_dict(conn, sql, (pain_id,))
        out.append(
            _format_list(
                f"RELATED_PREDICTIONS [{pred_table}]",
                pred_rows,
                id_keys=("prediction_id", "Prediction_ID", "id", "ID"),
                text_keys=("statement", "question", "title", "summary"),
            )
        )
    else:
        out.append("RELATED_PREDICTIONS: (table not found)")

    out.append("END_DB_CONTEXT")
    return "\n".join(out)


def build_portfolio_context(conn) -> str:
    """
    Summarize portfolio health for prompt context (best-effort).
    If canonical fields are missing, include a compact JSON snapshot of the newest row.
    """
    if conn is None:
        return "PORTFOLIO_CONTEXT: (db connection unavailable)"
    table = _find_table(conn, ("portfolio_health_view", "Portfolio_Health_View", "Portfolio_Health", "portfolio_health", "portfolio"))
    if not table:
        return "PORTFOLIO_CONTEXT: (no portfolio health table/view found)"
    rows = _recent_rows(conn, table, limit=3)
    if not rows:
        return f"PORTFOLIO_CONTEXT [{table}]: (no rows)"
    row = rows[0]
    keys_l = {k.lower(): k for k in row.keys()}

    def get_any(cands: Sequence[str]) -> str:
        for c in cands:
            k = keys_l.get(c.lower())
            if k:
                return _safe_str(row.get(k))
        return ""

    cash = get_any(("cash_balance", "cash", "cash_on_hand", "cash_usd", "cash_php"))
    runway = get_any(("runway_days", "runway", "runway_months", "runwayDays"))
    burn = get_any(("monthly_burn", "burn_rate", "burn", "monthlyBurn"))
    value = get_any(("portfolio_value", "total_value", "net_worth", "equity_value"))
    as_of = get_any(("as_of", "timestamp", "date", "updated_at", "updatedAt", "created_at", "createdAt"))
    lines = ["BEGIN_PORTFOLIO_CONTEXT", f"GeneratedAtUTC: {_utc_now_iso()}"]
    if as_of:
        lines.append(f"DataAsOf: {as_of}")
    if value:
        lines.append(f"- portfolio_value: {value}")
    if cash:
        lines.append(f"- cash_balance: {cash}")
    if burn:
        lines.append(f"- monthly_burn: {burn}")
    if runway:
        lines.append(f"- runway: {runway}")
    if len(lines) <= 3:
        lines.append("- snapshot: " + _truncate(json.dumps(row, ensure_ascii=False), 700))
    lines.append("END_PORTFOLIO_CONTEXT")
    return "\n".join(lines)


def build_decision_context(conn, question: str) -> str:
    """
    Pull relevant pains + solutions + mental models for a decision question.
    Uses LIKE search; falls back to recent records if no matches.
    """
    if conn is None:
        return "DECISION_CONTEXT: (db connection unavailable)"
    kw = _keywordize(question)
    pain_table = _find_table(conn, ("Pain_Point_Register", "pain_point_register", "pain_points", "pains", "pain"))
    sol_table = _find_table(conn, ("Solution_Design", "solution_design", "solutions", "solution"))
    mm_table = _find_table(conn, ("Mental_Models_Registry", "mental_models_registry", "mental_models", "mental_model"))
    pains = _search_table_like(conn, pain_table, kw, 5) if pain_table else []
    sols = _search_table_like(conn, sol_table, kw, 5) if sol_table else []
    mms = _search_table_like(conn, mm_table, kw, 5) if mm_table else []
    if pain_table and not pains:
        pains = _recent_rows(conn, pain_table, 3)
    if sol_table and not sols:
        sols = _recent_rows(conn, sol_table, 3)
    if mm_table and not mms:
        mms = _recent_rows(conn, mm_table, 3)
    lines = [
        "BEGIN_DECISION_CONTEXT",
        f"GeneratedAtUTC: {_utc_now_iso()}",
        f"Question: {_safe_str(question, 700)}",
        "Keywords: " + (", ".join(kw) if kw else "(none)"),
        "",
    ]
    lines.append(
        _format_list(
            f"RELEVANT_PAINS [{pain_table}]",
            pains,
            id_keys=("pain_id", "Pain_ID", "id", "ID"),
            text_keys=("title", "name", "summary", "description"),
        )
        if pain_table
        else "RELEVANT_PAINS: (table not found)"
    )
    lines.append("")
    lines.append(
        _format_list(
            f"RELEVANT_SOLUTIONS [{sol_table}]",
            sols,
            id_keys=("solution_id", "Solution_ID", "id", "ID"),
            text_keys=("title", "name", "summary", "description"),
        )
        if sol_table
        else "RELEVANT_SOLUTIONS: (table not found)"
    )
    lines.append("")
    lines.append(
        _format_list(
            f"RELEVANT_MENTAL_MODELS [{mm_table}]",
            mms,
            id_keys=("model_id", "mm_id", "id", "ID"),
            text_keys=("name", "title", "summary", "description"),
        )
        if mm_table
        else "RELEVANT_MENTAL_MODELS: (table not found)"
    )
    lines.append("END_DECISION_CONTEXT")
    return "\n".join(lines)


# ----------------------------
# KB context (duck-typed)
# ----------------------------


def _kb_query(kb_conn: Any, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """
    Best-effort KB query.

    Supports:
    - Chroma Collection: collection.query(query_texts=[...], n_results=...)
    - Wrapper: kb_conn.search(query, top_k=...) or kb_conn.search(query, k=...)
    """
    if kb_conn is None or not query:
        return []
    if hasattr(kb_conn, "query") and callable(getattr(kb_conn, "query")):
        try:
            res = kb_conn.query(query_texts=[query], n_results=top_k)
            docs = (res.get("documents") or [[]])[0]
            metas = (res.get("metadatas") or [[]])[0]
            ids = (res.get("ids") or [[]])[0]
            dists = (res.get("distances") or [[]])[0]
            out: List[Dict[str, Any]] = []
            for i in range(min(top_k, len(docs))):
                out.append(
                    {
                        "id": ids[i] if i < len(ids) else "",
                        "text": docs[i],
                        "metadata": metas[i] if i < len(metas) else {},
                        "distance": dists[i] if i < len(dists) else None,
                    }
                )
            return out
        except TypeError:
            pass  # wrapper uses different signature; fall through
        except Exception as e:
            logger.warning("KB .query failed: %s", e)
    if hasattr(kb_conn, "search") and callable(getattr(kb_conn, "search")):
        try:
            try:
                res = kb_conn.search(query, top_k=top_k)
            except TypeError:
                res = kb_conn.search(query, k=top_k)
            if isinstance(res, dict):
                res = res.get("results") or res.get("items") or []
            if isinstance(res, list):
                out: List[Dict[str, Any]] = []
                for item in res[:top_k]:
                    if isinstance(item, dict):
                        out.append(
                            {
                                "id": item.get("id") or item.get("doc_id") or "",
                                "text": item.get("text") or item.get("document") or item.get("content") or "",
                                "metadata": item.get("metadata") or {},
                                "distance": item.get("distance"),
                                "score": item.get("score"),
                            }
                        )
                    else:
                        out.append({"id": "", "text": str(item), "metadata": {}})
                return out
        except Exception as e:
            logger.warning("KB .search failed: %s", e)
    return []


def build_kb_context(kb_conn, query: str) -> str:
    """Search KB and format the top 3 results for prompt context."""
    results = _kb_query(kb_conn, query, top_k=3)
    lines = ["BEGIN_KB_CONTEXT", f"GeneratedAtUTC: {_utc_now_iso()}", f"Query: {_safe_str(query, 600)}", ""]
    if not results:
        lines += ["KB_RESULTS: (none)", "END_KB_CONTEXT"]
        return "\n".join(lines)
    lines.append(f"KB_RESULTS ({len(results)}):")
    for i, r in enumerate(results, start=1):
        meta = r.get("metadata") or {}
        title = meta.get("title") or meta.get("name") or meta.get("source") or meta.get("path") or ""
        rid = r.get("id") or ""
        snippet = _safe_str(r.get("text") or "", 800)
        header_bits: List[str] = []
        if title:
            header_bits.append(_safe_str(title, 120))
        if rid:
            header_bits.append(_safe_str(rid, 80))
        header = " | ".join(header_bits) if header_bits else "(untitled)"
        lines.append(f"{i}. {header}")
        lines.append("   " + (snippet if snippet else "(empty)"))
        src = meta.get("url") or meta.get("file") or meta.get("filepath")
        if src:
            lines.append("   source: " + _safe_str(src, 200))
    lines.append("END_KB_CONTEXT")
    return "\n".join(lines)


def assemble_full_context(conn, kb_conn, query: str) -> str:
    """
    Combine DB + KB context into a single prompt pack.
    Order: portfolio → decision records → KB snippets.
    """
    parts: List[str] = ["=== aeOS_CONTEXT_PACK ===", f"GeneratedAtUTC: {_utc_now_iso()}", ""]
    try:
        parts.append(build_portfolio_context(conn))
    except Exception as e:
        logger.warning("build_portfolio_context failed: %s", e)
        parts.append("PORTFOLIO_CONTEXT: (error building context)")
    parts.append("")
    try:
        parts.append(build_decision_context(conn, query))
    except Exception as e:
        logger.warning("build_decision_context failed: %s", e)
        parts.append("DECISION_CONTEXT: (error building context)")
    parts.append("")
    try:
        parts.append(build_kb_context(kb_conn, query))
    except Exception as e:
        logger.warning("build_kb_context failed: %s", e)
        parts.append("KB_CONTEXT: (error building context)")
    parts.append("=== END_aeOS_CONTEXT_PACK ===")
    # Defensive bound to avoid prompt overflows if schemas contain unexpectedly large fields.
    return _truncate("\n".join(parts), 9000)


__all__ = [
    "build_pain_context",
    "build_portfolio_context",
    "build_decision_context",
    "build_kb_context",
    "assemble_full_context",
]
