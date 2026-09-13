# RAG Indexer Documentation

## Module Overview
`rag_indexer` parses, indexes, and filters large text corpuses (papers, drafts, codebases) into budgeted contexts for LLMs, and maintains a semantic prompt cache.

## File Structure
- `models.py`: Data classes (`DocumentPayload`, `IndexingReport`, `RetrievedPassage`, `BudgetedContextResult`, `CachedLLMResponse`).
- `indexer.py`: Chunking, BM25 Okapi scoring, token budget packing, and persistent SQLite semantic cache.
- `tests/test_rag_indexer.py`: Unit test suite testing chunking, BM25 ranking, token budget limits, and cache retrieval.

## API Reference

### `index_document_corpus(documents: List[DocumentPayload], collection: str = "default") -> IndexingReport`
Chunks and indexes a batch of documents into the specified collection.
- **`documents`**: List of `DocumentPayload(doc_id, content, metadata)`.
- **`collection`**: Namespace identifier.
- **Returns**: `IndexingReport(chunks_indexed, vector_dim, indexing_duration_ms, collection)`.

### `filter_and_budget_context(query: str, collection: str = "default", token_budget: int = 500) -> BudgetedContextResult`
Retrieves and packs the most relevant passages strictly within `token_budget`.
- **`query`**: Search inquiry or hypothesis claim.
- **`token_budget`**: Hard token cap.
- **Returns**: `BudgetedContextResult(assembled_context, actual_tokens_used, pruned_candidate_count, retrieved_passages)`.

### `query_semantic_cache(prompt_text: str, similarity_threshold: float = 0.94) -> Optional[CachedLLMResponse]`
Checks if an identical or semantically matching prompt has already been computed.

### `cache_llm_response(prompt_text: str, response_text: str) -> None`
Saves a prompt-response pair into the semantic cache.

## Usage Example

```python
from rag_indexer import index_document_corpus, filter_and_budget_context, DocumentPayload

docs = [
    DocumentPayload("attention", "Transformers utilize multi-head self-attention without recurrent layers."),
    DocumentPayload("recipes", "Baking bread requires yeast, water, and flour.")
]

# Index
index_document_corpus(docs, collection="papers")

# Retrieve under 50 token budget
result = filter_and_budget_context("self-attention layers", collection="papers", token_budget=50)
print(f"Packed {result.actual_tokens_used} tokens (pruned {result.pruned_candidate_count} docs):")
print(result.assembled_context)
```

## Running Tests
```bash
python -m pytest rag_indexer/tests/test_rag_indexer.py -v
```
