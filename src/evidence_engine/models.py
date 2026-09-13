"""Evidence Engine data models.

Minimal, frozen dataclasses for paper references and retrieval results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class PaperRef:
    """Normalized identity of a paper, independent of source adapter."""

    title: str
    authors: str
    year: Optional[int]
    doi: Optional[str]
    url: Optional[str]
    venue: Optional[str] = None
    citation_count: Optional[int] = None
    abstract: str = ""
    open_access: bool = False
    source: str = ""


@dataclass
class RetrievalResult:
    """Aggregate retrieval output: deduplicated papers + per-source report."""

    papers: list  # list[PaperRef]
    sources: dict = field(default_factory=dict)  # name -> {"papers": int, "status": str}
    wall_ms: float = 0.0
    raw: list = field(default_factory=list)  # parallel list of source-specific dicts

    def summary(self) -> str:
        src = ", ".join(f"{k}={v['papers']}" for k, v in self.sources.items())
        return f"{len(self.papers)} unique papers in {self.wall_ms:.0f} ms [{src}]"


@dataclass(frozen=True)
class EvidenceItem:
    """A single piece of evidence: a sentence judged by the LLM."""

    quote: str
    paper: PaperRef
    confidence: float
    section: str = ""


@dataclass
class EvidenceResult:
    """Final pipeline output: top evidence items for a claim."""

    claim: str
    items: list  # list[EvidenceItem]
    total_papers: int = 0
    total_sentences: int = 0
    wall_ms: float = 0.0

    def summary(self) -> str:
        return (f"{len(self.items)} evidence items from {self.total_papers} papers "
                f"({self.total_sentences} sentences) in {self.wall_ms:.0f} ms")
