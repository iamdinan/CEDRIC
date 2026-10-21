"""Command router, text normalizer, and rapidfuzz matching engine.
Includes Phase 2 hooks (Router interface, RouterContext, prompt serialization readiness).
"""

import re
import logging
from abc import ABC, abstractmethod
from typing import Optional, List, Tuple, Dict, Any
from rapidfuzz import fuzz, process

from cedric.core.registry import CommandRegistry, CommandEntry

logger = logging.getLogger("cedric.router")


FILLER_WORDS = [
    r"\bplease\b",
    r"\bcan you\b",
    r"\bcould you\b",
    r"\bwould you\b",
    r"\bthe\b",
    r"\ba\b",
    r"\ban\b",
    r"\bfor me\b",
    r"\bhey cedric\b",
    r"\bcedric\b",
]

SYNONYM_REPLACEMENTS = [
    (r"\blaunch\b", "open"),
    (r"\bstart\b", "open"),
    (r"\bopen up\b", "open"),
    (r"\bpull up\b", "open"),
    (r"\bbring up\b", "open"),
    (r"\brun\b", "open"),
]


def normalize_utterance(text: str) -> str:
    """Normalizes raw speech text:
    - Lowercase
    - Expand synonyms (launch, start, open up, pull up -> open)
    - Strip filler words (please, can you, the, etc.)
    - Remove punctuation and collapse whitespace
    """
    if not text:
        return ""

    t = text.lower().strip()

    # Expand multi-word synonyms before word removal
    for pattern, repl in SYNONYM_REPLACEMENTS:
        t = re.sub(pattern, repl, t)

    # Strip filler words
    for pattern in FILLER_WORDS:
        t = re.sub(pattern, " ", t)

    # Remove non-alphanumeric except spaces
    t = re.sub(r"[^\w\s]", " ", t)

    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()
    return t


class RouterContext:
    """Context object holding state for router decisions and multi-turn follow-ups.
    Prepared as a Phase 2 hook for LLM routing.
    """
    def __init__(self):
        self.last_action: Optional[str] = None
        self.last_utterance: Optional[str] = None
        self.last_reply: Optional[str] = None
        self.current_explorer_path: Optional[str] = None
        self.pending_confirmation_command: Optional[CommandEntry] = None

    def update(self, action: Optional[str] = None, utterance: Optional[str] = None, reply: Optional[str] = None):
        if action:
            self.last_action = action
        if utterance:
            self.last_utterance = utterance
        if reply:
            self.last_reply = reply


class RoutingResult:
    """Result returned by Router implementations."""
    def __init__(
        self,
        status: str,  # "matched", "clarification", "meta", "no_match"
        command: Optional[CommandEntry] = None,
        meta_action: Optional[str] = None,
        confidence: float = 0.0,
        clarification_prompt: Optional[str] = None,
        matched_phrase: Optional[str] = None,
    ):
        self.status = status
        self.command = command
        self.meta_action = meta_action
        self.confidence = confidence
        self.clarification_prompt = clarification_prompt
        self.matched_phrase = matched_phrase

    def __repr__(self):
        return f"<RoutingResult status={self.status} cmd={self.command.id if self.command else None} score={self.confidence:.1f}>"


class Router(ABC):
    """Abstract router interface designed for Phase 1 rules and Phase 2 LLM router."""

    @abstractmethod
    def route(self, text: str, context: Optional[RouterContext] = None) -> RoutingResult:
        pass


class RuleRouter(Router):
    """Phase 1 Rule-based fuzzy matcher using RapidFuzz."""

    META_COMMANDS = {
        "cancel": ["cancel", "never mind", "nevermind", "abort", "dismiss"],
        "repeat_that": ["repeat that", "what did you say", "repeat", "say that again"],
        "stop_listening": ["stop listening", "go to sleep", "sleep", "pause listening", "mute"],
        "what_can_you_do": ["what can you do", "help", "list commands", "show commands", "what are your commands"],
    }

    def __init__(
        self,
        registry: CommandRegistry,
        high_confidence: float = 85.0,
        low_confidence: float = 65.0,
    ):
        self.registry = registry
        self.high_confidence = high_confidence
        self.low_confidence = low_confidence
        self._target_map: Dict[str, CommandEntry] = {}
        self._all_targets: List[str] = []
        self._build_target_index()

    def _build_target_index(self):
        """Indexes all command aliases and forms for rapidfuzz matching."""
        self._target_map.clear()
        for cmd in self.registry.all_commands():
            candidates = set()
            candidates.add(cmd.name.lower())
            candidates.add(f"open {cmd.name.lower()}")
            for a in cmd.aliases:
                a_lower = a.lower()
                candidates.add(a_lower)
                candidates.add(f"open {a_lower}")

            for c in candidates:
                norm_c = normalize_utterance(c)
                if norm_c:
                    self._target_map[norm_c] = cmd

        self._all_targets = list(self._target_map.keys())

    def reload(self):
        self._build_target_index()

    def _check_meta_commands(self, normalized_text: str) -> Optional[Tuple[str, float]]:
        """Checks for meta commands: cancel, repeat that, stop listening, what can you do."""
        best_meta = None
        best_score = 0.0

        for meta_id, phrases in self.META_COMMANDS.items():
            for p in phrases:
                norm_p = normalize_utterance(p)
                score = fuzz.ratio(normalized_text, norm_p)
                if score >= 85 and score > best_score:
                    best_score = score
                    best_meta = meta_id

        if best_meta:
            return best_meta, best_score
        return None

    def route(self, text: str, context: Optional[RouterContext] = None) -> RoutingResult:
        normalized = normalize_utterance(text)
        if not normalized:
            return RoutingResult("no_match", confidence=0.0)

        # 1. Check meta commands
        meta_match = self._check_meta_commands(normalized)
        if meta_match:
            meta_id, score = meta_match
            logger.info(f"Meta command matched: '{meta_id}' with score {score:.1f}")
            return RoutingResult("meta", meta_action=meta_id, confidence=score, matched_phrase=text)

        # 2. Check direct / prefix matching
        text_variants = [normalized]
        if normalized.startswith("open "):
            stripped = normalized[5:].strip()
            if stripped:
                text_variants.append(stripped)

        best_cmd: Optional[CommandEntry] = None
        best_score: float = 0.0
        best_phrase: Optional[str] = None

        for variant in text_variants:
            match = process.extractOne(
                variant,
                self._all_targets,
                scorer=fuzz.ratio,
            )
            if match:
                candidate_target, score, _ = match
                if score > best_score:
                    best_score = score
                    best_cmd = self._target_map[candidate_target]
                    best_phrase = candidate_target

        logger.info(f"Fuzzy match evaluation: text='{text}' -> norm='{normalized}', best='{best_cmd.name if best_cmd else None}', score={best_score:.1f}")

        if best_score >= self.high_confidence and best_cmd:
            return RoutingResult(
                status="matched",
                command=best_cmd,
                confidence=best_score,
                matched_phrase=best_phrase,
            )
        elif best_score >= self.low_confidence and best_cmd:
            return RoutingResult(
                status="clarification",
                command=best_cmd,
                confidence=best_score,
                clarification_prompt=f"Did you mean {best_cmd.name}?",
                matched_phrase=best_phrase,
            )
        else:
            return RoutingResult(
                status="no_match",
                confidence=best_score,
            )
