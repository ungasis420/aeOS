"""
aeOS Phase 5 — agent_synthesis.py

Autonomous Knowledge Base synthesis agent.
Reads across KB + DB, identifies emerging themes, produces synthesis documents,
and surfaces non-obvious cross-domain insights.

Design goals:
- Works with SQLite + ChromaDB (or mocked equivalents in tests).
- Uses LLM via infer/infer_json when available; degrades gracefully offline.
- Never crashes: all public functions wrap logic in try/except and return dicts.

"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from src.ai.ai_infer import infer, infer_json
from src.ai.ai_context import build_kb_context, build_portfolio_context


# -----------------------------
# Helpers (internal)
# -----------------------------


def _now_utc() -> datetime:
    """Return current UTC time (naive datetime)."""
    return datetime.utcnow()


def _iso(dt: datetime) -> str:
    """ISO format helper."""
    return dt.replace(microsecond=0).isoformat()


def _safe_str(x: Any) -> str:
    """Best-effort stringify without throwing."""
    try:
        if x is None:
            return ""
        return str(x)
    except Exception:
        return ""


def _truncate(text: str, max_chars: int = 600) -> str:
    """Truncate text for prompts/logging."""
    if not isinstance(text, str):
        text = _safe_str(text)
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _safe_json_loads(s: str) -> Optional[Any]:
    """Parse JSON safely; return None if invalid."""
    try:
        return json.loads(s)
    except Exception:
        return None


def _unwrap_infer_payload(result: Any) -> Tuple[bool, Optional[Any], str]:
    """
    Normalize infer/infer_json outputs.

    Returns: (ok, payload, error_message)
    - ok True means payload is usable (dict/list/str->json).
    """
    try:
        if result is None:
            return False, None, "infer returned None"

        # Common wrapper: {"success": True, "response": ...}
        if isinstance(result, dict):
            if result.get("success") is False:
                return False, None, _safe_str(result.get("error") or result.get("response") or "infer failed")

            if "response" in result:
                resp = result.get("response")
                if isinstance(resp, (dict, list)):
                    return True, resp, ""
                if isinstance(resp, str):
                    parsed = _safe_json_loads(resp)
                    if parsed is not None:
                        return True, parsed, ""
                    # If not JSON, still return the string (caller may want narrative)
                    return True, resp, ""
                return True, resp, ""

            # Sometimes infer_json may already return the parsed object directly as dict
            return True, result, ""

        # If it's a raw string, try parse JSON
        if isinstance(result, str):
            parsed = _safe_json_loads(result)
            if parsed is not None:
                return True, parsed, ""
            return True, result, ""

        return True, result, ""
    except Exception as e:
        return False, None, f"unwrap error: {_safe_str(e)}"


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """Check if a SQLite table exists."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,))
        return cur.fetchone() is not None
    except Exception:
        return False


def _get_table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    """Return columns for a table (empty list on failure)."""
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        rows = cur.fetchall() or []
        cols = []
        for r in rows:
            # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
            if isinstance(r, (tuple, list)) and len(r) >= 2:
                cols.append(_safe_str(r[1]))
        return cols
    except Exception:
        return []


def _safe_fetchall(conn: sqlite3.Connection, query: str, params: Tuple[Any, ...] = ()) -> List[Tuple[Any, ...]]:
    """Execute query safely; return rows or [] if error."""
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
        if rows is None:
            return []
        if isinstance(rows, list):
            return rows
        # In case a mock returns something non-list
        try:
            return list(rows)
        except Exception:
            return []
    except Exception:
        return []


def _pick_activity_source(
    conn: sqlite3.Connection,
    candidates: List[Tuple[str, List[str]]],
) -> Tuple[Optional[str], Optional[str]]:
    """
    Pick (table, date_column) from candidates by checking existence and column presence.

    candidates: [(table, [possible_date_columns...]), ...]
    """
    try:
        for table, date_cols in candidates:
            if not _table_exists(conn, table):
                continue
            cols = set([c.lower() for c in _get_table_columns(conn, table)])
            for dc in date_cols:
                if dc.lower() in cols:
                    return table, dc
        return None, None
    except Exception:
        return None, None


def _kb_list_collections(kb_conn: Any) -> List[str]:
    """Best-effort list of KB collection names across possible ChromaDB interfaces."""
    try:
        if kb_conn is None:
            return []

        # Dict-like
        if isinstance(kb_conn, dict):
            return [str(k) for k in kb_conn.keys()]

        # Chroma client-like
        if hasattr(kb_conn, "list_collections"):
            cols = kb_conn.list_collections()
            if cols is None:
                return []
            out: List[str] = []
            for c in cols:
                if isinstance(c, str):
                    out.append(c)
                elif hasattr(c, "name"):
                    out.append(_safe_str(getattr(c, "name")))
                elif isinstance(c, dict) and "name" in c:
                    out.append(_safe_str(c.get("name")))
            return [c for c in out if c]

        # If kb_conn itself is a Collection-like object
        if hasattr(kb_conn, "name") and hasattr(kb_conn, "get"):
            name = _safe_str(getattr(kb_conn, "name"))
            return [name] if name else ["default"]

        return []
    except Exception:
        return []


def _kb_get_collection(kb_conn: Any, name: str) -> Any:
    """Best-effort get a collection handle."""
    try:
        if kb_conn is None:
            return None

        if isinstance(kb_conn, dict):
            return kb_conn.get(name)

        if hasattr(kb_conn, "get_collection"):
            return kb_conn.get_collection(name)

        if hasattr(kb_conn, "get_or_create_collection"):
            return kb_conn.get_or_create_collection(name)

        # Maybe kb_conn is already a collection
        if hasattr(kb_conn, "get") and hasattr(kb_conn, "name"):
            if _safe_str(getattr(kb_conn, "name")) == name:
                return kb_conn

        return None
    except Exception:
        return None


def _kb_collection_get_all(coll: Any) -> Dict[str, Any]:
    """
    Best-effort get all docs from a collection.
    Expected keys in return: ids, documents, metadatas (when available).
    """
    try:
        if coll is None or not hasattr(coll, "get"):
            return {"ids": [], "documents": [], "metadatas": []}

        # Try common chroma pattern
        try:
            data = coll.get(include=["documents", "metadatas"])
        except TypeError:
            data = coll.get()
        except Exception:
            # Try with limit/offset if get() requires ids
            try:
                data = coll.get(ids=[])
            except Exception:
                return {"ids": [], "documents": [], "metadatas": []}

        if not isinstance(data, dict):
            return {"ids": [], "documents": [], "metadatas": []}

        ids = data.get("ids") or []
        docs = data.get("documents") or []
        metas = data.get("metadatas") or []

        # Chroma sometimes returns documents as List[List[str]]
        flat_docs: List[str] = []
        if isinstance(docs, list):
            for d in docs:
                if isinstance(d, list):
                    for dd in d:
                        if dd is not None:
                            flat_docs.append(_safe_str(dd))
                else:
                    if d is not None:
                        flat_docs.append(_safe_str(d))
        else:
            flat_docs = [_safe_str(docs)]

        # Ensure metas list aligns loosely (best-effort)
        if not isinstance(metas, list):
            metas = []

        if not isinstance(ids, list):
            try:
                ids = list(ids)
            except Exception:
                ids = []

        return {"ids": ids, "documents": flat_docs, "metadatas": metas}
    except Exception:
        return {"ids": [], "documents": [], "metadatas": []}


def _tokenize(text: str) -> List[str]:
    """Very small tokenizer for offline fallback theme extraction."""
    try:
        if not isinstance(text, str):
            text = _safe_str(text)
        text = text.lower()
        buf = []
        cur = []
        for ch in text:
            if ch.isalnum():
                cur.append(ch)
            else:
                if cur:
                    buf.append("".join(cur))
                    cur = []
        if cur:
            buf.append("".join(cur))
        return buf
    except Exception:
        return []


_STOPWORDS = {
    "the", "and", "or", "to", "of", "in", "a", "is", "it", "that", "this", "for", "on", "with", "as",
    "are", "be", "was", "were", "by", "from", "at", "an", "not", "but", "we", "you", "i", "they",
    "their", "our", "your", "can", "could", "should", "would", "will", "may", "might", "into", "over",
    "more", "most", "less", "very", "than", "then", "so", "if", "when", "what", "how", "why", "who",
    "which", "also", "just", "about", "because", "been", "being", "do", "does", "did", "done",
}


def _offline_themes_from_docs(docs: List[str], top_n: int = 5) -> List[Dict[str, Any]]:
    """
    Offline fallback: simple keyword frequency themes.
    Returns list of {theme, evidence, strength}.
    """
    try:
        if not docs:
            return []

        counts: Dict[str, int] = {}
        doc_hits: Dict[str, List[int]] = {}
        total = 0

        for idx, d in enumerate(docs):
            toks = _tokenize(d)
            seen_in_doc = set()
            for t in toks:
                if len(t) < 3 or t in _STOPWORDS:
                    continue
                total += 1
                counts[t] = counts.get(t, 0) + 1
                if t not in seen_in_doc:
                    doc_hits.setdefault(t, []).append(idx)
                    seen_in_doc.add(t)

        if not counts:
            return []

        top_terms = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[: max(10, top_n * 2)]
        themes: List[Dict[str, Any]] = []

        used = set()
        for term, cnt in top_terms:
            if term in used:
                continue
            used.add(term)
            strength = float(cnt) / float(max(total, 1))
            evidence: List[str] = []
            for doc_idx in (doc_hits.get(term) or [])[:3]:
                evidence.append(_truncate(docs[doc_idx], 240))
            themes.append({"theme": term, "evidence": evidence, "strength": round(strength, 4)})
            if len(themes) >= top_n:
                break

        return themes
    except Exception:
        return []


def _categorize_collection(name: str) -> str:
    """Heuristic domain classifier for cross-domain synthesis."""
    n = (name or "").lower()
    business_kw = ("biz", "business", "work", "client", "consult", "career", "sales", "marketing", "product", "startup", "agency")
    personal_kw = ("personal", "life", "health", "fitness", "relationship", "family", "journal", "therapy", "mind", "habit")
    if any(k in n for k in business_kw):
        return "business"
    if any(k in n for k in personal_kw):
        return "personal"
    return "unknown"


# -----------------------------
# Public API
# -----------------------------


def synthesize_kb(kb_conn: Any, collection: str = None) -> dict:
    """
    Read KB documents (all collections or a specific one) and produce top themes + synthesis.

    Returns:
      {
        collections_scanned: int,
        documents_processed: int,
        themes: [{theme, evidence: [], strength}],
        synthesis: str,
        success: bool
      }
    """
    try:
        collections = [collection] if collection else _kb_list_collections(kb_conn)
        if not collections:
            # If kb_conn itself looks like a collection, synthesize from it
            if hasattr(kb_conn, "get") and hasattr(kb_conn, "name"):
                collections = [_safe_str(getattr(kb_conn, "name") or "default")]

        all_docs: List[str] = []
        all_ids: List[str] = []
        collections_scanned = 0

        for col_name in collections:
            coll = _kb_get_collection(kb_conn, col_name) if collection is None or col_name == collection else _kb_get_collection(kb_conn, col_name)
            data = _kb_collection_get_all(coll)
            docs = data.get("documents") or []
            ids = data.get("ids") or []
            if docs:
                all_docs.extend([d for d in docs if d])
            if ids:
                all_ids.extend([_safe_str(i) for i in ids if i is not None])
            collections_scanned += 1

        documents_processed = len(all_docs)

        if documents_processed == 0:
            return {
                "collections_scanned": collections_scanned,
                "documents_processed": 0,
                "themes": [],
                "synthesis": "No KB documents found to synthesize.",
                "success": True,
            }

        # Build KB context (best-effort)
        kb_context = ""
        try:
            # build_kb_context signature may vary; keep it defensive
            kb_context = build_kb_context(kb_conn, collection=collection)  # type: ignore[arg-type]
            if isinstance(kb_context, dict):
                kb_context = _safe_str(kb_context.get("context") or kb_context.get("kb_context") or "")
            kb_context = _truncate(kb_context, 4000)
        except Exception:
            kb_context = ""

        # Sample docs for prompt (avoid giant prompts)
        sample_docs = all_docs[: min(30, len(all_docs))]
        sample_blob = "\n\n---\n\n".join([_truncate(d, 600) for d in sample_docs])

        prompt = (
            "You are aeOS Synthesis Agent.\n"
            "Task: Identify the TOP 5 themes across the provided KB excerpts.\n"
            "Return STRICT JSON with this schema:\n"
            "{\n"
            '  "themes": [ {"theme": "string", "strength": 0.0, "evidence": ["string", "..."]} ],\n'
            '  "synthesis": "string"\n'
            "}\n"
            "Rules:\n"
            "- Exactly 5 themes if possible.\n"
            "- strength is 0.0 to 1.0.\n"
            "- evidence items should be short excerpts (<= 200 chars).\n"
            "- synthesis should be ~200-400 words, actionable and concrete.\n\n"
            f"KB_CONTEXT (optional):\n{kb_context}\n\n"
            f"KB_EXCERPTS:\n{sample_blob}\n"
        )

        themes: List[Dict[str, Any]] = []
        synthesis_text: str = ""

        # LLM path (preferred)
        llm_ok = False
        try:
            llm_res = infer_json(prompt)
            ok, payload, err = _unwrap_infer_payload(llm_res)
            if ok and isinstance(payload, dict) and "themes" in payload:
                raw_themes = payload.get("themes") or []
                if isinstance(raw_themes, list):
                    for t in raw_themes[:5]:
                        if isinstance(t, dict):
                            themes.append(
                                {
                                    "theme": _safe_str(t.get("theme")),
                                    "evidence": list(t.get("evidence") or []) if isinstance(t.get("evidence"), list) else [],
                                    "strength": t.get("strength"),
                                }
                            )
                synthesis_text = _safe_str(payload.get("synthesis"))
                llm_ok = True
        except Exception:
            llm_ok = False

        # Offline fallback
        if not llm_ok:
            themes = _offline_themes_from_docs(all_docs, top_n=5)
            synthesis_text = (
                "Offline synthesis (LLM unavailable). "
                "Themes were extracted via keyword-frequency across KB documents. "
                "Use these as provisional clusters and refine once the local model is online."
            )

        # Clean/normalize theme list
        normalized: List[Dict[str, Any]] = []
        for t in themes[:5]:
            if not isinstance(t, dict):
                continue
            theme = _safe_str(t.get("theme")).strip()
            if not theme:
                continue
            evidence = t.get("evidence") or []
            if not isinstance(evidence, list):
                evidence = []
            strength = t.get("strength")
            try:
                strength_f = float(strength)
            except Exception:
                strength_f = 0.0
            normalized.append(
                {
                    "theme": theme,
                    "evidence": [_truncate(_safe_str(e), 200) for e in evidence[:4]],
                    "strength": round(max(0.0, min(1.0, strength_f)), 4),
                }
            )

        return {
            "collections_scanned": collections_scanned,
            "documents_processed": documents_processed,
            "themes": normalized,
            "synthesis": synthesis_text.strip() if synthesis_text else "",
            "success": True,
        }

    except Exception as e:
        return {"success": False, "error": f"synthesize_kb failed: {_safe_str(e)}"}


def synthesize_week(conn: sqlite3.Connection, kb_conn: Any) -> dict:
    """
    Weekly synthesis across DB activity (past 7 days) + recent KB ingestions.

    Returns:
      {
        period: str,
        new_pains: int,
        new_solutions: int,
        weekly_insight: str,
        emerging_patterns: [],
        recommended_focus: str,
        success: bool
      }
    """
    try:
        end = _now_utc()
        start = end - timedelta(days=7)
        period = f"{start.date().isoformat()} to {end.date().isoformat()}"
        start_iso = _iso(start)

        # Candidate tables (Phase 4/5 implementation names + Blueprint-style names)
        pain_table, pain_date = _pick_activity_source(
            conn,
            [
                ("Pain_Registry", ["created_at", "createdAt", "date_created", "created"]),
                ("Pain_Point_Register", ["created_at", "Date_Identified", "date_identified", "Last_Updated"]),
            ],
        )
        sol_table, sol_date = _pick_activity_source(
            conn,
            [
                ("Solution_Registry", ["updated_at", "created_at", "date_created", "created"]),
                ("Solution_Design", ["Date_Created", "created_at", "Last_Updated"]),
            ],
        )
        pred_table, pred_date = _pick_activity_source(
            conn,
            [
                ("Prediction_Registry", ["created_at", "date_created", "created", "resolution_date", "Resolution_Date"]),
            ],
        )
        kb_log_table, kb_log_date = _pick_activity_source(
            conn,
            [
                ("KB_Entry_Log", ["created_at", "createdAt", "date_created", "created"]),
            ],
        )

        # Fetch recent activity (best-effort)
        new_pains_rows: List[Tuple[Any, ...]] = []
        new_solutions_rows: List[Tuple[Any, ...]] = []
        new_predictions_rows: List[Tuple[Any, ...]] = []
        kb_recent_rows: List[Tuple[Any, ...]] = []

        if pain_table and pain_date:
            new_pains_rows = _safe_fetchall(
                conn,
                f"SELECT * FROM {pain_table} WHERE {pain_date} >= ? ORDER BY {pain_date} DESC LIMIT 20",
                (start_iso,),
            )

        if sol_table and sol_date:
            new_solutions_rows = _safe_fetchall(
                conn,
                f"SELECT * FROM {sol_table} WHERE {sol_date} >= ? ORDER BY {sol_date} DESC LIMIT 20",
                (start_iso,),
            )

        if pred_table and pred_date:
            new_predictions_rows = _safe_fetchall(
                conn,
                f"SELECT * FROM {pred_table} WHERE {pred_date} >= ? ORDER BY {pred_date} DESC LIMIT 20",
                (start_iso,),
            )

        if kb_log_table and kb_log_date:
            kb_recent_rows = _safe_fetchall(
                conn,
                f"SELECT * FROM {kb_log_table} WHERE {kb_log_date} >= ? ORDER BY {kb_log_date} DESC LIMIT 30",
                (start_iso,),
            )

        new_pains = len(new_pains_rows)
        new_solutions = len(new_solutions_rows)
        new_predictions = len(new_predictions_rows)
        kb_recent = len(kb_recent_rows)

        # Build portfolio context (best-effort)
        portfolio_context = ""
        try:
            pc = build_portfolio_context(conn)  # type: ignore[arg-type]
            if isinstance(pc, dict):
                portfolio_context = _safe_str(pc.get("context") or pc.get("portfolio_context") or "")
            else:
                portfolio_context = _safe_str(pc)
            portfolio_context = _truncate(portfolio_context, 2000)
        except Exception:
            portfolio_context = ""

        # Build small activity summary blob (don’t assume column order)
        def _rows_to_bullets(rows: List[Tuple[Any, ...]], max_items: int = 8) -> str:
            out = []
            for r in rows[:max_items]:
                if isinstance(r, (tuple, list)) and len(r) > 0:
                    # Try to pick a "title-ish" field by scanning for strings
                    title = ""
                    for cell in r:
                        if isinstance(cell, str) and len(cell.strip()) >= 3:
                            title = cell.strip()
                            break
                    if not title:
                        title = " | ".join([_truncate(_safe_str(c), 40) for c in r[:4]])
                    out.append(f"- {title}")
            return "\n".join(out)

        pains_blob = _rows_to_bullets(new_pains_rows)
        sols_blob = _rows_to_bullets(new_solutions_rows)
        preds_blob = _rows_to_bullets(new_predictions_rows)
        kb_blob = _rows_to_bullets(kb_recent_rows)

        prompt = (
            "You are aeOS Weekly Synthesis Agent.\n"
            "Given the last 7 days of DB activity + recent KB ingestions, produce:\n"
            "- weekly_insight (plain English, 150-250 words)\n"
            "- emerging_patterns (3-7 bullet-like strings)\n"
            "- recommended_focus (1 crisp focus statement)\n"
            "Return STRICT JSON:\n"
            "{\n"
            '  "weekly_insight": "string",\n'
            '  "emerging_patterns": ["string", "..."],\n'
            '  "recommended_focus": "string"\n'
            "}\n\n"
            f"PERIOD: {period}\n"
            f"COUNTS: pains={new_pains}, solutions={new_solutions}, predictions={new_predictions}, kb_ingestions={kb_recent}\n\n"
            f"PORTFOLIO_CONTEXT (optional):\n{portfolio_context}\n\n"
            f"NEW_PAINS:\n{pains_blob}\n\n"
            f"NEW_SOLUTIONS:\n{sols_blob}\n\n"
            f"NEW_PREDICTIONS:\n{preds_blob}\n\n"
            f"KB_RECENT_INGESTIONS:\n{kb_blob}\n"
        )

        weekly_insight = ""
        emerging_patterns: List[str] = []
        recommended_focus = ""

        llm_ok = False
        try:
            llm_res = infer_json(prompt)
            ok, payload, _ = _unwrap_infer_payload(llm_res)
            if ok and isinstance(payload, dict):
                weekly_insight = _safe_str(payload.get("weekly_insight"))
                ep = payload.get("emerging_patterns") or []
                if isinstance(ep, list):
                    emerging_patterns = [_safe_str(x) for x in ep][:10]
                recommended_focus = _safe_str(payload.get("recommended_focus"))
                llm_ok = True
        except Exception:
            llm_ok = False

        if not llm_ok:
            weekly_insight = (
                f"Weekly activity summary ({period}): "
                f"{new_pains} new pains, {new_solutions} new solutions, {new_predictions} new predictions, "
                f"{kb_recent} KB ingestions. "
                "LLM synthesis unavailable; treat this as a counts-only checkpoint."
            )
            emerging_patterns = [
                "If new pains > new solutions: backlog pressure may be rising.",
                "If solutions rising: implementation bandwidth may be improving.",
                "If predictions rising: calibration discipline is increasing.",
            ]
            recommended_focus = "Pick 1 high-severity pain and drive it to an executable next step."

        return {
            "period": period,
            "new_pains": new_pains,
            "new_solutions": new_solutions,
            "weekly_insight": weekly_insight.strip(),
            "emerging_patterns": [p for p in emerging_patterns if p][:10],
            "recommended_focus": recommended_focus.strip(),
            "success": True,
        }

    except Exception as e:
        return {"success": False, "error": f"synthesize_week failed: {_safe_str(e)}"}


def cross_domain_synthesis(conn: sqlite3.Connection, kb_conn: Any) -> dict:
    """
    Cross-domain synthesis between business-oriented KB and personal KB.

    Returns:
      {
        domain_pairs: [],
        insights: [{domains, connection, application, confidence}],
        success: bool
      }
    """
    try:
        collections = _kb_list_collections(kb_conn)
        if not collections and hasattr(kb_conn, "get") and hasattr(kb_conn, "name"):
            collections = [_safe_str(getattr(kb_conn, "name") or "default")]

        business_cols = [c for c in collections if _categorize_collection(c) == "business"]
        personal_cols = [c for c in collections if _categorize_collection(c) == "personal"]

        # If we can't classify, do a shallow split: first half "business", second half "personal"
        if not business_cols and not personal_cols and collections:
            mid = max(1, len(collections) // 2)
            business_cols = collections[:mid]
            personal_cols = collections[mid:] if len(collections) > 1 else collections[:]

        domain_pairs: List[List[str]] = []
        for b in business_cols[:5]:
            for p in personal_cols[:5]:
                if b != p:
                    domain_pairs.append([b, p])
        domain_pairs = domain_pairs[:10]

        # Gather doc samples
        biz_docs: List[str] = []
        per_docs: List[str] = []

        for b in business_cols[:3]:
            coll = _kb_get_collection(kb_conn, b)
            data = _kb_collection_get_all(coll)
            biz_docs.extend((data.get("documents") or [])[:5])

        for p in personal_cols[:3]:
            coll = _kb_get_collection(kb_conn, p)
            data = _kb_collection_get_all(coll)
            per_docs.extend((data.get("documents") or [])[:5])

        biz_blob = "\n\n---\n\n".join([_truncate(d, 500) for d in biz_docs if d][:10])
        per_blob = "\n\n---\n\n".join([_truncate(d, 500) for d in per_docs if d][:10])

        prompt = (
            "You are aeOS Cross-Domain Synthesis Agent.\n"
            "Goal: Find non-obvious applications of insights from one domain into the other.\n"
            "Return STRICT JSON:\n"
            "{\n"
            '  "domain_pairs": [["business_collection","personal_collection"], ...],\n'
            '  "insights": [\n'
            '    {"domains": ["A","B"], "connection": "string", "application": "string", "confidence": 0.0}\n'
            "  ]\n"
            "}\n"
            "Rules:\n"
            "- 3 to 8 insights.\n"
            "- confidence is 0.0 to 1.0.\n"
            "- Make applications concrete (what to do differently tomorrow).\n\n"
            f"DOMAIN_PAIRS_CANDIDATE:\n{json.dumps(domain_pairs)}\n\n"
            f"BUSINESS_EXCERPTS:\n{biz_blob}\n\n"
            f"PERSONAL_EXCERPTS:\n{per_blob}\n"
        )

        insights: List[Dict[str, Any]] = []
        llm_ok = False
        try:
            llm_res = infer_json(prompt)
            ok, payload, _ = _unwrap_infer_payload(llm_res)
            if ok and isinstance(payload, dict):
                dp = payload.get("domain_pairs")
                if isinstance(dp, list) and dp:
                    # prefer LLM's pairs if given
                    domain_pairs = dp[:10]  # type: ignore[assignment]
                raw_insights = payload.get("insights") or []
                if isinstance(raw_insights, list):
                    for it in raw_insights[:10]:
                        if not isinstance(it, dict):
                            continue
                        conf = it.get("confidence")
                        try:
                            conf_f = float(conf)
                        except Exception:
                            conf_f = 0.5
                        insights.append(
                            {
                                "domains": it.get("domains") if isinstance(it.get("domains"), list) else [],
                                "connection": _safe_str(it.get("connection")),
                                "application": _safe_str(it.get("application")),
                                "confidence": round(max(0.0, min(1.0, conf_f)), 3),
                            }
                        )
                llm_ok = True
        except Exception:
            llm_ok = False

        if not llm_ok:
            # Offline fallback: overlap keywords between corpora → “possible transfer”
            biz_terms = {}
            per_terms = {}
            for d in biz_docs:
                for t in _tokenize(d):
                    if len(t) >= 4 and t not in _STOPWORDS:
                        biz_terms[t] = biz_terms.get(t, 0) + 1
            for d in per_docs:
                for t in _tokenize(d):
                    if len(t) >= 4 and t not in _STOPWORDS:
                        per_terms[t] = per_terms.get(t, 0) + 1
            overlap = sorted(set(biz_terms.keys()) & set(per_terms.keys()), key=lambda k: biz_terms.get(k, 0) + per_terms.get(k, 0), reverse=True)[:5]
            insights = []
            for kw in overlap[:3]:
                insights.append(
                    {
                        "domains": ["business", "personal"],
                        "connection": f"Shared concept keyword '{kw}' appears in both domains.",
                        "application": f"Create a mini-experiment that applies '{kw}' from personal routines into a business workflow (or vice versa).",
                        "confidence": 0.35,
                    }
                )

        return {"domain_pairs": domain_pairs, "insights": insights[:10], "success": True}

    except Exception as e:
        return {"success": False, "error": f"cross_domain_synthesis failed: {_safe_str(e)}"}


def generate_synthesis_report(conn: sqlite3.Connection, kb_conn: Any) -> dict:
    """
    Master synthesis function:
    - synthesize_kb
    - synthesize_week
    - cross_domain_synthesis
    Then assembles a structured report.

    Returns:
      {report: str, word_count: int, themes: [], patterns: [], recommended_actions: [], success: bool}
    """
    try:
        kb_res = synthesize_kb(kb_conn)
        wk_res = synthesize_week(conn, kb_conn)
        cd_res = cross_domain_synthesis(conn, kb_conn)

        themes = kb_res.get("themes") if isinstance(kb_res, dict) else []
        patterns = wk_res.get("emerging_patterns") if isinstance(wk_res, dict) else []
        insights = cd_res.get("insights") if isinstance(cd_res, dict) else []

        if not isinstance(themes, list):
            themes = []
        if not isinstance(patterns, list):
            patterns = []
        if not isinstance(insights, list):
            insights = []

        # Recommended actions: derive from recommended_focus + top insights
        recommended_actions: List[str] = []
        focus = _safe_str(wk_res.get("recommended_focus") if isinstance(wk_res, dict) else "")
        if focus:
            recommended_actions.append(focus)

        for it in insights[:3]:
            if isinstance(it, dict):
                app = _safe_str(it.get("application"))
                if app:
                    recommended_actions.append(app)

        # Deduplicate actions
        seen = set()
        deduped_actions = []
        for a in recommended_actions:
            key = a.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped_actions.append(a.strip())
        recommended_actions = deduped_actions[:6]

        ts = _iso(_now_utc())
        period = _safe_str(wk_res.get("period") if isinstance(wk_res, dict) else "")

        # Compose report (markdown)
        theme_lines = []
        for t in themes[:5]:
            if not isinstance(t, dict):
                continue
            theme_lines.append(f"- **{_safe_str(t.get('theme'))}** (strength: {_safe_str(t.get('strength'))})")
            ev = t.get("evidence") or []
            if isinstance(ev, list) and ev:
                for e in ev[:2]:
                    theme_lines.append(f"  - { _truncate(_safe_str(e), 180) }")

        insight_lines = []
        for it in insights[:8]:
            if not isinstance(it, dict):
                continue
            domains = it.get("domains") if isinstance(it.get("domains"), list) else []
            domains_s = " ↔ ".join([_safe_str(d) for d in domains if d]) or "cross-domain"
            conf = _safe_str(it.get("confidence"))
            insight_lines.append(f"- **{domains_s}** (conf: {conf}) — {_safe_str(it.get('connection'))}\n  - Apply: {_safe_str(it.get('application'))}")

        report = (
            f"# aeOS Synthesis Report\n\n"
            f"**Generated (UTC):** {ts}\n"
            + (f"**Weekly window:** {period}\n\n" if period else "\n")
            + "## KB Themes\n"
            + ("\n".join(theme_lines) if theme_lines else "- (No themes found)\n")
            + "\n\n"
            + "## Weekly Insight\n"
            + (_safe_str(wk_res.get("weekly_insight")) if isinstance(wk_res, dict) else "(Unavailable)")
            + "\n\n"
            + "## Emerging Patterns\n"
            + ("\n".join([f"- {p}" for p in patterns[:10] if _safe_str(p)]) if patterns else "- (None detected)\n")
            + "\n\n"
            + "## Cross-Domain Insights\n"
            + ("\n".join(insight_lines) if insight_lines else "- (None detected)\n")
            + "\n\n"
            + "## Recommended Actions (next 24–72h)\n"
            + ("\n".join([f"- {a}" for a in recommended_actions]) if recommended_actions else "- Pick one theme and define a single proof step.\n")
            + "\n"
        )

        word_count = len([w for w in report.split() if w.strip()])

        return {
            "report": report,
            "word_count": word_count,
            "themes": themes[:10],
            "patterns": patterns[:15],
            "recommended_actions": recommended_actions,
            "success": True,
        }

    except Exception as e:
        return {"success": False, "error": f"generate_synthesis_report failed: {_safe_str(e)}"}


def save_synthesis(conn: sqlite3.Connection, synthesis_dict: dict) -> dict:
    """
    Persist synthesis report into Synthesis_Log.

    Creates table if not exists:
      CREATE TABLE IF NOT EXISTS Synthesis_Log (
          synthesis_id TEXT PRIMARY KEY,
          report TEXT,
          themes TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )

    Returns: {saved: bool, synthesis_id: str, success: bool}
    """
    try:
        if conn is None:
            return {"success": False, "error": "save_synthesis: conn is None"}

        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS Synthesis_Log (
                synthesis_id TEXT PRIMARY KEY,
                report TEXT,
                themes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        synthesis_id = _safe_str(synthesis_dict.get("synthesis_id")) or str(uuid.uuid4())
        report = _safe_str(synthesis_dict.get("report"))
        themes = synthesis_dict.get("themes") if isinstance(synthesis_dict, dict) else []
        try:
            themes_json = json.dumps(themes, ensure_ascii=False)
        except Exception:
            themes_json = "[]"

        cur.execute(
            "INSERT OR REPLACE INTO Synthesis_Log (synthesis_id, report, themes) VALUES (?, ?, ?)",
            (synthesis_id, report, themes_json),
        )
        conn.commit()

        return {"saved": True, "synthesis_id": synthesis_id, "success": True}

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"success": False, "error": f"save_synthesis failed: {_safe_str(e)}"}


# S✅ T✅ L✅ A✅