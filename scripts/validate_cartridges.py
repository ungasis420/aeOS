"""
scripts/validate_cartridges.py
Validates all aeOS cartridge JSON files for schema compliance.
Run before Phase 4 loads them.
Usage:
    python scripts/validate_cartridges.py
    python scripts/validate_cartridges.py --dir src/cartridges --strict
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Schema contract
# ---------------------------------------------------------------------------
REQUIRED_TOP_LEVEL = ["cartridge_id", "domain", "version", "rule_count", "rules"]
REQUIRED_RULE_FIELDS = ["rule_id", "text"]
EXPECTED_RULE_COUNT = 10
CARTRIDGE_ID_PREFIX = "CART-"


@dataclass
class ValidationError:
    file: str
    field: str
    message: str
    severity: str = "ERROR"  # ERROR | WARNING


@dataclass
class CartridgeReport:
    path: str
    cartridge_id: str = ""
    domain: str = ""
    rule_count_declared: int = 0
    rule_count_actual: int = 0
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------
class CartridgeValidator:
    def __init__(self, strict: bool = False):
        self.strict = strict

    def validate_file(self, path: Path) -> CartridgeReport:
        report = CartridgeReport(path=str(path))

        # 1. Parse JSON
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            report.errors.append(ValidationError(str(path), "json", f"Invalid JSON: {e}"))
            return report
        except Exception as e:
            report.errors.append(ValidationError(str(path), "file", f"Cannot read: {e}"))
            return report

        # 2. Top-level required fields
        for field_name in REQUIRED_TOP_LEVEL:
            if field_name not in data:
                report.errors.append(ValidationError(str(path), field_name, f"Missing required field '{field_name}'"))

        if report.errors:
            return report  # can't go further

        report.cartridge_id = data.get("cartridge_id", "")
        report.domain = data.get("domain", "")
        report.rule_count_declared = data.get("rule_count", 0)

        # 3. cartridge_id format
        if not report.cartridge_id.startswith(CARTRIDGE_ID_PREFIX):
            report.errors.append(ValidationError(
                str(path), "cartridge_id",
                f"Must start with '{CARTRIDGE_ID_PREFIX}', got '{report.cartridge_id}'"
            ))

        # 4. cartridge_id matches filename
        expected_stem = report.cartridge_id.replace("CART-", "").lower().replace("_", "-")
        actual_stem = path.stem.lower()
        if expected_stem not in actual_stem and actual_stem not in expected_stem:
            report.warnings.append(ValidationError(
                str(path), "cartridge_id",
                f"cartridge_id '{report.cartridge_id}' may not match filename '{path.name}'",
                severity="WARNING"
            ))

        # 5. Rules array
        rules = data.get("rules", [])
        if not isinstance(rules, list):
            report.errors.append(ValidationError(str(path), "rules", "Must be a list"))
            return report

        report.rule_count_actual = len(rules)

        # 6. Rule count matches declared
        if report.rule_count_declared != report.rule_count_actual:
            report.errors.append(ValidationError(
                str(path), "rule_count",
                f"Declared {report.rule_count_declared} but found {report.rule_count_actual} rules"
            ))

        # 7. Expected 10 rules
        if report.rule_count_actual != EXPECTED_RULE_COUNT:
            sev = "ERROR" if self.strict else "WARNING"
            msg = f"Expected {EXPECTED_RULE_COUNT} rules, found {report.rule_count_actual}"
            item = ValidationError(str(path), "rules", msg, severity=sev)
            if sev == "ERROR":
                report.errors.append(item)
            else:
                report.warnings.append(item)

        # 8. Each rule has required fields
        seen_rule_ids = set()
        for i, rule in enumerate(rules):
            if not isinstance(rule, dict):
                report.errors.append(ValidationError(str(path), f"rules[{i}]", "Rule must be an object"))
                continue
            for rf in REQUIRED_RULE_FIELDS:
                if rf not in rule:
                    report.errors.append(ValidationError(
                        str(path), f"rules[{i}].{rf}", f"Missing required rule field '{rf}'"
                    ))

            # Duplicate rule_id check
            rid = rule.get("rule_id", "")
            if rid in seen_rule_ids:
                report.errors.append(ValidationError(
                    str(path), f"rules[{i}].rule_id", f"Duplicate rule_id '{rid}'"
                ))
            if rid:
                seen_rule_ids.add(rid)

        # 9. Version field format
        version = data.get("version", "")
        if not isinstance(version, (str, int, float)):
            report.warnings.append(ValidationError(str(path), "version", "Version should be string or number", "WARNING"))

        return report


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run_validation(cartridge_dir: str, strict: bool = False) -> int:
    """Returns exit code: 0=all valid, 1=errors found."""
    base = Path(cartridge_dir)
    if not base.exists():
        print(f"ERROR: Directory not found: {cartridge_dir}")
        return 1

    json_files = sorted(base.glob("*.json"))
    if not json_files:
        print(f"WARNING: No JSON files found in {cartridge_dir}")
        return 0

    validator = CartridgeValidator(strict=strict)
    reports: List[CartridgeReport] = []
    for f in json_files:
        r = validator.validate_file(f)
        reports.append(r)

    # Print results
    valid = [r for r in reports if r.valid]
    invalid = [r for r in reports if not r.valid]
    warnings_only = [r for r in valid if r.warnings]

    print(f"\naeOS Cartridge Validator")
    print(f"{'='*50}")
    print(f"Directory : {cartridge_dir}")
    print(f"Files     : {len(reports)}")
    print(f"Valid     : {len(valid)}")
    print(f"Invalid   : {len(invalid)}")
    print(f"Warnings  : {sum(len(r.warnings) for r in reports)}")
    print()

    if invalid:
        print("ERRORS:")
        for r in invalid:
            print(f"  ✗ {Path(r.path).name}")
            for e in r.errors:
                print(f"      [{e.severity}] {e.field}: {e.message}")
        print()

    if warnings_only:
        print("WARNINGS (valid but flagged):")
        for r in warnings_only:
            print(f"  ⚠ {Path(r.path).name}")
            for w in r.warnings:
                print(f"      [WARN] {w.field}: {w.message}")
        print()

    if not invalid:
        print(f"✓ All {len(reports)} cartridges valid")
        if strict:
            total_warnings = sum(len(r.warnings) for r in reports)
            if total_warnings > 0:
                print(f"  (strict mode: {total_warnings} warnings treated as failures)")
                return 1
    else:
        print(f"✗ {len(invalid)} cartridge(s) failed validation")

    # Summary table
    print(f"\n{'ID':<35} {'Domain':<25} {'Rules':<6} {'Status'}")
    print("-" * 80)
    for r in sorted(reports, key=lambda x: x.cartridge_id):
        status = "✓" if r.valid else "✗"
        warn = f" ({len(r.warnings)}w)" if r.warnings else ""
        print(f"{r.cartridge_id:<35} {r.domain:<25} {r.rule_count_actual:<6} {status}{warn}")

    return 1 if invalid else 0


def main():
    parser = argparse.ArgumentParser(description="Validate aeOS cartridge JSON files")
    parser.add_argument("--dir", default="src/cartridges", help="Cartridge directory")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    args = parser.parse_args()
    sys.exit(run_validation(args.dir, strict=args.strict))


if __name__ == "__main__":
    main()
