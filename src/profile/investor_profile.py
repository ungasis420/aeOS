"""
investor_profile.py
Pure configuration module for aeOS.
- No DB queries, no math engines, no AI calls.
- Stores and retrieves the user's operating mode + basic investing profile.
- Persistence is a stub: JSON file read/write to ../db/investor_profile.json
Stdlib only: json, os, pathlib, datetime, typing
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
_ALLOWED_MODES = {"personal", "professional"}
_ALLOWED_RISK = {"conservative", "moderate", "aggressive"}
def _now_iso_utc() -> str:
    """
    Return an ISO-8601 datetime string in UTC with explicit timezone offset.
    Example: '2026-02-27T02:10:30.123456+00:00'
    """
    return datetime.now(timezone.utc).isoformat()
def _parse_iso_datetime(value: str) -> datetime:
    """
    Parse an ISO datetime string.
    Notes:
    - Accepts 'Z' suffix by converting it to '+00:00'.
    - Raises ValueError for invalid formats.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Datetime value must be a non-empty string.")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    return datetime.fromisoformat(v)
def _default_profile_path() -> Path:
    """
    Default location for persistence stub:
    ../db/investor_profile.json (relative to this module file)
    This keeps the path stable regardless of the current working directory.
    """
    return (Path(__file__).resolve().parent / ".." / "db" / "investor_profile.json").resolve()
@dataclass
class InvestorProfile:
    """
    Configuration container for aeOS "InvestorProfile".
    Fields:
      - mode: "personal" | "professional"
      - risk_tolerance: "conservative" | "moderate" | "aggressive"
      - primary_currency: str (default "PHP")
      - monthly_income_target: float (default 0.0)
      - created_at: str (ISO datetime string, set at init if not provided)
      - updated_at: str (ISO datetime string, updated on changes)
    This is a "pure configuration" object: it does not talk to databases,
    call AI, or compute portfolio math. It only validates and serializes.
    """
    mode: str = "personal"
    risk_tolerance: str = "moderate"
    primary_currency: str = "PHP"
    monthly_income_target: float = 0.0
    created_at: str = ""
    updated_at: str = ""
    def __init__(
        self,
        mode: str = "personal",
        risk_tolerance: str = "moderate",
        primary_currency: str = "PHP",
        monthly_income_target: float = 0.0,
    ) -> None:
        self.mode = mode
        self.risk_tolerance = risk_tolerance
        self.primary_currency = primary_currency
        self.monthly_income_target = float(monthly_income_target)
        # Timestamps are created at initialization time.
        # We use UTC for consistency across environments.
        now = _now_iso_utc()
        self.created_at = now
        self.updated_at = now
    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize to a JSON-friendly dict (all fields included).
        """
        return {
            "mode": self.mode,
            "risk_tolerance": self.risk_tolerance,
            "primary_currency": self.primary_currency,
            "monthly_income_target": float(self.monthly_income_target),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InvestorProfile":
        """
        Reconstruct an InvestorProfile from a dict.
        Missing fields fall back to defaults.
        This does NOT auto-save; it only creates an in-memory object.
        """
        if not isinstance(data, dict):
            # Defensive: if corrupted JSON is not a dict, return defaults.
            return cls()
        mode = data.get("mode", "personal")
        risk = data.get("risk_tolerance", "moderate")
        currency = data.get("primary_currency", "PHP")
        income_raw = data.get("monthly_income_target", 0.0)
        try:
            income = float(income_raw)
        except (TypeError, ValueError):
            income = 0.0
        profile = cls(
            mode=str(mode),
            risk_tolerance=str(risk),
            primary_currency=str(currency),
            monthly_income_target=income,
        )
        # Preserve stored timestamps when present; otherwise keep init timestamps.
        created_at = data.get("created_at")
        updated_at = data.get("updated_at")
        if isinstance(created_at, str) and created_at.strip():
            profile.created_at = created_at.strip()
        if isinstance(updated_at, str) and updated_at.strip():
            profile.updated_at = updated_at.strip()
        return profile
    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validate the profile fields.
        Returns:
            (is_valid, errors)
        Notes:
        - This is intentionally strict on enum fields (mode, risk_tolerance).
        - Currency is allowed to be any non-empty string, but normalized to upper-case.
        """
        errors: List[str] = []
        # mode
        if not isinstance(self.mode, str) or self.mode.strip() not in _ALLOWED_MODES:
            errors.append(f"mode must be one of {_ALLOWED_MODES}.")
        else:
            self.mode = self.mode.strip()
        # risk_tolerance
        if not isinstance(self.risk_tolerance, str) or self.risk_tolerance.strip() not in _ALLOWED_RISK:
            errors.append(f"risk_tolerance must be one of {_ALLOWED_RISK}.")
        else:
            self.risk_tolerance = self.risk_tolerance.strip()
        # primary_currency
        if not isinstance(self.primary_currency, str) or not self.primary_currency.strip():
            errors.append("primary_currency must be a non-empty string.")
        else:
            # Normalize for consistency (e.g., 'php' -> 'PHP').
            self.primary_currency = self.primary_currency.strip().upper()
        # monthly_income_target
        try:
            self.monthly_income_target = float(self.monthly_income_target)
            if self.monthly_income_target < 0:
                errors.append("monthly_income_target must be >= 0.0.")
        except (TypeError, ValueError):
            errors.append("monthly_income_target must be a number.")
        # created_at / updated_at
        try:
            created_dt = _parse_iso_datetime(self.created_at)
        except Exception:
            errors.append("created_at must be a valid ISO datetime string.")
            created_dt = None
        try:
            updated_dt = _parse_iso_datetime(self.updated_at)
        except Exception:
            errors.append("updated_at must be a valid ISO datetime string.")
            updated_dt = None
        # updated_at should not be earlier than created_at (if both parse)
        if created_dt is not None and updated_dt is not None:
            if updated_dt < created_dt:
                errors.append("updated_at must be >= created_at.")
        return (len(errors) == 0, errors)
    def is_professional_mode(self) -> bool:
        """
        True if profile is in professional mode.
        """
        return self.mode == "professional"
    def is_personal_mode(self) -> bool:
        """
        True if profile is in personal mode.
        """
        return self.mode == "personal"
    def update_mode(self, new_mode: str) -> None:
        """
        Update the operating mode after validating the new value.
        Updates updated_at on success.
        Raises:
            ValueError: if new_mode is invalid.
        """
        if not isinstance(new_mode, str) or new_mode.strip() not in _ALLOWED_MODES:
            raise ValueError(f"new_mode must be one of {_ALLOWED_MODES}.")
        self.mode = new_mode.strip()
        self.updated_at = _now_iso_utc()
def save_profile(profile: InvestorProfile) -> bool:
    """
    Persistence stub: serialize to JSON and write to ../db/investor_profile.json
    Returns:
        True if written successfully, False otherwise.
    """
    is_valid, _errors = profile.validate()
    if not is_valid:
        return False
    path = _default_profile_path()
    # Ensure ../db exists (stub persistence only).
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False
def load_profile() -> InvestorProfile:
    """
    Persistence stub: read ../db/investor_profile.json and reconstruct profile.
    Behavior:
      - If file not found: returns default InvestorProfile()
      - If JSON invalid/corrupt: returns default InvestorProfile()
      - If loaded profile fails validation: returns default InvestorProfile()
    """
    path = _default_profile_path()
    if not path.exists():
        return InvestorProfile()
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        profile = InvestorProfile.from_dict(data if isinstance(data, dict) else {})
        ok, _errs = profile.validate()
        return profile if ok else InvestorProfile()
    except (OSError, json.JSONDecodeError):
        return InvestorProfile()
# Optional convenience: allow overriding path via env var for testing/dev.
# (Not required by spec; harmless and stdlib-only.)
ENV_PROFILE_PATH = "AEOS_INVESTOR_PROFILE_PATH"
def save_profile_to_env_path(profile: InvestorProfile) -> bool:
    """
    Optional helper: if AEOS_INVESTOR_PROFILE_PATH is set, save there instead.
    Falls back to default path if env var is missing/empty.
    This keeps the primary save_profile() behavior exactly as spec'd.
    """
    custom = os.getenv(ENV_PROFILE_PATH, "").strip()
    if not custom:
        return save_profile(profile)
    is_valid, _errors = profile.validate()
    if not is_valid:
        return False
    path = Path(custom).expanduser().resolve()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False
