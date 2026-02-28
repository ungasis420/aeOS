"""
db_init.py
SQLite schema bootstrap + migrations scaffold for aeOS.
This module is responsible for:
- Initializing the SQLite database schema from the canonical SQL file
  (aeOS_PERSIST_v1.0.sql).
- Tracking which schema version has been applied via `schema_migrations`.
- Providing lightweight verification and dev-only reset helpers.
Design constraints
------------------
- Uses `sqlite3` (stdlib) only for DB operations.
- Does NOT duplicate connection configuration logic; it imports and uses
  `get_connection()` from `db_connect.py`.
Notes
-----
- The aeOS_PERSIST_v1.0.sql script is *destructive* (it drops and recreates
  tables). This is why `run_migrations()` must skip execution when the
  migration version is already recorded as applied.
Public API
----------
- run_migrations(db_path: str, sql_path: str) -> bool
- get_schema_version(db_path: str) -> str
- verify_tables(db_path: str) -> dict
- reset_db(db_path: str, confirm: bool = False) -> bool
"""
from __future__ import annotations
import hashlib
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from db_connect import close_connection, get_connection
logger = logging.getLogger(__name__)
# Library-style module: don't configure global logging; avoid "No handler" warnings.
logger.addHandler(logging.NullHandler())
# -----------------------------------------------------------------------------
# Expected tables (37) — derived from aeOS_PERSIST_v1.0.sql CREATE TABLE list.
# -----------------------------------------------------------------------------
EXPECTED_TABLES: Tuple[str, ...] = (
    "CT_Stage",
    "CT_Category",
    "CT_Rev_Model",
    "CT_Source",
    "CT_Priority",
    "CT_Freq",
    "CT_Phase",
    "CT_Impact",
    "CT_Complexity",
    "CT_Horizon",
    "CT_Outcome",
    "CT_Cog_State",
    "CT_Scenario",
    "CT_Sol_Type",
    "CT_Sol_Status",
    "CT_Pain_Status",
    "CT_NM_Type",
    "CT_Bias",
    "CT_MM_Category",
    "CT_Feedback_Type",
    "CT_Loop_Polarity",
    "CT_Loop_Speed",
    "CT_Reversibility",
    "CT_Exec_Status",
    "CT_Suggestion_Type",
    "Pain_Point_Register",
    "MoneyScan_Records",
    "Solution_Design",
    "Non_Monetary_Ledger",
    "Prediction_Registry",
    "Bias_Audit_Log",
    "Scenario_Map",
    "Decision_Tree_Log",
    "Synergy_Map",
    "Mental_Models_Registry",
    "Calibration_Ledger",
    "Project_Execution_Log",
)
# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------
def _now_iso_utc() -> str:
    """Return an ISO-8601 datetime string in UTC with explicit timezone offset."""
    return datetime.now(timezone.utc).isoformat()
def _as_path(value: str, *, name: str) -> Path:
    """Validate a string path and return it as a resolved Path (no FS touch)."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return Path(value).expanduser().resolve()
def _sha256_file(path: Path) -> str:
    """Compute SHA-256 checksum for a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
_VERSION_RE = re.compile(r"_v(\d+\.\d+(?:\.\d+)?)", re.IGNORECASE)
def _infer_version_from_sql_path(sql_path: Path) -> str:
    """Infer a semver-ish version string from the SQL filename.
    Example:
        aeOS_PERSIST_v1.0.sql -> "1.0.0"
    If no version is found, returns "0.0.0".
    """
    m = _VERSION_RE.search(sql_path.name)
    if not m:
        return "0.0.0"
    raw = m.group(1)
    parts = raw.split(".")
    # Normalize to MAJOR.MINOR.PATCH
    if len(parts) == 2:
        parts.append("0")
    # Defensive: if still malformed, fall back.
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return "0.0.0"
    return ".".join(parts)
def _ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    """Create the schema_migrations table if it doesn't exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY,
            version TEXT,
            applied_at TEXT,
            checksum TEXT
        );
        """
    )
def _schema_migrations_exists(conn: sqlite3.Connection) -> bool:
    """Return True if schema_migrations exists in the database."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations' LIMIT 1;"
    ).fetchone()
    return row is not None
def _migration_version_exists(conn: sqlite3.Connection, version: str) -> Tuple[bool, Optional[str]]:
    """Check whether a migration version is already recorded.
    Returns:
        (exists, checksum_if_found)
    """
    row = conn.execute(
        "SELECT checksum FROM schema_migrations WHERE version = ? ORDER BY id DESC LIMIT 1;",
        (version,),
    ).fetchone()
    if row is None:
        return False, None
    checksum = None
    try:
        checksum = str(row[0]) if row[0] is not None else None
    except Exception:
        checksum = None
    return True, checksum
def _resolve_default_sql_path() -> Path:
    """Best-effort resolution for the canonical SQL file.
    This is used by reset_db() (dev-only) so callers don't need to pass sql_path.
    Search order:
      1) AEOS_PERSIST_SQL_PATH env var
      2) project_root/db/aeOS_PERSIST_v1.0.sql (assuming this module is src/db/)
      3) project_root/aeOS_PERSIST_v1.0.sql
    Raises:
        FileNotFoundError if not found.
    """
    env = os.getenv("AEOS_PERSIST_SQL_PATH", "").strip()
    if env:
        p = Path(env).expanduser().resolve()
        if p.exists():
            return p
    here = Path(__file__).resolve()
    # If this file is src/db/db_init.py -> project root is parents[2].
    # (db_init.py -> db -> src -> <root>)
    candidates: List[Path] = []
    if len(here.parents) >= 3:
        project_root = here.parents[2]
        candidates.extend(
            [
                project_root / "db" / "aeOS_PERSIST_v1.0.sql",
                project_root / "aeOS_PERSIST_v1.0.sql",
            ]
        )
    for c in candidates:
        if c.exists():
            return c.resolve()
    raise FileNotFoundError(
        "Could not locate aeOS_PERSIST_v1.0.sql. Set AEOS_PERSIST_SQL_PATH or place the file in <root>/db/."
    )
# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
def run_migrations(db_path: str, sql_path: str) -> bool:
    """Run the schema migration if it has not been applied yet.
    Behavior:
      - Reads the SQL file at `sql_path` (expected: aeOS_PERSIST_v1.0.sql).
      - Ensures `schema_migrations` exists.
      - Skips execution if the inferred schema version is already recorded.
      - On successful execution, inserts a row into `schema_migrations`.
    Important:
      The aeOS_PERSIST SQL script drops and recreates tables. This function
      *must* be version-gated to avoid destroying user data.
    Args:
        db_path: Path to SQLite database file.
        sql_path: Path to aeOS_PERSIST_v1.0.sql.
    Returns:
        True if the migration ran and was recorded.
        False if the database is already up-to-date (migration already applied).
    Raises:
        ValueError: If inputs are invalid.
        FileNotFoundError: If the SQL file does not exist.
        sqlite3.Error: If SQL execution fails.
        OSError: If file operations fail.
    """
    db_p = _as_path(db_path, name="db_path")
    sql_p = _as_path(sql_path, name="sql_path")
    if not sql_p.exists():
        raise FileNotFoundError(f"SQL file not found: {sql_p}")
    version = _infer_version_from_sql_path(sql_p)
    checksum = _sha256_file(sql_p)
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = get_connection(db_p)
        # Create migrations table (and commit) *before* running the SQL script.
        _ensure_schema_migrations_table(conn)
        conn.commit()
        already_applied, stored_checksum = _migration_version_exists(conn, version)
        if already_applied:
            if stored_checksum and stored_checksum != checksum:
                logger.warning(
                    "Migration version %s already applied but checksum differs. "
                    "Stored=%s Current=%s. You may have edited the SQL without bumping the version.",
                    version,
                    stored_checksum,
                    checksum,
                )
            return False
        sql_text = sql_p.read_text(encoding="utf-8")
        if not sql_text.strip():
            raise ValueError(f"SQL file is empty: {sql_p}")
        # executescript is the safest way to run a full schema file.
        # aeOS_PERSIST_v1.0.sql includes its own BEGIN/COMMIT transaction.
        conn.executescript(sql_text)
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at, checksum) VALUES (?, ?, ?);",
            (version, _now_iso_utc(), checksum),
        )
        conn.commit()
        return True
    finally:
        close_connection(conn)
def get_schema_version(db_path: str) -> str:
    """Return the current schema version recorded in schema_migrations.
    Args:
        db_path: Path to SQLite database file.
    Returns:
        Latest migration version (string) if present; otherwise "0.0.0".
    Raises:
        ValueError: If db_path is invalid.
        sqlite3.Error: If a database error occurs.
    """
    db_p = _as_path(db_path, name="db_path")
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = get_connection(db_p)
        if not _schema_migrations_exists(conn):
            return "0.0.0"
        row = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY id DESC LIMIT 1;"
        ).fetchone()
        if row is None or row[0] is None:
            return "0.0.0"
        return str(row[0])
    finally:
        close_connection(conn)
def verify_tables(db_path: str) -> Dict[str, object]:
    """Verify that all expected tables exist in the SQLite database.
    This checks for the 37 expected tables created by aeOS_PERSIST_v1.0.sql.
    Args:
        db_path: Path to SQLite database file.
    Returns:
        dict with keys:
          - expected: int (always 37)
          - found: int
          - missing: list[str]
          - status: "ok" | "incomplete"
    Raises:
        ValueError: If db_path is invalid.
        sqlite3.Error: If a database error occurs.
    """
    db_p = _as_path(db_path, name="db_path")
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = get_connection(db_p)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
        ).fetchall()
        present = {str(r[0]) for r in rows if r and r[0] is not None}
        missing = [t for t in EXPECTED_TABLES if t not in present]
        found = len(EXPECTED_TABLES) - len(missing)
        return {
            "expected": len(EXPECTED_TABLES),
            "found": found,
            "missing": missing,
            "status": "ok" if not missing else "incomplete",
        }
    finally:
        close_connection(conn)
def reset_db(db_path: str, confirm: bool = False) -> bool:
    """DEV ONLY: Drop and recreate the entire database.
    ⚠️ WARNING (DEV ONLY)
    ---------------------
    This deletes the SQLite database file and its WAL/SHM sidecar files.
    Use only in development or when you explicitly want to lose all data.
    Safety guard:
      - Does nothing unless confirm=True.
    Behavior when confirm=True:
      - Deletes db file, db-wal, db-shm if present.
      - Recreates schema by running the canonical migration SQL if it can be found.
    Args:
        db_path: Path to SQLite database file.
        confirm: Must be True to execute.
    Returns:
        False immediately if confirm=False.
        True if reset succeeded.
    Raises:
        ValueError: If db_path is invalid.
        FileNotFoundError: If SQL file cannot be located for re-init.
        sqlite3.Error: If schema recreation fails.
        OSError: If file deletion fails.
    """
    if confirm is not True:
        return False
    db_p = _as_path(db_path, name="db_path")
    # Delete main db + sidecars (WAL mode creates -wal and -shm)
    sidecars = [db_p, db_p.with_suffix(db_p.suffix + "-wal"), db_p.with_suffix(db_p.suffix + "-shm")]
    for p in sidecars:
        try:
            if p.exists():
                p.unlink()
        except OSError:
            logger.exception("Failed to delete database file: %s", p)
            raise
    # Recreate schema using canonical SQL file.
    sql_p = _resolve_default_sql_path()
    # For a fresh DB, run_migrations will always apply and return True.
    run_migrations(str(db_p), str(sql_p))
    return True
__all__ = [
    "EXPECTED_TABLES",
    "run_migrations",
    "get_schema_version",
    "verify_tables",
    "reset_db",
]
