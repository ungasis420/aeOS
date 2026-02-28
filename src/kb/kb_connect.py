"""src/kb/kb_connect.py
ChromaDB connection manager for the aeOS Knowledge Base (KB) layer.
This module provides:
- KBConnection: a thin wrapper over a persistent ChromaDB client.
- Convenience functions for common collection operations.
Design goals:
- Persist all KB data under core.config.KB_PATH by default.
- Keep the surface area small and predictable for kb_ingest/kb_search/kb_index.
- Support both modern and legacy ChromaDB client constructors.
Allowed third-party dependency for this layer: chromadb
"""
from __future__ import annotations
import inspect
import os
from typing import Any, Dict, List, Optional

__all__ = [
    "KBConnection",
    "get_kb_connection",
    "list_collections",
    "create_collection",
    "delete_collection",
]

# --- Internal imports (with safe fallbacks for different PYTHONPATH layouts) ---
try:
    # Typical runtime layout when `src/` is on PYTHONPATH.
    from core.config import KB_PATH  # type: ignore
except Exception:  # pragma: no cover - fallback path
    try:
        # Alternate layout when importing as a package.
        from src.core.config import KB_PATH  # type: ignore
    except Exception:  # pragma: no cover - last-resort fallback
        KB_PATH = os.path.join(os.getcwd(), "kb")

try:
    from core.logger import get_logger  # type: ignore
except Exception:  # pragma: no cover - fallback path
    try:
        from src.core.logger import get_logger  # type: ignore
    except Exception:  # pragma: no cover - last-resort fallback
        import logging

        def get_logger(name: str) -> "logging.Logger":  # type: ignore
            """Fallback logger if aeOS logger.py is unavailable."""
            logging.basicConfig(level=logging.INFO)
            return logging.getLogger(name)

# Some aeOS builds may expose get_logger() with no args.
try:
    _log = get_logger(__name__)
except TypeError:  # pragma: no cover
    _log = get_logger()  # type: ignore

# --- Optional third-party dependency (ChromaDB) ---
try:
    import chromadb  # type: ignore
    from chromadb.config import Settings  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    chromadb = None  # type: ignore
    Settings = None  # type: ignore


def _require_chromadb() -> Any:
    """Raise a clear error if ChromaDB is not installed."""
    if chromadb is None:
        raise ModuleNotFoundError(
            "chromadb is required for the aeOS KB layer. Install with: pip install chromadb"
        )
    return chromadb


def _resolve_kb_path(path: Optional[str]) -> str:
    """Resolve and normalize the ChromaDB persistence directory.

    Args:
        path: Optional explicit path. If empty/None, defaults to KB_PATH from core.config.

    Returns:
        Absolute path to a directory suitable for ChromaDB persistent storage.
    """
    raw = (path or "").strip()
    resolved = raw if raw else str(KB_PATH)
    return os.path.abspath(os.path.expanduser(resolved))


def _ensure_dir(path: str) -> None:
    """Ensure a directory exists (idempotent)."""
    os.makedirs(path, exist_ok=True)


def _unwrap_client(conn: Any) -> Any:
    """Return a Chroma client from either a KBConnection or a raw client."""
    if isinstance(conn, KBConnection):
        conn.connect()
        return conn.client
    return conn


class KBConnection:
    """ChromaDB connection manager for the aeOS Knowledge Base layer.

    The KB is stored as a persistent ChromaDB database on disk. This class manages
    client construction and provides a stable interface for downstream modules.

    Notes:
        - `connect()` is idempotent.
        - ChromaDB versions vary; `connect()` includes a legacy fallback path.
    """

    def __init__(
        self,
        path: Optional[str] = None,
        *,
        tenant: Optional[str] = None,
        database: Optional[str] = None,
    ) -> None:
        self._path = path
        self._tenant = tenant
        self._database = database
        self._client: Any = None

    @property
    def path(self) -> str:
        """Resolved persistence directory used by this connection."""
        return _resolve_kb_path(self._path)

    @property
    def client(self) -> Any:
        """Underlying ChromaDB client (only available after connect())."""
        if self._client is None:
            raise RuntimeError("KBConnection is not connected. Call connect() first.")
        return self._client

    def connect(self) -> "KBConnection":
        """Create and cache a persistent ChromaDB client (idempotent).

        Returns:
            Self, so callers can chain: `conn = KBConnection().connect()`.
        """
        if self._client is not None:
            return self

        chroma = _require_chromadb()
        persist_path = self.path
        _ensure_dir(persist_path)

        # Preferred modern API: chromadb.PersistentClient(path=...).
        if hasattr(chroma, "PersistentClient"):
            try:
                # Some Chroma versions support tenant/database (multi-tenancy).
                # We probe the signature to avoid passing unsupported kwargs.
                kwargs: Dict[str, Any] = {}
                try:
                    sig = inspect.signature(chroma.PersistentClient)
                except Exception:  # pragma: no cover
                    sig = None

                if sig is not None:
                    if "path" in sig.parameters:
                        kwargs["path"] = persist_path
                    elif "persist_directory" in sig.parameters:
                        kwargs["persist_directory"] = persist_path
                    else:
                        # Most common parameter name is `path`.
                        kwargs["path"] = persist_path

                    if self._tenant is not None and "tenant" in sig.parameters:
                        kwargs["tenant"] = self._tenant
                    if self._database is not None and "database" in sig.parameters:
                        kwargs["database"] = self._database
                else:
                    kwargs = {"path": persist_path}

                self._client = chroma.PersistentClient(**kwargs)
                _log.debug("Connected to ChromaDB PersistentClient at %s", persist_path)
                return self
            except Exception as e:
                # If modern init fails, fall back to the older Settings-based client.
                _log.warning(
                    "PersistentClient init failed (%s). Falling back to legacy Settings client.",
                    e,
                )

        # Legacy API fallback: chromadb.Client(Settings(..., persist_directory=...))
        if Settings is None:
            raise RuntimeError(
                "chromadb is installed but chromadb.config.Settings is unavailable; cannot create legacy client."
            )

        settings = Settings(
            chroma_db_impl="duckdb+parquet",
            persist_directory=persist_path,
        )
        self._client = chroma.Client(settings)
        _log.debug("Connected to ChromaDB legacy Client at %s", persist_path)
        return self

    def disconnect(self) -> None:
        """Release the cached Chroma client handle (idempotent).

        Chroma does not consistently expose an explicit close() method across versions.
        This method performs a best-effort close if available and clears the handle.
        """
        if self._client is None:
            return
        # Best-effort close if the client exposes it.
        try:
            close_fn = getattr(self._client, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:  # pragma: no cover
            pass
        self._client = None

    def get_collection(
        self,
        name: str,
        *,
        create_if_missing: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Get a collection by name, optionally creating it.

        Args:
            name: Collection name.
            create_if_missing: If True, create the collection if it does not exist.
            metadata: Optional collection metadata (stored by Chroma).

        Returns:
            A ChromaDB collection object.
        """
        self.connect()
        client = self.client
        meta = metadata or {}

        if create_if_missing and hasattr(client, "get_or_create_collection"):
            return client.get_or_create_collection(name=name, metadata=meta)

        if create_if_missing:
            try:
                return client.get_collection(name=name)
            except Exception:
                return client.create_collection(name=name, metadata=meta)

        return client.get_collection(name=name)

    # Context manager support: `with KBConnection() as conn: ...`
    def __enter__(self) -> "KBConnection":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.disconnect()


def get_kb_connection(path: str) -> KBConnection:
    """Factory that returns a connected KBConnection.

    Args:
        path: Persistence directory for ChromaDB. If empty, falls back to KB_PATH.

    Returns:
        Connected KBConnection instance.
    """
    conn = KBConnection(path=path)
    conn.connect()
    return conn


def list_collections(conn: Any) -> List[str]:
    """List collection names for the given connection/client.

    Args:
        conn: Either a KBConnection instance or a raw Chroma client.

    Returns:
        List of collection names.
    """
    client = _unwrap_client(conn)
    cols = client.list_collections()

    names: List[str] = []
    # Different Chroma versions return different shapes; normalize to names.
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


def create_collection(conn: Any, name: str, metadata: Dict[str, Any]) -> Any:
    """Create a collection (or return existing if already present).

    Args:
        conn: Either a KBConnection instance or a raw Chroma client.
        name: Collection name.
        metadata: Collection metadata dictionary.

    Returns:
        A ChromaDB collection object.
    """
    client = _unwrap_client(conn)
    meta = metadata or {}

    # Prefer idempotent API when available.
    if hasattr(client, "get_or_create_collection"):
        return client.get_or_create_collection(name=name, metadata=meta)

    try:
        return client.create_collection(name=name, metadata=meta)
    except Exception:
        # If it already exists (or create fails), return the existing collection.
        return client.get_collection(name=name)


def delete_collection(conn: Any, name: str) -> bool:
    """Delete a collection by name.

    Args:
        conn: Either a KBConnection instance or a raw Chroma client.
        name: Collection name.

    Returns:
        True if delete succeeded, False if the collection did not exist (or delete failed).
    """
    client = _unwrap_client(conn)
    try:
        client.delete_collection(name=name)
        return True
    except Exception:
        return False
