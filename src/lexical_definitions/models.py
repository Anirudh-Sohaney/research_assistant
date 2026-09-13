"""Data models for Lexical Definitions Subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class WordSense:
    """A distinct semantic dictionary sense."""
    definition: str
    part_of_speech: str
    examples: List[str] = field(default_factory=list)
    synonyms: List[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class WordDefinitionResult:
    """Aggregated, context-disambiguated dictionary entry."""
    word: str
    phonetic_ipa: str = ""
    audio_url: Optional[str] = None
    primary_sense: Optional[WordSense] = None
    secondary_senses: List[WordSense] = field(default_factory=list)
    disambiguation_confidence: float = 0.0
    etymology: str = ""
