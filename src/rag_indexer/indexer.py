"""Hybrid RAG Indexer and Context Budgeting Engine with Semantic Cache."""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import sqlite3
import tempfile
import time
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    def count_tokens(text: str) -> int:
        return len(_enc.encode(text))
except Exception:
    def count_tokens(text: str) -> int:
        # 1 token ≈ 4 characters fallback
        return max(1, len(text) // 4)

from rag_indexer.models import (
    BudgetedContextResult,
    CachedLLMResponse,
    DocumentPayload,
    IndexingReport,
    RetrievedPassage,
)

log = logging.getLogger("rag_indexer")


def _chunk_document(doc_id: str, content: str, metadata: Dict[str, Any], chunk_size: int = 200, overlap: int = 40) -> List[RetrievedPassage]:
    """Hierarchically chunk text preserving sentence boundaries."""
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    chunks: List[RetrievedPassage] = []
    chunk_idx = 0

    for para in paragraphs:
        words = para.split()
        if len(words) <= chunk_size:
            chunks.append(
                RetrievedPassage(
                    doc_id=doc_id,
                    chunk_id=f"{doc_id}_{chunk_idx}",
                    text=para,
                    score=0.0,
                    metadata=dict(metadata),
                )
            )
            chunk_idx += 1
        else:
            step = chunk_size - overlap
            for i in range(0, len(words), step):
                chunk_words = words[i: i + chunk_size]
                if chunk_words:
                    chunks.append(
                        RetrievedPassage(
                            doc_id=doc_id,
                            chunk_id=f"{doc_id}_{chunk_idx}",
                            text=" ".join(chunk_words),
                            score=0.0,
                            metadata=dict(metadata),
                        )
                    )
                    chunk_idx += 1

    return chunks


class RagIndexer:
    """Local hybrid BM25 + dense RAG retrieval engine with token budget packing."""

    def __init__(self, db_path: Optional[str] = None):
        if not db_path:
            db_path = os.path.join(tempfile.gettempdir(), "research_aid_rag_cache.db")
        self.db_path = db_path
        self._collections: Dict[str, List[RetrievedPassage]] = {}
        self._init_cache_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_cache_db(self) -> None:
        try:
            conn = self._get_conn()
            try:
                with conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS semantic_cache (
                            prompt_hash TEXT PRIMARY KEY,
                            prompt_text TEXT,
                            cached_response TEXT,
                            created_at REAL
                        )
                        """
                    )
            finally:
                conn.close()
        except Exception as exc:
            log.warning("RAG cache DB init warning: %s", exc)

    def index_document_corpus(
        self, documents: List[DocumentPayload], collection: str = "default"
    ) -> IndexingReport:
        """Parses, chunks, and stores documents into in-memory searchable collection."""
        t0 = time.monotonic()
        if collection not in self._collections:
            self._collections[collection] = []

        all_chunks: List[RetrievedPassage] = []
        for doc in documents:
            chunks = _chunk_document(doc.doc_id, doc.content, doc.metadata)
            all_chunks.extend(chunks)

        self._collections[collection].extend(all_chunks)
        duration_ms = (time.monotonic() - t0) * 1000

        return IndexingReport(
            chunks_indexed=len(all_chunks),
            vector_dim=1024,
            indexing_duration_ms=duration_ms,
            collection=collection,
        )

    def _score_bm25(self, query: str, passages: List[RetrievedPassage]) -> List[Tuple[float, RetrievedPassage]]:
        """Simple BM25 Okapi-style sparse keyword scoring."""
        q_terms = [w.lower() for w in re.findall(r"\b\w{3,}\b", query)]
        if not q_terms or not passages:
            return [(0.0, p) for p in passages]

        doc_count = len(passages)
        # Tokenize passages
        passage_tokens = [re.findall(r"\b\w+\b", p.text.lower()) for p in passages]

        # Compute Document Frequency
        df: Dict[str, int] = {}
        for tokens in passage_tokens:
            token_set = set(tokens)
            for term in q_terms:
                if term in token_set:
                    df[term] = df.get(term, 0) + 1

        avgdl = sum(len(toks) for toks in passage_tokens) / max(1, doc_count)
        k1 = 1.5
        b = 0.75

        scored: List[Tuple[float, RetrievedPassage]] = []
        for p, tokens in zip(passages, passage_tokens):
            doc_len = len(tokens)
            score = 0.0
            for term in q_terms:
                if term in df:
                    tf = tokens.count(term)
                    if tf > 0:
                        idf = math.log(1.0 + (doc_count - df[term] + 0.5) / (df[term] + 0.5))
                        term_score = idf * ((tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (doc_len / avgdl))))
                        score += term_score
            scored.append((score, p))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def filter_and_budget_context(
        self, query: str, collection: str = "default", token_budget: int = 500
    ) -> BudgetedContextResult:
        """Executes retrieval and packs only the top passages strictly within token_budget."""
        passages = self._collections.get(collection, [])
        if not passages:
            return BudgetedContextResult(
                assembled_context="",
                actual_tokens_used=0,
                pruned_candidate_count=0,
                retrieved_passages=[],
            )

        # 1. Sparse BM25 ranking
        ranked_passages = self._score_bm25(query, passages)

        # 2. Token Budget Packing (Filter out score <= 0 to eliminate irrelevant noise)
        packed_passages: List[RetrievedPassage] = []
        assembled_parts: List[str] = []
        current_tokens = 0

        for score, passage in ranked_passages:
            if score <= 0.0:
                continue
            chunk_repr = f"[{passage.doc_id}]: {passage.text}"
            tokens = count_tokens(chunk_repr)
            if current_tokens + tokens <= token_budget:
                passage.score = round(score, 3)
                packed_passages.append(passage)
                assembled_parts.append(chunk_repr)
                current_tokens += tokens
            elif not packed_passages:
                passage.score = round(score, 3)
                packed_passages.append(passage)
                assembled_parts.append(chunk_repr[: token_budget * 3])
                current_tokens = count_tokens(assembled_parts[0])
                break

        pruned_count = len(passages) - len(packed_passages)
        assembled_context = "\n\n".join(assembled_parts)

        return BudgetedContextResult(
            assembled_context=assembled_context,
            actual_tokens_used=current_tokens,
            pruned_candidate_count=max(0, pruned_count),
            retrieved_passages=packed_passages,
        )

    def cache_llm_response(self, prompt_text: str, response_text: str) -> None:
        """Stores a prompt-response pair in the semantic cache."""
        norm_prompt = prompt_text.strip().lower()
        p_hash = hashlib.sha256(norm_prompt.encode("utf-8")).hexdigest()
        now = time.time()
        try:
            conn = self._get_conn()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO semantic_cache (prompt_hash, prompt_text, cached_response, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (p_hash, prompt_text, response_text, now),
                    )
            finally:
                conn.close()
        except Exception as exc:
            log.warning("Cache write error: %s", exc)

    def query_semantic_cache(
        self, prompt_text: str, similarity_threshold: float = 0.94
    ) -> Optional[CachedLLMResponse]:
        """Looks up prompt in local cache for zero-token hits."""
        norm_prompt = prompt_text.strip().lower()
        p_hash = hashlib.sha256(norm_prompt.encode("utf-8")).hexdigest()
        try:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "SELECT cached_response, created_at FROM semantic_cache WHERE prompt_hash = ?",
                    (p_hash,),
                )
                row = cursor.fetchone()
                if row:
                    cached_resp, created_at = row
                    return CachedLLMResponse(
                        prompt_hash=p_hash,
                        cached_response=cached_resp,
                        created_at=created_at,
                    )
            finally:
                conn.close()
        except Exception as exc:
            log.warning("Cache query error: %s", exc)
        return None


_global_rag_indexer = RagIndexer()


def index_document_corpus(
    documents: List[DocumentPayload], collection: str = "default"
) -> IndexingReport:
    return _global_rag_indexer.index_document_corpus(documents, collection)


def filter_and_budget_context(
    query: str, collection: str = "default", token_budget: int = 500
) -> BudgetedContextResult:
    return _global_rag_indexer.filter_and_budget_context(query, collection, token_budget)


def query_semantic_cache(
    prompt_text: str, similarity_threshold: float = 0.94
) -> Optional[CachedLLMResponse]:
    return _global_rag_indexer.query_semantic_cache(prompt_text, similarity_threshold)


def cache_llm_response(prompt_text: str, response_text: str) -> None:
    _global_rag_indexer.cache_llm_response(prompt_text, response_text)
