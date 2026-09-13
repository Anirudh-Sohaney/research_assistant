"""Data models for Lexical Synonyms Subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class RawCandidate:
    """A raw candidate word harvested from lexical sources."""
    word: str
    source: str = "DATAMUSE"
    pos: Optional[str] = None
    frequency: float = 0.0


@dataclass
class SynonymItem:
    """A ranked academic synonym item with contextual fitness scores."""
    word: str
    composite_score: float
    semantic_similarity: float = 0.0
    academic_register: float = 0.0
    part_of_speech: str = "general"


@dataclass
class SynonymGroupResult:
    """Final result containing contextually ranked synonyms."""
    query_word: str
    sentence: str
    ranked_synonyms: List[SynonymItem] = field(default_factory=list)
    antonyms: List[str] = field(default_factory=list)
    inference_latency_ms: float = 0.0
