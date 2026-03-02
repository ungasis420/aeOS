"""connect.py — DB connection adapter for aeOS cognitive modules.

Re-exports get_db_connection from db_connect for modules that import
from src.db.connect (e.g., FlywheelLogger).
"""
from src.db.db_connect import get_connection as get_db_connection

__all__ = ["get_db_connection"]
