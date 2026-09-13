"""Data models for Text Reword Subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class RewordStyle(str, Enum):
    ACADEMIC_FORMAL = "ACADEMIC_FORMAL"
    CONCISE_FLOW = "CONCISE_FLOW"
    SIMPLIFIED_CLARITY = "SIMPLIFIED_CLARITY"
    EXPANDED_ARGUMENT = "EXPANDED_ARGUMENT"


@dataclass
class SurroundingContext:
    """Immediate adjacent sentences and domain context."""
    preceding_sentence: str = ""
    following_sentence: str = ""
    document_domain: str = "ACADEMIC_STEM"


@dataclass
class EntityMaskReport:
    """Text with citations and math formulas shielded by atomic placeholders."""
    masked_text: str
    mask_map: Dict[str, str] = field(default_factory=dict)


@dataclass
class RewordResult:
    """Outcome containing primary rewritten text and secondary alternatives."""
    primary_replacement: str
    alternative_variants: List[str] = field(default_factory=list)
    tokens_used: int = 0
    style_applied: str = "ACADEMIC_FORMAL"
    cached: bool = False
    error: Optional[str] = None
