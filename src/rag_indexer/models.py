"""Data models for RAG Indexer Subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DocumentPayload:
    """Document to be indexed."""
    doc_id: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IndexingReport:
    """Report emitted upon index completion."""
    chunks_indexed: int
    vector_dim: int
    indexing_duration_ms: float
    collection: str


@dataclass
class RetrievedPassage:
    """Individual retrieved and scored chunk."""
    doc_id: str
    chunk_id: str
    text: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BudgetedContextResult:
    """Packed context string fitting strictly within token budget."""
    assembled_context: str
    actual_tokens_used: int
    pruned_candidate_count: int
    retrieved_passages: List[RetrievedPassage] = field(default_factory=list)


@dataclass
class CachedLLMResponse:
    """Cached response from semantic prompt cache."""
    prompt_hash: str
    cached_response: str
    created_at: float
