"""src/kb/kb_search.py
Stamp: S✅ T✅ L✅ A✅
aeOS KB Layer — Semantic search across ChromaDB collections.
API:
- search(conn, collection, query, n_results=5) -> [{doc_id, text, score, metadata}]
- search_across_collections(conn, query, collections, n_results=5) -> [{...}]  # dedupe + rerank
- get_similar_documents(conn, collection, doc_id, n_results=5) -> [{...}]
- search_with_filter(conn, collection, query, filter_dict, n_results=5) -> [{...}]
- get_search_stats(conn, collection) -> {total_searchable_docs, avg_query_time_ms, last_query_at}
Score semantics:
Chroma returns *distances* (lower=better). We convert to similarity score in (0, 1]:
    score = 1 / (1 + distance)
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

__all__ = [
    "search",
    "search_across_collections",
    "get_similar_documents",
    "search_with_filter",
    "get_search_stats",
]

# In-memory rolling timing stats (per collection, per process).
# Shape: {collection: {"queries": int, "total_ms": float, "last_query_at": str|None}}
_SEARCH_STATS: Dict[str, Dict[str, Any]] = {}


def _utc_now_iso() -> str:
    """Current UTC time as ISO-8601 string (no microseconds)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _record_query_stat(collection: str, elapsed_ms: float) -> None:
    """Record query timing for a collection (rolling totals)."""
    key = str(collection)
    st = _SEARCH_STATS.setdefault(key, {"queries": 0, "total_ms": 0.0, "last_query_at": None})
    st["queries"] = int(st.get("queries", 0)) + 1
    st["total_ms"] = float(st.get("total_ms", 0.0)) + max(0.0, float(elapsed_ms))
    st["last_query_at"] = _utc_now_iso()


def _distance_to_score(distance: Any) -> float:
    """Convert Chroma distance (lower=better) to similarity score (higher=better)."""
    if distance is None:
        return 0.0
    try:
        d = float(distance)
    except Exception:
        return 0.0
    if d < 0:
        d = 0.0
    return 1.0 / (1.0 + d)


def _unwrap_client(conn: Any) -> Any:
    """Unwrap KBConnection-like objects into a raw Chroma client."""
    # KBConnection (kb_connect.py) exposes connect() + client.
    if hasattr(conn, "connect") and callable(getattr(conn, "connect")) and hasattr(conn, "client"):
        try:
            conn.connect()  # type: ignore[call-arg]
        except Exception:
            pass
        try:
            return conn.client  # type: ignore[attr-defined]
        except Exception:
            pass
    # Other wrappers may expose common attributes.
    for attr in ("client", "_client", "chroma", "_chroma"):
        if hasattr(conn, attr):
            try:
                return getattr(conn, attr)
            except Exception:
                continue
    return conn


def _get_collection(conn: Any, name: str) -> Any:
    """Get a collection by name from a Chroma client / KBConnection."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("collection must be a non-empty string")
    client = _unwrap_client(conn)
    if not hasattr(client, "get_collection"):
        raise TypeError("conn must be a Chroma client or KBConnection-like object")
    try:
        return client.get_collection(name=name)  # type: ignore[misc]
    except TypeError:
        return client.get_collection(name)  # type: ignore[misc]


def _query_collection(
    col: Any,
    query: str,
    n_results: int,
    *,
    where: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Query a collection with safe fallbacks across Chroma versions."""
    empty = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
    if not isinstance(query, str) or not query.strip():
        return empty
    kwargs: Dict[str, Any] = {
        "query_texts": [query],
        "n_results": int(n_results),
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where
    try:
        return col.query(**kwargs)  # type: ignore[misc]
    except TypeError:
        # Some versions do not accept `include`.
        kwargs.pop("include", None)
        try:
            return col.query(**kwargs)  # type: ignore[misc]
        except Exception:
            return empty
    except Exception:
        return empty


def _normalize_query_result(collection: str, res: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize Chroma query result to [{doc_id, text, score, metadata}] sorted best-first."""
    ids = (res.get("ids") or [[]])[0] or []
    docs = (res.get("documents") or [[]])[0] or []
    metas = (res.get("metadatas") or [[]])[0] or []
    dists = (res.get("distances") or [[]])[0] or []

    n = max(len(ids), len(docs), len(metas), len(dists))
    out: List[Dict[str, Any]] = []
    for i in range(n):
        doc_id = str(ids[i]) if i < len(ids) else ""
        text = str(docs[i]) if i < len(docs) else ""
        md_raw = metas[i] if i < len(metas) else {}
        dist = dists[i] if i < len(dists) else None
        md = dict(md_raw) if isinstance(md_raw, dict) else {"value": md_raw}
        md.setdefault("collection", collection)  # provenance for cross-collection search
        out.append({"doc_id": doc_id, "text": text, "score": _distance_to_score(dist), "metadata": md})

    out.sort(key=lambda r: (float(r.get("score", 0.0)), str(r.get("doc_id", ""))), reverse=True)
    return out


def search(conn: Any, collection: str, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
    """Semantic search in a single collection."""
    if n_results <= 0:
        return []
    col = _get_collection(conn, collection)
    t0 = time.perf_counter()
    res = _query_collection(col, query, n_results)
    _record_query_stat(collection, (time.perf_counter() - t0) * 1000.0)
    return _normalize_query_result(collection, res)[: int(n_results)]


def search_with_filter(
    conn: Any,
    collection: str,
    query: str,
    filter_dict: Dict[str, Any],
    n_results: int = 5,
) -> List[Dict[str, Any]]:
    """Search with Chroma `where` filter applied before ranking."""
    if n_results <= 0:
        return []
    if filter_dict is None:
        filter_dict = {}
    if not isinstance(filter_dict, dict):
        raise TypeError("filter_dict must be a dict")
    col = _get_collection(conn, collection)
    t0 = time.perf_counter()
    res = _query_collection(col, query, n_results, where=filter_dict)
    _record_query_stat(collection, (time.perf_counter() - t0) * 1000.0)
    return _normalize_query_result(collection, res)[: int(n_results)]


def search_across_collections(
    conn: Any,
    query: str,
    collections: List[str],
    n_results: int = 5,
) -> List[Dict[str, Any]]:
    """Search multiple collections, then dedupe + rerank (best score wins).

    Dedupe key:
    - metadata["group_id"] (kb_ingest logical document id) when present
    - else doc_id
    """
    if n_results <= 0 or not collections:
        return []
    per_col = max(int(n_results), min(50, int(n_results) * 2))  # fetch extra candidates per collection

    best: Dict[str, Dict[str, Any]] = {}
    for col_name in collections:
        if not isinstance(col_name, str) or not col_name.strip():
            continue
        try:
            hits = search(conn, col_name, query, n_results=per_col)
        except Exception:
            continue
        for hit in hits:
            md = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
            key = str(md.get("group_id") or hit.get("doc_id") or "")
            if not key:
                continue
            prev = best.get(key)
            if prev is None or float(hit.get("score", 0.0)) > float(prev.get("score", 0.0)):
                best[key] = hit

    ranked = list(best.values())
    ranked.sort(key=lambda r: (float(r.get("score", 0.0)), str(r.get("doc_id", ""))), reverse=True)
    return ranked[: int(n_results)]


def _get_document_text(col: Any, doc_id: str) -> str:
    """Fetch the document text for a given doc_id; returns '' if not found."""
    if not isinstance(doc_id, str) or not doc_id.strip():
        return ""
    try:
        res = col.get(ids=[doc_id], include=["documents"])  # type: ignore[arg-type]
    except TypeError:
        try:
            res = col.get(ids=[doc_id])  # type: ignore[arg-type]
        except Exception:
            return ""
    except Exception:
        return ""
    if not isinstance(res, dict):
        return ""
    docs = res.get("documents") or []
    return str(docs[0]) if docs else ""


def get_similar_documents(
    conn: Any,
    collection: str,
    doc_id: str,
    n_results: int = 5,
) -> List[Dict[str, Any]]:
    """Find documents similar to an existing doc_id (uses the doc's text as the query)."""
    if n_results <= 0:
        return []
    col = _get_collection(conn, collection)
    text = _get_document_text(col, doc_id)
    if not text.strip():
        return []
    hits = search(conn, collection, text, n_results=int(n_results) + 1)
    hits = [h for h in hits if str(h.get("doc_id")) != doc_id]
    return hits[: int(n_results)]


def get_search_stats(conn: Any, collection: str) -> Dict[str, Any]:
    """Return {total_searchable_docs, avg_query_time_ms, last_query_at} for a collection."""
    total_docs = 0
    try:
        col = _get_collection(conn, collection)
        total_docs = int(col.count())  # type: ignore[misc]
    except Exception:
        total_docs = 0

    st = _SEARCH_STATS.get(str(collection), {})
    q = int(st.get("queries", 0) or 0)
    total_ms = float(st.get("total_ms", 0.0) or 0.0)
    avg_ms = (total_ms / q) if q > 0 else 0.0

    return {
        "total_searchable_docs": total_docs,
        "avg_query_time_ms": round(avg_ms, 3),
        "last_query_at": st.get("last_query_at"),
    }
