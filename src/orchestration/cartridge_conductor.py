"""
cartridge_conductor.py — Loads relevant cartridges and produces ranked insights.

Receives an OrchestratorRequest, loads cartridges whose domain matches the
intent, runs trigger matching against the input text via
``cartridge_loader.run_rules``, and returns a ranked list of
CartridgeInsight objects (max 20, sorted by confidence descending).

Stamp: S✅ T✅ L✅ A✅
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.cognitive.cartridge_loader import load_cartridges, run_rules
from src.orchestration.models import CartridgeInsight, OrchestratorRequest

logger = logging.getLogger(__name__)

_MAX_INSIGHTS = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _domain_matches(cartridge_domain: str, requested_domains: List[str]) -> bool:
    """Return True if *cartridge_domain* is reachable from any requested domain.

    Supports prefix matching in both directions:
      - requested "philosophy" matches cartridge "philosophy.stoicism"
      - requested "philosophy.stoicism" matches cartridge "philosophy.stoicism"
    """
    cd = cartridge_domain.lower()
    for rd in requested_domains:
        rd_l = rd.lower()
        if cd.startswith(rd_l) or rd_l.startswith(cd):
            return True
    return False


def _extract_context(text: str) -> Dict[str, Any]:
    """Build a context dict from raw user text for template rendering.

    Populates ``situation`` (used by most cartridge templates) and ``text``
    as a fallback.  Also attempts lightweight noun-phrase extraction so
    additional ``{variables}`` in templates can be filled.
    """
    ctx: Dict[str, Any] = {"situation": text, "text": text}

    # Lightweight extraction: pull quoted phrases or capitalized noun groups.
    # These become available as {topic}, {subject} in templates.
    quoted = re.findall(r'"([^"]+)"', text)
    if quoted:
        ctx["topic"] = quoted[0]

    words = text.split()
    if len(words) >= 2:
        ctx["subject"] = " ".join(words[:5])

    return ctx


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class CartridgeConductor:
    """Loads cartridges, runs rules, and returns ranked insights."""

    def __init__(
        self,
        cartridges_dir: Optional[Path] = None,
        cartridges: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Initialise the conductor.

        Parameters
        ----------
        cartridges_dir:
            Directory to load cartridge JSON files from.  Ignored when
            *cartridges* is provided.
        cartridges:
            Pre-loaded cartridge dicts (useful for testing).
        """
        self._cartridges_dir = cartridges_dir
        self._preloaded = cartridges

    def _get_cartridges(self) -> List[Dict[str, Any]]:
        """Return all available cartridges, loading from disk if needed."""
        if self._preloaded is not None:
            return self._preloaded
        return load_cartridges(self._cartridges_dir)

    def conduct(self, request: OrchestratorRequest) -> List[CartridgeInsight]:
        """Run cartridge rules against the request and return ranked insights.

        Returns at most ``_MAX_INSIGHTS`` CartridgeInsight objects sorted by
        confidence descending.
        """
        all_cartridges = self._get_cartridges()
        domains = request.intent.domains

        # Filter cartridges by domain affinity.
        relevant = [
            c for c in all_cartridges
            if _domain_matches(c.get("domain", ""), domains)
        ]

        if not relevant:
            logger.warning("No cartridges matched domains %s", domains)
            return []

        context = _extract_context(request.raw_text)

        # Gather insights from all relevant cartridges.
        raw_insights: List[CartridgeInsight] = []
        for cart in relevant:
            cart_id = cart.get("cartridge_id", "unknown")
            for ins in run_rules(cart, context):
                raw_insights.append(
                    CartridgeInsight(
                        rule_id=ins["rule_id"],
                        cartridge_id=cart_id,
                        insight_text=ins["insight"],
                        confidence=ins["confidence"],
                        sovereign_need=ins.get("sovereign_need_served", ""),
                        tags=ins.get("tags", []),
                    )
                )

        # Rank by confidence descending, cap at MAX_INSIGHTS.
        raw_insights.sort(key=lambda i: i.confidence, reverse=True)
        result = raw_insights[:_MAX_INSIGHTS]

        logger.info(
            "Conductor produced %d insights (from %d cartridges, %d domains)",
            len(result), len(relevant), len(domains),
        )
        return result
