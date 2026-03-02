"""Tests for Settings screen"""
import pytest
from src.screens.settings import Settings


def test_config_snapshot_has_required_keys():
    s = Settings()
    snap = s.get_config_snapshot()
    for key in ["ai_routing", "cost_caps", "alert_thresholds",
                 "investor_profile_active", "data_paths", "version"]:
        assert key in snap


def test_update_setting_validates_type():
    s = Settings()
    result = s.update_setting("investor_profile_active", "not_a_bool")
    assert result["success"] is False


def test_update_setting_success():
    s = Settings()
    result = s.update_setting("investor_profile_active", True)
    assert result["success"] is True
    assert result["new_value"] is True


def test_invalid_key_returns_error():
    s = Settings()
    result = s.update_setting("nonexistent_key", 42)
    assert result["success"] is False


def test_approve_proposal_returns_true():
    s = Settings()
    pid = s.add_proposal("Test", "module_a", "Change X", "low")
    assert s.approve_proposal(pid) is True
    # Second approve should fail (already approved)
    assert s.approve_proposal(pid) is False


def test_reject_proposal():
    s = Settings()
    pid = s.add_proposal("Test2", "module_b", "Change Y")
    assert s.reject_proposal(pid, reason="Not needed") is True


def test_export_data_returns_path_and_count():
    s = Settings()
    result = s.export_data("config")
    assert result["export_id"]
    assert result["file_path"]
    assert result["record_count"] > 0
    assert result["size_bytes"] > 0


def test_routing_config():
    s = Settings()
    config = s.get_routing_config()
    assert "default_model" in config


def test_update_routing_config():
    s = Settings()
    result = s.update_routing_config({"auto_escalate": True})
    assert result["success"] is True
    assert "auto_escalate" in result["updated_keys"]
