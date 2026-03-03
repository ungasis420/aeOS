"""
cartridge_loader.py — COGNITIVE_CORE cartridge loader for aeOS.

Loads JSON cartridge files from src/cartridges/, validates them against the
cartridge schema, runs rules against a context dict, and returns triggered
insights with confidence scores.  Supports parallel loading via
concurrent.futures.

Stamp: S✅ T✅ L✅ A✅
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default paths are relative to this file's location in the repo tree.
_DEFAULT_CARTRIDGES_DIR = (Path(__file__).resolve().parent / ".." / "cartridges").resolve()
_DEFAULT_SCHEMA_PATH = _DEFAULT_CARTRIDGES_DIR / "cartridge_schema.json"

# ---------------------------------------------------------------------------
# Schema validation (stdlib-only, no jsonschema dependency)
# ---------------------------------------------------------------------------

def _validate_type(value: Any, type_name: str) -> bool:
    """Check that *value* matches the JSON-Schema *type_name*."""
    mapping = {
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    expected = mapping.get(type_name)
    if expected is None:
        return True  # unknown type — allow
    return isinstance(value, expected)


def _validate_against_schema(data: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    """Validate *data* against a JSON-Schema *schema*.

    Returns a list of human-readable error strings (empty == valid).
    This is a lightweight validator covering the subset of JSON-Schema used
    by cartridge_schema.json (required, type, properties, items, minimum,
    maximum, $ref with local definitions).
    """
    errors: List[str] = []
    definitions = schema.get("definitions", {})

    def _resolve(node: Dict[str, Any]) -> Dict[str, Any]:
        ref = node.get("$ref")
        if ref and ref.startswith("#/definitions/"):
            def_name = ref.split("/")[-1]
            return definitions.get(def_name, node)
        return node

    def _check(obj: Any, node: Dict[str, Any], path: str) -> None:
        node = _resolve(node)
        # type
        obj_type = node.get("type")
        if obj_type and not _validate_type(obj, obj_type):
            errors.append(f"{path}: expected type '{obj_type}', got {type(obj).__name__}")
            return
        # minimum / maximum (numbers)
        if isinstance(obj, (int, float)):
            if "minimum" in node and obj < node["minimum"]:
                errors.append(f"{path}: {obj} < minimum {node['minimum']}")
            if "maximum" in node and obj > node["maximum"]:
                errors.append(f"{path}: {obj} > maximum {node['maximum']}")
        # required keys
        if obj_type == "object" or isinstance(obj, dict):
            for key in node.get("required", []):
                if key not in obj:
                    errors.append(f"{path}: missing required key '{key}'")
            # properties
            props = node.get("properties", {})
            for key, sub_schema in props.items():
                if key in obj:
                    _check(obj[key], sub_schema, f"{path}.{key}")
            # additionalProperties
            if node.get("additionalProperties") is False:
                allowed = set(props.keys())
                for key in obj:
                    if key not in allowed:
                        errors.append(f"{path}: unexpected key '{key}'")
            elif isinstance(node.get("additionalProperties"), dict):
                ap_schema = node["additionalProperties"]
                for key, val in obj.items():
                    if key not in node.get("properties", {}):
                        _check(val, ap_schema, f"{path}.{key}")
        # array items
        if (obj_type == "array" or isinstance(obj, list)) and "items" in node:
            item_schema = node["items"]
            for idx, item in enumerate(obj):
                _check(item, item_schema, f"{path}[{idx}]")

    _check(data, schema, "$")
    return errors


# ---------------------------------------------------------------------------
# Cartridge loading
# ---------------------------------------------------------------------------

def load_schema(schema_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load and return the cartridge JSON-Schema as a dict."""
    path = Path(schema_path) if schema_path is not None else _DEFAULT_SCHEMA_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        logger.exception("Failed to load cartridge schema from %s", path)
        raise


def load_cartridge(
    filepath: Path,
    schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Load a single cartridge file, validate it, and return its data.

    Raises ``ValueError`` if schema validation fails.
    Raises ``OSError`` / ``json.JSONDecodeError`` on I/O or parse errors.
    """
    filepath = Path(filepath)
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        logger.exception("Failed to load cartridge file %s", filepath)
        raise

    if schema is not None:
        errors = _validate_against_schema(data, schema)
        if errors:
            msg = f"Cartridge {filepath.name} failed validation:\n  " + "\n  ".join(errors)
            logger.error(msg)
            raise ValueError(msg)

    logger.info("Loaded cartridge '%s' (v%s) from %s", data.get("cartridge_id"), data.get("version"), filepath)
    return data


def load_cartridges(
    cartridges_dir: Optional[Path] = None,
    schema: Optional[Dict[str, Any]] = None,
    max_workers: int = 4,
) -> List[Dict[str, Any]]:
    """Load all .json cartridge files from *cartridges_dir* in parallel.

    Skips the schema file itself. Returns a list of validated cartridge dicts.
    """
    cdir = Path(cartridges_dir) if cartridges_dir is not None else _DEFAULT_CARTRIDGES_DIR
    if schema is None:
        schema = load_schema(cdir / "cartridge_schema.json")

    json_files = [p for p in sorted(cdir.glob("*.json")) if p.name != "cartridge_schema.json"]
    if not json_files:
        logger.warning("No cartridge files found in %s", cdir)
        return []

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(load_cartridge, fp, schema): fp for fp in json_files}
        for future in as_completed(futures):
            fp = futures[future]
            try:
                results.append(future.result())
            except Exception:
                logger.exception("Skipping cartridge %s due to load error", fp.name)
    return results


def load_cartridge_by_id(
    cartridge_id: str,
    cartridges_dir: Optional[Path] = None,
    schema: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Load a single cartridge by its ``cartridge_id``.

    Scans the cartridges directory for a JSON file whose ``cartridge_id``
    field matches *cartridge_id* (case-insensitive).  Returns the cartridge
    dict or ``None`` if not found.
    """
    cdir = Path(cartridges_dir) if cartridges_dir is not None else _DEFAULT_CARTRIDGES_DIR
    if schema is None:
        try:
            schema = load_schema(cdir / "cartridge_schema.json")
        except Exception:
            schema = None

    target = cartridge_id.strip().upper()
    for fp in sorted(cdir.glob("*.json")):
        if fp.name == "cartridge_schema.json":
            continue
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            cid = str(data.get("cartridge_id", "")).strip().upper()
            if cid == target:
                if schema is not None:
                    errors = _validate_against_schema(data, schema)
                    if errors:
                        logger.warning("Cartridge %s validation warnings: %s", cartridge_id, errors)
                logger.info("Loaded cartridge '%s' by ID from %s", cartridge_id, fp)
                return data
        except (OSError, json.JSONDecodeError):
            continue
    logger.warning("Cartridge '%s' not found in %s", cartridge_id, cdir)
    return None


def get_cartridge_index(
    cartridges_dir: Optional[Path] = None,
) -> Dict[str, str]:
    """Return a mapping of cartridge_id → filename for all cartridges.

    Useful for quick lookups without loading full cartridge data.
    """
    cdir = Path(cartridges_dir) if cartridges_dir is not None else _DEFAULT_CARTRIDGES_DIR
    index: Dict[str, str] = {}
    for fp in sorted(cdir.glob("*.json")):
        if fp.name == "cartridge_schema.json":
            continue
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            cid = data.get("cartridge_id", "")
            if cid:
                index[cid] = fp.name
        except (OSError, json.JSONDecodeError):
            continue
    return index


# ---------------------------------------------------------------------------
# Rule execution engine
# ---------------------------------------------------------------------------

def _match_triggers(triggers: List[str], context: Dict[str, Any]) -> List[str]:
    """Return the subset of *triggers* found in any string value of *context*.

    Matching is case-insensitive.
    """
    matched: List[str] = []
    # Flatten context values to searchable strings.
    search_corpus = " ".join(
        str(v) for v in context.values() if isinstance(v, (str, int, float, bool))
    ).lower()
    for trigger in triggers:
        if trigger.lower() in search_corpus:
            matched.append(trigger)
    return matched


def _render_template(template: str, context: Dict[str, Any]) -> str:
    """Fill ``{variable}`` placeholders in *template* from *context*.

    Unknown placeholders are left as-is.
    """
    def _replacer(match: re.Match) -> str:
        key = match.group(1)
        return str(context[key]) if key in context else match.group(0)

    return re.sub(r"\{(\w+)\}", _replacer, template)


def run_rules(
    cartridge: Dict[str, Any],
    context: Dict[str, Any],
    min_confidence: float = 0.0,
) -> List[Dict[str, Any]]:
    """Run all rules in *cartridge* against *context*.

    Returns a list of insight dicts for every rule whose detection_triggers
    matched at least one context value and whose confidence_weight is
    >= *min_confidence*.

    Each insight dict contains:
        rule_id, name, principle, matched_triggers, insight, confidence,
        sovereign_need_served, connects_to, tags
    """
    insights: List[Dict[str, Any]] = []
    for rule in cartridge.get("rules", []):
        matched = _match_triggers(rule.get("detection_triggers", []), context)
        if not matched:
            continue
        weight = rule.get("confidence_weight", 0.0)
        if weight < min_confidence:
            continue

        # Proportional confidence: base weight * fraction of triggers matched.
        total_triggers = len(rule.get("detection_triggers", []))
        hit_ratio = len(matched) / total_triggers if total_triggers else 1.0
        confidence = round(weight * hit_ratio, 4)

        insight_text = _render_template(rule.get("insight_template", ""), context)

        insights.append({
            "rule_id": rule["rule_id"],
            "name": rule["name"],
            "principle": rule["principle"],
            "matched_triggers": matched,
            "insight": insight_text,
            "confidence": confidence,
            "sovereign_need_served": rule.get("sovereign_need_served", ""),
            "connects_to": rule.get("connects_to", []),
            "tags": rule.get("tags", []),
        })
    return insights
