"""SETTINGS screen — System configuration and Evolution Proposals review.

Centralises all system configuration reads/writes including AI routing,
cost caps, alert thresholds, investor profile, and data export/import.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional


# Default configuration
_DEFAULT_CONFIG: Dict[str, Any] = {
    "ai_routing": {
        "default_model": "claude-sonnet-4-20250514",
        "escalation_model": "claude-opus-4-20250514",
        "auto_escalate": False,
        "max_retries": 3,
    },
    "cost_caps": {
        "daily_cap_usd": 10.0,
        "monthly_cap_usd": 100.0,
    },
    "alert_thresholds": {
        "default_sensitivity": 2.0,
        "max_active_alerts": 100,
    },
    "investor_profile_active": False,
    "data_paths": {
        "db": "db/aeOS.db",
        "exports": "exports/",
    },
    "version": "9.0.0",
}

# Valid types for each config key
_CONFIG_TYPES: Dict[str, type] = {
    "ai_routing": dict,
    "cost_caps": dict,
    "alert_thresholds": dict,
    "investor_profile_active": bool,
    "data_paths": dict,
    "version": str,
}


class Settings:
    """SETTINGS screen data provider and config manager.

    Centralises all system configuration reads/writes.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._config: Dict[str, Any] = (
            json.loads(json.dumps(config))
            if config
            else json.loads(json.dumps(_DEFAULT_CONFIG))
        )
        self._proposals: Dict[str, dict] = {}

    def get_config_snapshot(self) -> dict:
        """Return full current configuration.

        Keys: ai_routing, cost_caps, alert_thresholds,
              investor_profile_active, data_paths, version
        """
        return json.loads(json.dumps(self._config))

    def update_setting(self, key: str, value: Any) -> dict:
        """Update a single config value.

        Returns:
            {success: bool, key: str, old_value: Any,
             new_value: Any, requires_restart: bool}
        Validates value type before writing.
        """
        if not isinstance(key, str) or not key.strip():
            return {
                "success": False,
                "key": key,
                "old_value": None,
                "new_value": value,
                "requires_restart": False,
            }

        if key not in self._config:
            return {
                "success": False,
                "key": key,
                "old_value": None,
                "new_value": value,
                "requires_restart": False,
            }

        expected_type = _CONFIG_TYPES.get(key)
        if expected_type and not isinstance(value, expected_type):
            return {
                "success": False,
                "key": key,
                "old_value": self._config.get(key),
                "new_value": value,
                "requires_restart": False,
            }

        old_value = self._config.get(key)
        self._config[key] = value

        restart_keys = {"ai_routing", "data_paths"}
        return {
            "success": True,
            "key": key,
            "old_value": old_value,
            "new_value": value,
            "requires_restart": key in restart_keys,
        }

    def get_evolution_proposals(self) -> List[dict]:
        """Return pending Evolution_Suggestions_Log entries for review."""
        return sorted(
            [
                p
                for p in self._proposals.values()
                if p.get("status") == "pending"
            ],
            key=lambda p: p.get("created_at", 0),
        )

    def add_proposal(
        self,
        description: str,
        source_module: str,
        proposed_change: str,
        impact_estimate: str = "unknown",
    ) -> str:
        """Add a new evolution proposal. Returns proposal_id."""
        proposal_id = str(uuid.uuid4())
        self._proposals[proposal_id] = {
            "proposal_id": proposal_id,
            "description": str(description),
            "source_module": str(source_module),
            "proposed_change": str(proposed_change),
            "impact_estimate": str(impact_estimate),
            "status": "pending",
            "created_at": time.time(),
        }
        return proposal_id

    def approve_proposal(self, proposal_id: str) -> bool:
        """Mark proposal as approved. Returns True if found."""
        if proposal_id not in self._proposals:
            return False
        if self._proposals[proposal_id]["status"] != "pending":
            return False
        self._proposals[proposal_id]["status"] = "approved"
        self._proposals[proposal_id]["reviewed_at"] = time.time()
        return True

    def reject_proposal(
        self, proposal_id: str, reason: Optional[str] = None
    ) -> bool:
        """Mark proposal as rejected. Returns True if found."""
        if proposal_id not in self._proposals:
            return False
        if self._proposals[proposal_id]["status"] != "pending":
            return False
        self._proposals[proposal_id]["status"] = "rejected"
        self._proposals[proposal_id]["reviewed_at"] = time.time()
        if reason:
            self._proposals[proposal_id]["rejection_reason"] = reason
        return True

    def export_data(self, export_type: str = "full") -> dict:
        """Export system data.

        export_type: 'full'|'config'|'cartridges'|'decisions'

        Returns:
            {export_id: str, file_path: str,
             record_count: int, size_bytes: int}
        """
        valid_types = {"full", "config", "cartridges", "decisions"}
        if export_type not in valid_types:
            export_type = "full"

        export_id = str(uuid.uuid4())

        if export_type == "config":
            data = self._config
            record_count = len(data)
        else:
            data = {
                "config": self._config,
                "proposals": list(self._proposals.values()),
            }
            record_count = len(self._config) + len(self._proposals)

        serialized = json.dumps(data, ensure_ascii=False)
        file_path = f"exports/aeOS_export_{export_type}_{export_id[:8]}.json"

        return {
            "export_id": export_id,
            "file_path": file_path,
            "record_count": record_count,
            "size_bytes": len(serialized.encode("utf-8")),
        }

    def get_routing_config(self) -> dict:
        """Return SMART_ROUTER configuration for display."""
        return dict(self._config.get("ai_routing", {}))

    def update_routing_config(self, updates: dict) -> dict:
        """Update SMART_ROUTER routing rules.

        Returns:
            {success: bool, updated_keys: list[str]}
        """
        if not isinstance(updates, dict):
            return {"success": False, "updated_keys": []}

        routing = self._config.get("ai_routing", {})
        updated_keys = []
        for k, v in updates.items():
            if k in routing:
                routing[k] = v
                updated_keys.append(k)
        self._config["ai_routing"] = routing

        return {"success": bool(updated_keys), "updated_keys": updated_keys}
