"""Evidence Engine — Part 1: clean paper extraction from peer-reviewed sources.

Current status: Part 1 is implemented and verified. Later pipeline stages
(claim decomposition, stance gating, LLM curation) are planned in the
sections below and will be rebuilt one part at a time on top of this base.

Part 1 contract (sources.py, models.py):

    from evidence_engine import extract_papers_sync
    result = extract_papers_sync("Multilayer perceptron is the dominant "
                                 "choice of learning based solutions for "
                                 "inverse kinematics")
    result.papers        # list[PaperRef], deduplicated across sources
    result.sources       # {"europepmc": {...}, "openalex": {...}, ...}
    result.summary()     # "N unique papers in X ms [europepmc=15, ...]"

Three peer-reviewed sources, fanned out in parallel under a deadline:
Europe PMC (full-text BODY: search), OpenAlex (240M works), Semantic Scholar
(200M works, best metadata). Never raises; every failure degrades to a
per-source status. Successful fetches are disk-cached 6 h and served even
when the network or a source is down.
"""

from evidence_engine.models import PaperRef, RetrievalResult, SourceReport
from evidence_engine.sources import (
    build_queries,
    dedupe_papers,
    extract_papers,
    extract_papers_sync,
    reconstruct_abstract,
)
from evidence_engine.similar_papers import (
    SimilarPaper,
    SimilarityResult,
    find_similar_papers,
    find_similar_papers_sync,
)

__all__ = [
    "PaperRef",
    "RetrievalResult",
    "SourceReport",
    "SimilarPaper",
    "SimilarityResult",
    "build_queries",
    "dedupe_papers",
    "extract_papers",
    "extract_papers_sync",
    "find_similar_papers",
    "find_similar_papers_sync",
    "reconstruct_abstract",
]
