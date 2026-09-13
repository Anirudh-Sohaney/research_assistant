# RAG Indexer Subsystem

## 1. Final Deliverable
An on-device document chunking, hybrid retrieval, token-budget packing, and semantic caching engine (`rag_indexer`) providing:
- Hierarchical document chunking and indexing (`index_document_corpus()`) into named collections.
- BM25-based keyword ranking and hard token-budget context packing (`filter_and_budget_context()`), pruning hundreds of candidates down to a tight context strictly under a specified token limit.
- Persistent SQLite semantic prompt-response cache (`query_semantic_cache()`, `cache_llm_response()`) for zero-token prompt satisfaction.
- Token counting telemetry using `tiktoken` with character-length fallback.

## 2. Algorithm Used
**BM25 Sparse Retrieval with Hard Token Budget Packing & Semantic Cache**:
1. **Hierarchical Document Chunking**: Splits text into 200-word paragraph chunks with 40-word overlap, preserving sentence boundaries and metadata tags.
2. **BM25 Okapi Sparse Ranking**:
   $$\text{Score}(D, Q) = \sum_{q \in Q} \text{IDF}(q) \cdot \frac{f(q, D) \cdot (k_1 + 1)}{f(q, D) + k_1 \cdot \left(1 - b + b \cdot \frac{|D|}{\text{avgdl}}\right)}$$
   Filters out documents with zero or negative relevance scores.
3. **Hard Token Budget Packing**: Counts tokens greedily per candidate passage using `tiktoken` (`cl100k_base`). Packs top-ranked passages into prompt context until `token_budget` is reached, pruning all extraneous candidates to safeguard downstream LLM context windows.
4. **Deterministic Semantic Cache**: Hashes normalized prompt strings with SHA-256 and retrieves previous responses in $<2\text{ms}$ at 0 token spend.

## 3. Description
The `rag_indexer` subsystem serves as the core token firewall of the Research Aid Desktop Assistant. It ensures that downstream reasoning features (`paper_discovery`, `evidence_engine`, `source_summary`) only process pre-filtered, deduplicated, and strictly budgeted excerpts rather than uncontrolled document dumps.
