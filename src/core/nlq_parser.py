"""
aeOS Phase 4 — NLQ_Parser (A5)
================================
Natural language query interface. Accepts plain English, routes to
correct AeOSCore method.

Most important decisions happen when you cannot remember command syntax.
Universal entry point.

Layer: 4 (AI — input layer)
Dependencies: LOCAL_LLM_BRIDGE (Tier 1 classification), SMART_ROUTER,
              CARTRIDGE_LOADER (domain detection)

Interface Contract (from Addendum A):
    parse(query)                -> ParsedIntent
    getSuggestions(partial)     -> list[str]
    getExamples(domain?)       -> list[str]
    train(feedback)            -> None

Classification: Tier 1 local model for intent classification. < 100ms.
Integration: AeOSCore.query() accepts raw string -> NLQ_Parser.parse()
             first -> routes to structured handler.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# Intent types
# ---------------------------------------------------------------------------

class IntentType:
    PRIORITY_QUERY = "PRIORITY_QUERY"
    FINANCE_STATUS = "FINANCE_STATUS"
    DECISION_REQUEST = "DECISION_REQUEST"
    REFLECTION = "REFLECTION"
    AUDIT = "AUDIT"
    SEARCH = "SEARCH"
    COMPARE = "COMPARE"
    FORECAST = "FORECAST"
    PAIN_ANALYSIS = "PAIN_ANALYSIS"
    IDEA_SCAN = "IDEA_SCAN"
    BACKUP = "BACKUP"
    STATUS = "STATUS"
    HELP = "HELP"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Intent pattern rules (keyword-based classification)
# ---------------------------------------------------------------------------

INTENT_PATTERNS: List[Dict[str, Any]] = [
    {
        "intent": IntentType.PRIORITY_QUERY,
        "patterns": [
            r"\bfocus\b.*\b(today|week|month|next)\b",
            r"\bpriori", r"\bwhat should i\b", r"\bmost important\b",
            r"\btop\s+\d+\b.*\b(task|thing|item|action)\b",
            r"\bwhat.*(next|now)\b",
        ],
        "domain": "strategy",
        "routed_to": "priorities",
    },
    {
        "intent": IntentType.FINANCE_STATUS,
        "patterns": [
            r"\bfinanc", r"\brevenue\b", r"\bburn\srate\b",
            r"\bcash\b", r"\bbudget\b", r"\bexpens",
            r"\brun\s*way\b", r"\bprofit\b", r"\bmoney\b",
            r"\bhow.*doing.*financ",
        ],
        "domain": "finance",
        "routed_to": "finance_insights",
    },
    {
        "intent": IntentType.DECISION_REQUEST,
        "patterns": [
            r"\bshould\s+i\b", r"\bdecid", r"\bdecision\b",
            r"\btake this\b.*\b(project|offer|deal|job)\b",
            r"\bpros?\s+and\s+cons?\b", r"\bshould\s+we\b",
            r"\bworth\s+(it|doing|pursuing)\b",
        ],
        "domain": "decision",
        "routed_to": "decision_engine",
    },
    {
        "intent": IntentType.REFLECTION,
        "patterns": [
            r"\breflect\b", r"\breview\b.*\b(last|past|previous)\b",
            r"\bwhat\s+(worked|failed|compounded)\b",
            r"\blessons?\s+learned\b", r"\blook\s*back\b",
        ],
        "domain": "reflection",
        "routed_to": "reflection_engine",
    },
    {
        "intent": IntentType.AUDIT,
        "patterns": [
            r"\baudit\b", r"\bwhat.*did.*aeos\b",
            r"\bshow.*log\b", r"\bhistory\b.*\b(action|decision)\b",
            r"\btransparency\b",
        ],
        "domain": "audit",
        "routed_to": "audit_trail",
    },
    {
        "intent": IntentType.SEARCH,
        "patterns": [
            r"\bsearch\b", r"\bfind\b", r"\blook\s*up\b",
            r"\bwhat\s+is\b", r"\bwhat\s+are\b",
            r"\btell\s+me\s+about\b", r"\bexplain\b",
        ],
        "domain": "search",
        "routed_to": "kb_search",
    },
    {
        "intent": IntentType.COMPARE,
        "patterns": [
            r"\bcompare\b", r"\bvs\.?\b", r"\bversus\b",
            r"\bdifference\s+between\b", r"\bbetter\b.*\bor\b",
        ],
        "domain": "analysis",
        "routed_to": "compare_engine",
    },
    {
        "intent": IntentType.FORECAST,
        "patterns": [
            r"\bforecast\b", r"\bpredict\b", r"\bprojection\b",
            r"\bscenario\b", r"\bwhat\s+if\b", r"\btrend\b",
            r"\bfuture\b",
        ],
        "domain": "forecast",
        "routed_to": "prediction_tracker",
    },
    {
        "intent": IntentType.PAIN_ANALYSIS,
        "patterns": [
            r"\bpain\b", r"\bproblem\b", r"\bfrustrat",
            r"\bstruggl", r"\bchallenge\b", r"\bhurdle\b",
        ],
        "domain": "pain",
        "routed_to": "pain_scanner",
    },
    {
        "intent": IntentType.IDEA_SCAN,
        "patterns": [
            r"\bidea\b", r"\bopportunit", r"\bscan\b",
            r"\bextract\b", r"\bpotential\b",
        ],
        "domain": "ideas",
        "routed_to": "idea_extractor",
    },
    {
        "intent": IntentType.BACKUP,
        "patterns": [
            r"\bbackup\b", r"\brestore\b", r"\bexport\b",
            r"\bsnapshot\b",
        ],
        "domain": "system",
        "routed_to": "identity_continuity",
    },
    {
        "intent": IntentType.STATUS,
        "patterns": [
            r"\bstatus\b", r"\bdashboard\b", r"\bhealth\b",
            r"\bhow.*system\b", r"\bsystem\s+check\b",
        ],
        "domain": "system",
        "routed_to": "sovereign_dashboard",
    },
    {
        "intent": IntentType.HELP,
        "patterns": [
            r"\bhelp\b", r"\bhow\s+do\s+i\b", r"\bwhat\s+can\b",
            r"\bcommand", r"\bguide\b",
        ],
        "domain": "help",
        "routed_to": "help",
    },
]

# Example queries for each domain
EXAMPLE_QUERIES: Dict[str, List[str]] = {
    "strategy": [
        "What should I focus on this week?",
        "What are my top 3 priorities?",
        "What's most important right now?",
    ],
    "finance": [
        "How am I doing financially?",
        "What's my cash runway?",
        "Show me revenue breakdown",
    ],
    "decision": [
        "Should I take this client project?",
        "Should we pivot to SaaS?",
        "Is it worth pursuing this opportunity?",
    ],
    "reflection": [
        "Reflect on last month",
        "What worked well this quarter?",
        "What failed and what did I learn?",
    ],
    "audit": [
        "What did aeOS do last week?",
        "Show me the audit log for March",
        "Give me a transparency report",
    ],
    "search": [
        "What is the Hormozi Value Equation?",
        "Tell me about network effects",
        "Explain first principles thinking",
    ],
    "pain": [
        "What are the biggest pain points?",
        "Analyze this customer problem",
        "Show me high-pain opportunities",
    ],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ParsedIntent:
    """Structured intent parsed from natural language query."""
    intent_type: str
    domain: str
    parameters: Dict[str, Any]
    routed_to: str
    confidence: float  # 0.0 to 1.0
    original_query: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IntentFeedback:
    """Feedback for when the parser's intent was wrong."""
    original_query: str
    parsed_intent: str
    correct_intent: str
    correct_domain: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# NLQParser
# ---------------------------------------------------------------------------

class NLQParser:
    """
    Natural language query parser for aeOS.

    Accepts plain English queries and routes them to the correct
    AeOSCore handler. Uses keyword pattern matching (Tier 0/1 speed)
    without requiring cloud API calls.

    Usage:
        parser = NLQParser()
        intent = parser.parse("What should I focus on this week?")
        print(intent.intent_type)   # PRIORITY_QUERY
        print(intent.routed_to)     # priorities
        print(intent.confidence)    # 0.85
    """

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
    ) -> None:
        if db_path is not None:
            self._db_path = Path(db_path).expanduser().resolve()
        else:
            self._db_path = (
                Path(__file__).resolve().parent.parent.parent / "db" / "aeOS.db"
            )

        # Compiled patterns for performance
        self._compiled_patterns: List[Dict[str, Any]] = []
        for rule in INTENT_PATTERNS:
            compiled = []
            for pattern in rule["patterns"]:
                try:
                    compiled.append(re.compile(pattern, re.IGNORECASE))
                except re.error:
                    logger.warning("Invalid regex pattern: %s", pattern)
            self._compiled_patterns.append({
                "intent": rule["intent"],
                "patterns": compiled,
                "domain": rule["domain"],
                "routed_to": rule["routed_to"],
            })

        # Learned corrections (from train())
        self._corrections: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API: parse
    # ------------------------------------------------------------------

    def parse(self, query: str) -> ParsedIntent:
        """
        Parse a natural language query into a structured intent.

        Args:
            query: Raw natural language query string.

        Returns:
            ParsedIntent with intent type, domain, and routing info.
        """
        if not query or not query.strip():
            return ParsedIntent(
                intent_type=IntentType.UNKNOWN,
                domain="unknown",
                parameters={},
                routed_to="help",
                confidence=0.0,
                original_query=query or "",
            )

        query_clean = query.strip()

        # Check learned corrections first
        if query_clean.lower() in self._corrections:
            corrected_intent = self._corrections[query_clean.lower()]
            for rule in self._compiled_patterns:
                if rule["intent"] == corrected_intent:
                    result = ParsedIntent(
                        intent_type=rule["intent"],
                        domain=rule["domain"],
                        parameters=self._extract_parameters(query_clean),
                        routed_to=rule["routed_to"],
                        confidence=0.95,
                        original_query=query_clean,
                    )
                    self._log_parse(result)
                    return result

        # Pattern matching
        best_match = None
        best_score = 0.0

        for rule in self._compiled_patterns:
            matches = 0
            total = len(rule["patterns"])
            if total == 0:
                continue

            for pattern in rule["patterns"]:
                if pattern.search(query_clean):
                    matches += 1

            if matches > 0:
                # Score: combination of match ratio and total matches
                score = (matches / total) * 0.6 + min(matches / 3, 1.0) * 0.4
                if score > best_score:
                    best_score = score
                    best_match = rule

        if best_match is not None and best_score > 0:
            confidence = min(best_score, 0.95)
            result = ParsedIntent(
                intent_type=best_match["intent"],
                domain=best_match["domain"],
                parameters=self._extract_parameters(query_clean),
                routed_to=best_match["routed_to"],
                confidence=round(confidence, 4),
                original_query=query_clean,
            )
            self._log_parse(result)
            return result

        # No match — fallback to SEARCH
        result = ParsedIntent(
            intent_type=IntentType.SEARCH,
            domain="unknown",
            parameters=self._extract_parameters(query_clean),
            routed_to="kb_search",
            confidence=0.2,
            original_query=query_clean,
        )
        self._log_parse(result)
        return result

    # ------------------------------------------------------------------
    # Public API: getSuggestions
    # ------------------------------------------------------------------

    def get_suggestions(self, partial: str) -> List[str]:
        """
        Get autocomplete suggestions for a partial query.

        Args:
            partial: Partial query string.

        Returns:
            List of suggested complete queries.
        """
        if not partial or len(partial) < 2:
            return []

        partial_lower = partial.lower().strip()
        suggestions = []

        for domain, examples in EXAMPLE_QUERIES.items():
            for example in examples:
                if partial_lower in example.lower():
                    suggestions.append(example)

        return suggestions[:10]

    # ------------------------------------------------------------------
    # Public API: getExamples
    # ------------------------------------------------------------------

    def get_examples(self, domain: Optional[str] = None) -> List[str]:
        """
        Get example queries, optionally filtered by domain.

        Args:
            domain: Optional domain filter. None = all examples.

        Returns:
            List of example query strings.
        """
        if domain and domain in EXAMPLE_QUERIES:
            return list(EXAMPLE_QUERIES[domain])

        all_examples = []
        for examples in EXAMPLE_QUERIES.values():
            all_examples.extend(examples)
        return all_examples

    # ------------------------------------------------------------------
    # Public API: train
    # ------------------------------------------------------------------

    def train(self, feedback: IntentFeedback) -> None:
        """
        Learn from a correction when the parser got the intent wrong.

        Args:
            feedback: IntentFeedback with original and correct intent.
        """
        self._corrections[feedback.original_query.lower()] = feedback.correct_intent

        # Log for future pattern learning
        self._log_correction(feedback)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_parameters(self, query: str) -> Dict[str, Any]:
        """Extract structured parameters from query text."""
        params: Dict[str, Any] = {}

        # Time references
        time_patterns = {
            "today": r"\btoday\b",
            "this_week": r"\bthis\s+week\b",
            "this_month": r"\bthis\s+month\b",
            "last_week": r"\blast\s+week\b",
            "last_month": r"\blast\s+month\b",
            "this_quarter": r"\bthis\s+quarter\b",
        }
        for key, pattern in time_patterns.items():
            if re.search(pattern, query, re.IGNORECASE):
                params["time_reference"] = key
                break

        # Numeric parameters (e.g., "top 5", "last 30 days")
        num_match = re.search(r"\b(top|last|next)\s+(\d+)\b", query, re.IGNORECASE)
        if num_match:
            params["count"] = int(num_match.group(2))
            params["count_type"] = num_match.group(1).lower()

        # Domain mentions
        domains = [
            "finance", "business", "health", "career", "creative",
            "learning", "relationships", "personal",
        ]
        for d in domains:
            if d in query.lower():
                params["mentioned_domain"] = d
                break

        return params

    def _log_parse(self, result: ParsedIntent) -> None:
        """Log parse result to database for learning."""
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "NLQ_Parse_Log" not in tables:
                conn.close()
                return

            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT INTO NLQ_Parse_Log
                (original_query, parsed_intent, confidence, routed_to, timestamp)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    result.original_query[:500],
                    json.dumps(result.to_dict()),
                    result.confidence,
                    result.routed_to,
                    now_iso,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("Failed to log parse: %s", e)

    def _log_correction(self, feedback: IntentFeedback) -> None:
        """Log a correction for future pattern learning."""
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "NLQ_Parse_Log" not in tables:
                conn.close()
                return

            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """INSERT INTO NLQ_Parse_Log
                (original_query, parsed_intent, confidence, routed_to,
                 was_corrected, correction, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    feedback.original_query[:500],
                    json.dumps({"intent_type": feedback.parsed_intent}),
                    0.0,
                    "",
                    1,
                    json.dumps(feedback.to_dict()),
                    now_iso,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("Failed to log correction: %s", e)


__all__ = [
    "NLQParser",
    "ParsedIntent",
    "IntentFeedback",
    "IntentType",
    "EXAMPLE_QUERIES",
]
