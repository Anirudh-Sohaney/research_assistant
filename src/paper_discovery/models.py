"""Data models for Paper Discovery Subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class TraversalDirection(str, Enum):
    CITES_INWARD = "CITES_INWARD"
    CITED_BY_OUTWARD = "CITED_BY_OUTWARD"
    CO_CITATION = "CO_CITATION"


@dataclass
class SearchScope:
    """Filter criteria for academic literature search."""
    disciplines: List[str] = field(default_factory=list)
    min_year: Optional[int] = None
    open_access_only: bool = False


@dataclass
class AcademicPaperRecommendation:
    """Curated academic paper candidate with citation metadata."""
    paper_id: str
    doi: str
    title: str
    authors: str
    year: int
    venue: str = ""
    citation_count: int = 0
    abstract_snippet: str = ""
    llm_relevance_assessment: str = ""
    suggested_citation_key: str = ""
    pdf_url: Optional[str] = None


@dataclass
class PaperDiscoveryResult:
    """Final result emitted by discovery pipeline."""
    query_summary: str
    papers: List[AcademicPaperRecommendation] = field(default_factory=list)


@dataclass
class LiteratureSynthesis:
    """Synthesized related work paragraph with in-text citation keys."""
    synthesis_paragraph: str
    cited_keys: List[str] = field(default_factory=list)


@dataclass
class CitationGraphResult:
    """Citation graph neighborhood of a seed paper."""
    seed_paper_id: str
    connected_papers: List[AcademicPaperRecommendation] = field(default_factory=list)
