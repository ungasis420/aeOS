"""
aeOS Phase 5 — agent_graph.py

Knowledge Graph traversal agent (GraphRAG-style) without a graph database.
Uses SQLite relationships + lightweight heuristics + local LLM (via infer/infer_json)
to discover non-obvious connections among pains, solutions, predictions, decisions,
and KB context.

Design goals:
- Robust to schema drift (table/column name variants)
- Graceful degradation when DB/KV/LLM are unavailable
- Deterministic return shapes (always dict; never raise)

Public API:
- find_connections(conn, kb_conn, concept: str) -> dict
- build_entity_graph(conn) -> dict
- traverse_from_pain(conn, kb_conn, pain_id: int) -> dict
- find_root_causes_across_portfolio(conn, kb_conn) -> dict
- suggest_leverage_points(conn, kb_conn) -> dict
"""

from __future__ import annotations

import inspect
import json
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

import sqlite3

from src.ai.ai_infer import infer, infer_json
from src.ai.ai_context import build_pain_context, build_kb_context


# -----------------------------
# Internal helpers (schema + IO)
# -----------------------------


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "who",
    "why",
    "with",
    "you",
    "your",
    "we",
    "they",
    "their",
    "our",
    "not",
    "no",
    "yes",
}


def _safe_error(error: str) -> Dict[str, Any]:
    """Return a consistent error dict."""
    return {"success": False, "error": str(error)}


def _rows_to_dicts(cur: sqlite3.Cursor, rows: Sequence[Sequence[Any]]) -> List[Dict[str, Any]]:
    """Convert cursor rows to list[dict] without relying on row_factory."""
    cols = [c[0] for c in (cur.description or [])]
    out: List[Dict[str, Any]] = []
    for r in rows:
        try:
            out.append({cols[i]: r[i] for i in range(min(len(cols), len(r)))})
        except Exception:
            # Worst case: fallback to positional map
            out.append({str(i): r[i] for i in range(len(r))})
    return out


def _get_existing_tables(conn: Any) -> Dict[str, str]:
    """Return mapping of lowercase table name -> actual table name."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        rows = cur.fetchall() or []
        names = [r[0] for r in rows if r and isinstance(r[0], str)]
        return {n.lower(): n for n in names}
    except Exception:
        return {}


def _resolve_table(conn: Any, candidates: Sequence[str]) -> Optional[str]:
    """Return the first existing table name (case-insensitive) from candidates."""
    existing = _get_existing_tables(conn)
    for t in candidates:
        if t.lower() in existing:
            return existing[t.lower()]
    # Fallback: try direct use (some mocks won't expose sqlite_master)
    for t in candidates:
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT 1 FROM {t} LIMIT 1")
            _ = cur.fetchall()
            return t
        except Exception:
            continue
    return None


def _get_columns(conn: Any, table: str) -> List[str]:
    """Get columns for a table; returns [] on failure."""
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        rows = cur.fetchall() or []
        # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
        return [r[1] for r in rows if len(r) > 1 and isinstance(r[1], str)]
    except Exception:
        return []


def _resolve_col(columns: Sequence[str], candidates: Sequence[str]) -> Optional[str]:
    """Return matching column name (case-insensitive) from candidates."""
    col_map = {c.lower(): c for c in columns}
    for c in candidates:
        if c.lower() in col_map:
            return col_map[c.lower()]
    return None


def _safe_execute_fetch(
    conn: Any, sql: str, params: Sequence[Any] = ()
) -> List[Dict[str, Any]]:
    """Execute SQL and return list[dict]; returns [] on any failure."""
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall() or []
        return _rows_to_dicts(cur, rows)
    except Exception:
        return []


def _safe_like(term: str) -> str:
    """Build LIKE pattern for user term."""
    t = (term or "").strip()
    return f"%{t}%" if t else "%"


def _coalesce_text(d: Dict[str, Any], keys: Sequence[str]) -> str:
    """Return first non-empty string value for keys."""
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _tokenize(text: str) -> List[str]:
    """Tokenize into lower alphanum terms; remove stopwords."""
    if not isinstance(text, str):
        return []
    toks = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [t for t in toks if t and t not in _STOPWORDS and len(t) > 2]


def _jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    """Jaccard similarity of token lists."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(1, len(sa | sb))


def _normalize_action_title(title: str) -> str:
    """Normalize solution/action titles for grouping duplicates."""
    if not isinstance(title, str):
        return ""
    t = title.lower().strip()
    t = re.sub(r"[\s\-_]+", " ", t)
    t = re.sub(r"[^a-z0-9 ]+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _safe_call_context_builder(fn: Any, *args: Any, **kwargs: Any) -> str:
    """
    Call context builder (build_pain_context/build_kb_context) without assuming signature.
    Returns "" on failure.
    """
    try:
        sig = inspect.signature(fn)
        bound_kwargs = {}
        # Keep only kwargs that exist in signature
        for k, v in kwargs.items():
            if k in sig.parameters:
                bound_kwargs[k] = v
        try:
            return fn(*args, **bound_kwargs)  # type: ignore[misc]
        except TypeError:
            # Fallback: try positional-only call
            return fn(*args)  # type: ignore[misc]
    except Exception:
        return ""


def _safe_infer_json(prompt: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    """
    Try infer_json; if it fails, return fallback.
    Handles different possible return shapes.
    """
    try:
        resp = infer_json(prompt)
        if isinstance(resp, dict) and resp.get("success") is True:
            if isinstance(resp.get("data"), dict):
                return resp["data"]
            if isinstance(resp.get("response"), dict):
                return resp["response"]
            if isinstance(resp.get("response"), str):
                try:
                    parsed = json.loads(resp["response"])
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    return fallback
        # If infer_json returns already-parsed dict without wrapper
        if isinstance(resp, dict) and "success" not in resp and any(k in resp for k in fallback.keys()):
            return resp
        return fallback
    except Exception:
        return fallback


def _safe_infer_text(prompt: str, fallback: str = "") -> str:
    """Try infer; return fallback on failure. Handles common return shapes."""
    try:
        resp = infer(prompt)
        if isinstance(resp, dict) and resp.get("success") is True:
            if isinstance(resp.get("response"), str):
                return resp["response"]
            if isinstance(resp.get("text"), str):
                return resp["text"]
        if isinstance(resp, str):
            return resp
        return fallback
    except Exception:
        return fallback


# -----------------------------
# Internal helpers (entity fetch)
# -----------------------------


def _fetch_pains(conn: Any, limit: int = 500) -> Dict[str, Any]:
    """Fetch pains from best-guess schema; returns {table, id_col, title_col, desc_col, root_col, rows}."""
    pain_table = _resolve_table(conn, ["Pain_Registry", "Pain_Point_Register", "PainPoints", "pain_registry"])
    if not pain_table:
        return {"table": None, "id_col": None, "title_col": None, "desc_col": None, "root_col": None, "rows": []}

    cols = _get_columns(conn, pain_table)
    id_col = _resolve_col(cols, ["id", "Pain_ID", "pain_id"])
    title_col = _resolve_col(cols, ["title", "Pain_Name", "name"])
    desc_col = _resolve_col(cols, ["description", "Description", "details", "context", "Evidence", "notes"])
    root_col = _resolve_col(cols, ["Root_Cause", "root_cause"])

    select_cols = [c for c in [id_col, title_col, desc_col, root_col] if c]
    if not select_cols:
        return {"table": pain_table, "id_col": None, "title_col": None, "desc_col": None, "root_col": None, "rows": []}

    sql = f"SELECT {', '.join(select_cols)} FROM {pain_table} LIMIT {int(limit)}"
    rows = _safe_execute_fetch(conn, sql)
    return {
        "table": pain_table,
        "id_col": id_col,
        "title_col": title_col,
        "desc_col": desc_col,
        "root_col": root_col,
        "rows": rows,
    }


def _fetch_solutions(conn: Any, limit: int = 1000) -> Dict[str, Any]:
    """Fetch solutions from best-guess schema; returns {table, id_col, pain_fk_col, title_col, desc_col, rows}."""
    sol_table = _resolve_table(conn, ["Solution_Registry", "Solution_Design", "Solutions", "solution_registry"])
    if not sol_table:
        return {"table": None, "id_col": None, "pain_fk_col": None, "title_col": None, "desc_col": None, "rows": []}

    cols = _get_columns(conn, sol_table)
    id_col = _resolve_col(cols, ["id", "Solution_ID", "solution_id"])
    pain_fk_col = _resolve_col(cols, ["pain_id", "Pain_ID", "linked_pain_id"])
    title_col = _resolve_col(cols, ["title", "Solution_Name", "name"])
    desc_col = _resolve_col(cols, ["description", "Description", "approach", "notes", "rationale"])

    select_cols = [c for c in [id_col, pain_fk_col, title_col, desc_col] if c]
    if not select_cols:
        return {"table": sol_table, "id_col": None, "pain_fk_col": None, "title_col": None, "desc_col": None, "rows": []}

    sql = f"SELECT {', '.join(select_cols)} FROM {sol_table} LIMIT {int(limit)}"
    rows = _safe_execute_fetch(conn, sql)
    return {
        "table": sol_table,
        "id_col": id_col,
        "pain_fk_col": pain_fk_col,
        "title_col": title_col,
        "desc_col": desc_col,
        "rows": rows,
    }


def _fetch_predictions(conn: Any, limit: int = 1500) -> Dict[str, Any]:
    """Fetch predictions from best-guess schema; returns {table, id_col, pain_fk_col, idea_fk_col, text_col, prob_col, rows}."""
    pred_table = _resolve_table(conn, ["Prediction_Registry", "Predictions", "prediction_registry"])
    if not pred_table:
        return {
            "table": None,
            "id_col": None,
            "pain_fk_col": None,
            "idea_fk_col": None,
            "text_col": None,
            "prob_col": None,
            "rows": [],
        }

    cols = _get_columns(conn, pred_table)
    id_col = _resolve_col(cols, ["id", "Pred_ID", "pred_id"])
    pain_fk_col = _resolve_col(cols, ["pain_id", "Pain_ID"])
    idea_fk_col = _resolve_col(cols, ["idea_id", "Idea_ID"])
    text_col = _resolve_col(cols, ["statement", "Prediction_Text", "prediction_text", "text"])
    prob_col = _resolve_col(cols, ["probability", "Confidence_Pct", "confidence_pct", "probability_pct"])

    select_cols = [c for c in [id_col, pain_fk_col, idea_fk_col, text_col, prob_col] if c]
    if not select_cols:
        return {
            "table": pred_table,
            "id_col": None,
            "pain_fk_col": None,
            "idea_fk_col": None,
            "text_col": None,
            "prob_col": None,
            "rows": [],
        }

    sql = f"SELECT {', '.join(select_cols)} FROM {pred_table} LIMIT {int(limit)}"
    rows = _safe_execute_fetch(conn, sql)
    return {
        "table": pred_table,
        "id_col": id_col,
        "pain_fk_col": pain_fk_col,
        "idea_fk_col": idea_fk_col,
        "text_col": text_col,
        "prob_col": prob_col,
        "rows": rows,
    }


def _fetch_decisions(conn: Any, limit: int = 1000) -> Dict[str, Any]:
    """Fetch decisions from best-guess schema; returns {table, id_col, title_col, context_col, decision_col, rows}."""
    dec_table = _resolve_table(conn, ["Decision_Log", "Decision_Tree_Log", "Decisions", "decision_log"])
    if not dec_table:
        return {"table": None, "id_col": None, "title_col": None, "context_col": None, "decision_col": None, "rows": []}

    cols = _get_columns(conn, dec_table)
    id_col = _resolve_col(cols, ["id", "Decision_ID", "decision_id", "Node_ID", "node_id"])
    title_col = _resolve_col(cols, ["title", "Decision_Title", "name"])
    context_col = _resolve_col(cols, ["context", "Context", "rationale", "notes", "Decision_Context"])
    decision_col = _resolve_col(cols, ["decision_made", "Decision_Made", "decision", "Selected_Option"])

    select_cols = [c for c in [id_col, title_col, context_col, decision_col] if c]
    if not select_cols:
        return {"table": dec_table, "id_col": None, "title_col": None, "context_col": None, "decision_col": None, "rows": []}

    sql = f"SELECT {', '.join(select_cols)} FROM {dec_table} LIMIT {int(limit)}"
    rows = _safe_execute_fetch(conn, sql)
    return {
        "table": dec_table,
        "id_col": id_col,
        "title_col": title_col,
        "context_col": context_col,
        "decision_col": decision_col,
        "rows": rows,
    }


def _fetch_kb_entry_log_matches(conn: Any, term: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Search KB_Entry_Log (if present) for term in summary-ish fields."""
    kb_table = _resolve_table(conn, ["KB_Entry_Log", "KBEntryLog", "kb_entry_log"])
    if not kb_table:
        return []

    cols = _get_columns(conn, kb_table)
    id_col = _resolve_col(cols, ["id", "kb_id", "KB_ID"])
    coll_col = _resolve_col(cols, ["collection", "Collection"])
    doc_col = _resolve_col(cols, ["document_id", "Document_ID", "doc_id"])
    sum_col = _resolve_col(cols, ["summary", "Summary", "text", "content"])

    text_cols = [c for c in [sum_col, coll_col] if c]
    if not text_cols:
        return []

    where = " OR ".join([f"LOWER({c}) LIKE LOWER(?)" for c in text_cols])
    select_cols = [c for c in [id_col, coll_col, doc_col, sum_col] if c] or text_cols
    sql = f"SELECT {', '.join(select_cols)} FROM {kb_table} WHERE {where} LIMIT {int(limit)}"
    rows = _safe_execute_fetch(conn, sql, params=[_safe_like(term)] * len(text_cols))

    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "type": "kb_entry_log",
                "id": r.get(id_col) if id_col else None,
                "title": r.get(doc_col) if doc_col else None,
                "snippet": (r.get(sum_col) if sum_col else "") or "",
                "collection": r.get(coll_col) if coll_col else None,
            }
        )
    return out


def _search_entity_table(
    conn: Any,
    table: str,
    term: str,
    id_col: Optional[str],
    title_col: Optional[str],
    text_cols: Sequence[str],
    limit: int = 25,
    entity_type: str = "entity",
) -> List[Dict[str, Any]]:
    """LIKE-search a table over provided text columns; return standardized match dicts."""
    cols = _get_columns(conn, table)
    usable_text_cols = [c for c in text_cols if c and c in cols]
    if not usable_text_cols:
        return []

    where = " OR ".join([f"LOWER({c}) LIKE LOWER(?)" for c in usable_text_cols])
    select_cols = [c for c in [id_col, title_col] if c]
    # include one best snippet col (first text col)
    if usable_text_cols and usable_text_cols[0] not in select_cols:
        select_cols.append(usable_text_cols[0])
    if not select_cols:
        select_cols = usable_text_cols[:1]

    sql = f"SELECT {', '.join(select_cols)} FROM {table} WHERE {where} LIMIT {int(limit)}"
    rows = _safe_execute_fetch(conn, sql, params=[_safe_like(term)] * len(usable_text_cols))

    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "type": entity_type,
                "id": r.get(id_col) if id_col else None,
                "title": r.get(title_col) if title_col else None,
                "snippet": r.get(usable_text_cols[0]) if usable_text_cols else "",
            }
        )
    return out


def _similar_pains(pains: List[Dict[str, Any]], target_idx: int, top_k: int = 5) -> List[Dict[str, Any]]:
    """Compute similar pains by token overlap; returns list of {pain_id, title, score}."""
    if target_idx < 0 or target_idx >= len(pains):
        return []
    tgt = pains[target_idx]
    tgt_tokens = _tokenize((_coalesce_text(tgt, ["title", "Pain_Name", "name"]) + " " + _coalesce_text(tgt, ["description", "Description", "details"])).strip())

    scored: List[Tuple[int, float]] = []
    for i, p in enumerate(pains):
        if i == target_idx:
            continue
        p_tokens = _tokenize((_coalesce_text(p, ["title", "Pain_Name", "name"]) + " " + _coalesce_text(p, ["description", "Description", "details"])).strip())
        sim = _jaccard(tgt_tokens, p_tokens)
        if sim > 0:
            scored.append((i, sim))
    scored.sort(key=lambda x: x[1], reverse=True)
    out: List[Dict[str, Any]] = []
    for i, s in scored[:top_k]:
        out.append(
            {
                "pain_id": pains[i].get("pain_id") or pains[i].get("Pain_ID") or pains[i].get("id"),
                "title": pains[i].get("title") or pains[i].get("Pain_Name") or pains[i].get("name"),
                "score": round(float(s), 4),
            }
        )
    return out


# -----------------------------
# Public functions
# -----------------------------


def find_connections(conn: Any, kb_conn: Any, concept: str) -> Dict[str, Any]:
    """
    Find non-obvious connections for a concept across pains, solutions, decisions, and KB context.

    Returns:
    {
      concept,
      direct_matches: [],
      related_concepts: [],
      cross_domain_insights: [],
      connection_map: {},
      success: bool
    }
    """
    try:
        concept = (concept or "").strip()
        direct_matches: List[Dict[str, Any]] = []

        # Pains
        pains = _fetch_pains(conn)
        if pains.get("table"):
            direct_matches.extend(
                _search_entity_table(
                    conn=conn,
                    table=pains["table"],
                    term=concept,
                    id_col=pains.get("id_col"),
                    title_col=pains.get("title_col"),
                    text_cols=[c for c in [pains.get("title_col"), pains.get("desc_col"), pains.get("root_col")] if c],
                    limit=25,
                    entity_type="pain",
                )
            )

        # Solutions
        sols = _fetch_solutions(conn)
        if sols.get("table"):
            direct_matches.extend(
                _search_entity_table(
                    conn=conn,
                    table=sols["table"],
                    term=concept,
                    id_col=sols.get("id_col"),
                    title_col=sols.get("title_col"),
                    text_cols=[c for c in [sols.get("title_col"), sols.get("desc_col")] if c],
                    limit=25,
                    entity_type="solution",
                )
            )

        # Decisions
        decs = _fetch_decisions(conn)
        if decs.get("table"):
            direct_matches.extend(
                _search_entity_table(
                    conn=conn,
                    table=decs["table"],
                    term=concept,
                    id_col=decs.get("id_col"),
                    title_col=decs.get("title_col"),
                    text_cols=[c for c in [decs.get("title_col"), decs.get("context_col"), decs.get("decision_col")] if c],
                    limit=15,
                    entity_type="decision",
                )
            )

        # KB entry log table (if present)
        direct_matches.extend(_fetch_kb_entry_log_matches(conn, concept, limit=25))

        # KB context (via context builder)
        kb_context = _safe_call_context_builder(build_kb_context, kb_conn, concept)

        # LLM synthesis (optional)
        fallback = {
            "related_concepts": [],
            "cross_domain_insights": [
                "LLM unavailable or returned non-JSON; showing direct matches + heuristic suggestions."
            ]
            if concept
            else [],
            "connection_map": {
                "bridges": [],
                "themes": [],
                "next_queries": [concept] if concept else [],
            },
        }

        prompt = (
            "You are aeOS Agent Graph (GraphRAG traversal). "
            "Given a concept and direct matches from an SQLite-based knowledge system plus KB context, "
            "infer non-obvious relationships across domains (pain→solution→prediction→decision→mental model). "
            "Return STRICT JSON only.\n\n"
            "JSON schema:\n"
            "{\n"
            '  "related_concepts": [string],\n'
            '  "cross_domain_insights": [string],\n'
            '  "connection_map": {\n'
            '     "bridges": [{"from_type":string,"from_id":string,"to_type":string,"to_id":string,"reason":string}],\n'
            '     "themes": [string],\n'
            '     "next_queries": [string]\n'
            "  }\n"
            "}\n\n"
            f"CONCEPT: {concept}\n\n"
            f"DIRECT_MATCHES (JSON): {json.dumps(direct_matches[:60], ensure_ascii=False)}\n\n"
            f"KB_CONTEXT (may be empty):\n{kb_context[:4000]}\n"
        )

        llm = _safe_infer_json(prompt, fallback)
        related_concepts = llm.get("related_concepts") if isinstance(llm.get("related_concepts"), list) else []
        cross_domain_insights = (
            llm.get("cross_domain_insights") if isinstance(llm.get("cross_domain_insights"), list) else []
        )
        connection_map = llm.get("connection_map") if isinstance(llm.get("connection_map"), dict) else {}

        # If nothing found, still provide minimal guidance
        if not direct_matches and not related_concepts and concept:
            cross_domain_insights = cross_domain_insights or [
                "No direct matches found. Try a narrower synonym, a metric, or a concrete symptom (e.g., 'pipeline conversion', 'lead follow-up')."
            ]
            connection_map = connection_map or {"bridges": [], "themes": [], "next_queries": [concept]}

        return {
            "concept": concept,
            "direct_matches": direct_matches,
            "related_concepts": related_concepts,
            "cross_domain_insights": cross_domain_insights,
            "connection_map": connection_map,
            "success": True,
        }
    except Exception as e:
        return _safe_error(e)


def build_entity_graph(conn: Any) -> Dict[str, Any]:
    """
    Build an adjacency graph from pains to linked solutions/predictions and heuristic related pains.
    Uses LLM to identify thematic clusters when available.

    Returns:
    {nodes: int, edges: int, clusters: [], graph: {}, success: bool}
    """
    try:
        pains_blob = _fetch_pains(conn)
        sols_blob = _fetch_solutions(conn)
        preds_blob = _fetch_predictions(conn)

        pain_rows = pains_blob.get("rows") or []
        sol_rows = sols_blob.get("rows") or []
        pred_rows = preds_blob.get("rows") or []

        pain_id_col = pains_blob.get("id_col")
        pain_title_col = pains_blob.get("title_col")
        pain_desc_col = pains_blob.get("desc_col")
        pain_root_col = pains_blob.get("root_col")

        sol_id_col = sols_blob.get("id_col")
        sol_fk_col = sols_blob.get("pain_fk_col")
        sol_title_col = sols_blob.get("title_col")

        pred_id_col = preds_blob.get("id_col")
        pred_pain_fk = preds_blob.get("pain_fk_col")
        pred_text_col = preds_blob.get("text_col")

        # Build pain list (normalized)
        pains_norm: List[Dict[str, Any]] = []
        for r in pain_rows:
            pains_norm.append(
                {
                    "pain_id": r.get(pain_id_col) if pain_id_col else r.get("id"),
                    "title": r.get(pain_title_col) if pain_title_col else r.get("title"),
                    "description": r.get(pain_desc_col) if pain_desc_col else r.get("description"),
                    "root_cause": r.get(pain_root_col) if pain_root_col else r.get("Root_Cause"),
                }
            )

        # Group solutions by pain
        sols_by_pain: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
        for s in sol_rows:
            pid = s.get(sol_fk_col) if sol_fk_col else None
            sols_by_pain[pid].append(
                {
                    "solution_id": s.get(sol_id_col) if sol_id_col else s.get("id"),
                    "title": s.get(sol_title_col) if sol_title_col else s.get("title"),
                }
            )

        # Group predictions by pain (direct fk if available)
        preds_by_pain: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
        if pred_pain_fk:
            for p in pred_rows:
                pid = p.get(pred_pain_fk)
                preds_by_pain[pid].append(
                    {
                        "pred_id": p.get(pred_id_col) if pred_id_col else p.get("id"),
                        "statement": p.get(pred_text_col) if pred_text_col else p.get("statement"),
                    }
                )

        # Build related pains (heuristic similarity)
        related_by_pain: Dict[Any, List[Any]] = defaultdict(list)
        for idx, p in enumerate(pains_norm):
            sims = _similar_pains(pains_norm, idx, top_k=5)
            related_by_pain[p.get("pain_id")] = [x.get("pain_id") for x in sims if x.get("pain_id")]

        # Assemble graph adjacency
        graph: Dict[Any, Dict[str, Any]] = {}
        for p in pains_norm:
            pid = p.get("pain_id")
            graph[pid] = {
                "solutions": sols_by_pain.get(pid, []),
                "predictions": preds_by_pain.get(pid, []),
                "related_pains": related_by_pain.get(pid, []),
            }

        # Count nodes/edges
        pain_nodes = {p.get("pain_id") for p in pains_norm if p.get("pain_id") is not None}
        sol_nodes = {s.get("solution_id") for lst in sols_by_pain.values() for s in lst if s.get("solution_id") is not None}
        pred_nodes = {p.get("pred_id") for lst in preds_by_pain.values() for p in lst if p.get("pred_id") is not None}

        nodes = len(pain_nodes) + len(sol_nodes) + len(pred_nodes)

        edges = 0
        for pid, adj in graph.items():
            edges += len(adj.get("solutions", []))
            edges += len(adj.get("predictions", []))
            edges += len(adj.get("related_pains", []))

        # LLM clusters (optional)
        pains_for_prompt = [
            {
                "pain_id": p.get("pain_id"),
                "title": p.get("title"),
                "root_cause": p.get("root_cause"),
                "description": (p.get("description") or "")[:220],
                "solution_titles": [s.get("title") for s in graph.get(p.get("pain_id"), {}).get("solutions", [])][:6],
            }
            for p in pains_norm[:80]
        ]

        fallback_clusters: List[Dict[str, Any]] = []
        if pains_for_prompt:
            # Heuristic cluster fallback: group by top keyword
            buckets: Dict[str, List[Any]] = defaultdict(list)
            for p in pains_for_prompt:
                toks = _tokenize((p.get("title") or "") + " " + (p.get("root_cause") or "") + " " + (p.get("description") or ""))
                key = toks[0] if toks else "misc"
                buckets[key].append(p.get("pain_id"))
            # Keep top few buckets
            for k, v in sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True)[:8]:
                fallback_clusters.append({"theme": k, "pain_ids": [x for x in v if x is not None], "rationale": "heuristic keyword bucket"})

        prompt = (
            "You are aeOS Agent Graph. Identify thematic clusters across pain points.\n"
            "Return STRICT JSON only.\n\n"
            "Schema:\n"
            '{ "clusters": [{"theme": string, "pain_ids": [string], "rationale": string}] }\n\n'
            f"PAINS (JSON): {json.dumps(pains_for_prompt, ensure_ascii=False)}\n"
        )
        llm = _safe_infer_json(prompt, {"clusters": fallback_clusters})
        clusters = llm.get("clusters") if isinstance(llm.get("clusters"), list) else fallback_clusters

        return {
            "nodes": int(nodes),
            "edges": int(edges),
            "clusters": clusters,
            "graph": graph,
            "success": True,
        }
    except Exception as e:
        return _safe_error(e)


def traverse_from_pain(conn: Any, kb_conn: Any, pain_id: int) -> Dict[str, Any]:
    """
    Traverse outward from a pain:
    - linked solutions
    - related predictions
    - KB mental models (via KB context + optional Mental_Models_Registry)
    - similar pains
    - one synthesized insight string

    Returns:
    {pain_id, solutions: [], predictions: [], mental_models: [], similar_pains: [], insight: str, success: bool}
    """
    try:
        # Fetch all pains (so we can compute similarity)
        pains_blob = _fetch_pains(conn)
        pain_rows = pains_blob.get("rows") or []
        pain_id_col = pains_blob.get("id_col")
        pain_title_col = pains_blob.get("title_col")
        pain_desc_col = pains_blob.get("desc_col")
        pain_root_col = pains_blob.get("root_col")

        pains_norm: List[Dict[str, Any]] = []
        target_idx = -1
        for idx, r in enumerate(pain_rows):
            pid = r.get(pain_id_col) if pain_id_col else r.get("id")
            item = {
                "pain_id": pid,
                "title": r.get(pain_title_col) if pain_title_col else r.get("title"),
                "description": r.get(pain_desc_col) if pain_desc_col else r.get("description"),
                "root_cause": r.get(pain_root_col) if pain_root_col else r.get("Root_Cause"),
            }
            pains_norm.append(item)
            if str(pid) == str(pain_id):
                target_idx = idx

        target_pain = pains_norm[target_idx] if target_idx >= 0 else {}

        # Linked solutions
        sols_blob = _fetch_solutions(conn)
        sol_rows = sols_blob.get("rows") or []
        sol_fk = sols_blob.get("pain_fk_col")
        sol_id = sols_blob.get("id_col")
        sol_title = sols_blob.get("title_col")
        solutions: List[Dict[str, Any]] = []
        if sol_fk:
            for s in sol_rows:
                if str(s.get(sol_fk)) == str(pain_id):
                    solutions.append(
                        {
                            "solution_id": s.get(sol_id) if sol_id else s.get("id"),
                            "title": s.get(sol_title) if sol_title else s.get("title"),
                        }
                    )

        # Related predictions
        preds_blob = _fetch_predictions(conn)
        pred_rows = preds_blob.get("rows") or []
        pred_pain_fk = preds_blob.get("pain_fk_col")
        pred_id = preds_blob.get("id_col")
        pred_text = preds_blob.get("text_col")
        predictions: List[Dict[str, Any]] = []
        if pred_pain_fk:
            for p in pred_rows:
                if str(p.get(pred_pain_fk)) == str(pain_id):
                    predictions.append(
                        {
                            "pred_id": p.get(pred_id) if pred_id else p.get("id"),
                            "statement": p.get(pred_text) if pred_text else p.get("statement"),
                        }
                    )

        # Similar pains (heuristic)
        similar_pains = _similar_pains(pains_norm, target_idx, top_k=6) if target_idx >= 0 else []

        # KB context -> mental models (LLM extract)
        pain_name = (target_pain.get("title") or str(pain_id) or "").strip()
        kb_context = _safe_call_context_builder(build_kb_context, kb_conn, pain_name)

        # Optional: Mental_Models_Registry (if present)
        mm_table = _resolve_table(conn, ["Mental_Models_Registry", "MentalModels", "mental_models_registry"])
        mm_rows: List[Dict[str, Any]] = []
        if mm_table:
            mm_cols = _get_columns(conn, mm_table)
            mm_id_col = _resolve_col(mm_cols, ["Model_ID", "model_id", "id"])
            mm_name_col = _resolve_col(mm_cols, ["Model_Name", "model_name", "name", "title"])
            mm_desc_col = _resolve_col(mm_cols, ["Description", "description", "summary"])
            # Pull a small subset for LLM grounding
            sel = [c for c in [mm_id_col, mm_name_col, mm_desc_col] if c]
            if sel:
                mm_rows = _safe_execute_fetch(conn, f"SELECT {', '.join(sel)} FROM {mm_table} LIMIT 60")
                # normalize keys
                normed = []
                for r in mm_rows:
                    normed.append(
                        {
                            "model_id": r.get(mm_id_col) if mm_id_col else r.get("id"),
                            "name": r.get(mm_name_col) if mm_name_col else r.get("name"),
                            "description": (r.get(mm_desc_col) if mm_desc_col else "") or "",
                        }
                    )
                mm_rows = normed

        mm_fallback = {"mental_models": [], "insight": ""}
        mm_prompt = (
            "You are aeOS Agent Graph. Extract the most relevant mental models for a pain.\n"
            "Return STRICT JSON only.\n\n"
            'Schema: { "mental_models": [string], "insight": string }\n\n'
            f"PAIN: {json.dumps(target_pain, ensure_ascii=False)}\n\n"
            f"SOLUTIONS: {json.dumps(solutions[:12], ensure_ascii=False)}\n\n"
            f"PREDICTIONS: {json.dumps(predictions[:12], ensure_ascii=False)}\n\n"
            f"SIMILAR_PAINS: {json.dumps(similar_pains[:8], ensure_ascii=False)}\n\n"
            f"MENTAL_MODELS_REGISTRY_SAMPLE (optional): {json.dumps(mm_rows[:60], ensure_ascii=False)}\n\n"
            f"KB_CONTEXT (optional):\n{kb_context[:4000]}\n"
        )
        mm_llm = _safe_infer_json(mm_prompt, mm_fallback)
        mental_models = mm_llm.get("mental_models") if isinstance(mm_llm.get("mental_models"), list) else []
        insight = mm_llm.get("insight") if isinstance(mm_llm.get("insight"), str) else ""

        if not insight:
            # Fallback insight via infer (text)
            pain_context = _safe_call_context_builder(build_pain_context, conn, pain_id)
            insight_prompt = (
                "You are aeOS Agent Graph. Provide one concise insight (1-3 sentences) connecting pain → solution(s) → prediction(s) → mental model(s).\n\n"
                f"PAIN_CONTEXT:\n{pain_context[:1800]}\n\n"
                f"SOLUTIONS: {json.dumps([s.get('title') for s in solutions], ensure_ascii=False)}\n"
                f"PREDICTIONS: {json.dumps([p.get('statement') for p in predictions], ensure_ascii=False)}\n"
                f"MENTAL_MODELS: {json.dumps(mental_models, ensure_ascii=False)}\n"
            )
            insight = _safe_infer_text(insight_prompt, fallback="")

        if not target_pain and not solutions and not predictions:
            insight = insight or "Pain not found (or no linked records)."

        return {
            "pain_id": pain_id,
            "solutions": solutions,
            "predictions": predictions,
            "mental_models": mental_models,
            "similar_pains": similar_pains,
            "insight": insight,
            "success": True,
        }
    except Exception as e:
        return _safe_error(e)


def find_root_causes_across_portfolio(conn: Any, kb_conn: Any) -> Dict[str, Any]:
    """
    Look across all pain points for shared root causes and group by theme using LLM (with heuristics fallback).

    Returns:
    {root_cause_clusters: [{theme, pains: [], frequency, insight}], success: bool}
    """
    try:
        pains_blob = _fetch_pains(conn)
        pain_rows = pains_blob.get("rows") or []
        pain_id_col = pains_blob.get("id_col")
        title_col = pains_blob.get("title_col")
        desc_col = pains_blob.get("desc_col")
        root_col = pains_blob.get("root_col")

        pains = []
        for r in pain_rows[:200]:
            pains.append(
                {
                    "pain_id": r.get(pain_id_col) if pain_id_col else r.get("id"),
                    "title": r.get(title_col) if title_col else r.get("title"),
                    "root_cause": r.get(root_col) if root_col else r.get("Root_Cause"),
                    "description": (r.get(desc_col) if desc_col else r.get("description") or "")[:220],
                }
            )

        # Heuristic fallback: group by root_cause if present else first keyword
        buckets: Dict[str, List[Any]] = defaultdict(list)
        for p in pains:
            rc = (p.get("root_cause") or "").strip()
            if rc:
                key = rc.lower()
            else:
                toks = _tokenize((p.get("title") or "") + " " + (p.get("description") or ""))
                key = toks[0] if toks else "misc"
            buckets[key].append(p.get("pain_id"))

        fallback_clusters = []
        for theme, ids in sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True)[:12]:
            ids_clean = [x for x in ids if x is not None]
            fallback_clusters.append(
                {
                    "theme": theme,
                    "pains": ids_clean,
                    "frequency": int(len(ids_clean)),
                    "insight": "heuristic cluster (no LLM or root_cause field used)",
                }
            )

        # KB context can help the LLM name themes better
        kb_context = _safe_call_context_builder(build_kb_context, kb_conn, "root causes across portfolio")

        prompt = (
            "You are aeOS Agent Graph. Group pains by underlying root-cause themes (shared drivers).\n"
            "Return STRICT JSON only.\n\n"
            'Schema: { "root_cause_clusters": [{"theme": string, "pains": [string], "frequency": number, "insight": string}] }\n\n'
            f"PAINS (JSON): {json.dumps(pains, ensure_ascii=False)}\n\n"
            f"KB_CONTEXT (optional):\n{kb_context[:2500]}\n"
        )

        llm = _safe_infer_json(prompt, {"root_cause_clusters": fallback_clusters})
        clusters = llm.get("root_cause_clusters") if isinstance(llm.get("root_cause_clusters"), list) else fallback_clusters

        # Ensure frequency present
        normalized = []
        for c in clusters:
            if not isinstance(c, dict):
                continue
            pains_list = c.get("pains") if isinstance(c.get("pains"), list) else []
            freq = c.get("frequency")
            if not isinstance(freq, (int, float)):
                freq = len(pains_list)
            normalized.append(
                {
                    "theme": c.get("theme") if isinstance(c.get("theme"), str) else "unknown",
                    "pains": pains_list,
                    "frequency": int(freq),
                    "insight": c.get("insight") if isinstance(c.get("insight"), str) else "",
                }
            )

        return {"root_cause_clusters": normalized, "success": True}
    except Exception as e:
        return _safe_error(e)


def suggest_leverage_points(conn: Any, kb_conn: Any) -> Dict[str, Any]:
    """
    Identify single actions likely to resolve multiple pains by finding repeated/overlapping solutions across pains.

    Returns:
    {leverage_points: [{action, resolves_pains: [], impact_score, rationale}], success: bool}
    """
    try:
        pains_blob = _fetch_pains(conn)
        sols_blob = _fetch_solutions(conn)

        pain_rows = pains_blob.get("rows") or []
        sol_rows = sols_blob.get("rows") or []

        pain_id_col = pains_blob.get("id_col")
        pain_title_col = pains_blob.get("title_col")
        pain_desc_col = pains_blob.get("desc_col")

        sol_fk = sols_blob.get("pain_fk_col")
        sol_title = sols_blob.get("title_col")

        # Map pain_id -> pain info
        pain_info: Dict[str, Dict[str, Any]] = {}
        for p in pain_rows:
            pid = p.get(pain_id_col) if pain_id_col else p.get("id")
            if pid is None:
                continue
            pain_info[str(pid)] = {
                "pain_id": pid,
                "title": p.get(pain_title_col) if pain_title_col else p.get("title"),
                "description": (p.get(pain_desc_col) if pain_desc_col else p.get("description") or "")[:180],
            }

        # Group solutions by normalized action title
        groups: Dict[str, Dict[str, Any]] = {}
        for s in sol_rows:
            pid = s.get(sol_fk) if sol_fk else None
            title = s.get(sol_title) if sol_title else s.get("title")
            if not isinstance(title, str) or not title.strip():
                continue
            key = _normalize_action_title(title)
            if not key:
                continue
            if key not in groups:
                groups[key] = {"action": title.strip(), "pain_ids": set()}
            if pid is not None:
                groups[key]["pain_ids"].add(str(pid))

        # Candidate actions resolving 2+ pains
        candidates = []
        for g in groups.values():
            pain_ids = sorted(list(g["pain_ids"]))
            if len(pain_ids) >= 2:
                candidates.append(
                    {
                        "action": g["action"],
                        "resolves_pains": [pain_info.get(pid, {"pain_id": pid}).get("pain_id") for pid in pain_ids],
                        "pain_titles": [pain_info.get(pid, {}).get("title") for pid in pain_ids if pid in pain_info][:8],
                        "coverage": len(pain_ids),
                    }
                )

        # Rank heuristic (coverage desc)
        candidates.sort(key=lambda x: int(x.get("coverage", 0)), reverse=True)
        candidates = candidates[:40]

        # KB context for better rationale
        kb_context = _safe_call_context_builder(build_kb_context, kb_conn, "leverage points actions that resolve multiple pains")

        fallback_points = []
        for c in candidates[:10]:
            impact_score = min(100, 30 + int(c.get("coverage", 0)) * 15)
            fallback_points.append(
                {
                    "action": c.get("action"),
                    "resolves_pains": c.get("resolves_pains", []),
                    "impact_score": impact_score,
                    "rationale": "Heuristic: repeated solution across multiple pains (higher coverage = higher leverage).",
                }
            )

        prompt = (
            "You are aeOS Agent Graph. Identify the highest-leverage single actions that resolve multiple pains.\n"
            "Return STRICT JSON only.\n\n"
            'Schema: { "leverage_points": [{"action": string, "resolves_pains": [string], "impact_score": number, "rationale": string}] }\n\n'
            f"CANDIDATE_ACTIONS (JSON): {json.dumps(candidates, ensure_ascii=False)}\n\n"
            f"KB_CONTEXT (optional):\n{kb_context[:2500]}\n"
        )

        llm = _safe_infer_json(prompt, {"leverage_points": fallback_points})
        points = llm.get("leverage_points") if isinstance(llm.get("leverage_points"), list) else fallback_points

        normalized = []
        for p in points:
            if not isinstance(p, dict):
                continue
            impact = p.get("impact_score")
            if not isinstance(impact, (int, float)):
                impact = 50
            normalized.append(
                {
                    "action": p.get("action") if isinstance(p.get("action"), str) else "",
                    "resolves_pains": p.get("resolves_pains") if isinstance(p.get("resolves_pains"), list) else [],
                    "impact_score": int(max(0, min(100, impact))),
                    "rationale": p.get("rationale") if isinstance(p.get("rationale"), str) else "",
                }
            )

        return {"leverage_points": normalized, "success": True}
    except Exception as e:
        return _safe_error(e)


def find_root_causes_across_portfolio(conn: Any, kb_conn: Any) -> Dict[str, Any]:
    """
    Look across all pain points for shared root causes and group by theme using LLM (with heuristics fallback).

    Returns:
    {root_cause_clusters: [{theme, pains: [], frequency, insight}], success: bool}
    """
    try:
        pains_blob = _fetch_pains(conn)
        pain_rows = pains_blob.get("rows") or []
        pain_id_col = pains_blob.get("id_col")
        title_col = pains_blob.get("title_col")
        desc_col = pains_blob.get("desc_col")
        root_col = pains_blob.get("root_col")

        pains = []
        for r in pain_rows[:200]:
            pains.append(
                {
                    "pain_id": r.get(pain_id_col) if pain_id_col else r.get("id"),
                    "title": r.get(title_col) if title_col else r.get("title"),
                    "root_cause": r.get(root_col) if root_col else r.get("Root_Cause"),
                    "description": (r.get(desc_col) if desc_col else r.get("description") or "")[:220],
                }
            )

        # Heuristic fallback: group by root_cause if present else first keyword
        buckets: Dict[str, List[Any]] = defaultdict(list)
        for p in pains:
            rc = (p.get("root_cause") or "").strip()
            if rc:
                key = rc.lower()
            else:
                toks = _tokenize((p.get("title") or "") + " " + (p.get("description") or ""))
                key = toks[0] if toks else "misc"
            buckets[key].append(p.get("pain_id"))

        fallback_clusters = []
        for theme, ids in sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True)[:12]:
            ids_clean = [x for x in ids if x is not None]
            fallback_clusters.append(
                {
                    "theme": theme,
                    "pains": ids_clean,
                    "frequency": int(len(ids_clean)),
                    "insight": "heuristic cluster (no LLM or root_cause field used)",
                }
            )

        kb_context = _safe_call_context_builder(build_kb_context, kb_conn, "root causes across portfolio")

        prompt = (
            "You are aeOS Agent Graph. Group pains by underlying root-cause themes (shared drivers).\n"
            "Return STRICT JSON only.\n\n"
            'Schema: { "root_cause_clusters": [{"theme": string, "pains": [string], "frequency": number, "insight": string}] }\n\n'
            f"PAINS (JSON): {json.dumps(pains, ensure_ascii=False)}\n\n"
            f"KB_CONTEXT (optional):\n{kb_context[:2500]}\n"
        )

        llm = _safe_infer_json(prompt, {"root_cause_clusters": fallback_clusters})
        clusters = llm.get("root_cause_clusters") if isinstance(llm.get("root_cause_clusters"), list) else fallback_clusters

        normalized = []
        for c in clusters:
            if not isinstance(c, dict):
                continue
            pains_list = c.get("pains") if isinstance(c.get("pains"), list) else []
            freq = c.get("frequency")
            if not isinstance(freq, (int, float)):
                freq = len(pains_list)
            normalized.append(
                {
                    "theme": c.get("theme") if isinstance(c.get("theme"), str) else "unknown",
                    "pains": pains_list,
                    "frequency": int(freq),
                    "insight": c.get("insight") if isinstance(c.get("insight"), str) else "",
                }
            )

        return {"root_cause_clusters": normalized, "success": True}
    except Exception as e:
        return _safe_error(e)


# NOTE: Kept last line as required by project standard.
# S✅ T✅ L✅ A✅