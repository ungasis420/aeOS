"""
dispatcher.py — Orchestration entry point for aeOS COGNITIVE_CORE.

Receives raw user input, classifies intent via keyword matching + domain
affinity scoring, and builds an OrchestratorRequest routed downstream.

Stamp: S✅ T✅ L✅ A✅
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from src.orchestration.models import IntentClassification, OrchestratorRequest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 45 cartridge domains with keyword affinities
# ---------------------------------------------------------------------------

_DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    # Philosophy (10)
    "philosophy.stoicism": [
        "stoic", "control", "fate", "endure", "virtue", "marcus aurelius",
        "seneca", "epictetus", "discipline", "resilience",
    ],
    "philosophy.existentialism": [
        "existential", "meaning", "absurd", "authenticity", "sartre",
        "camus", "kierkegaard", "dread", "existence", "nihilism",
    ],
    "philosophy.buddhism": [
        "buddhist", "buddha", "mindful", "attachment", "suffering",
        "impermanence", "meditation", "dharma", "zen", "compassion",
    ],
    "philosophy.taoism": [
        "tao", "taoist", "wu wei", "balance", "harmony", "yin yang",
        "lao tzu", "flow", "nature", "effortless",
    ],
    "philosophy.epicureanism": [
        "epicurean", "pleasure", "moderation", "tranquility", "desire",
        "epicurus", "simple living", "friendship", "ataraxia", "hedonism",
    ],
    "philosophy.pragmatism": [
        "pragmatic", "practical", "utility", "james", "dewey", "peirce",
        "consequence", "action oriented", "empirical", "workable",
    ],
    "philosophy.virtue_ethics": [
        "virtue ethics", "character", "moral virtue", "eudaimonia",
        "aristotle", "flourishing", "temperance", "courage", "justice",
        "practical wisdom",
    ],
    "philosophy.utilitarianism": [
        "utilitarian", "greatest good", "consequentialism", "bentham",
        "mill", "welfare", "cost benefit", "maximize", "aggregate",
        "social good",
    ],
    "philosophy.deontology": [
        "duty", "moral law", "categorical imperative", "kant", "obligation",
        "deontological", "rights", "universal law", "principle", "rule based",
    ],
    "philosophy.phenomenology": [
        "phenomenology", "consciousness", "husserl", "heidegger", "dasein",
        "intentionality", "lived experience", "perception", "being",
        "subjective",
    ],
    # Psychology (10)
    "psychology.cbt": [
        "cognitive distortion", "thought pattern", "reframe", "cbt",
        "automatic thought", "cognitive behavioral", "belief", "schema",
        "irrational", "thought record",
    ],
    "psychology.emotional_regulation": [
        "emotional", "regulate", "mood", "anger", "sadness", "anxiety",
        "coping", "overwhelmed", "feeling", "reactive",
    ],
    "psychology.attachment_theory": [
        "attachment", "secure", "avoidant", "anxious attachment", "bonding",
        "abandonment", "trust issues", "intimacy", "caregiver", "codependent",
    ],
    "psychology.positive_psychology": [
        "gratitude", "strength", "flourish", "optimism", "wellbeing",
        "positive", "seligman", "flow state", "engagement", "savoring",
    ],
    "psychology.behavioral": [
        "habit", "reward", "punishment", "conditioning", "stimulus",
        "behavioral", "reinforcement", "skinner", "routine", "trigger",
    ],
    "psychology.depth": [
        "unconscious", "shadow", "archetype", "jung", "freud", "dream",
        "psyche", "projection", "complex", "repression",
    ],
    "psychology.trauma_recovery": [
        "trauma", "ptsd", "flashback", "trigger", "survivor", "healing",
        "recovery", "abuse", "hypervigilance", "dissociation",
    ],
    "psychology.motivation": [
        "motivation", "drive", "procrastinate", "lazy", "willpower",
        "momentum", "inspired", "unmotivated", "apathy", "ambition",
    ],
    "psychology.habit_formation": [
        "habit", "routine", "streak", "consistency", "atomic", "cue",
        "craving", "response", "reward loop", "identity",
    ],
    "psychology.social": [
        "social", "peer pressure", "conformity", "group", "influence",
        "reputation", "belonging", "tribe", "social proof", "status",
    ],
    # Productivity (6)
    "productivity.deep_work": [
        "deep work", "focus", "distraction", "concentration", "flow",
        "shallow work", "attention", "newport", "uninterrupted", "cognitively",
    ],
    "productivity.essentialism": [
        "essential", "priority", "less but better", "eliminate", "trade off",
        "simplify", "focused", "mckeown", "vital few", "trivial many",
    ],
    "productivity.time_management": [
        "schedule", "deadline", "calendar", "time block", "pomodoro",
        "time management", "procrastinate", "late", "organize", "plan",
    ],
    "productivity.goal_setting": [
        "goal", "objective", "target", "milestone", "plan", "vision",
        "purpose", "okr", "kpi", "aspiration",
    ],
    "productivity.decision_making": [
        "decision", "choose", "dilemma", "option", "trade off", "paralysis",
        "analysis", "risk", "uncertain", "commit",
    ],
    "productivity.systems_thinking": [
        "system", "feedback loop", "leverage", "interconnect", "emergent",
        "holistic", "root cause", "second order", "complexity", "dynamic",
    ],
    # Health (6)
    "health.physical_wellness": [
        "exercise", "fitness", "body", "physical", "workout", "strength",
        "endurance", "cardio", "energy", "vitality",
    ],
    "health.mental_health": [
        "mental health", "depression", "anxiety", "therapy", "burnout",
        "stress", "panic", "lonely", "self care", "wellbeing",
    ],
    "health.sleep": [
        "sleep", "insomnia", "rest", "tired", "fatigue", "circadian",
        "nap", "exhausted", "wake", "dream",
    ],
    "health.nutrition": [
        "diet", "nutrition", "eating", "food", "meal", "fasting",
        "supplement", "calories", "healthy eating", "gut",
    ],
    "health.stress_management": [
        "stress", "relax", "calm", "overwhelmed", "burnout", "pressure",
        "tension", "breathe", "unwind", "cortisol",
    ],
    "health.mindfulness": [
        "mindfulness", "meditation", "present", "breathe", "awareness",
        "observe", "grounded", "centered", "stillness", "contemplation",
    ],
    # Finance (5)
    "finance.personal_finance": [
        "money", "budget", "savings", "debt", "expenses", "income",
        "financial", "spending", "afford", "frugal",
    ],
    "finance.investing": [
        "invest", "portfolio", "stock", "dividend", "compound", "market",
        "return", "asset", "diversify", "etf",
    ],
    "finance.risk_management": [
        "risk", "hedge", "insurance", "downside", "volatility", "exposure",
        "safety net", "contingency", "protect", "loss",
    ],
    "finance.wealth_building": [
        "wealth", "rich", "net worth", "passive income", "financial freedom",
        "abundance", "generational", "millionaire", "accumulate", "prosper",
    ],
    "finance.financial_planning": [
        "retirement", "estate", "tax", "plan", "fiduciary", "forecast",
        "long term", "annuity", "pension", "inheritance",
    ],
    # Relationships (5)
    "relationships.communication": [
        "communicate", "conversation", "listen", "express", "talk",
        "dialogue", "misunderstand", "articulate", "honest", "open up",
    ],
    "relationships.conflict_resolution": [
        "conflict", "argument", "disagree", "fight", "tension", "resolve",
        "mediate", "compromise", "reconcile", "dispute",
    ],
    "relationships.boundaries": [
        "boundary", "say no", "limit", "codependent", "people pleaser",
        "assert", "space", "respect", "overstep", "firm",
    ],
    "relationships.empathy": [
        "empathy", "compassion", "understand", "perspective taking",
        "emotional intelligence", "sympathy", "validate", "feel for",
        "care", "kind",
    ],
    "relationships.leadership": [
        "leadership", "lead", "inspire", "team", "vision", "mentor",
        "delegate", "influence", "authority", "servant leader",
    ],
    # Career (3)
    "career.career_development": [
        "career", "promotion", "job", "skill", "resume", "interview",
        "professional", "growth", "advancement", "opportunity",
    ],
    "career.negotiation": [
        "negotiate", "salary", "offer", "bargain", "leverage", "deal",
        "counter offer", "compensation", "terms", "concession",
    ],
    "career.entrepreneurship": [
        "startup", "entrepreneur", "business", "founder", "venture",
        "bootstrap", "hustle", "product", "customer", "scale",
    ],
}

# ---------------------------------------------------------------------------
# Sovereign-need keyword map (9 needs)
# ---------------------------------------------------------------------------

SOVEREIGN_NEEDS = (
    "autonomy", "security", "purpose", "resilience", "clarity",
    "belonging", "integrity", "growth", "expression",
)

_NEED_KEYWORDS: Dict[str, List[str]] = {
    "autonomy": [
        "control", "freedom", "independence", "choice", "self determined",
        "agency", "sovereign", "my own",
    ],
    "security": [
        "safe", "secure", "protect", "stable", "certainty", "reliable",
        "risk", "threat", "danger", "worry",
    ],
    "purpose": [
        "meaning", "purpose", "mission", "calling", "destiny", "legacy",
        "why", "matter", "contribution", "significant",
    ],
    "resilience": [
        "endure", "recover", "bounce back", "tough", "persevere",
        "withstand", "overcome", "grit", "strong", "survive",
    ],
    "clarity": [
        "clarity", "clear", "understand", "insight", "confused", "foggy",
        "uncertain", "direction", "focus", "perspective",
    ],
    "belonging": [
        "belong", "connect", "community", "lonely", "isolated", "tribe",
        "accepted", "included", "together", "relationship",
    ],
    "integrity": [
        "integrity", "honest", "truth", "authentic", "values", "ethics",
        "principled", "moral", "right thing", "conscience",
    ],
    "growth": [
        "grow", "improve", "learn", "develop", "evolve", "progress",
        "potential", "better", "mastery", "skill",
    ],
    "expression": [
        "express", "create", "voice", "art", "share", "communicate",
        "identity", "unique", "authentic", "represent",
    ],
}


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _score_text(text: str, keywords: List[str]) -> int:
    """Count how many *keywords* appear as substrings in *text* (case-insensitive)."""
    lower = text.lower()
    return sum(1 for kw in keywords if kw in lower)


def _classify_complexity(text: str, n_domains: int) -> str:
    """Heuristic complexity bucket based on input length and domain spread."""
    words = len(text.split())
    if words <= 12 and n_domains <= 2:
        return "low"
    if words >= 40 or n_domains >= 5:
        return "high"
    return "medium"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class Dispatcher:
    """Classifies user intent and builds an OrchestratorRequest."""

    def classify_intent(self, text: str) -> IntentClassification:
        """Classify raw text into domains, complexity, and sovereign need hint.

        Uses keyword matching + domain affinity scoring.  All 45 cartridge
        domains are reachable through the keyword map.
        """
        # Score every domain.
        scores: List[tuple[str, int]] = []
        for domain, keywords in _DOMAIN_KEYWORDS.items():
            score = _score_text(text, keywords)
            if score > 0:
                scores.append((domain, score))

        # Sort by score descending, take top 5.
        scores.sort(key=lambda t: t[1], reverse=True)
        domains = [d for d, _ in scores[:5]] if scores else ["philosophy.stoicism"]

        # Sovereign need hint — pick highest-scoring need.
        need_scores = [
            (need, _score_text(text, kws))
            for need, kws in _NEED_KEYWORDS.items()
        ]
        need_scores.sort(key=lambda t: t[1], reverse=True)
        need_hint: Optional[str] = need_scores[0][0] if need_scores[0][1] > 0 else None

        complexity = _classify_complexity(text, len(domains))

        intent = IntentClassification(
            domains=domains,
            complexity=complexity,
            sovereign_need_hint=need_hint,
        )
        logger.info("Classified intent: domains=%s complexity=%s need=%s",
                     domains, complexity, need_hint)
        return intent

    def dispatch(self, text: str) -> OrchestratorRequest:
        """Build a full OrchestratorRequest from raw user text."""
        intent = self.classify_intent(text)
        return OrchestratorRequest(
            raw_text=text,
            intent=intent,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
