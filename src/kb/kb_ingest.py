"""
kb_ingest.py
Stamp: S✅ T✅ L✅ A✅
aeOS Phase 3 — Layer 1 (Knowledge Base)
Purpose
-------
Ingest text and documents into ChromaDB collections for the aeOS
Knowledge Base.
Key behaviors (by requirement)
------------------------------
- ingest_text(): chunk text (500 chars, 50 overlap) → returns document_id
- ingest_file(): read .txt/.md, split by paragraph, chunk each paragraph → returns document_ids
- ingest_batch(): bulk ingest (each item: text + metadata) → returns document_ids
- delete_document(): delete a chunk id OR a logical document id
- get_ingestion_stats(): total_docs, last_ingested, collection_size_mb
Implementation notes
--------------------
ChromaDB stores *chunks*. To keep a single "document_id" per logical doc,
we generate a `group_id` (prefix KBG-...) and store that `group_id` in
each chunk's metadata. The returned `document_id` is the `group_id`.
Deletion supports:
- doc_id == chunk id (KBD-...) → deletes that chunk only
- doc_id == group id (KBG-...) → deletes all chunks with metadata.group_id == doc_id
Dependencies
------------
- chromadb (allowed in KB layer)
- stdlib only for file reading and utilities
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from itertools import count
from typing import Any, Dict, Iterable, List, Optional

# ---------------------------------------------------------------------------
# Optional aeOS imports (keep module usable in isolation/tests)
# ---------------------------------------------------------------------------
try:
    from ..core.config import KB_PATH  # type: ignore
except Exception:  # pragma: no cover
    try:
        from src.core.config import KB_PATH  # type: ignore
    except Exception:  # pragma: no cover
        KB_PATH = None  # type: ignore

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


DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50

_GROUP_PREFIX = "KBG"  # logical document id
_CHUNK_PREFIX = "KBD"  # physical chunk id stored in Chroma

# Seed counter with ms to reduce collision risk across runs.
_ID_COUNTER = count(start=int(time.time() * 1000) % 1_000_000)

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


def _utc_now_iso() -> str:
    """UTC timestamp as ISO-8601 string (lexicographically sortable)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id(prefix: str) -> str:
    """Create PREFIX-YYYYMMDD-NNN (NNN numeric, width >= 3)."""
    yyyymmdd = datetime.now(timezone.utc).strftime("%Y%m%d")
    seq = next(_ID_COUNTER)
    return f"{prefix}-{yyyymmdd}-{seq:03d}"


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
        # Lists/dicts/tuples/etc → JSON string
        try:
            out[str(k)] = json.dumps(v, ensure_ascii=False, default=str)
        except Exception:
            out[str(k)] = str(v)
    return out


def _split_paragraphs(text: str) -> List[str]:
    """Split text by 1+ blank lines (works for .txt and .md)."""
    if not text:
        return []
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    parts = re.split(r"\n\s*\n+", normalized)
    return [p.strip() for p in parts if p.strip()]


def _chunk_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Chunk text into overlapping windows."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0:
        raise ValueError("overlap must be >= 0")
    if overlap >= chunk_size:
        raise ValueError("overlap must be < chunk_size")
    t = text.strip()
    if not t:
        return []
    if len(t) <= chunk_size:
        return [t]
    step = chunk_size - overlap
    chunks: List[str] = []
    for start in range(0, len(t), step):
        end = min(start + chunk_size, len(t))
        chunk = t[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(t):
            break
    return chunks


def _unwrap_client(conn: Any) -> Any:
    """If `conn` is a wrapper, try to unwrap to the underlying Chroma client."""
    for attr in ("client", "_client", "chroma", "_chroma"):
        if hasattr(conn, attr):
            return getattr(conn, attr)
    return conn


def _get_collection(conn: Any, name: str):
    """
    Get an existing Chroma collection; create if missing.

    This keeps ingestion workflows simple. If a caller needs stricter
    control over embedding_function/metadata, they can pre-create the
    collection via kb_connect helpers.
    """
    client = _unwrap_client(conn)
    if not hasattr(client, "get_collection"):
        raise TypeError("conn must provide get_collection(name)")

    try:
        return client.get_collection(name)  # type: ignore[misc]
    except Exception as e:
        if not hasattr(client, "create_collection"):
            raise
        _log().warning("Collection '%s' missing; creating it. (%s)", name, e)
        try:
            return client.create_collection(  # type: ignore[misc]
                name=name, metadata={"created_by": "kb_ingest"}
            )
        except TypeError:
            return client.create_collection(name)  # type: ignore[misc]


def _resolve_kb_path(conn: Any) -> Optional[str]:
    """Best-effort resolve KB persistence directory for size stats."""
    for obj in (conn, _unwrap_client(conn)):
        for attr in ("path", "_path", "persist_path", "_persist_path"):
            val = getattr(obj, attr, None)
            if isinstance(val, str) and val:
                return val
    if isinstance(KB_PATH, str) and KB_PATH:
        return KB_PATH
    return None


def _dir_size_bytes(path: str) -> int:
    """Compute directory (or file) size recursively."""
    if not path:
        return 0
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            fp = os.path.join(root, fn)
            try:
                total += os.path.getsize(fp)
            except OSError:
                continue
    return total


def _iter_metadatas(col: Any) -> Iterable[Dict[str, Any]]:
    """
    Iterate metadatas in a collection (paged when supported).

    This is diagnostic-only (stats), so a slower fallback is acceptable.
    """
    batch_size = 1000
    offset = 0

    # Preferred: page through (common in modern chroma versions)
    while True:
        try:
            res = col.get(include=["metadatas"], limit=batch_size, offset=offset)  # type: ignore[arg-type]
            ids = res.get("ids") or []
            metas = res.get("metadatas") or []
            for md in metas:
                if isinstance(md, dict):
                    yield md
            if not ids or len(ids) < batch_size:
                return
            offset += len(ids)
        except TypeError:
            break
        except Exception:
            break

    # Fallback: single get()
    try:
        res = col.get(include=["metadatas"])  # type: ignore[arg-type]
        metas = res.get("metadatas") or []
        for md in metas:
            if isinstance(md, dict):
                yield md
    except Exception:
        return


def ingest_text(conn: Any, collection: str, text: str, metadata: Dict[str, Any]) -> str:
    """
    Ingest a text blob into a collection (chunked) and return a document_id.

    Returns:
        str: document_id (logical group_id for all stored chunks)
    """
    col = _get_collection(conn, collection)

    chunks = _chunk_text(text, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP)
    if not chunks:
        raise ValueError("Text is empty after trimming; nothing to ingest.")

    group_id = _new_id(_GROUP_PREFIX)
    ingested_at = _utc_now_iso()
    base_md = _sanitize_metadata(metadata)
    base_md.update({"source": "text", "collection": collection, "group_id": group_id})

    ids: List[str] = []
    docs: List[str] = []
    metas: List[Dict[str, Any]] = []

    for idx, chunk in enumerate(chunks):
        ids.append(_new_id(_CHUNK_PREFIX))
        docs.append(chunk)
        md = dict(base_md)
        md.update(
            {
                "chunk_index": idx,
                "chunk_count": len(chunks),
                "ingested_at": ingested_at,
            }
        )
        metas.append(_sanitize_metadata(md))

    col.add(ids=ids, documents=docs, metadatas=metas)
    _log().info(
        "Ingested text: collection='%s' group_id='%s' chunks=%d",
        collection,
        group_id,
        len(chunks),
    )
    return group_id


def ingest_file(conn: Any, collection: str, filepath: str) -> List[str]:
    """
    Ingest a .txt or .md file. Splits by paragraph; each paragraph is a document_id.

    Returns:
        list[str]: document_ids (group_ids), one per paragraph
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(filepath)

    ext = os.path.splitext(filepath)[1].lower()
    if ext not in (".txt", ".md"):
        raise ValueError("Only .txt and .md files are supported for ingestion.")

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    paragraphs = _split_paragraphs(content)
    if not paragraphs:
        _log().warning("No ingestible content found in file: %s", filepath)
        return []

    col = _get_collection(conn, collection)

    abs_path = os.path.abspath(filepath)
    filename = os.path.basename(filepath)
    group_ids: List[str] = []
    all_ids: List[str] = []
    all_docs: List[str] = []
    all_metas: List[Dict[str, Any]] = []

    for p_idx, para in enumerate(paragraphs):
        chunks = _chunk_text(para, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP)
        if not chunks:
            continue

        group_id = _new_id(_GROUP_PREFIX)
        group_ids.append(group_id)
        ingested_at = _utc_now_iso()

        base_md = {
            "source": "file",
            "collection": collection,
            "group_id": group_id,
            "filepath": abs_path,
            "filename": filename,
            "file_ext": ext.lstrip("."),
            "paragraph_index": p_idx,
        }

        for c_idx, chunk in enumerate(chunks):
            all_ids.append(_new_id(_CHUNK_PREFIX))
            all_docs.append(chunk)
            md = dict(base_md)
            md.update(
                {
                    "chunk_index": c_idx,
                    "chunk_count": len(chunks),
                    "ingested_at": ingested_at,
                }
            )
            all_metas.append(_sanitize_metadata(md))

    if all_ids:
        col.add(ids=all_ids, documents=all_docs, metadatas=all_metas)

    _log().info(
        "Ingested file: collection='%s' file='%s' groups=%d chunks=%d",
        collection,
        abs_path,
        len(group_ids),
        len(all_ids),
    )
    return group_ids


def ingest_batch(conn: Any, collection: str, items: List[Dict[str, Any]]) -> List[str]:
    """
    Bulk ingest: each item has keys: text (str) + metadata (dict).

    Returns:
        list[str]: document_ids (group_ids) in the same order as `items`
    """
    if not items:
        return []

    col = _get_collection(conn, collection)
    group_ids: List[str] = []
    all_ids: List[str] = []
    all_docs: List[str] = []
    all_metas: List[Dict[str, Any]] = []

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise TypeError(f"items[{i}] must be a dict")

        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"items[{i}].text must be a non-empty string")

        user_md = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        extra_md = {k: v for k, v in item.items() if k not in ("text", "metadata")}
        base_md = _sanitize_metadata({**user_md, **extra_md})
        base_md.update({"source": "batch", "collection": collection})

        group_id = _new_id(_GROUP_PREFIX)
        group_ids.append(group_id)
        ingested_at = _utc_now_iso()

        chunks = _chunk_text(text, DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP)
        if not chunks:
            continue

        for c_idx, chunk in enumerate(chunks):
            all_ids.append(_new_id(_CHUNK_PREFIX))
            all_docs.append(chunk)
            md = dict(base_md)
            md.update(
                {
                    "group_id": group_id,
                    "chunk_index": c_idx,
                    "chunk_count": len(chunks),
                    "ingested_at": ingested_at,
                    "batch_index": i,
                }
            )
            all_metas.append(_sanitize_metadata(md))

    if all_ids:
        col.add(ids=all_ids, documents=all_docs, metadatas=all_metas)

    _log().info(
        "Batch ingested: collection='%s' groups=%d chunks=%d",
        collection,
        len(group_ids),
        len(all_ids),
    )
    return group_ids


def delete_document(conn: Any, collection: str, doc_id: str) -> bool:
    """
    Delete a chunk id (KBD-...) or a logical document_id/group_id (KBG-...).

    Returns:
        bool: True if something was deleted, else False
    """
    col = _get_collection(conn, collection)

    # 1) Try direct chunk-id delete.
    try:
        hit = col.get(ids=[doc_id])  # type: ignore[arg-type]
        if isinstance(hit, dict) and hit.get("ids"):
            col.delete(ids=[doc_id])  # type: ignore[arg-type]
            _log().info(
                "Deleted chunk doc_id='%s' from collection='%s'", doc_id, collection
            )
            return True
    except Exception:
        # If get(ids=...) isn't supported, continue to group delete.
        pass

    # 2) Try group-id delete.
    try:
        hit = col.get(where={"group_id": doc_id})  # type: ignore[arg-type]
        ids = hit.get("ids") if isinstance(hit, dict) else None
        if ids:
            col.delete(where={"group_id": doc_id})  # type: ignore[arg-type]
            _log().info(
                "Deleted group_id='%s' (%d chunks) from collection='%s'",
                doc_id,
                len(ids),
                collection,
            )
            return True
    except Exception as e:
        _log().warning("Failed to delete doc_id/group_id='%s': %s", doc_id, e)
        return False

    return False


def get_ingestion_stats(conn: Any, collection: str) -> Dict[str, Any]:
    """
    Get collection stats.

    Returns:
        dict: {total_docs, last_ingested, collection_size_mb}
    """
    col = _get_collection(conn, collection)

    try:
        total_docs = int(col.count())
    except Exception:
        total_docs = 0

    last_ingested: Optional[str] = None
    for md in _iter_metadatas(col):
        ts = md.get("ingested_at")
        if isinstance(ts, str) and (last_ingested is None or ts > last_ingested):
            last_ingested = ts

    kb_path = _resolve_kb_path(conn)
    size_bytes = _dir_size_bytes(kb_path) if kb_path else 0
    size_mb = round(size_bytes / (1024 * 1024), 3)

    return {
        "total_docs": total_docs,
        "last_ingested": last_ingested,
        "collection_size_mb": size_mb,
    }


__all__ = [
    "ingest_text",
    "ingest_file",
    "ingest_batch",
    "delete_document",
    "get_ingestion_stats",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_CHUNK_OVERLAP",
]
