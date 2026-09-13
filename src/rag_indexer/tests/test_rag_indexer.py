"""Unit tests for rag_indexer subsystem."""

import os
import sys
import tempfile
import time

import pytest

_src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from rag_indexer.models import (
    BudgetedContextResult,
    CachedLLMResponse,
    DocumentPayload,
    IndexingReport,
)
from rag_indexer.indexer import (
    RagIndexer,
    count_tokens,
    index_document_corpus,
    filter_and_budget_context,
    query_semantic_cache,
    cache_llm_response,
)


class TestRagIndexer:
    def test_indexing_and_chunking(self):
        indexer = RagIndexer()
        docs = [
            DocumentPayload(
                doc_id="paper_1",
                content="Transformers rely on self-attention mechanisms. They eliminate recurrent neural networks completely.\n\nMulti-head attention allows the model to jointly attend to information from different representation subspaces.",
                metadata={"title": "Attention Is All You Need", "year": 2017},
            ),
            DocumentPayload(
                doc_id="paper_2",
                content="Convolutional networks process visual features across spatial dimensions.\n\nResidual connections enable training of deep networks.",
                metadata={"title": "Deep Residual Learning", "year": 2016},
            ),
        ]
        report = indexer.index_document_corpus(docs, collection="test_col")
        assert isinstance(report, IndexingReport)
        assert report.chunks_indexed >= 4
        assert report.collection == "test_col"

    def test_bm25_retrieval_and_budget_packing(self):
        indexer = RagIndexer()
        docs = [
            DocumentPayload(
                doc_id="transformer_doc",
                content="Self-attention mechanisms calculate similarity between query and key vectors. Softmax normalizes attention weights.",
            ),
            DocumentPayload(
                doc_id="cooking_doc",
                content="Baking sourdough bread requires flour, water, salt, and fermentation time at ambient room temperature.",
            ),
            DocumentPayload(
                doc_id="transformer_doc_2",
                content="Positional encodings provide order awareness to permutation-invariant self-attention transformer layers.",
            ),
        ]
        indexer.index_document_corpus(docs, collection="ml_col")

        # Query about attention with tight budget of 50 tokens
        result = indexer.filter_and_budget_context(
            query="self-attention query key weights",
            collection="ml_col",
            token_budget=50,
        )

        assert isinstance(result, BudgetedContextResult)
        assert result.actual_tokens_used <= 50
        assert "transformer_doc" in result.assembled_context
        # The cooking document should be pruned
        assert "sourdough" not in result.assembled_context
        assert result.pruned_candidate_count >= 1

    def test_token_counter(self):
        text = "The quick brown fox jumps over the lazy dog."
        tokens = count_tokens(text)
        assert 5 <= tokens <= 15

    def test_semantic_cache_roundtrip(self):
        db_file = os.path.join(tempfile.gettempdir(), f"test_rag_cache_{os.getpid()}_{time.time_ns()}.db")
        try:
            indexer = RagIndexer(db_path=db_file)
            prompt = "Explain quantum entanglement in one sentence."
            resp_text = "Entanglement is a phenomenon where quantum particles remain interconnected."

            assert indexer.query_semantic_cache(prompt) is None
            indexer.cache_llm_response(prompt, resp_text)

            cached = indexer.query_semantic_cache(prompt)
            assert cached is not None
            assert cached.cached_response == resp_text
        finally:
            try:
                if os.path.exists(db_file):
                    os.unlink(db_file)
                for ext in ("-wal", "-shm"):
                    if os.path.exists(db_file + ext):
                        os.unlink(db_file + ext)
            except Exception:
                pass
