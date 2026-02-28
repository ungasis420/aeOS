"""db_connect.py
SQLite connection manager for aeOS.
Database file location: ../db/aeOS.db (relative to the scripts folder).
"""
from __future__ import annotations
import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional, Union
logger = logging.getLogger(__name__)
# Default DB path is relative to this file (expected to live in /scripts).
_DEFAULT_DB_PATH = (Path(__file__).resolve().parent / ".." / "db" / "aeOS.db").resolve()
def get_connection(db_path: Union[str, Path, None] = None, timeout: float = 30.0) -> sqlite3.Connection:
    """Return a configured sqlite3 connection.
    Guarantees:
    - WAL mode enabled
    - Foreign keys enabled
    - row_factory = sqlite3.Row
    """
    path = Path(db_path) if db_path is not None else _DEFAULT_DB_PATH
    # SQLite creates the DB file if missing, but it cannot create parent folders.
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("Failed to ensure database directory exists: %s", path.parent)
        raise
    try:
        conn = sqlite3.connect(
            str(path),
            timeout=timeout,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
    except sqlite3.Error:
        logger.exception("Failed to connect to SQLite database at: %s", path)
        raise
    try:
        _configure_connection(conn)
    except sqlite3.Error:
        # Avoid leaking open handles if PRAGMA setup fails.
        logger.exception("Failed to configure SQLite connection")
        close_connection(conn)
        raise
    return conn
def close_connection(conn: Optional[sqlite3.Connection]) -> None:
    """Safely close a sqlite3 connection."""
    if conn is None:
        return
    try:
        conn.close()
    except Exception:
        logger.exception("Error while closing SQLite connection")
def execute_query(conn: sqlite3.Connection, sql: str, params: Any = None) -> sqlite3.Cursor:
    """Safely execute a single SQL statement.
    Returns:
        sqlite3.Cursor: caller can fetch rows or check rowcount.
    Behavior:
    - Commits automatically for write statements (INSERT/UPDATE/DELETE/DDL).
    - Does not commit for read statements (SELECT/PRAGMA/WITH).
    - On error: logs + best-effort rollback, then re-raises.
    """
    if conn is None:
        raise ValueError("execute_query() requires a valid sqlite3.Connection")
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("execute_query() requires a non-empty SQL string")
    bound_params = () if params is None else params
    try:
        cur = conn.execute(sql, bound_params)
        if _should_commit(sql):
            conn.commit()
        return cur
    except sqlite3.Error:
        logger.exception("SQLite query failed. SQL=%r Params=%r", _trim_sql(sql), bound_params)
        # Best-effort rollback to leave connection in a clean state.
        try:
            conn.rollback()
        except sqlite3.Error:
            logger.exception("SQLite rollback failed after query error")
        raise
def _configure_connection(conn: sqlite3.Connection) -> None:
    """Apply required PRAGMA settings and row factory."""
    conn.row_factory = sqlite3.Row
    # Enforce constraints + improve concurrency.
    conn.execute("PRAGMA foreign_keys = ON;")
    mode_row = conn.execute("PRAGMA journal_mode = WAL;").fetchone()
    if mode_row and isinstance(mode_row[0], str) and mode_row[0].lower() != "wal":
        logger.warning("Requested WAL mode, but SQLite reported journal_mode=%s", mode_row[0])
    # Pragmas below are safe defaults; adjust later only if you have a reason.
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
def _should_commit(sql: str) -> bool:
    """Return True if the statement likely mutates the database."""
    stripped = sql.lstrip()
    if not stripped:
        return False
    first_token = stripped.split(None, 1)[0].upper()
    return first_token in {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER", "VACUUM"}
def _trim_sql(sql: str, limit: int = 500) -> str:
    """Trim SQL for logging to avoid dumping huge statements."""
    compact = " ".join(sql.split())
    return compact if len(compact) <= limit else (compact[: limit - 3] + "...")
