"""
aeOS Phase 4 — Identity_Continuity_Protocol (A1)
=================================================
CRITICAL — Backup, recovery, and sovereignty guarantee for all aeOS data.

If the database is lost, aeOS loses compound intelligence, cognitive twin,
all decisions — everything. A sovereign system that can be wiped is not
truly sovereign. This is the single most critical gap.

Layer: 0 (Storage) + 9 (Century-Gap bridge)
Dependencies: PERSIST (db_connect), CRYPTO_STATE (CryptoGuard), DB

Interface Contract (from Addendum A):
    createBackup()              -> BackupManifest
    restore(path, passphrase)   -> RestoreResult
    verify()                    -> IntegrityReport
    getSchedule()               -> BackupSchedule
    setSchedule(config)         -> None
    listBackups()               -> list[BackupManifest]

Encryption: Uses CryptoGuard with hardware-bound key (AES-256-GCM).
Auto-Schedule: Daily at 3AM local. Retains: 7 daily, 4 weekly, 12 monthly.
Performance: Full backup 50K records < 30s. Restore < 60s. Verify < 10s.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BackupManifest:
    """Metadata record for a single backup snapshot."""
    backup_id: str
    created_at: str
    tables_included: List[str]
    decision_count: int
    compound_score: float
    encrypted: bool
    checksum: str
    size_bytes: int
    backup_path: Optional[str] = None
    backup_type: str = "manual"
    status: str = "complete"
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RestoreResult:
    """Result of a restore operation."""
    success: bool
    tables_restored: List[str]
    records_restored: int
    backup_id: str
    restored_at: str
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IntegrityReport:
    """Result of a database integrity verification."""
    healthy: bool
    tables_checked: int
    tables_found: int
    total_records: int
    missing_tables: List[str]
    corruption_detected: bool
    fk_violations: int
    timestamp: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BackupSchedule:
    """Auto-backup schedule configuration."""
    enabled: bool = True
    daily_hour: int = 3       # 3 AM local
    daily_minute: int = 0
    retain_daily: int = 7
    retain_weekly: int = 4
    retain_monthly: int = 12
    backup_dir: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Core tables to backup (all aeOS tables in dependency-safe order)
# ---------------------------------------------------------------------------

BACKUP_TABLES = (
    # Code tables (lookup/reference)
    "CT_Stage", "CT_Category", "CT_Rev_Model", "CT_Source",
    "CT_Priority", "CT_Freq", "CT_Phase", "CT_Impact",
    "CT_Complexity", "CT_Horizon", "CT_Outcome", "CT_Cog_State",
    "CT_Scenario", "CT_Sol_Type", "CT_Sol_Status", "CT_Pain_Status",
    "CT_NM_Type", "CT_Bias", "CT_MM_Category", "CT_Feedback_Type",
    "CT_Loop_Polarity", "CT_Loop_Speed", "CT_Reversibility",
    "CT_Exec_Status", "CT_Suggestion_Type",
    # Core data tables
    "Pain_Point_Register", "MoneyScan_Records", "Solution_Design",
    "Non_Monetary_Ledger", "Prediction_Registry", "Bias_Audit_Log",
    "Scenario_Map", "Decision_Tree_Log", "Synergy_Map",
    "Mental_Models_Registry", "Calibration_Ledger",
    "Project_Execution_Log",
    # v9.0 foundation tables
    "Compound_Intelligence_Log", "Cartridge_Performance_Log",
    "Cognitive_Twin_State", "Causal_Graph_Log",
    "Cartridge_Evolution_Proposals",
    # Phase 4 tables
    "Backup_Manifest", "Contradiction_Log", "Audit_Log",
    "NLQ_Parse_Log", "Cartridge_Arbitration_Log", "Offline_Mode_Log",
    # Migrations tracking
    "schema_migrations",
)


# ---------------------------------------------------------------------------
# Identity_Continuity_Protocol
# ---------------------------------------------------------------------------

class IdentityContinuityProtocol:
    """
    Backup, recovery, and sovereignty guarantee for all aeOS data.

    Encrypted full-state snapshots with integrity verification.
    Uses CryptoGuard (F0.3) for AES-256-GCM encryption with
    hardware-bound keys.

    Usage:
        proto = IdentityContinuityProtocol(db_path="/path/to/aeOS.db")
        manifest = proto.create_backup()
        result = proto.restore(manifest.backup_path, passphrase="...")
        report = proto.verify()
    """

    VERSION = "1.0.0"

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        backup_dir: Optional[Union[str, Path]] = None,
        crypto_guard: Optional[Any] = None,
    ) -> None:
        """
        Initialize the Identity Continuity Protocol.

        Args:
            db_path:      Path to the SQLite database. Defaults to standard location.
            backup_dir:   Directory for backup files. Defaults to <db_dir>/backups/.
            crypto_guard: Optional CryptoGuard instance for encryption.
        """
        if db_path is not None:
            self._db_path = Path(db_path).expanduser().resolve()
        else:
            self._db_path = (
                Path(__file__).resolve().parent.parent.parent / "db" / "aeOS.db"
            )

        if backup_dir is not None:
            self._backup_dir = Path(backup_dir).expanduser().resolve()
        else:
            self._backup_dir = self._db_path.parent / "backups"

        self._crypto = crypto_guard
        self._schedule = BackupSchedule(backup_dir=str(self._backup_dir))

    # ------------------------------------------------------------------
    # Public API: createBackup
    # ------------------------------------------------------------------

    def create_backup(
        self,
        backup_type: str = "manual",
        passphrase: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> BackupManifest:
        """
        Create a full encrypted snapshot of all aeOS data.

        Args:
            backup_type: Type of backup (manual/daily/weekly/monthly).
            passphrase:  Encryption passphrase. If None and CryptoGuard
                         is initialized, uses existing key.
            notes:       Optional notes for the backup.

        Returns:
            BackupManifest with backup metadata.

        Raises:
            RuntimeError: If backup fails.
            sqlite3.Error: If database read fails.
        """
        start_time = time.monotonic()
        backup_id = self._generate_backup_id(backup_type)
        now_iso = datetime.now(timezone.utc).isoformat()

        self._backup_dir.mkdir(parents=True, exist_ok=True)

        conn = self._get_connection()
        try:
            # Collect all table data
            tables_data: Dict[str, List[Dict[str, Any]]] = {}
            tables_included: List[str] = []
            total_records = 0

            for table_name in BACKUP_TABLES:
                rows = self._export_table(conn, table_name)
                if rows is not None:
                    tables_data[table_name] = rows
                    tables_included.append(table_name)
                    total_records += len(rows)

            # Get compound score
            compound_score = self._get_compound_score(conn)
            decision_count = self._get_decision_count(conn)

            # Build the backup payload
            payload = {
                "version": self.VERSION,
                "backup_id": backup_id,
                "created_at": now_iso,
                "db_path": str(self._db_path),
                "tables": tables_data,
                "tables_included": tables_included,
                "total_records": total_records,
                "decision_count": decision_count,
                "compound_score": compound_score,
            }

            # Serialize
            payload_json = json.dumps(payload, default=str, ensure_ascii=False)
            payload_bytes = payload_json.encode("utf-8")

            # Encrypt if possible
            encrypted = False
            output_bytes = payload_bytes

            if self._crypto is not None and passphrase:
                try:
                    if not getattr(self._crypto, "_initialized", False):
                        self._crypto.initialize_crypto(passphrase)
                    encrypted_str = self._crypto.encrypt_cognitive_state(payload)
                    output_bytes = encrypted_str.encode("utf-8")
                    encrypted = True
                except Exception as e:
                    logger.warning("Encryption failed, saving unencrypted: %s", e)
            elif self._crypto is not None and getattr(self._crypto, "_initialized", False):
                try:
                    encrypted_str = self._crypto.encrypt_cognitive_state(payload)
                    output_bytes = encrypted_str.encode("utf-8")
                    encrypted = True
                except Exception as e:
                    logger.warning("Encryption failed, saving unencrypted: %s", e)

            # Compute checksum of output
            checksum = hashlib.sha256(output_bytes).hexdigest()

            # Write backup file
            ext = ".aeos.enc" if encrypted else ".aeos.json"
            backup_filename = f"{backup_id}{ext}"
            backup_path = self._backup_dir / backup_filename
            backup_path.write_bytes(output_bytes)

            size_bytes = len(output_bytes)

            # Generate human-readable summary (unencrypted, no PII)
            summary_path = self._backup_dir / f"{backup_id}.summary.md"
            self._write_summary(
                summary_path, backup_id, now_iso, tables_included,
                total_records, decision_count, compound_score,
                encrypted, checksum, size_bytes,
            )

            manifest = BackupManifest(
                backup_id=backup_id,
                created_at=now_iso,
                tables_included=tables_included,
                decision_count=decision_count,
                compound_score=compound_score,
                encrypted=encrypted,
                checksum=checksum,
                size_bytes=size_bytes,
                backup_path=str(backup_path),
                backup_type=backup_type,
                status="complete",
                notes=notes,
            )

            # Record manifest in DB
            self._save_manifest(conn, manifest)

            elapsed = time.monotonic() - start_time
            logger.info(
                "Backup %s complete: %d tables, %d records, %.1fs, %s",
                backup_id, len(tables_included), total_records,
                elapsed, "encrypted" if encrypted else "plaintext",
            )

            return manifest

        except Exception:
            logger.exception("Backup failed for %s", backup_id)
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: restore
    # ------------------------------------------------------------------

    def restore(
        self,
        backup_path: str,
        passphrase: Optional[str] = None,
    ) -> RestoreResult:
        """
        Restore aeOS from a backup file.

        Args:
            backup_path: Path to the backup file.
            passphrase:  Decryption passphrase (required for encrypted backups).

        Returns:
            RestoreResult with restoration details.

        Raises:
            FileNotFoundError: If backup file not found.
            ValueError: If backup is corrupted or checksum fails.
            RuntimeError: If restore fails.
        """
        start_time = time.monotonic()
        bp = Path(backup_path).expanduser().resolve()

        if not bp.exists():
            raise FileNotFoundError(f"Backup file not found: {bp}")

        raw_bytes = bp.read_bytes()

        # Detect encrypted backup
        is_encrypted = bp.suffix == ".enc" or bp.name.endswith(".aeos.enc")

        if is_encrypted:
            if self._crypto is None:
                raise RuntimeError(
                    "Encrypted backup requires CryptoGuard. "
                    "Pass crypto_guard to constructor."
                )
            if passphrase and not getattr(self._crypto, "_initialized", False):
                self._crypto.initialize_crypto(passphrase)
            try:
                ciphertext_str = raw_bytes.decode("utf-8")
                payload = self._crypto.decrypt_cognitive_state(ciphertext_str)
            except Exception as e:
                raise ValueError(
                    f"Decryption failed — wrong passphrase or corrupted backup: {e}"
                ) from e
        else:
            try:
                payload = json.loads(raw_bytes.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise ValueError(f"Invalid backup file format: {e}") from e

        # Validate payload structure
        if not isinstance(payload, dict) or "tables" not in payload:
            raise ValueError("Invalid backup format: missing 'tables' key")

        tables_data = payload["tables"]
        backup_id = payload.get("backup_id", "unknown")

        conn = self._get_connection()
        errors: List[str] = []
        tables_restored: List[str] = []
        records_restored = 0

        try:
            for table_name, rows in tables_data.items():
                try:
                    count = self._import_table(conn, table_name, rows)
                    tables_restored.append(table_name)
                    records_restored += count
                except Exception as e:
                    error_msg = f"Failed to restore table {table_name}: {e}"
                    errors.append(error_msg)
                    logger.warning(error_msg)

            conn.commit()

            elapsed = time.monotonic() - start_time
            logger.info(
                "Restore from %s complete: %d tables, %d records, %.1fs, %d errors",
                backup_id, len(tables_restored), records_restored,
                elapsed, len(errors),
            )

            return RestoreResult(
                success=len(errors) == 0,
                tables_restored=tables_restored,
                records_restored=records_restored,
                backup_id=backup_id,
                restored_at=datetime.now(timezone.utc).isoformat(),
                errors=errors,
            )

        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: verify
    # ------------------------------------------------------------------

    def verify(self) -> IntegrityReport:
        """
        Verify current database integrity without creating a backup.

        Checks:
            - All expected tables exist
            - Foreign key constraints valid
            - Record counts per table
            - SQLite integrity check

        Returns:
            IntegrityReport with verification results.
        """
        start_time = time.monotonic()
        now_iso = datetime.now(timezone.utc).isoformat()

        conn = self._get_connection()
        try:
            # Get existing tables
            existing_tables = self._get_existing_tables(conn)

            # Check for missing tables
            missing_tables = [
                t for t in BACKUP_TABLES if t not in existing_tables
            ]

            # Count records per table
            table_counts: Dict[str, int] = {}
            total_records = 0
            for table_name in existing_tables:
                try:
                    row = conn.execute(
                        f'SELECT COUNT(*) FROM "{table_name}"'
                    ).fetchone()
                    count = row[0] if row else 0
                    table_counts[table_name] = count
                    total_records += count
                except sqlite3.Error:
                    table_counts[table_name] = -1  # error reading

            # SQLite integrity check
            corruption_detected = False
            try:
                result = conn.execute("PRAGMA integrity_check;").fetchone()
                if result and result[0] != "ok":
                    corruption_detected = True
            except sqlite3.Error:
                corruption_detected = True

            # FK violation check
            fk_violations = 0
            try:
                violations = conn.execute(
                    "PRAGMA foreign_key_check;"
                ).fetchall()
                fk_violations = len(violations)
            except sqlite3.Error:
                pass

            elapsed = time.monotonic() - start_time
            healthy = (
                not corruption_detected
                and fk_violations == 0
                and len(missing_tables) == 0
            )

            return IntegrityReport(
                healthy=healthy,
                tables_checked=len(BACKUP_TABLES),
                tables_found=len(existing_tables),
                total_records=total_records,
                missing_tables=missing_tables,
                corruption_detected=corruption_detected,
                fk_violations=fk_violations,
                timestamp=now_iso,
                details={
                    "table_counts": table_counts,
                    "elapsed_seconds": round(elapsed, 3),
                    "sqlite_version": sqlite3.sqlite_version,
                },
            )

        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: getSchedule / setSchedule
    # ------------------------------------------------------------------

    def get_schedule(self) -> BackupSchedule:
        """Return current auto-backup schedule configuration."""
        return self._schedule

    def set_schedule(self, config: Dict[str, Any]) -> None:
        """
        Configure auto-backup schedule.

        Args:
            config: Dict with optional keys: enabled, daily_hour,
                    daily_minute, retain_daily, retain_weekly,
                    retain_monthly, backup_dir.
        """
        if "enabled" in config:
            self._schedule.enabled = bool(config["enabled"])
        if "daily_hour" in config:
            hour = int(config["daily_hour"])
            if not 0 <= hour <= 23:
                raise ValueError("daily_hour must be 0-23")
            self._schedule.daily_hour = hour
        if "daily_minute" in config:
            minute = int(config["daily_minute"])
            if not 0 <= minute <= 59:
                raise ValueError("daily_minute must be 0-59")
            self._schedule.daily_minute = minute
        if "retain_daily" in config:
            self._schedule.retain_daily = max(1, int(config["retain_daily"]))
        if "retain_weekly" in config:
            self._schedule.retain_weekly = max(1, int(config["retain_weekly"]))
        if "retain_monthly" in config:
            self._schedule.retain_monthly = max(1, int(config["retain_monthly"]))
        if "backup_dir" in config:
            self._schedule.backup_dir = str(config["backup_dir"])
            self._backup_dir = Path(config["backup_dir"]).expanduser().resolve()

    # ------------------------------------------------------------------
    # Public API: listBackups
    # ------------------------------------------------------------------

    def list_backups(self) -> List[BackupManifest]:
        """
        List all available backup manifests from the database.

        Returns:
            List of BackupManifest records, newest first.
        """
        conn = self._get_connection()
        try:
            if "Backup_Manifest" not in self._get_existing_tables(conn):
                return []

            rows = conn.execute(
                "SELECT * FROM Backup_Manifest ORDER BY created_at DESC"
            ).fetchall()

            results = []
            for row in rows:
                tables_included = json.loads(row["tables_included"]) if row["tables_included"] else []
                results.append(BackupManifest(
                    backup_id=row["backup_id"],
                    created_at=row["created_at"],
                    tables_included=tables_included,
                    decision_count=row["decision_count"],
                    compound_score=row["compound_score"],
                    encrypted=bool(row["encrypted"]),
                    checksum=row["checksum"],
                    size_bytes=row["size_bytes"],
                    backup_path=row["backup_path"],
                    backup_type=row["backup_type"],
                    status=row["status"],
                    notes=row["notes"],
                ))
            return results
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: prune_old_backups
    # ------------------------------------------------------------------

    def prune_old_backups(self) -> int:
        """
        Remove old backup files according to retention policy.

        Retention: retain_daily most recent daily, retain_weekly weekly,
        retain_monthly monthly backups. Manual backups are never pruned.

        Returns:
            Number of backups pruned.
        """
        backups = self.list_backups()
        pruned = 0

        for btype, retain in [
            ("daily", self._schedule.retain_daily),
            ("weekly", self._schedule.retain_weekly),
            ("monthly", self._schedule.retain_monthly),
        ]:
            typed_backups = [b for b in backups if b.backup_type == btype]
            if len(typed_backups) > retain:
                to_remove = typed_backups[retain:]
                for backup in to_remove:
                    self._delete_backup(backup)
                    pruned += 1

        return pruned

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        """Get a configured SQLite connection."""
        conn = sqlite3.connect(str(self._db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _generate_backup_id(self, backup_type: str) -> str:
        """Generate a unique backup ID."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        import random
        unique = f"{ts}_{backup_type}_{os.getpid()}_{time.monotonic_ns()}_{random.randint(0, 999999)}"
        short_hash = hashlib.sha256(unique.encode()).hexdigest()[:8]
        return f"BKP-{ts}-{backup_type}-{short_hash}"

    def _get_existing_tables(self, conn: sqlite3.Connection) -> set:
        """Return set of existing table names."""
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {row[0] for row in rows}

    def _export_table(
        self, conn: sqlite3.Connection, table_name: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Export all rows from a table as list of dicts. Returns None if table doesn't exist."""
        existing = self._get_existing_tables(conn)
        if table_name not in existing:
            return None

        try:
            cursor = conn.execute(f'SELECT * FROM "{table_name}"')
            columns = [desc[0] for desc in cursor.description]
            rows = []
            for row in cursor.fetchall():
                row_dict = {}
                for i, col in enumerate(columns):
                    val = row[i]
                    # Ensure JSON-serializable
                    if isinstance(val, bytes):
                        val = val.hex()
                    row_dict[col] = val
                rows.append(row_dict)
            return rows
        except sqlite3.Error as e:
            logger.warning("Failed to export table %s: %s", table_name, e)
            return None

    def _import_table(
        self, conn: sqlite3.Connection, table_name: str,
        rows: List[Dict[str, Any]],
    ) -> int:
        """Import rows into a table. Returns number of rows imported."""
        if not rows:
            return 0

        existing = self._get_existing_tables(conn)
        if table_name not in existing:
            logger.warning("Table %s does not exist, skipping import", table_name)
            return 0

        # Clear existing data for clean restore
        conn.execute(f'DELETE FROM "{table_name}"')

        count = 0
        for row in rows:
            columns = list(row.keys())
            placeholders = ", ".join(["?"] * len(columns))
            col_names = ", ".join([f'"{c}"' for c in columns])
            values = [row[c] for c in columns]

            try:
                conn.execute(
                    f'INSERT OR REPLACE INTO "{table_name}" ({col_names}) '
                    f'VALUES ({placeholders})',
                    values,
                )
                count += 1
            except sqlite3.Error as e:
                logger.warning(
                    "Failed to insert row into %s: %s", table_name, e
                )

        return count

    def _get_compound_score(self, conn: sqlite3.Connection) -> float:
        """Get current compound intelligence score."""
        existing = self._get_existing_tables(conn)
        if "Compound_Intelligence_Log" not in existing:
            return 0.0
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM Compound_Intelligence_Log"
            ).fetchone()
            total = row[0] if row else 0
            # Simple compound score based on decision volume
            return min(total / 100.0, 1.0) * 100.0
        except sqlite3.Error:
            return 0.0

    def _get_decision_count(self, conn: sqlite3.Connection) -> int:
        """Get total decision count."""
        existing = self._get_existing_tables(conn)
        if "Compound_Intelligence_Log" not in existing:
            return 0
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM Compound_Intelligence_Log"
            ).fetchone()
            return row[0] if row else 0
        except sqlite3.Error:
            return 0

    def _save_manifest(
        self, conn: sqlite3.Connection, manifest: BackupManifest
    ) -> None:
        """Save backup manifest to the Backup_Manifest table."""
        existing = self._get_existing_tables(conn)
        if "Backup_Manifest" not in existing:
            return

        conn.execute(
            """INSERT OR REPLACE INTO Backup_Manifest
            (backup_id, created_at, tables_included, decision_count,
             compound_score, encrypted, checksum, size_bytes,
             backup_path, backup_type, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                manifest.backup_id,
                manifest.created_at,
                json.dumps(manifest.tables_included),
                manifest.decision_count,
                manifest.compound_score,
                1 if manifest.encrypted else 0,
                manifest.checksum,
                manifest.size_bytes,
                manifest.backup_path,
                manifest.backup_type,
                manifest.status,
                manifest.notes,
            ),
        )
        conn.commit()

    def _write_summary(
        self, path: Path, backup_id: str, created_at: str,
        tables: List[str], total_records: int, decision_count: int,
        compound_score: float, encrypted: bool, checksum: str,
        size_bytes: int,
    ) -> None:
        """Write human-readable markdown summary (no PII)."""
        lines = [
            f"# aeOS Backup Summary",
            f"",
            f"- **Backup ID**: {backup_id}",
            f"- **Created**: {created_at}",
            f"- **Tables**: {len(tables)}",
            f"- **Total Records**: {total_records}",
            f"- **Decisions Logged**: {decision_count}",
            f"- **Compound Score**: {compound_score:.1f}",
            f"- **Encrypted**: {'Yes (AES-256-GCM)' if encrypted else 'No'}",
            f"- **Checksum (SHA-256)**: `{checksum[:16]}...`",
            f"- **Size**: {size_bytes:,} bytes",
            f"",
            f"## Tables Included",
            f"",
        ]
        for t in tables:
            lines.append(f"- {t}")
        lines.append("")
        lines.append("---")
        lines.append("*Generated by aeOS Identity_Continuity_Protocol v1.0*")

        path.write_text("\n".join(lines), encoding="utf-8")

    def _delete_backup(self, manifest: BackupManifest) -> None:
        """Delete a backup file and its manifest record."""
        if manifest.backup_path:
            try:
                bp = Path(manifest.backup_path)
                if bp.exists():
                    bp.unlink()
                # Also remove summary
                summary = bp.parent / f"{manifest.backup_id}.summary.md"
                if summary.exists():
                    summary.unlink()
            except OSError as e:
                logger.warning("Failed to delete backup file: %s", e)

        conn = self._get_connection()
        try:
            conn.execute(
                "DELETE FROM Backup_Manifest WHERE backup_id = ?",
                (manifest.backup_id,),
            )
            conn.commit()
        finally:
            conn.close()


__all__ = [
    "IdentityContinuityProtocol",
    "BackupManifest",
    "RestoreResult",
    "IntegrityReport",
    "BackupSchedule",
    "BACKUP_TABLES",
]
