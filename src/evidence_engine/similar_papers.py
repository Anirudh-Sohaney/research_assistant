"""Simple paper similarity finder.

Given a user's thesis/prompt, finds 20-50 similar research papers using
parallel federated retrieval across multiple academic sources.

Design:
  - Reuses the evidence_engine/sources.py parallel fan-out infrastructure
  - Adds simple BM25-like scoring for relevance ranking
  - Hard 4-second deadline with graceful degradation
  - Returns deduplicated papers ranked by relevance + citation impact
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

from evidence_engine.models import PaperRef, RetrievalResult
from evidence_engine.sources import extract_papers


@dataclass(frozen=True)
class SimilarPaper:
    """A paper identified as similar to the user's thesis."""
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
    relevance_score: float = 0.0


@dataclass
class SimilarityResult:
    """Result of the similarity search."""
    query: str
    papers: List[SimilarPaper] = field(default_factory=list)
    total_candidates: int = 0
    wall_ms: float = 0.0
    sources_used: List[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"{len(self.papers)} similar papers from {self.total_candidates} "
                f"candidates in {self.wall_ms:.0f} ms")


# ------------------------------------------------------- scoring

_STOP_WORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or "
    "that the this to with which into their than thus we our using used "
    "may might suggests could would about".split()
)


def _tokenize(text: str) -> List[str]:
    """Extract lowercase alphanumeric tokens, length >= 2."""
    return [w for w in re.findall(r"[a-z0-9]{2,}", text.lower())
            if w not in _STOP_WORDS]


def _score_paper(paper: PaperRef, query_tokens: List[str]) -> float:
    """Simple relevance score: token overlap + citation boost."""
    if not query_tokens:
        return 0.0

    paper_text = f"{paper.title} {paper.abstract}".lower()
    paper_tokens = set(re.findall(r"[a-z0-9]{2,}", paper_text))

    if not paper_tokens:
        return 0.0

    # Token overlap (Jaccard-like, weighted toward query coverage)
    overlap = len(set(query_tokens) & paper_tokens)
    coverage = overlap / len(query_tokens) if query_tokens else 0.0

    # Citation boost (log scale, normalized)
    cite_score = 0.0
    if paper.citation_count and paper.citation_count > 0:
        import math
        cite_score = min(1.0, math.log10(paper.citation_count + 1) / 6.0)

    # Recency boost (papers from last 5 years get a small boost)
    recency_score = 0.0
    if paper.year and paper.year >= 2020:
        recency_score = 0.1

    return coverage * 0.7 + cite_score * 0.2 + recency_score * 0.1


# ------------------------------------------------------- public API


async def find_similar_papers(
    thesis: str,
    target_count: int = 30,
    deadline_s: float = 4.0,
) -> SimilarityResult:
    """Find research papers similar to the user's thesis.

    Args:
        thesis: User's thesis statement or research question (10-200 chars)
        target_count: Desired number of similar papers (20-50)
        deadline_s: Hard deadline in seconds (default 4.0)

    Returns:
        SimilarityResult with ranked papers
    """
    start = time.perf_counter()
    query_tokens = _tokenize(thesis)

    # Fan out to all sources in parallel with the deadline
    retrieval = await extract_papers(
        thesis,
        per_source_limit=100,
        deadline_s=deadline_s,
    )

    # Score and rank
    scored = []
    for paper in retrieval.papers:
        score = _score_paper(paper, query_tokens)
        scored.append(SimilarPaper(
            title=paper.title,
            authors=paper.authors,
            year=paper.year,
            doi=paper.doi,
            url=paper.url,
            venue=paper.venue,
            citation_count=paper.citation_count,
            abstract=paper.abstract,
            open_access=paper.open_access,
            source=paper.source,
            relevance_score=score,
        ))

    # Sort by relevance score (descending), then citation count as tiebreaker
    scored.sort(key=lambda p: (p.relevance_score, p.citation_count or 0), reverse=True)

    # Take top N
    top_papers = scored[:target_count]

    wall_ms = (time.perf_counter() - start) * 1000
    sources_used = list(retrieval.sources.keys())

    return SimilarityResult(
        query=thesis,
        papers=top_papers,
        total_candidates=len(retrieval.papers),
        wall_ms=wall_ms,
        sources_used=sources_used,
    )


def find_similar_papers_sync(thesis: str, **kwargs) -> SimilarityResult:
    """Synchronous convenience wrapper."""
    return asyncio.run(find_similar_papers(thesis, **kwargs))
