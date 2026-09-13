"""Evidence Engine — federated retrieval + LLM judging for academic evidence.

Usage:

    from evidence_engine import find_evidence_sync
    result = find_evidence_sync("MLP is a strong choice for learning-based IK")
    for item in result.items:
        print(f"[{item.confidence:.2f}] {item.quote[:100]}...")
        print(f"  Paper: {item.paper.title}")
"""

from evidence_engine.models import (
    EvidenceItem,
    EvidenceResult,
    PaperRef,
    RetrievalResult,
)
from evidence_engine.evidence_pipeline import (
    build_queries,
    dedupe_papers,
    find_evidence,
    find_evidence_sync,
    retrieve_papers,
)

__all__ = [
    "EvidenceItem",
    "EvidenceResult",
    "PaperRef",
    "RetrievalResult",
    "build_queries",
    "dedupe_papers",
    "find_evidence",
    "find_evidence_sync",
    "retrieve_papers",
]
