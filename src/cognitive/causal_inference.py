"""CausalInferenceEngine — Stub for F1.6 causal graph interface.

Provides a lightweight directed graph for tracking causal relationships
between events, metrics, and decisions within aeOS.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional, Tuple


class CausalInferenceEngine:
    """Causal graph engine for tracking cause-effect relationships.

    Maintains an in-memory directed graph of causal edges with weights
    and evidence. Designed for later persistence to Causal_Graph_Log.
    """

    def __init__(self) -> None:
        self._edges: List[dict] = []

    def add_edge(
        self,
        cause: str,
        effect: str,
        weight: float = 0.5,
        evidence: str = "",
        domain: str = "general",
    ) -> str:
        """Add a causal edge to the graph.

        Args:
            cause: Cause node identifier.
            effect: Effect node identifier.
            weight: Edge weight (0.0–1.0), strength of causal link.
            evidence: Supporting evidence text.
            domain: Domain tag.

        Returns:
            edge_id (str).
        """
        if not isinstance(cause, str) or not cause.strip():
            raise ValueError("cause must be a non-empty string")
        if not isinstance(effect, str) or not effect.strip():
            raise ValueError("effect must be a non-empty string")
        w = float(weight)
        if w < 0.0 or w > 1.0:
            raise ValueError("weight must be between 0.0 and 1.0")

        edge_id = str(uuid.uuid4())
        self._edges.append({
            "edge_id": edge_id,
            "cause": cause.strip(),
            "effect": effect.strip(),
            "weight": w,
            "evidence": str(evidence),
            "domain": str(domain),
            "created_at": time.time(),
        })
        return edge_id

    def get_causes(self, effect: str) -> List[dict]:
        """Get all cause nodes for a given effect."""
        return [e for e in self._edges if e["effect"] == effect]

    def get_effects(self, cause: str) -> List[dict]:
        """Get all effect nodes for a given cause."""
        return [e for e in self._edges if e["cause"] == cause]

    def get_all_edges(self) -> List[dict]:
        """Return all edges in the graph."""
        return list(self._edges)

    def get_nodes(self) -> List[str]:
        """Return all unique node identifiers."""
        nodes = set()
        for e in self._edges:
            nodes.add(e["cause"])
            nodes.add(e["effect"])
        return sorted(nodes)

    def compute_influence_score(self, node: str) -> float:
        """Compute influence score for a node (sum of outgoing weights).

        Returns:
            Influence score (float >= 0).
        """
        return sum(e["weight"] for e in self._edges if e["cause"] == node)

    def find_path(self, start: str, end: str, max_depth: int = 10) -> Optional[List[str]]:
        """Find a causal path from start to end using BFS.

        Returns:
            List of node names forming the path, or None if no path found.
        """
        if start == end:
            return [start]
        visited = set()
        queue: List[Tuple[str, List[str]]] = [(start, [start])]
        while queue:
            current, path = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            if len(path) > max_depth:
                continue
            for edge in self._edges:
                if edge["cause"] == current and edge["effect"] not in visited:
                    new_path = path + [edge["effect"]]
                    if edge["effect"] == end:
                        return new_path
                    queue.append((edge["effect"], new_path))
        return None

    def get_graph_summary(self) -> dict:
        """Return summary statistics of the causal graph.

        Returns:
            {node_count, edge_count, avg_weight, domains}
        """
        nodes = self.get_nodes()
        weights = [e["weight"] for e in self._edges]
        domains = list(set(e["domain"] for e in self._edges))
        return {
            "node_count": len(nodes),
            "edge_count": len(self._edges),
            "avg_weight": sum(weights) / len(weights) if weights else 0.0,
            "domains": sorted(domains),
        }
