# Paper Discovery Subsystem

## 1. Final Deliverable
A two-stage hybrid RAG literature discovery engine (`paper_discovery`) providing:
- Multi-source academic paper discovery (`discover_similar_papers()`) across Semantic Scholar, OpenAlex, and local seminal indices.
- Algorithmic pruning filtering hundreds of candidate papers down to the top 4–6 relevant publications with valid DOIs and BibTeX citation keys (`vaswani2017attention`).
- Contextual related-work literature synthesis (`synthesize_literature_context()`) generating drafted synthesis paragraphs.
- Graph traversal (`traverse_citation_network()`) navigating inward and outward citation edges.

## 2. Algorithm Used
**Two-Stage Hybrid RAG Academic Literature Retrieval**:
1. **Stage 1 (Algorithmic RAG Filtering — 0 LLM Tokens)**:
   - Extracts academic keyphrases and terminology from the draft text.
   - Dispatches federated search requests via `src/api_gateway/` targeting Semantic Scholar Graph API and OpenAlex works catalog.
   - Falls back to offline indexed seminal publications if external APIs are unreachable.
   - Prunes and deduplicates candidate papers by citation count and semantic relevance into a shortlist of 4–6 publications.
   - Generates standardized BibTeX citation keys from first author surname, publication year, and primary title noun.
2. **Stage 2 (Targeted Relevance Assessment)**:
   - Formats a compact prompt for the LLM via `src/api_gateway/` (or generates abstract excerpt summaries) to explain how each paper specifically connects to the author's claim.

## 3. Description
The `paper_discovery` subsystem helps authors writing in Word, Google Docs, or LaTeX quickly identify foundational and state-of-the-art academic papers related to their active draft, insert BibTeX citation keys, and generate related-work paragraphs without hallucinated citations.
