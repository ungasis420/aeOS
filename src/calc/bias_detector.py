"""bias_detector.py
aeOS — Cognitive Bias Detector (pre-scoring guard)
Purpose
-------
Detect cognitive biases in decision inputs before they corrupt scoring.
Designed to feed Bias_Audit_Log (persistence happens elsewhere).
Constraints
-----------
- stdlib only (no DB, no I/O)
- Session tracking for urgency_inflation is in-memory and resets on instantiation.
Minimum bias set (per spec)
---------------------------
- overconfidence: confidence > 0.85 with low evidence_count
- urgency_inflation: urgency > 8 more than 3x in session
- sunk_cost: rationale contains keywords (already invested, too far in, can't stop now)
- confirmation: only positive evidence provided, no counterarguments
- recency: all examples from last 30 days only
- anchoring: first_value present and final_value within 10% of first_value
Stamp: S✅ T✅ L✅ A✅
"""
from __future__ import annotations
import logging
import math
import re
from datetime import date, datetime, timedelta
from numbers import Real
from typing import Any, Dict, List, Optional, Sequence, Tuple, TypedDict, Union
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())
Number = Union[int, float]
class BiasEntry(TypedDict):
    bias_type: str
    confidence_that_bias_exists: float
    evidence: str
    correction_suggestion: str
class DecisionScanResult(TypedDict):
    biases_detected: List[BiasEntry]
    severity: str  # low | medium | high
    clean_decision: Dict[str, Any]
    recommendations: List[str]
# -----------------------------------------------------------------------------
# Generic helpers (calc_pain / calc_bestmoves style: strict + explicit)
# -----------------------------------------------------------------------------
def _is_real_number(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)
def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)
def _as_float(value: Any) -> Optional[float]:
    if not _is_real_number(value):
        return None
    v = float(value)
    return v if math.isfinite(v) else None
def _as_text_list(value: Any) -> List[str]:
    """Normalize value to list[str] (best-effort)."""
    if value is None:
        return []
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else []
    if isinstance(value, (list, tuple)):
        out: List[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif item is not None:
                out.append(str(item))
        return [x for x in out if x.strip()]
    return [str(value)]
def _normalize_confidence(raw: Any) -> Optional[float]:
    """Return confidence normalized to 0.0–1.0 (supports 0–1 or 0–100)."""
    v = _as_float(raw)
    if v is None:
        return None
    if 0.0 <= v <= 1.0:
        return v
    if 1.0 < v <= 100.0:
        return v / 100.0
    return None
def _count_evidence(decision: Dict[str, Any]) -> Optional[int]:
    """Best-effort evidence item count."""
    if "evidence_count" in decision:
        n = _as_int(decision.get("evidence_count"))
        return max(0, n) if n is not None else None
    # evidence_for/evidence can be list or string.
    for key in ("evidence_for", "evidence", "supporting_evidence"):
        v = decision.get(key)
        if isinstance(v, (list, tuple)):
            return len(v)
        if isinstance(v, str) and v.strip():
            # Heuristic: count non-empty lines split by newline/semicolon.
            chunks = [c.strip() for c in re.split(r"[\n;]+", v.strip()) if c.strip()]
            return max(1, len(chunks))
    return None
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
def _parse_date(value: Any) -> Optional[date]:
    """Parse date inputs (date/datetime/ISO string/embedded YYYY-MM-DD)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # ISO date
        try:
            if len(s) == 10 and s[4] == "-" and s[7] == "-":
                return date.fromisoformat(s)
        except Exception:
            pass
        # ISO datetime
        try:
            ss = s.replace("Z", "+00:00")
            return datetime.fromisoformat(ss).date()
        except Exception:
            pass
        # Embedded YYYY-MM-DD
        m = _DATE_RE.search(s)
        if m:
            try:
                return date.fromisoformat(m.group(1))
            except Exception:
                return None
    return None
def _extract_example_dates(decision: Dict[str, Any]) -> Tuple[List[date], int]:
    """Return (parsed_dates, total_examples)."""
    if "example_dates" in decision:
        raw = decision.get("example_dates")
        if isinstance(raw, (list, tuple)):
            total = len(raw)
            parsed = [d for d in (_parse_date(x) for x in raw) if d is not None]
            return parsed, total
        d = _parse_date(raw)
        return ([d] if d else []), (1 if raw is not None else 0)
    examples = decision.get("examples")
    if examples is None:
        return [], 0
    if isinstance(examples, (list, tuple)):
        total = len(examples)
        parsed: List[date] = []
        for ex in examples:
            if isinstance(ex, dict):
                d = _parse_date(ex.get("date") or ex.get("when"))
            else:
                d = _parse_date(ex)
            if d is not None:
                parsed.append(d)
        return parsed, total
    d = _parse_date(examples)
    return ([d] if d else []), 1
def _dedupe_preserve_order(items: Sequence[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
# -----------------------------------------------------------------------------
# Bias detector
# -----------------------------------------------------------------------------
class BiasDetector:
    """Session-scoped bias detector (holds in-memory counters)."""
    def __init__(
        self,
        *,
        overconfidence_threshold: float = 0.85,
        low_evidence_threshold: int = 2,  # "low evidence" means evidence_count < 2
        high_urgency_threshold: int = 8,  # urgency > 8 is considered "high"
        high_urgency_limit: int = 3,      # flag when high urgency occurs > 3 times in session
        recency_window_days: int = 30,
        anchoring_tolerance_ratio: float = 0.10,
    ) -> None:
        self.overconfidence_threshold = float(overconfidence_threshold)
        self.low_evidence_threshold = int(low_evidence_threshold)
        self.high_urgency_threshold = int(high_urgency_threshold)
        self.high_urgency_limit = int(high_urgency_limit)
        self.recency_window_days = int(recency_window_days)
        self.anchoring_tolerance_ratio = float(anchoring_tolerance_ratio)
        # Session counter (resets on instantiation)
        self._high_urgency_count = 0
    def scan_decision(self, decision_dict: Dict[str, Any]) -> DecisionScanResult:
        """Scan a decision dict for cognitive bias signals (best-effort).
        The input may be sparse; missing keys simply result in fewer detections.
        """
        if not isinstance(decision_dict, dict):
            raise TypeError(f"decision_dict must be a dict, got {type(decision_dict).__name__}")
        decision: Dict[str, Any] = dict(decision_dict)  # shallow copy
        biases: List[BiasEntry] = []
        urgency = _as_int(decision.get("urgency"))
        confidence = _normalize_confidence(decision.get("confidence"))
        evidence_count = _count_evidence(decision)
        rationale = str(decision.get("rationale") or decision.get("reason") or decision.get("notes") or "").strip()
        # Detect biases (minimum 6 per spec)
        oc = self._detect_overconfidence(confidence=confidence, evidence_count=evidence_count)
        if oc:
            biases.append(oc)
        ui = self._detect_urgency_inflation(urgency=urgency)
        if ui:
            biases.append(ui)
        sc = self._detect_sunk_cost(rationale=rationale)
        if sc:
            biases.append(sc)
        cb = self._detect_confirmation(decision)
        if cb:
            biases.append(cb)
        rb = self._detect_recency(decision)
        if rb:
            biases.append(rb)
        ab = self._detect_anchoring(decision)
        if ab:
            biases.append(ab)
        severity = _overall_severity(biases)
        recommendations = _recommendations_from_biases(biases)
        decision["bias_flags"] = {b["bias_type"]: True for b in biases}
        decision["bias_severity"] = severity
        return {
            "biases_detected": biases,
            "severity": severity,
            "clean_decision": decision,
            "recommendations": recommendations,
        }
    # -----------------------------
    # Individual detectors
    # -----------------------------
    def _detect_overconfidence(self, *, confidence: Optional[float], evidence_count: Optional[int]) -> Optional[BiasEntry]:
        if confidence is None or not (0.0 <= confidence <= 1.0):
            return None
        if confidence <= self.overconfidence_threshold:
            return None
        if evidence_count is None:
            # Conservative: can't assert "low evidence" if evidence_count is unknown.
            logger.debug("Overconfidence check skipped: evidence_count missing.")
            return None
        if evidence_count >= self.low_evidence_threshold:
            return None
        conf_factor = min(
            1.0,
            max(
                0.0,
                (confidence - self.overconfidence_threshold)
                / max(1e-9, (1.0 - self.overconfidence_threshold)),
            ),
        )
        evidence_factor = 1.0 if evidence_count <= 0 else 0.8
        bias_conf = min(1.0, 0.6 + (0.4 * conf_factor * evidence_factor))
        return {
            "bias_type": "overconfidence",
            "confidence_that_bias_exists": round(float(bias_conf), 2),
            "evidence": f"confidence={confidence:.2f} (> {self.overconfidence_threshold:.2f}) with evidence_count={evidence_count} (< {self.low_evidence_threshold}).",
            "correction_suggestion": "Lower confidence until you add disconfirming evidence (>=2 counterpoints) or raise evidence_count; write 'what would change my mind?'.",
        }
    def _detect_urgency_inflation(self, *, urgency: Optional[int]) -> Optional[BiasEntry]:
        if urgency is None:
            return None
        if urgency > self.high_urgency_threshold:
            self._high_urgency_count += 1
            if self._high_urgency_count > self.high_urgency_limit:
                over_by = self._high_urgency_count - self.high_urgency_limit
                bias_conf = min(1.0, 0.65 + (0.08 * over_by) + (0.03 * (urgency - self.high_urgency_threshold)))
                return {
                    "bias_type": "urgency_inflation",
                    "confidence_that_bias_exists": round(float(bias_conf), 2),
                    "evidence": (
                        f"urgency={urgency} (> {self.high_urgency_threshold}) has appeared "
                        f"{self._high_urgency_count} times this session (limit={self.high_urgency_limit})."
                    ),
                    "correction_suggestion": "Cooling-off: re-score urgency after 30\u201360 minutes and add a due date; ask 'what breaks if this waits 24 hours?'.",
                }
        return None
    def _detect_sunk_cost(self, *, rationale: str) -> Optional[BiasEntry]:
        if not rationale:
            return None
        keywords = [
            "already invested",
            "too far in",
            "can't stop now",
            "can\u2019t stop now",
        ]
        hits = [kw for kw in keywords if kw.lower() in rationale.lower()]
        if not hits:
            return None
        bias_conf = min(1.0, 0.80 + (0.05 * max(0, len(hits) - 1)))
        return {
            "bias_type": "sunk_cost",
            "confidence_that_bias_exists": round(float(bias_conf), 2),
            "evidence": f"rationale includes sunk-cost language: {', '.join(sorted(set(hits)))}",
            "correction_suggestion": "Decide from today forward: ignore past spend/time; compare options by future cost vs future benefit; ask 'if I had not started, would I start now?'.",
        }
    def _detect_confirmation(self, decision: Dict[str, Any]) -> Optional[BiasEntry]:
        evidence_for = _as_text_list(decision.get("evidence_for") or decision.get("pros") or decision.get("supporting_evidence"))
        evidence_against = _as_text_list(
            decision.get("evidence_against")
            or decision.get("counterarguments")
            or decision.get("cons")
            or decision.get("risks")
            or decision.get("downside")
        )
        if not evidence_for:
            return None
        if evidence_against:
            return None
        bias_conf = 0.70 + min(0.25, 0.05 * max(0, len(evidence_for) - 1))
        return {
            "bias_type": "confirmation",
            "confidence_that_bias_exists": round(float(bias_conf), 2),
            "evidence": f"Provided {len(evidence_for)} positive evidence items but no counterarguments/evidence_against.",
            "correction_suggestion": "Add >=2 counterarguments (or run a quick pre-mortem) and one disconfirming test; then revisit confidence.",
        }
    def _detect_recency(self, decision: Dict[str, Any]) -> Optional[BiasEntry]:
        parsed_dates, total_examples = _extract_example_dates(decision)
        if total_examples <= 0:
            return None
        # Conservative: only trigger when we can parse all example dates.
        if len(parsed_dates) != total_examples:
            logger.debug(
                "Recency check skipped: could not parse all example dates (%s/%s).",
                len(parsed_dates),
                total_examples,
            )
            return None
        window = max(1, int(self.recency_window_days))
        cutoff = date.today() - timedelta(days=window)
        if all(d >= cutoff for d in parsed_dates):
            bias_conf = 0.65 + min(0.25, 0.05 * max(0, total_examples - 1))
            oldest = min(parsed_dates).isoformat()
            newest = max(parsed_dates).isoformat()
            return {
                "bias_type": "recency",
                "confidence_that_bias_exists": round(float(bias_conf), 2),
                "evidence": f"All {total_examples} examples are within the last {window} days (range: {oldest} to {newest}).",
                "correction_suggestion": "Bring an outside view: add older examples or base-rate data (3\u201312 months) and check if the decision still holds.",
            }
        return None
    def _detect_anchoring(self, decision: Dict[str, Any]) -> Optional[BiasEntry]:
        first = _as_float(decision.get("first_value") or decision.get("initial_value") or decision.get("anchor_value"))
        final = _as_float(decision.get("final_value") or decision.get("estimate") or decision.get("proposed_value") or decision.get("current_value"))
        if first is None or final is None:
            return None
        tol = max(0.0, float(self.anchoring_tolerance_ratio))
        # Avoid division by zero; anchoring around 0 only triggers when final is ~0.
        if first == 0.0:
            if final != 0.0:
                return None
            ratio = 0.0
        else:
            ratio = abs(final - first) / abs(first)
        if ratio > tol:
            return None
        closeness = 1.0 - min(1.0, ratio / tol) if tol > 0 else 1.0
        bias_conf = min(1.0, 0.65 + (0.25 * closeness))
        return {
            "bias_type": "anchoring",
            "confidence_that_bias_exists": round(float(bias_conf), 2),
            "evidence": f"final_value={final} is within {ratio*100:.1f}% of first_value={first} (tolerance={tol*100:.0f}%).",
            "correction_suggestion": "Generate an independent estimate before looking at the anchor; use a range (best/base/worst) and compare to base rates.",
        }
# -----------------------------------------------------------------------------
# Synthesis helpers
# -----------------------------------------------------------------------------
def _overall_severity(biases: Sequence[BiasEntry]) -> str:
    if not biases:
        return "low"
    confidences = [float(b.get("confidence_that_bias_exists", 0.0)) for b in biases]
    max_c = max(confidences) if confidences else 0.0
    sum_c = sum(confidences)
    if max_c >= 0.80 or sum_c >= 2.00 or len(biases) >= 3:
        return "high"
    if max_c >= 0.50 or sum_c >= 1.00:
        return "medium"
    return "low"
def _recommendations_from_biases(biases: Sequence[BiasEntry]) -> List[str]:
    recs = [
        str(b.get("correction_suggestion", "")).strip()
        for b in biases
        if str(b.get("correction_suggestion", "")).strip()
    ]
    if biases:
        recs.append("Do a 2-minute 'outside view' check: base rate + simplest falsifiable test.")
    return _dedupe_preserve_order(recs)
# -----------------------------------------------------------------------------
# Module-level convenience API (keeps session tracking in-process)
# -----------------------------------------------------------------------------
_DEFAULT_DETECTOR = BiasDetector()
def scan_decision(decision_dict: Dict[str, Any]) -> DecisionScanResult:
    """Convenience function using a module-level detector instance."""
    return _DEFAULT_DETECTOR.scan_decision(decision_dict)
__all__ = ["BiasDetector", "scan_decision"]
