"""
tests/test_cartridge_loader.py

Pytest unit tests for `src.cognitive.cartridge_loader`.

All tests use in-memory / temp-dir fixtures — no real filesystem side-effects.
Stamp: S✅ T✅ L✅ A✅
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure repo root is importable when running `pytest` from different CWDs.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.cognitive.cartridge_loader import (
    _match_triggers,
    _render_template,
    _validate_against_schema,
    get_cartridge_index,
    load_cartridge,
    load_cartridge_by_id,
    load_cartridges,
    load_schema,
    run_rules,
)

# ---------------------------------------------------------------------------
# Paths to real repo assets
# ---------------------------------------------------------------------------
_CARTRIDGES_DIR = Path(_REPO_ROOT) / "src" / "cartridges"
_SCHEMA_PATH = _CARTRIDGES_DIR / "cartridge_schema.json"
_STOIC_PATH = _CARTRIDGES_DIR / "stoic.json"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def schema():
    """Load the real cartridge schema."""
    return load_schema(_SCHEMA_PATH)


@pytest.fixture()
def stoic(schema):
    """Load the real stoic cartridge (validated)."""
    return load_cartridge(_STOIC_PATH, schema)


@pytest.fixture()
def minimal_cartridge():
    """Return a minimal valid cartridge dict."""
    return {
        "cartridge_id": "test-minimal",
        "version": "0.1.0",
        "domain": "testing",
        "description": "Minimal cartridge for unit tests.",
        "dependencies": [],
        "ethical_guardrail": "Do no harm.",
        "rules": [
            {
                "rule_id": "t-001",
                "name": "Trigger Test",
                "principle": "Test principle.",
                "detection_triggers": ["stressed", "overwhelmed"],
                "insight_template": "You seem {mood}. Consider pausing.",
                "connects_to": [],
                "confidence_weight": 0.75,
                "sovereign_need_served": "clarity",
                "tags": ["test"],
            }
        ],
        "cross_references": {},
    }


@pytest.fixture()
def tmp_cartridge_dir(minimal_cartridge, schema):
    """Create a temp directory with schema + one cartridge file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write schema
        schema_path = Path(tmpdir) / "cartridge_schema.json"
        with open(schema_path, "w") as f:
            json.dump(schema, f)
        # Write cartridge
        cart_path = Path(tmpdir) / "test_minimal.json"
        with open(cart_path, "w") as f:
            json.dump(minimal_cartridge, f)
        yield Path(tmpdir)


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------

class TestLoadSchema:
    def test_loads_valid_schema(self):
        schema = load_schema(_SCHEMA_PATH)
        assert isinstance(schema, dict)
        assert "properties" in schema
        assert "definitions" in schema

    def test_missing_schema_raises(self, tmp_path):
        with pytest.raises(OSError):
            load_schema(tmp_path / "nonexistent.json")

    def test_invalid_json_schema_raises(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            load_schema(bad_file)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_valid_cartridge_passes(self, schema, minimal_cartridge):
        errors = _validate_against_schema(minimal_cartridge, schema)
        assert errors == []

    def test_missing_required_field(self, schema, minimal_cartridge):
        del minimal_cartridge["cartridge_id"]
        errors = _validate_against_schema(minimal_cartridge, schema)
        assert any("cartridge_id" in e for e in errors)

    def test_wrong_type(self, schema, minimal_cartridge):
        minimal_cartridge["version"] = 123  # should be string
        errors = _validate_against_schema(minimal_cartridge, schema)
        assert any("version" in e and "string" in e for e in errors)

    def test_confidence_weight_out_of_range(self, schema, minimal_cartridge):
        minimal_cartridge["rules"][0]["confidence_weight"] = 1.5
        errors = _validate_against_schema(minimal_cartridge, schema)
        assert any("maximum" in e for e in errors)

    def test_confidence_weight_below_zero(self, schema, minimal_cartridge):
        minimal_cartridge["rules"][0]["confidence_weight"] = -0.1
        errors = _validate_against_schema(minimal_cartridge, schema)
        assert any("minimum" in e for e in errors)

    def test_extra_key_rejected(self, schema, minimal_cartridge):
        minimal_cartridge["unexpected_key"] = "oops"
        errors = _validate_against_schema(minimal_cartridge, schema)
        assert any("unexpected" in e for e in errors)

    def test_stoic_json_validates(self, schema):
        """The shipped stoic.json must pass validation."""
        with open(_STOIC_PATH, "r") as f:
            data = json.load(f)
        errors = _validate_against_schema(data, schema)
        assert errors == [], f"stoic.json validation errors: {errors}"


# ---------------------------------------------------------------------------
# Cartridge loading
# ---------------------------------------------------------------------------

class TestLoadCartridge:
    def test_load_stoic(self, schema):
        cart = load_cartridge(_STOIC_PATH, schema)
        assert cart["cartridge_id"] == "stoic"
        assert cart["version"] == "1.0.0"
        assert len(cart["rules"]) == 10

    def test_load_invalid_raises_value_error(self, schema, tmp_path):
        bad_cart = {"cartridge_id": "bad"}  # missing many required fields
        fp = tmp_path / "bad.json"
        fp.write_text(json.dumps(bad_cart), encoding="utf-8")
        with pytest.raises(ValueError, match="failed validation"):
            load_cartridge(fp, schema)

    def test_load_without_schema_skips_validation(self, tmp_path):
        data = {"any": "dict"}
        fp = tmp_path / "noschema.json"
        fp.write_text(json.dumps(data), encoding="utf-8")
        result = load_cartridge(fp, schema=None)
        assert result == data

    def test_load_missing_file_raises(self, schema, tmp_path):
        with pytest.raises(OSError):
            load_cartridge(tmp_path / "missing.json", schema)


# ---------------------------------------------------------------------------
# Parallel loading
# ---------------------------------------------------------------------------

class TestLoadCartridges:
    def test_loads_from_real_dir(self):
        carts = load_cartridges(_CARTRIDGES_DIR)
        assert len(carts) >= 1
        ids = [c["cartridge_id"] for c in carts]
        assert "stoic" in ids

    def test_loads_from_tmp_dir(self, tmp_cartridge_dir):
        carts = load_cartridges(tmp_cartridge_dir)
        assert len(carts) == 1
        assert carts[0]["cartridge_id"] == "test-minimal"

    def test_empty_dir_returns_empty(self, tmp_path):
        # Write schema but no cartridges.
        schema_path = tmp_path / "cartridge_schema.json"
        schema_path.write_text(json.dumps(load_schema(_SCHEMA_PATH)), encoding="utf-8")
        carts = load_cartridges(tmp_path)
        assert carts == []

    def test_bad_cartridge_skipped(self, tmp_cartridge_dir):
        # Add a broken cartridge alongside the valid one.
        bad = tmp_cartridge_dir / "broken.json"
        bad.write_text('{"cartridge_id": "broken"}', encoding="utf-8")
        carts = load_cartridges(tmp_cartridge_dir)
        ids = [c["cartridge_id"] for c in carts]
        assert "test-minimal" in ids
        assert "broken" not in ids


# ---------------------------------------------------------------------------
# Load cartridge by ID
# ---------------------------------------------------------------------------

class TestLoadCartridgeById:
    def test_find_stoic_by_id(self):
        result = load_cartridge_by_id("stoic", _CARTRIDGES_DIR)
        assert result is not None
        assert result["cartridge_id"] == "stoic"

    def test_find_by_id_case_insensitive(self):
        result = load_cartridge_by_id("STOIC", _CARTRIDGES_DIR)
        assert result is not None
        assert result["cartridge_id"] == "stoic"

    def test_find_prefixed_id(self):
        result = load_cartridge_by_id("CART-FIRST-PRINCIPLES", _CARTRIDGES_DIR)
        assert result is not None
        assert result["cartridge_id"] == "CART-FIRST-PRINCIPLES"

    def test_find_prefixed_id_lowercase(self):
        result = load_cartridge_by_id("cart-leadership", _CARTRIDGES_DIR)
        assert result is not None
        assert result["cartridge_id"] == "CART-LEADERSHIP"

    def test_not_found_returns_none(self):
        result = load_cartridge_by_id("nonexistent-cartridge", _CARTRIDGES_DIR)
        assert result is None

    def test_from_tmp_dir(self, tmp_cartridge_dir):
        result = load_cartridge_by_id("test-minimal", tmp_cartridge_dir)
        assert result is not None
        assert result["cartridge_id"] == "test-minimal"

    def test_whitespace_stripped(self):
        result = load_cartridge_by_id("  stoic  ", _CARTRIDGES_DIR)
        assert result is not None
        assert result["cartridge_id"] == "stoic"

    def test_empty_dir_returns_none(self, tmp_path):
        schema_path = tmp_path / "cartridge_schema.json"
        schema_path.write_text(json.dumps(load_schema(_SCHEMA_PATH)), encoding="utf-8")
        result = load_cartridge_by_id("stoic", tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# Cartridge index
# ---------------------------------------------------------------------------

class TestGetCartridgeIndex:
    def test_index_from_real_dir(self):
        index = get_cartridge_index(_CARTRIDGES_DIR)
        assert isinstance(index, dict)
        assert "stoic" in index
        assert index["stoic"] == "stoic.json"

    def test_index_contains_all_cartridges(self):
        index = get_cartridge_index(_CARTRIDGES_DIR)
        # Should have at least the 9 known cartridges.
        assert len(index) >= 9
        assert "CART-FIRST-PRINCIPLES" in index
        assert "CART-LEADERSHIP" in index
        assert "CART-ENERGY-MANAGEMENT" in index

    def test_index_from_tmp_dir(self, tmp_cartridge_dir):
        index = get_cartridge_index(tmp_cartridge_dir)
        assert "test-minimal" in index
        assert index["test-minimal"] == "test_minimal.json"

    def test_index_empty_dir(self, tmp_path):
        index = get_cartridge_index(tmp_path)
        assert index == {}

    def test_schema_not_in_index(self):
        index = get_cartridge_index(_CARTRIDGES_DIR)
        for cid, fname in index.items():
            assert fname != "cartridge_schema.json"

    def test_bad_file_skipped(self, tmp_cartridge_dir):
        bad = tmp_cartridge_dir / "corrupt.json"
        bad.write_text("{invalid json", encoding="utf-8")
        index = get_cartridge_index(tmp_cartridge_dir)
        assert "test-minimal" in index
        assert len(index) == 1


# ---------------------------------------------------------------------------
# Trigger matching
# ---------------------------------------------------------------------------

class TestMatchTriggers:
    def test_basic_match(self):
        triggers = ["stressed", "anxious"]
        context = {"mood": "I feel stressed and tired"}
        assert _match_triggers(triggers, context) == ["stressed"]

    def test_case_insensitive(self):
        triggers = ["Overwhelmed"]
        context = {"state": "COMPLETELY OVERWHELMED"}
        assert _match_triggers(triggers, context) == ["Overwhelmed"]

    def test_no_match(self):
        triggers = ["angry"]
        context = {"mood": "happy"}
        assert _match_triggers(triggers, context) == []

    def test_multiple_matches(self):
        triggers = ["stressed", "overwhelmed", "anxious"]
        context = {"text": "overwhelmed and stressed about everything"}
        matched = _match_triggers(triggers, context)
        assert set(matched) == {"stressed", "overwhelmed"}

    def test_numeric_context_values(self):
        triggers = ["42"]
        context = {"answer": 42}
        assert _match_triggers(triggers, context) == ["42"]


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

class TestRenderTemplate:
    def test_basic_render(self):
        result = _render_template("Hello {name}!", {"name": "aeOS"})
        assert result == "Hello aeOS!"

    def test_missing_placeholder_preserved(self):
        result = _render_template("Hello {unknown}!", {})
        assert result == "Hello {unknown}!"

    def test_multiple_placeholders(self):
        result = _render_template("{a} + {b} = {c}", {"a": "1", "b": "2", "c": "3"})
        assert result == "1 + 2 = 3"

    def test_no_placeholders(self):
        result = _render_template("no placeholders here", {"key": "val"})
        assert result == "no placeholders here"


# ---------------------------------------------------------------------------
# Rule execution
# ---------------------------------------------------------------------------

class TestRunRules:
    def test_stoic_dichotomy_triggers(self, stoic):
        context = {"situation": "a toxic coworker", "mood": "frustrated and helpless"}
        insights = run_rules(stoic, context)
        rule_ids = [i["rule_id"] for i in insights]
        assert "stoic-001" in rule_ids  # Dichotomy of Control

    def test_stoic_memento_mori_triggers(self, stoic):
        context = {"situation": "scrolling social media", "mood": "wasting time and procrastinating"}
        insights = run_rules(stoic, context)
        rule_ids = [i["rule_id"] for i in insights]
        assert "stoic-002" in rule_ids

    def test_insight_contains_rendered_template(self, stoic):
        context = {"situation": "a job loss", "mood": "suffering and setback"}
        insights = run_rules(stoic, context)
        amor_fati = [i for i in insights if i["rule_id"] == "stoic-003"]
        assert len(amor_fati) == 1
        assert "a job loss" in amor_fati[0]["insight"]

    def test_no_triggers_returns_empty(self, stoic):
        context = {"situation": "eating breakfast", "mood": "neutral"}
        insights = run_rules(stoic, context)
        assert insights == []

    def test_confidence_is_proportional(self, stoic):
        # Match only 1 of 6 triggers for stoic-001 (weight=0.92).
        context = {"mood": "frustrated"}
        insights = run_rules(stoic, context)
        dic = [i for i in insights if i["rule_id"] == "stoic-001"]
        assert len(dic) == 1
        # 0.92 * (1/6) ≈ 0.1533
        assert 0.10 < dic[0]["confidence"] < 0.20

    def test_min_confidence_filter(self, stoic):
        context = {"mood": "frustrated"}
        # min_confidence filters on the rule's base confidence_weight.
        # stoic-001 has weight=0.92 which passes 0.9, so it is included.
        insights = run_rules(stoic, context, min_confidence=0.9)
        assert len(insights) == 1
        assert insights[0]["rule_id"] == "stoic-001"
        # But with a threshold above 0.92, nothing passes.
        insights_high = run_rules(stoic, context, min_confidence=0.95)
        assert insights_high == []

    def test_insight_structure(self, stoic):
        context = {"situation": "a decision", "mood": "anxious and worried"}
        insights = run_rules(stoic, context)
        assert len(insights) > 0
        required_keys = {
            "rule_id", "name", "principle", "matched_triggers",
            "insight", "confidence", "sovereign_need_served",
            "connects_to", "tags",
        }
        for insight in insights:
            assert required_keys.issubset(insight.keys())
            assert isinstance(insight["matched_triggers"], list)
            assert isinstance(insight["confidence"], float)
            assert 0.0 <= insight["confidence"] <= 1.0

    def test_multiple_rules_fire(self, stoic):
        """Context that hits many rules should return multiple insights."""
        context = {
            "situation": "everything falling apart",
            "mood": "overwhelmed, anxious, frustrated, regret, isolated",
        }
        insights = run_rules(stoic, context)
        assert len(insights) >= 4

    def test_minimal_cartridge_runs(self, minimal_cartridge):
        context = {"mood": "stressed out"}
        insights = run_rules(minimal_cartridge, context)
        assert len(insights) == 1
        assert insights[0]["rule_id"] == "t-001"
        assert "stressed" in insights[0]["matched_triggers"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
