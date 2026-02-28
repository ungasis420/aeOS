"""kb_index.py
Stamp: S✅ T✅ L✅ A✅
aeOS Phase 3 — Layer 1 (Knowledge Base)
Purpose
-------
Index management utilities for ChromaDB collections used by the aeOS KB layer.
This module provides operational maintenance tasks:
- Rebuild a collection "index" by exporting records, dropping the collection,
  recreating it, and re-inserting the records (best-effort across Chroma versions).
- Validate basic index integrity (missing/duplicate IDs).
- Report health across all collections.
- Optimize collections by removing orphaned docs and fixing common metadata gaps.
- Export an index manifest (collection-level snapshot) for backup/restore workflows.
Notes
-----
ChromaDB does not expose a universal "reindex" API across versions. The most
portable approach is:
1) Read all records from the collection (ids + docs + metadatas [+ embeddings]).
2) Delete the collection.
3) Recreate it with prior collection metadata.
4) Re-add the records (passing embeddings when supported, otherwise letting Chroma
   compute embeddings from documents).
Dependencies
------------
- chromadb (allowed in KB layer)
- stdlib only otherwise
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from itertools import count
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "rebuild_index",
    "validate_index",
    "get_index_health",
    "optimize_collection",
    "export_index_manifest",
]

# ---------------------------------------------------------------------------
# Optional aeOS imports (keep module usable in isolation/tests)
# ---------------------------------------------------------------------------
try:
    from ..core.logger import get_logger  # type: ignore
except Exception:  # pragma: no cover
    try:
        from src.core.logger import get_logger  # type: ignore
    except Exception:  # pragma: no cover
        import logging

        def get_logger(name: str = "aeOS") -> "logging.Logger":  # type: ignore
            """Fallback logger used only if aeOS logger is unavailable."""
            logger = logging.getLogger(name)
            if not logger.handlers:
                handler = logging.StreamHandler()
                handler.setFormatter(
                    logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
                )
                logger.addHandler(handler)
                logger.setLevel(logging.INFO)
            return logger


try:
    from ..core.config import KB_PATH  # type: ignore
except Exception:  # pragma: no cover
    try:
        from src.core.config import KB_PATH  # type: ignore
    except Exception:  # pragma: no cover
        KB_PATH = None  # type: ignore

try:
    import chromadb  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    chromadb = None  # type: ignore

_LOG = None


def _log():
    """Lazy-init logger (handles differing get_logger signatures)."""
    global _LOG
    if _LOG is None:
        try:
            _LOG = get_logger(__name__)  # type: ignore[arg-type]
        except TypeError:  # pragma: no cover
            _LOG = get_logger()  # type: ignore[call-arg]
    return _LOG


# ---------------------------------------------------------------------------
# ID helpers (used for metadata repair)
# ---------------------------------------------------------------------------
_GROUP_PREFIX = "KBG"  # logical document group id (matches kb_ingest.py)

# Seed counter with ms to reduce collision risk across runs.
_ID_COUNTER = count(start=int(time.time() * 1000) % 1_000_000)


def _utc_now_iso() -> str:
    """UTC timestamp as ISO-8601 string (lexicographically sortable)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id(prefix: str) -> str:
    """Create PREFIX-YYYYMMDD-NNN (NNN numeric, width >= 3)."""
    yyyymmdd = datetime.now(timezone.utc).strftime("%Y%m%d")
    seq = next(_ID_COUNTER)
    return f"{prefix}-{yyyymmdd}-{seq:03d}"


# ---------------------------------------------------------------------------
# Chroma compatibility helpers
# ---------------------------------------------------------------------------

def _require_chromadb() -> None:
    """Raise a clear error if ChromaDB is not installed."""
    if chromadb is None:
        raise ModuleNotFoundError(
            "chromadb is required for the aeOS KB layer. Install with: pip install chromadb"
        )


def _unwrap_client(conn: Any) -> Any:
    """
    Unwrap a connection wrapper to a raw Chroma client.

    Supports:
    - KBConnection from kb_connect.py (has .connect() and .client)
    - raw chromadb client (PersistentClient/Client)
    """
    # If it's a KBConnection-like wrapper, connect() is idempotent.
    if hasattr(conn, "connect") and callable(getattr(conn, "connect")):
        try:
            conn.connect()
        except Exception:
            pass
    for attr in ("client", "_client"):
        if hasattr(conn, attr):
            try:
                return getattr(conn, attr)
            except Exception:
                continue
    return conn


def _get_collection(client: Any, name: str) -> Optional[Any]:
    """Get a collection by name. Returns None if missing."""
    if client is None or not hasattr(client, "get_collection"):
        raise TypeError("conn/client must provide get_collection(name)")
    try:
        return client.get_collection(name)  # type: ignore[misc]
    except Exception:
        return None


def _create_collection(
    client: Any, name: str, metadata: Optional[Dict[str, Any]] = None
) -> Any:
    """Create (or get) a collection, preferring idempotent APIs when available."""
    meta = metadata or {}
    if hasattr(client, "get_or_create_collection"):
        return client.get_or_create_collection(name=name, metadata=meta)  # type: ignore[misc]
    try:
        return client.create_collection(name=name, metadata=meta)  # type: ignore[misc]
    except Exception:
        return client.get_collection(name)  # type: ignore[misc]


def _delete_collection(client: Any, name: str) -> bool:
    """Delete a collection by name (best-effort)."""
    if not hasattr(client, "delete_collection"):
        return False
    try:
        client.delete_collection(name=name)  # type: ignore[misc]
        return True
    except Exception:
        return False


def _list_collection_names(client: Any) -> List[str]:
    """List collection names with normalization across Chroma versions."""
    if not hasattr(client, "list_collections"):
        return []
    cols = client.list_collections()  # type: ignore[misc]
    names: List[str] = []
    for c in cols or []:
        if isinstance(c, str):
            names.append(c)
        elif isinstance(c, dict) and "name" in c:
            names.append(str(c["name"]))
        elif hasattr(c, "name"):
            names.append(str(getattr(c, "name")))
        else:
            names.append(str(c))
    return names


def _sanitize_metadata(md: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Convert metadata to Chroma-compatible primitives.

    ChromaDB metadata values must be primitives (str/int/float/bool).
    Non-primitives are JSON-encoded. None values are dropped.
    """
    if not md:
        return {}
    out: Dict[str, Any] = {}
    for k, v in md.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[str(k)] = v
            continue
        try:
            out[str(k)] = json.dumps(v, ensure_ascii=False, default=str)
        except Exception:
            out[str(k)] = str(v)
    return out


def _paged_get(
    col: Any,
    *,
    include: Sequence[str],
    batch_size: int = 1000,
) -> Iterable[Dict[str, Any]]:
    """
    Page through a collection using get(limit/offset) when supported.

    If pagination is not supported, yields a single result.
    """
    offset = 0
    while True:
        try:
            res = col.get(include=list(include), limit=batch_size, offset=offset)  # type: ignore[arg-type]
            yield res
            ids = res.get("ids") or []
            if not ids or len(ids) < batch_size:
                return
            offset += len(ids)
        except TypeError:
            # limit/offset not supported (or include signature differs).
            try:
                yield col.get(include=list(include))  # type: ignore[arg-type]
            except Exception:
                yield col.get()  # type: ignore[misc]
            return
        except Exception:
            return


def _read_all_records(
    col: Any,
    *,
    want_embeddings: bool = True,
) -> Tuple[List[str], List[Optional[str]], List[Dict[str, Any]], Optional[List[Any]]]:
    """
    Read all records from a collection.

    Returns:
        (ids, documents, metadatas, embeddings_or_none)
    """
    ids_all: List[str] = []
    docs_all: List[Optional[str]] = []
    metas_all: List[Dict[str, Any]] = []
    embeds_all: List[Any] = []

    include = ["documents", "metadatas"] + (["embeddings"] if want_embeddings else [])
    got_embeddings = want_embeddings

    for page in _paged_get(col, include=include):
        ids = page.get("ids") or []
        docs = page.get("documents") or []
        metas = page.get("metadatas") or []
        embeds = page.get("embeddings") or []

        # If embeddings were requested but not returned for non-empty pages, stop collecting.
        if want_embeddings and got_embeddings and ids and not embeds:
            got_embeddings = False

        for i in range(len(ids)):
            _id = ids[i]
            ids_all.append(_id)

            doc = docs[i] if i < len(docs) else None
            docs_all.append(doc if isinstance(doc, str) else None)

            md = metas[i] if i < len(metas) else {}
            metas_all.append(md if isinstance(md, dict) else {})

            if want_embeddings and got_embeddings:
                emb = embeds[i] if i < len(embeds) else None
                embeds_all.append(emb)

    return ids_all, docs_all, metas_all, (
        embeds_all if want_embeddings and got_embeddings else None
    )


def _batched(seq: Sequence[Any], batch_size: int) -> Iterable[Sequence[Any]]:
    """Yield a sequence in fixed-size batches."""
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")
    for i in range(0, len(seq), batch_size):
        yield seq[i : i + batch_size]


def _collection_metadata(col: Any) -> Dict[str, Any]:
    """Best-effort fetch of collection-level metadata."""
    meta = getattr(col, "metadata", None)
    return meta if isinstance(meta, dict) else {}


def _resolve_kb_path(conn: Any) -> Optional[str]:
    """Best-effort resolve KB persistence directory (for manifests)."""
    for obj in (conn, _unwrap_client(conn)):
        for attr in ("path", "_path", "persist_path", "_persist_path"):
            val = getattr(obj, attr, None)
            if isinstance(val, str) and val:
                return os.path.abspath(os.path.expanduser(val))
    if isinstance(KB_PATH, str) and KB_PATH:
        return os.path.abspath(os.path.expanduser(KB_PATH))
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def rebuild_index(conn: Any, collection: str) -> bool:
    """
    Rebuild a collection "index" by exporting, dropping, recreating, and re-ingesting.

    Args:
        conn: KBConnection instance or raw Chroma client.
        collection: Collection name to rebuild.

    Returns:
        bool: True if rebuild succeeded, else False.
    """
    _require_chromadb()
    client = _unwrap_client(conn)

    if not isinstance(collection, str) or not collection.strip():
        raise ValueError("collection must be a non-empty string")

    name = collection.strip()

    # If the collection does not exist, "rebuild" means create it.
    old_col = _get_collection(client, name)
    old_meta: Dict[str, Any] = (
        _collection_metadata(old_col) if old_col is not None else {}
    )

    # Export records (best-effort).
    ids: List[str] = []
    docs: List[Optional[str]] = []
    metas: List[Dict[str, Any]] = []
    embeds: Optional[List[Any]] = None

    if old_col is not None:
        try:
            ids, docs, metas, embeds = _read_all_records(old_col, want_embeddings=True)
        except Exception as e:
            _log().warning("Failed to export collection '%s' for rebuild: %s", name, e)
            return False
        if not _delete_collection(client, name):
            _log().warning("Failed to delete collection '%s' for rebuild.", name)
            return False

    # Recreate collection with prior metadata.
    try:
        new_col = _create_collection(client, name, metadata=old_meta)
    except Exception as e:
        _log().warning("Failed to recreate collection '%s': %s", name, e)
        return False

    # Re-ingest records.
    if ids:
        for idxs in _batched(list(range(len(ids))), 500):
            b_ids = [ids[i] for i in idxs]
            b_docs = [(docs[i] or "") for i in idxs]
            b_metas = [_sanitize_metadata(metas[i]) for i in idxs]

            # Prefer to reuse embeddings when supported; fall back to doc-based embeddings.
            if embeds is not None:
                b_embeds = [embeds[i] for i in idxs]
                try:
                    new_col.add(  # type: ignore[misc]
                        ids=b_ids,
                        documents=b_docs,
                        metadatas=b_metas,
                        embeddings=b_embeds,
                    )
                    continue
                except TypeError:
                    pass
                except Exception as e:
                    _log().warning(
                        "Failed to add batch with embeddings to '%s' (%s). Retrying without embeddings.",
                        name,
                        e,
                    )

            try:
                new_col.add(ids=b_ids, documents=b_docs, metadatas=b_metas)  # type: ignore[misc]
            except Exception as e:
                _log().warning("Failed to add records back to '%s': %s", name, e)
                return False

    _log().info("Rebuilt collection '%s' (restored %d records).", name, len(ids))
    return True


def validate_index(conn: Any, collection: str) -> Dict[str, Any]:
    """
    Validate a collection index for basic integrity.

    Checks:
    - Missing IDs (empty/None)
    - Duplicate IDs

    Args:
        conn: KBConnection instance or raw Chroma client.
        collection: Collection name.

    Returns:
        dict: {
            "is_valid": bool,
            "doc_count": int,
            "missing_ids": list[str],
            "duplicate_ids": list[str]
        }
    """
    _require_chromadb()
    client = _unwrap_client(conn)

    if not isinstance(collection, str) or not collection.strip():
        raise ValueError("collection must be a non-empty string")

    name = collection.strip()
    col = _get_collection(client, name)

    if col is None:
        return {
            "is_valid": False,
            "doc_count": 0,
            "missing_ids": [],
            "duplicate_ids": [],
            "error": "COLLECTION_NOT_FOUND",
        }

    try:
        doc_count = int(col.count())
    except Exception:
        doc_count = 0

    ids_all: List[Any] = []
    for page in _paged_get(col, include=["metadatas"]):
        ids_all.extend(page.get("ids") or [])

    missing_ids: List[str] = []
    normalized_ids: List[str] = []

    for raw_id in ids_all:
        if not isinstance(raw_id, str) or not raw_id.strip():
            missing_ids.append(str(raw_id))
            continue
        normalized_ids.append(raw_id)

    seen = set()
    duplicates = set()
    for _id in normalized_ids:
        if _id in seen:
            duplicates.add(_id)
        else:
            seen.add(_id)

    duplicate_ids = sorted(duplicates)
    is_valid = (len(missing_ids) == 0) and (len(duplicate_ids) == 0)

    return {
        "is_valid": is_valid,
        "doc_count": doc_count if doc_count else len(normalized_ids),
        "missing_ids": missing_ids,
        "duplicate_ids": duplicate_ids,
    }


def get_index_health(conn: Any) -> Dict[str, Any]:
    """
    Compute health across ALL collections.

    Health is derived from validate_index() results.

    Args:
        conn: KBConnection instance or raw Chroma client.

    Returns:
        dict with keys:
          - collections: list[dict]
          - total_docs: int
          - health_score: int (0-100)
          - issues_found: int
    """
    _require_chromadb()
    client = _unwrap_client(conn)
    names = _list_collection_names(client)

    per: List[Dict[str, Any]] = []
    total_docs = 0
    issues_found = 0
    scores: List[int] = []

    for name in names:
        v = validate_index(client, name)
        doc_count = int(v.get("doc_count") or 0)
        total_docs += doc_count

        miss = v.get("missing_ids") or []
        dup = v.get("duplicate_ids") or []
        issue_count = int(len(miss) + len(dup))
        issues_found += issue_count

        score = 100 if issue_count == 0 else max(0, 100 - min(100, issue_count * 10))
        scores.append(score)

        per.append(
            {
                "name": name,
                "doc_count": doc_count,
                "is_valid": bool(v.get("is_valid")),
                "issue_count": issue_count,
            }
        )

    health_score = 100 if not scores else int(round(sum(scores) / len(scores)))

    return {
        "collections": per,
        "total_docs": total_docs,
        "health_score": health_score,
        "issues_found": issues_found,
    }


def optimize_collection(conn: Any, collection: str) -> Dict[str, Any]:
    """
    Optimize a collection by removing orphaned docs and fixing metadata gaps.

    Rules:
    - Remove records whose document text is empty/whitespace.
    - Ensure metadata is a dict and values are Chroma primitives.
    - Ensure common metadata keys exist:
        - group_id (KBG-...)     [generated if missing]
        - collection             [set to collection name]
        - ingested_at            [UTC ISO, generated if missing]
        - source                 ["unknown" if missing]
        - chunk_index            [default 0]
        - chunk_count            [default 1]

    Args:
        conn: KBConnection instance or raw Chroma client.
        collection: Collection name.

    Returns:
        dict: {docs_removed, docs_fixed, time_taken_ms}
    """
    _require_chromadb()
    client = _unwrap_client(conn)

    if not isinstance(collection, str) or not collection.strip():
        raise ValueError("collection must be a non-empty string")

    name = collection.strip()
    col = _get_collection(client, name)

    if col is None:
        return {
            "docs_removed": 0,
            "docs_fixed": 0,
            "time_taken_ms": 0,
            "error": "COLLECTION_NOT_FOUND",
        }

    t0 = time.perf_counter()
    ids, docs, metas, _ = _read_all_records(col, want_embeddings=False)

    ids_to_delete: List[str] = []
    fix_ids: List[str] = []
    fix_metas: List[Dict[str, Any]] = []
    now_iso = _utc_now_iso()

    for i in range(len(ids)):
        _id = ids[i]
        doc = (docs[i] or "").strip()
        md = metas[i] if isinstance(metas[i], dict) else {}

        # Orphan rule: empty document.
        if not doc:
            ids_to_delete.append(_id)
            continue

        md_changed = False

        if not isinstance(md, dict):
            md = {}
            md_changed = True

        if not md.get("group_id"):
            md["group_id"] = _new_id(_GROUP_PREFIX)
            md_changed = True

        if md.get("collection") != name:
            md["collection"] = name
            md_changed = True

        if not md.get("ingested_at"):
            md["ingested_at"] = now_iso
            md_changed = True

        if not md.get("source"):
            md["source"] = "unknown"
            md_changed = True

        if "chunk_index" not in md:
            md["chunk_index"] = 0
            md_changed = True

        if "chunk_count" not in md:
            md["chunk_count"] = 1
            md_changed = True

        # Normalize chunk_index / chunk_count to sane ints.
        try:
            ci = int(md.get("chunk_index", 0))
            cc = int(md.get("chunk_count", 1))
            if ci < 0:
                md["chunk_index"] = 0
                md_changed = True
                ci = 0
            if cc < 1:
                md["chunk_count"] = 1
                md_changed = True
                cc = 1
            if ci >= cc:
                md["chunk_count"] = ci + 1
                md_changed = True
        except Exception:
            md["chunk_index"] = 0
            md["chunk_count"] = 1
            md_changed = True

        sanitized = _sanitize_metadata(md)
        if sanitized != md:
            md = sanitized
            md_changed = True

        if md_changed:
            fix_ids.append(_id)
            fix_metas.append(md)

    # Apply deletions first (removes dead records from subsequent updates).
    docs_removed = 0
    if ids_to_delete:
        for batch in _batched(ids_to_delete, 500):
            try:
                col.delete(ids=list(batch))  # type: ignore[misc]
                docs_removed += len(batch)
            except Exception as e:
                _log().warning(
                    "Failed to delete %d orphaned docs from '%s': %s",
                    len(batch),
                    name,
                    e,
                )

    docs_fixed = 0
    if fix_ids:
        fallback_ids: List[str] = []

        # Preferred: update() if available and supports metadatas-only updates.
        if hasattr(col, "update"):
            for start in range(0, len(fix_ids), 500):
                b_ids = fix_ids[start : start + 500]
                b_metas = fix_metas[start : start + 500]
                try:
                    col.update(ids=b_ids, metadatas=b_metas)  # type: ignore[misc]
                    docs_fixed += len(b_ids)
                except TypeError:
                    # update() exists but signature differs; fall back to delete+add for all.
                    fallback_ids = fix_ids[:]
                    docs_fixed = 0
                    break
                except Exception as e:
                    _log().warning(
                        "Failed to update metadata batch in '%s': %s", name, e
                    )
                    fallback_ids.extend(b_ids)
        else:
            fallback_ids = fix_ids[:]

        # Fallback: delete+add for any IDs not updated (or when update isn't supported).
        if fallback_ids:
            doc_map = {ids[i]: (docs[i] or "") for i in range(len(ids))}
            meta_map = {fix_ids[i]: fix_metas[i] for i in range(len(fix_ids))}

            for batch in _batched(fallback_ids, 200):
                b_ids = list(batch)
                b_docs = [(doc_map.get(_id) or "") for _id in b_ids]
                b_metas = [meta_map.get(_id, {}) for _id in b_ids]

                try:
                    col.delete(ids=b_ids)  # type: ignore[misc]
                except Exception:
                    continue

                try:
                    col.add(ids=b_ids, documents=b_docs, metadatas=b_metas)  # type: ignore[misc]
                    docs_fixed += len(b_ids)
                except Exception as e:
                    _log().warning("Failed to re-add fixed docs in '%s': %s", name, e)

    elapsed_ms = int(round((time.perf_counter() - t0) * 1000))

    return {
        "docs_removed": docs_removed,
        "docs_fixed": docs_fixed,
        "time_taken_ms": elapsed_ms,
    }


def export_index_manifest(conn: Any) -> Dict[str, Any]:
    """
    Export a manifest snapshot of all collection-level metadata.

    This is intended for lightweight backup/restore metadata, not for exporting
    full documents.

    Args:
        conn: KBConnection instance or raw Chroma client.

    Returns:
        dict: Manifest payload with collection names, metadata, doc counts, and basic health.
    """
    _require_chromadb()
    client = _unwrap_client(conn)
    kb_path = _resolve_kb_path(conn)
    names = _list_collection_names(client)

    collections: List[Dict[str, Any]] = []
    total_docs = 0

    for name in names:
        col = _get_collection(client, name)

        if col is None:
            collections.append({"name": name, "error": "COLLECTION_NOT_FOUND"})
            continue

        try:
            doc_count = int(col.count())
        except Exception:
            doc_count = 0

        # Best-effort last_ingested extraction by scanning metadatas.
        last_ingested: Optional[str] = None
        try:
            for page in _paged_get(col, include=["metadatas"]):
                metas = page.get("metadatas") or []
                for md in metas:
                    if not isinstance(md, dict):
                        continue
                    ts = md.get("ingested_at")
                    if isinstance(ts, str) and (
                        last_ingested is None or ts > last_ingested
                    ):
                        last_ingested = ts
        except Exception:
            last_ingested = None

        meta = _collection_metadata(col)

        collections.append(
            {
                "name": name,
                "metadata": meta,
                "doc_count": doc_count,
                "last_ingested": last_ingested,
            }
        )
        total_docs += doc_count

    manifest: Dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "kb_path": kb_path,
        "chroma_version": getattr(chromadb, "__version__", None),
        "collection_count": len(names),
        "total_docs": total_docs,
        "collections": collections,
        "health": get_index_health(client),
    }

    return manifest
