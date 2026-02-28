"""
agent_memory.py
aeOS Phase 4 — Layer 2 (AI Agents)

AI agent that manages KB ingestion and memory retrieval pipeline.

Responsibilities:
- ingest_with_extraction(file_path, collection) -> dict
    Ingests a document into the KB and uses the local LLM to extract
    key concepts (for downstream retrieval / tagging).
- smart_search(kb_conn, query) -> list
    Enhances the query with the local LLM before searching the KB,
    and returns ranked results with relevance scores.
- summarize_collection(kb_conn, collection) -> str
    Produces an LLM-generated overview of what a collection contains
    and its key themes.
- find_connections(kb_conn, concept) -> list
    Uses the local LLM to find non-obvious connections between a
    concept and existing KB contents.

Notes:
- This agent is intentionally "duck-typed" around KB connections:
  it can operate on a Chroma Collection, a wrapper object, or a
  Chroma client, as long as it provides compatible methods.
- All failures are graceful: callers receive best-effort outputs.

Stamp: S✅ T✅ L✅ A✅
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ---- Logging (centralized) ---------------------------------------------------
try:
    from src.core.logger import get_logger  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    from core.logger import get_logger  # type: ignore

_LOG = get_logger(__name__)


# ---- AI primitives -----------------------------------------------------------
try:
    from src.ai.ai_infer import infer, infer_json  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    from ai.ai_infer import infer, infer_json  # type: ignore


# ---- KB helpers (best-effort) ------------------------------------------------
# These are internal modules from Phase 3. We avoid hard-coding their APIs and
# instead "probe" for a usable function at runtime.
# Note: repo execution modes vary (sometimes `src/` is a package, sometimes it
# is on PYTHONPATH). We try a few import patterns.

try:
    from src.kb import kb_ingest as _kb_ingest  # type: ignore
except Exception:  # pragma: no cover
    try:
        from kb import kb_ingest as _kb_ingest  # type: ignore
    except Exception:  # pragma: no cover
        _kb_ingest = None  # type: ignore

try:
    from src.kb import kb_search as _kb_search  # type: ignore
except Exception:  # pragma: no cover
    try:
        from kb import kb_search as _kb_search  # type: ignore
    except Exception:  # pragma: no cover
        _kb_search = None  # type: ignore

try:
    from src.kb import kb_connect as _kb_connect  # type: ignore
except Exception:  # pragma: no cover
    try:
        from kb import kb_connect as _kb_connect  # type: ignore
    except Exception:  # pragma: no cover
        _kb_connect = None  # type: ignore


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

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
    "kb",
    "knowledge",
    "base",
    "notes",
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


def _clamp01(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        return float(default)
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _keywordize(text: str, max_keywords: int = 10) -> List[str]:
    """
    Deterministic keyword extraction: words >=4 chars, de-duped, basic stopwords removed.
    """
    toks = re.findall(r"[A-Za-z0-9_]{4,}", (text or "").lower())
    out: List[str] = []
    seen = set()
    for t in toks:
        if t in _STOPWORDS or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= max_keywords:
            break
    return out


def _hash_id(*parts: str) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update((p or "").encode("utf-8", errors="ignore"))
        h.update(b"|")
    return h.hexdigest()


def _try_call(fn, *args, **kwargs):
    """
    Attempt calling fn with args/kwargs.
    Returns:
        (ok, value, error_str)
    """
    try:
        return True, fn(*args, **kwargs), None
    except TypeError as e:
        return False, None, str(e)
    except Exception as e:  # noqa: BLE001
        return False, None, str(e)


def _call_first_available(module: Any, names: Sequence[str], call_specs: Sequence[Tuple[Tuple[Any, ...], Dict[str, Any]]]):
    """
    Try functions in `names` on `module` using `call_specs` until one works.

    Args:
        module: imported module (or None)
        names: candidate function attribute names
        call_specs: list of (args_tuple, kwargs_dict) to try for each fn

    Returns:
        dict: {
          "ok": bool,
          "fn": str | None,
          "value": any,
          "error": str | None
        }
    """
    if module is None:
        return {"ok": False, "fn": None, "value": None, "error": "module_unavailable"}
    last_err: Optional[str] = None
    for name in names:
        fn = getattr(module, name, None)
        if not callable(fn):
            continue
        for args, kwargs in call_specs:
            ok, val, err = _try_call(fn, *args, **kwargs)
            if ok:
                return {"ok": True, "fn": name, "value": val, "error": None}
            last_err = err
    return {"ok": False, "fn": None, "value": None, "error": last_err or "no_callable_found"}


def _resolve_collection(kb_conn: Any, collection: str) -> Any:
    """
    Resolve a collection object for downstream calls.

    Accepts either:
    - a Chroma Collection object (already resolved)
    - a Chroma client (supports get_collection / get_or_create_collection)
    - a wrapper that exposes `.collection` or `.get_collection(...)`
    """
    if kb_conn is None:
        return None

    # Already a collection-like object.
    if hasattr(kb_conn, "query") and hasattr(kb_conn, "add"):
        return kb_conn

    # Wrapper: holds a collection attribute.
    coll = getattr(kb_conn, "collection", None)
    if coll is not None and hasattr(coll, "query"):
        return coll

    # Chroma client interface.
    if collection:
        if hasattr(kb_conn, "get_collection") and callable(getattr(kb_conn, "get_collection")):
            ok, val, _ = _try_call(getattr(kb_conn, "get_collection"), collection)
            if ok:
                return val
        if hasattr(kb_conn, "get_or_create_collection") and callable(getattr(kb_conn, "get_or_create_collection")):
            ok, val, _ = _try_call(getattr(kb_conn, "get_or_create_collection"), collection)
            if ok:
                return val

    return None


def _get_kb_collection_via_connect(collection: str) -> Any:
    """
    Best-effort: ask src.kb.kb_connect for a collection.
    This keeps agent_memory usable even when callers don't provide kb_conn.
    """
    if _kb_connect is None or not collection:
        return None
    call_specs = [
        ((collection,), {}),
        ((), {"collection": collection}),
        ((), {"name": collection}),
    ]
    res = _call_first_available(
        _kb_connect,
        names=("get_collection", "get_or_create_collection", "connect_collection", "collection", "kb_collection"),
        call_specs=call_specs,
    )
    if res.get("ok"):
        return res.get("value")

    # Some implementations expose a client, then we resolve collection on it.
    client_res = _call_first_available(
        _kb_connect,
        names=("get_kb_client", "connect", "get_client", "kb_client"),
        call_specs=[((), {})],
    )
    if client_res.get("ok"):
        return _resolve_collection(client_res.get("value"), collection)

    return None


# ---------------------------------------------------------------------------
# KB searching (duck-typed)
# ---------------------------------------------------------------------------


def _normalize_search_results(raw: Any) -> List[Dict[str, Any]]:
    """
    Normalize a variety of KB search responses into a list of dicts.

    Expected output keys per item:
      - id: str
      - text: str
      - metadata: dict
      - distance: float | None
      - score: float | None
    """
    if raw is None:
        return []

    # Common wrapper format: {"results": [...]} or {"items": [...]}
    if isinstance(raw, dict):
        if isinstance(raw.get("results"), list):
            raw = raw.get("results")
        elif isinstance(raw.get("items"), list):
            raw = raw.get("items")

    if isinstance(raw, list):
        out: List[Dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict):
                out.append(
                    {
                        "id": item.get("id") or item.get("doc_id") or item.get("chunk_id") or "",
                        "text": item.get("text") or item.get("document") or item.get("content") or "",
                        "metadata": item.get("metadata") or {},
                        "distance": item.get("distance"),
                        "score": item.get("score"),
                    }
                )
            else:
                out.append({"id": "", "text": str(item), "metadata": {}, "distance": None, "score": None})
        return out

    return [{"id": "", "text": str(raw), "metadata": {}, "distance": None, "score": None}]


def _kb_query(kb_conn: Any, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
    """
    Query KB (best-effort).

    Supports:
    - Chroma Collection: collection.query(query_texts=[...], n_results=...)
    - Wrapper: kb_conn.search(query, top_k=...) or kb_conn.search(query, k=...)
    """
    if kb_conn is None or not query:
        return []

    # Prefer Phase 3 kb_search module if available.
    if _kb_search is not None:
        # Try common function names and signatures.
        call_specs = [
            ((kb_conn, query), {"top_k": top_k}),
            ((kb_conn, query), {"k": top_k}),
            ((kb_conn, query), {}),
            ((query,), {"kb_conn": kb_conn, "top_k": top_k}),
            ((query,), {"kb_conn": kb_conn, "k": top_k}),
            ((query,), {}),
        ]
        res = _call_first_available(
            _kb_search,
            names=("search", "query", "semantic_search", "search_kb", "kb_search"),
            call_specs=call_specs,
        )
        if res.get("ok"):
            return _normalize_search_results(res.get("value"))

    # Chroma collection.query (native).
    if hasattr(kb_conn, "query") and callable(getattr(kb_conn, "query")):
        try:
            res = kb_conn.query(query_texts=[query], n_results=int(top_k))
            docs = (res.get("documents") or [[]])[0]
            metas = (res.get("metadatas") or [[]])[0]
            ids = (res.get("ids") or [[]])[0]
            dists = (res.get("distances") or [[]])[0]
            out: List[Dict[str, Any]] = []
            for i in range(min(int(top_k), len(docs))):
                out.append(
                    {
                        "id": ids[i] if i < len(ids) else "",
                        "text": docs[i],
                        "metadata": metas[i] if i < len(metas) else {},
                        "distance": dists[i] if i < len(dists) else None,
                        "score": None,
                    }
                )
            return out
        except TypeError:
            pass
        except Exception as e:  # noqa: BLE001
            _LOG.warning("KB .query failed: %s", e)

    # Wrapper kb_conn.search(...)
    if hasattr(kb_conn, "search") and callable(getattr(kb_conn, "search")):
        try:
            try:
                res = kb_conn.search(query, top_k=int(top_k))
            except TypeError:
                res = kb_conn.search(query, k=int(top_k))
            return _normalize_search_results(res)
        except Exception as e:  # noqa: BLE001
            _LOG.warning("KB .search failed: %s", e)

    return []


def _lexical_overlap_score(keywords: Sequence[str], text: str) -> float:
    """
    Cheap lexical scoring: fraction of keywords present in result text.
    """
    if not keywords:
        return 0.0
    hay = (text or "").lower()
    hits = 0
    for kw in keywords:
        if kw and kw.lower() in hay:
            hits += 1
    return float(hits) / float(max(1, len(keywords)))


def _relevance_score(item: Dict[str, Any], keywords: Sequence[str]) -> float:
    """
    Convert a KB result item to a stable 0..1 relevance score.

    - If item.score exists, assume it may already be similarity-like.
    - If item.distance exists, convert via 1/(1+distance).
    - Blend with lexical overlap to help when distance is missing.
    """
    base = 0.0
    s = item.get("score")
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        base = _clamp01(s, default=0.0)

    d = item.get("distance")
    if isinstance(d, (int, float)) and not isinstance(d, bool):
        # 1/(1+d) makes distance=0 -> 1.0, distance=1 -> 0.5, distance=2 -> 0.33, ...
        base = max(base, float(1.0 / (1.0 + max(0.0, float(d)))))

    lex = _lexical_overlap_score(keywords, _safe_str(item.get("text"), 2000))

    if base <= 0.0:
        return _clamp01(lex, default=0.0)

    # Blend: keep retrieval score primary, lexical as secondary sanity check.
    return _clamp01((0.75 * base) + (0.25 * lex), default=base)


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------


def _llm_extract_key_concepts(text: str) -> Dict[str, Any]:
    """
    Extract key concepts/entities/tags from document text using the local LLM.

    Returns:
        dict: {"summary": str, "key_concepts": list[str], "entities": list[str], "tags": list[str]}
    """
    text = (text or "").strip()
    if not text:
        return {"summary": "", "key_concepts": [], "entities": [], "tags": []}

    # Keep the prompt bounded to avoid blowing token budgets on long docs.
    snippet = _truncate(text, 4500)
    prompt = (
        "Extract key concepts from the document text.\n"
        "Constraints:\n"
        "- key_concepts: 5-12 short noun-phrases (no sentences)\n"
        "- entities: 0-10 proper nouns (people/orgs/products), if present\n"
        "- tags: 3-10 generic tags (topics/areas)\n"
        "- summary: 1-2 sentences\n\n"
        "<DOCUMENT>\n"
        f"{snippet}\n"
        "</DOCUMENT>\n"
    )
    schema_hint = (
        "{\n"
        '  "summary": "string",\n'
        '  "key_concepts": ["string"],\n'
        '  "entities": ["string"],\n'
        '  "tags": ["string"]\n'
        "}"
    )
    out = infer_json(prompt=prompt, schema_hint=schema_hint)
    if out.get("success") and isinstance(out.get("data"), dict):
        data = out["data"]
        return {
            "summary": _safe_str(data.get("summary"), 800),
            "key_concepts": [_safe_str(x, 80) for x in (data.get("key_concepts") or []) if _safe_str(x, 80)],
            "entities": [_safe_str(x, 80) for x in (data.get("entities") or []) if _safe_str(x, 80)],
            "tags": [_safe_str(x, 50) for x in (data.get("tags") or []) if _safe_str(x, 50)],
        }

    # Fallback: deterministic keywords only.
    kws = _keywordize(snippet, max_keywords=10)
    return {"summary": "", "key_concepts": kws, "entities": [], "tags": kws[:6]}


def _llm_enhance_query(query: str) -> Dict[str, Any]:
    """
    Enhance a query for KB search using the local LLM.

    Returns:
        dict: {"enhanced_query": str, "keywords": list[str]}
    """
    q = (query or "").strip()
    if not q:
        return {"enhanced_query": "", "keywords": []}

    prompt = (
        "Rewrite the query for semantic search over a personal knowledge base.\n"
        "Rules:\n"
        "- Preserve the user's intent.\n"
        "- Add synonyms and related terms ONLY if they are highly likely.\n"
        "- Keep it concise (one line).\n\n"
        f"Original query: {q}\n"
    )
    schema_hint = (
        "{\n"
        '  "enhanced_query": "string",\n'
        '  "keywords": ["string"]\n'
        "}"
    )
    out = infer_json(prompt=prompt, schema_hint=schema_hint)
    if out.get("success") and isinstance(out.get("data"), dict):
        data = out["data"]
        enhanced = _safe_str(data.get("enhanced_query"), 600) or q
        kws = [_safe_str(x, 60) for x in (data.get("keywords") or []) if _safe_str(x, 60)]
        if not kws:
            kws = _keywordize(enhanced, max_keywords=10)
        return {"enhanced_query": enhanced, "keywords": kws[:12]}

    # Fallback: use original query and deterministic keywords.
    return {"enhanced_query": q, "keywords": _keywordize(q, max_keywords=10)}


# ---------------------------------------------------------------------------
# Ingestion helpers
# ---------------------------------------------------------------------------


def _read_text_best_effort(file_path: str, max_chars: int = 20000) -> str:
    """
    Extract text from a file best-effort.

    Preference:
    1) Ask kb_ingest for an extraction helper if it exists.
    2) For text-ish files, read directly (utf-8 with replacement).
    3) Otherwise, return empty string (we avoid pretending binary is text).
    """
    path = (file_path or "").strip()
    if not path or not os.path.exists(path):
        return ""

    # 1) Use kb_ingest extractors if present.
    if _kb_ingest is not None:
        call_specs = [
            ((path,), {}),
            ((), {"file_path": path}),
            ((), {"path": path}),
        ]
        res = _call_first_available(
            _kb_ingest,
            names=("extract_text", "read_text", "load_text", "parse_text", "document_text", "get_text"),
            call_specs=call_specs,
        )
        if res.get("ok"):
            return _safe_str(res.get("value"), max_chars)

    # 2) Local text read for common extensions.
    ext = os.path.splitext(path)[1].lower()
    if ext in {".txt", ".md", ".log", ".csv", ".json", ".py", ".sql", ".yaml", ".yml"}:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return _truncate(f.read(), max_chars)
        except Exception:
            return ""

    return ""


def _kb_ingest_file(file_path: str, collection: str) -> Dict[str, Any]:
    """
    Ingest a file into the KB via src.kb.kb_ingest if possible.

    Returns:
        dict: {"ok": bool, "fn": str|None, "value": any, "error": str|None}
    """
    if _kb_ingest is None:
        return {"ok": False, "fn": None, "value": None, "error": "kb_ingest_unavailable"}

    path = (file_path or "").strip()
    coll = (collection or "").strip()

    call_specs = [
        ((path, coll), {}),  # fn(path, collection)
        ((path,), {"collection": coll}),  # fn(path, collection="...")
        ((), {"file_path": path, "collection": coll}),
        ((), {"path": path, "collection": coll}),
        ((path,), {}),  # fn(path) (module may embed default collection)
    ]

    return _call_first_available(
        _kb_ingest,
        names=("ingest_with_extraction", "ingest_file", "ingest_document", "ingest", "ingest_path", "add_file"),
        call_specs=call_specs,
    )


def _extract_ids_from_ingest_result(value: Any) -> List[str]:
    """
    Best-effort extraction of inserted IDs from an ingest result object.
    """
    ids: List[str] = []
    if isinstance(value, dict):
        for k in ("ids", "doc_ids", "chunk_ids", "inserted_ids", "documents_ids"):
            v = value.get(k)
            if isinstance(v, list):
                ids = [str(x) for x in v if str(x)]
                break
        if not ids and isinstance(value.get("result"), dict):
            return _extract_ids_from_ingest_result(value.get("result"))
    if isinstance(value, list):
        ids = [str(x) for x in value if str(x)]
    return ids


def _try_update_ingested_metadata(collection_obj: Any, ids: List[str], meta_patch: Dict[str, Any]) -> bool:
    """
    Best-effort: patch metadata for ingested chunks (if collection.update exists).
    """
    if not collection_obj or not ids or not isinstance(meta_patch, dict):
        return False
    if not hasattr(collection_obj, "update") or not callable(getattr(collection_obj, "update")):
        return False
    # Chroma expects a list of metadatas matching ids.
    metadatas = [meta_patch for _ in ids]
    ok, _, _ = _try_call(getattr(collection_obj, "update"), ids=ids, metadatas=metadatas)
    return bool(ok)


# ---------------------------------------------------------------------------
# Public API (required)
# ---------------------------------------------------------------------------


def ingest_with_extraction(file_path: str, collection: str) -> Dict[str, Any]:
    """
    Ingest a document into the KB and extract key concepts via the local LLM.

    Args:
        file_path: Path to the file to ingest.
        collection: Target KB collection name.

    Returns:
        dict: Ingestion summary (safe to log/store).
    """
    started = time.perf_counter()
    path = (file_path or "").strip()
    coll = (collection or "").strip()

    if not path:
        return {"success": False, "error": "empty_file_path", "file_path": file_path, "collection": coll}
    if not os.path.exists(path):
        return {"success": False, "error": "file_not_found", "file_path": path, "collection": coll}

    ingest_res = _kb_ingest_file(path, coll)
    ingest_ok = bool(ingest_res.get("ok"))

    # Extract text (best effort) for concept extraction.
    text = _read_text_best_effort(path, max_chars=20000)
    extraction = _llm_extract_key_concepts(text)

    # Optionally patch metadata for ingested chunks (if we can locate IDs + collection object).
    ingested_ids = _extract_ids_from_ingest_result(ingest_res.get("value"))
    coll_obj = _get_kb_collection_via_connect(coll) if coll else None
    meta_updated = False
    if coll_obj is not None and ingested_ids:
        meta_patch = {
            "source_file": os.path.basename(path),
            "tags": extraction.get("tags") or [],
            "key_concepts": extraction.get("key_concepts") or [],
        }
        meta_updated = _try_update_ingested_metadata(coll_obj, ingested_ids, meta_patch)

    latency_ms = int((time.perf_counter() - started) * 1000)

    return {
        "success": bool(ingest_ok),
        "file_path": path,
        "collection": coll,
        "ingest": {
            "ok": bool(ingest_ok),
            "fn": ingest_res.get("fn"),
            "error": ingest_res.get("error"),
            # Keep the raw value, but bounded for safety in logs.
            "result_preview": _truncate(json.dumps(ingest_res.get("value"), ensure_ascii=False, default=str), 1200)
            if ingest_res.get("value") is not None
            else None,
            "ids_count": len(ingested_ids),
            "metadata_updated": bool(meta_updated),
        },
        "extraction": extraction,
        "latency_ms": latency_ms,
    }


def smart_search(kb_conn: Any, query: str) -> List[Dict[str, Any]]:
    """
    Enhance a query with the local LLM, search the KB, and return ranked results.

    Args:
        kb_conn: KB connection/collection (duck-typed).
        query: User query.

    Returns:
        list[dict]: Ranked results, each containing:
          {id, text, metadata, relevance_score, distance, score}
    """
    q = (query or "").strip()
    if not q:
        return []

    enhanced = _llm_enhance_query(q)
    q_used = enhanced.get("enhanced_query") or q
    keywords = enhanced.get("keywords") or _keywordize(q_used)

    raw = _kb_query(kb_conn, q_used, top_k=10)

    out: List[Dict[str, Any]] = []
    for item in raw:
        # Normalize.
        rid = _safe_str(item.get("id"), 120)
        text = _safe_str(item.get("text"), 2500)
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        dist = item.get("distance")
        sc = item.get("score")

        r = {
            "id": rid,
            "text": text,
            "metadata": meta,
            "distance": dist,
            "score": sc,
        }
        r["relevance_score"] = _relevance_score(r, keywords)
        out.append(r)

    out.sort(key=lambda d: float(d.get("relevance_score") or 0.0), reverse=True)

    # Include the enhanced query on the first item for caller visibility (without changing return type).
    if out:
        out[0] = dict(out[0])
        out[0]["query_used"] = q_used
        out[0]["query_original"] = q

    return out


def summarize_collection(kb_conn: Any, collection: str) -> str:
    """
    Produce an LLM-generated summary of what a collection contains.

    Args:
        kb_conn: KB connection or client (duck-typed).
        collection: Collection name.

    Returns:
        str: Summary text (best-effort).
    """
    coll_name = (collection or "").strip()
    coll = _resolve_collection(kb_conn, coll_name)
    if coll is None:
        # Try connecting via kb_connect if kb_conn is not a client.
        coll = _get_kb_collection_via_connect(coll_name)
    if coll is None:
        return f"(collection_unavailable: {coll_name})"

    # Pull a small sample of documents for summarization.
    sample = _sample_collection_docs(coll, limit=12)
    if not sample:
        return f"(no_documents_found: {coll_name})"

    lines = [f"Collection: {coll_name}", "Samples:"]
    for s in sample:
        title = s.get("title") or ""
        sid = s.get("id") or ""
        snippet = s.get("snippet") or ""
        bits = []
        if title:
            bits.append(title)
        if sid:
            bits.append(sid)
        header = " | ".join(bits) if bits else "(untitled)"
        lines.append(f"- {header}: {snippet}")

    prompt = (
        "Summarize what this knowledge base collection contains.\n"
        "Output:\n"
        "- 3-6 bullets of key themes\n"
        "- 1 short paragraph describing the 'center of gravity' of the collection\n"
        "- If obvious gaps exist (e.g., missing time range, missing domains), mention them.\n\n"
        f"{_truncate(chr(10).join(lines), 6500)}\n"
    )

    out = infer(prompt=prompt, system_prompt="You are aeOS KB Summarizer.")
    if out.get("success") and isinstance(out.get("response"), str) and out.get("response").strip():
        return out["response"].strip()

    # Fallback: deterministic summary from titles.
    titles = [s.get("title") for s in sample if s.get("title")]
    unique = []
    seen = set()
    for t in titles:
        tl = str(t).lower()
        if tl in seen:
            continue
        seen.add(tl)
        unique.append(str(t))
    return "Collection themes (fallback): " + (", ".join(unique[:10]) if unique else "(unknown)")


def find_connections(kb_conn: Any, concept: str) -> List[Dict[str, Any]]:
    """
    Find non-obvious connections between a concept and KB contents.

    Args:
        kb_conn: KB connection/collection (duck-typed).
        concept: Concept or term to explore.

    Returns:
        list[dict]: Connection objects with rationale and supporting doc IDs.
    """
    c = (concept or "").strip()
    if not c:
        return []

    # Use the KB itself as the "evidence corpus" for connections.
    hits = smart_search(kb_conn, c)[:8]

    # If KB is empty/unreachable, we can't connect anything.
    if not hits:
        return []

    # Build a compact evidence pack for the LLM.
    evidence_lines = []
    for h in hits:
        meta = h.get("metadata") or {}
        title = meta.get("title") or meta.get("name") or meta.get("source") or meta.get("path") or ""
        evidence_lines.append(
            json.dumps(
                {
                    "id": h.get("id"),
                    "title": _safe_str(title, 120),
                    "snippet": _truncate(_safe_str(h.get("text"), 700), 700),
                },
                ensure_ascii=False,
            )
        )

    prompt = (
        "You are aeOS Connection Finder.\n"
        "Task: find non-obvious connections between the CONCEPT and the KB snippets.\n"
        "Rules:\n"
        "- Connections should NOT be trivial synonyms.\n"
        "- Each connection must cite 1-3 supporting snippet ids.\n"
        "- Keep rationale short (1-2 sentences).\n\n"
        f"CONCEPT: {c}\n\n"
        "SNIPPETS (JSON lines):\n"
        + "\n".join(evidence_lines[:8])
        + "\n"
    )

    schema_hint = (
        "{\n"
        '  "connections": [\n'
        "    {\n"
        '      "connection": "string",\n'
        '      "supporting_ids": ["string"],\n'
        '      "rationale": "string",\n'
        '      "confidence": "number 0-1"\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    out = infer_json(prompt=prompt, schema_hint=schema_hint)
    if out.get("success") and isinstance(out.get("data"), dict):
        data = out["data"]
        conns = data.get("connections")
        if isinstance(conns, list):
            cleaned: List[Dict[str, Any]] = []
            for cobj in conns[:12]:
                if not isinstance(cobj, dict):
                    continue
                cleaned.append(
                    {
                        "connection": _safe_str(cobj.get("connection"), 200),
                        "supporting_ids": [str(x) for x in (cobj.get("supporting_ids") or []) if str(x)],
                        "rationale": _safe_str(cobj.get("rationale"), 500),
                        "confidence": _clamp01(cobj.get("confidence"), default=0.5),
                    }
                )
            return cleaned

    # Fallback: surface the best KB hits as "connections" (not non-obvious, but usable).
    fallback: List[Dict[str, Any]] = []
    for h in hits[:6]:
        meta = h.get("metadata") or {}
        title = meta.get("title") or meta.get("name") or meta.get("source") or meta.get("path") or ""
        fallback.append(
            {
                "connection": _safe_str(title or "Related note", 200),
                "supporting_ids": [str(h.get("id") or "")],
                "rationale": "Fallback: surfaced a related KB snippet (LLM connection step unavailable).",
                "confidence": 0.3,
            }
        )
    return fallback


# ---------------------------------------------------------------------------
# Router integration (optional but expected by ai_router.py)
# ---------------------------------------------------------------------------


def handle(query: str, conn, kb_conn) -> Dict[str, Any]:
    """
    Router entry point for intent: memory_search.

    Contract (Layer 2 agents):
        handle(query: str, conn, kb_conn) -> dict

    Returns:
        dict: {response, success, results}
    """
    q = (query or "").strip()
    if not q:
        return {"response": "", "success": False, "error": "empty_query", "results": []}

    results = smart_search(kb_conn, q)
    top = results[:5]

    # Construct a compact, human-readable response.
    lines = ["Top memory hits:"]
    for i, r in enumerate(top, start=1):
        meta = r.get("metadata") or {}
        title = meta.get("title") or meta.get("name") or meta.get("source") or meta.get("path") or ""
        header = _safe_str(title or r.get("id") or f"Result {i}", 120)
        snippet = _truncate(_safe_str(r.get("text"), 400), 400)
        score = r.get("relevance_score")
        lines.append(f"{i}. {header} (score={score:.2f})" if isinstance(score, (int, float)) else f"{i}. {header}")
        if snippet:
            lines.append(f"   {snippet}")

    return {
        "response": "\n".join(lines),
        "success": True,
        "results": results,
        "count": len(results),
    }


# ---------------------------------------------------------------------------
# Sampling helpers (collection summaries)
# ---------------------------------------------------------------------------


def _sample_collection_docs(collection_obj: Any, limit: int = 12) -> List[Dict[str, Any]]:
    """
    Fetch a small sample of documents from a collection, without embeddings.

    Chroma Collection.get typically supports:
      get(limit=?, offset=?, include=[...])
    but some wrappers differ; we probe defensively.
    """
    if collection_obj is None:
        return []
    if not hasattr(collection_obj, "get") or not callable(getattr(collection_obj, "get")):
        return []

    include = ["documents", "metadatas", "ids"]
    call_specs = [
        ((), {"limit": int(limit), "include": include}),
        ((), {"n_results": int(limit), "include": include}),
        ((), {"include": include}),
        ((), {}),
    ]

    # We need to try signatures on the bound method, not via _call_first_available.
    get_fn = getattr(collection_obj, "get")
    raw: Optional[Dict[str, Any]] = None
    for args, kwargs in call_specs:
        ok, val, _ = _try_call(get_fn, *args, **kwargs)
        if ok and isinstance(val, dict):
            raw = val
            break

    if not raw:
        return []

    ids = raw.get("ids") or []
    docs = raw.get("documents") or []
    metas = raw.get("metadatas") or []

    # Some Chroma versions nest these.
    if isinstance(ids, list) and ids and isinstance(ids[0], list):
        ids = ids[0]
    if isinstance(docs, list) and docs and isinstance(docs[0], list):
        docs = docs[0]
    if isinstance(metas, list) and metas and isinstance(metas[0], list):
        metas = metas[0]

    out: List[Dict[str, Any]] = []
    for i in range(min(int(limit), len(docs))):
        meta = metas[i] if i < len(metas) and isinstance(metas[i], dict) else {}
        title = meta.get("title") or meta.get("name") or meta.get("source") or meta.get("path") or ""
        out.append(
            {
                "id": str(ids[i]) if i < len(ids) else "",
                "title": _safe_str(title, 140),
                "snippet": _truncate(_safe_str(docs[i], 700), 700),
                "metadata": meta,
            }
        )
    return out


__all__ = [
    "ingest_with_extraction",
    "smart_search",
    "summarize_collection",
    "find_connections",
    "handle",
]
