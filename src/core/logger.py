"""aeOS centralized logging.
- Stdlib `logging` only (no external deps)
- Logs to both console and a rotating file: ../logs/aeOS.log
- Format: [TIMESTAMP] [LEVEL] [MODULE] message
Usage:
    from logger import get_logger
    log = get_logger(__name__)
    log.info("hello")
"""
from __future__ import annotations
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Final
# ---- Public API -----------------------------------------------------------------
__all__ = ["get_logger"]
# ---- Configuration (tweak only here) --------------------------------------------
_BASE_LOGGER_NAME: Final[str] = "aeOS"
# Requirement: log file lives at ../logs/aeOS.log (relative to this module file)
_LOG_FILE_RELATIVE: Final[Path] = Path("..") / "logs" / "aeOS.log"
# Requirement: rotating file handler (max 5MB, keep 3 backups)
_MAX_BYTES: Final[int] = 5 * 1024 * 1024
_BACKUP_COUNT: Final[int] = 3
# Optional: allow runtime override without changing code (still stdlib)
_ENV_LOG_LEVEL: Final[str] = "AEOS_LOG_LEVEL"
_DEFAULT_LEVEL_NAME: Final[str] = "INFO"
# ---- Internal state --------------------------------------------------------------
_config_lock: Final[Lock] = Lock()
_configured: bool = False
class _SafeFormatter(logging.Formatter):
    """Formatter that guarantees `module_name` exists on every record.
    Why:
      - We want a strict format: [TIMESTAMP] [LEVEL] [MODULE] message
      - Some records (e.g., from 3rd-party libs) won't include extra fields.
      - This keeps formatting robust (no KeyError) while preserving the spec.
    """
    def format(self, record: logging.LogRecord) -> str:
        # Ensure our format field exists; fall back to logger name if missing.
        if not hasattr(record, "module_name"):
            record.module_name = record.name
        return super().format(record)
def _resolve_log_path() -> Path:
    """Resolve log path relative to this file, not the current working dir."""
    here = Path(__file__).resolve()
    return (here.parent / _LOG_FILE_RELATIVE).resolve()
def _parse_level() -> int:
    """Parse AEOS_LOG_LEVEL, defaulting safely to INFO."""
    level_name = os.getenv(_ENV_LOG_LEVEL, _DEFAULT_LEVEL_NAME).upper().strip()
    return getattr(logging, level_name, logging.INFO)
def _ensure_configured() -> None:
    """Configure the base aeOS logger exactly once (idempotent + thread-safe)."""
    global _configured
    if _configured:
        return
    with _config_lock:
        if _configured:
            return
        log_path = _resolve_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)  # Requirement: ensure logs dir exists
        level = _parse_level()
        base_logger = logging.getLogger(_BASE_LOGGER_NAME)
        base_logger.setLevel(level)
        # Critical: stop duplication if the root logger is also configured elsewhere.
        base_logger.propagate = False
        # Avoid duplicate handlers if this module gets reloaded in dev environments.
        if not base_logger.handlers:
            formatter = _SafeFormatter(
                fmt="[%(asctime)s] [%(levelname)s] [%(module_name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            # File output (rotating)
            file_handler = RotatingFileHandler(
                filename=str(log_path),
                maxBytes=_MAX_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            # Console output (stdout keeps logs visible in most dev consoles)
            console_handler = logging.StreamHandler(stream=sys.stdout)
            console_handler.setLevel(level)
            console_handler.setFormatter(formatter)
            base_logger.addHandler(file_handler)
            base_logger.addHandler(console_handler)
        _configured = True
def get_logger(module_name: str) -> logging.LoggerAdapter:
    """Return a configured logger for `module_name`.
    This returns a LoggerAdapter so the formatter can reliably show:
        [TIMESTAMP] [LEVEL] [MODULE] message
    Args:
        module_name: Typically `__name__` from the caller.
    Returns:
        logging.LoggerAdapter: ready-to-use logger instance.
    """
    if not module_name:
        module_name = "unknown"
    _ensure_configured()
    # Use a child logger so everything still routes through the base "aeOS" logger,
    # which holds the handlers. This allows per-module filtering later if needed.
    if module_name.startswith(_BASE_LOGGER_NAME + "."):
        logger_name = module_name
    elif module_name == _BASE_LOGGER_NAME:
        logger_name = _BASE_LOGGER_NAME
    else:
        logger_name = f"{_BASE_LOGGER_NAME}.{module_name}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.NOTSET)  # inherit from base logger
    logger.propagate = True  # bubble to base logger (handlers live there)
    # Inject `module_name` for formatting (and keep it exactly as the caller passed it).
    return logging.LoggerAdapter(logger, {"module_name": module_name})
