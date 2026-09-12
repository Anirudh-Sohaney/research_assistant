# RAG Pipelines for Academic Research

## The Problem

The research aid needs two key features — "find supporting/opposing evidence" and "find similar papers" — both requiring RAG over academic paper corpora. The system needs to accept user-selected text or a full paper, retrieve relevant academic papers, classify evidence as supporting or opposing, use LLM reasoning to synthesize findings, and return results with proper citations.

---

## 1. RAG Frameworks

### LlamaIndex (Recommended)

**GitHub:** https://github.com/run-llama/llama_index (~51k stars)  
**License:** MIT

Strongest document ingestion and retrieval quality. VectorStoreIndex handles splitting, embedding, and indexing in one call. Advanced retrieval patterns (SubQuestion, HyDE, RAG Fusion) built in. Hierarchical chunking preserves document structure. Auto-merging retrieval reconstructs coherent sections from fragmented chunks.

For "find similar papers": excellent with hierarchical chunking plus recommendation retrieval. For "find supporting/opposing evidence": Sub-question decomposition splits complex queries into parallel retrievals.

### LangChain

**GitHub:** https://github.com/langchain-ai/langchain (~142k stars)  
**License:** MIT

General LLM orchestration with broadest integration ecosystem (100+ vector stores, 60+ LLM providers). LangGraph enables stateful agent workflows. Best when RAG is one step in a larger workflow (retrieve, analyze, act).

### Haystack

**GitHub:** https://github.com/deepset-ai/haystack (~26k stars)  
**License:** Apache 2.0

Explicit typed pipelines, YAML serialization, component-based architecture. Best for auditable, compliance-sensitive pipelines where every retrieval step needs logging.

### OpenScholar

**GitHub:** https://github.com/AkariAsai/OpenScholar (~1,587 stars)  
**License:** Apache 2.0

Purpose-built for scientific literature synthesis. Published in Nature (2026). Includes OpenScholar DataStore with 45M open-access papers and 236M passage embeddings. Self-feedback inference loop for iterative refinement. Outperforms GPT-4o by 6.1% on ScholarQABench. Citation accuracy on par with human experts (GPT-4o hallucinates citations 78-90% of the time).

---

## 2. Academic Paper Sources

### Semantic Scholar API (Primary)

**URL:** https://api.semanticscholar.org/graph/v1  
**Coverage:** 200M+ papers, strong in CS and biomedicine  
**Free:** Yes, API key optional but recommended  
**Rate limits:** With API key: 1 req/sec per user  
**Features:** Citation graphs, TL;DR summaries, SPECTER2 embeddings, recommendations API, bulk search, batch endpoints (500 papers per request)

Best for: citation graph traversal, finding related papers via recommendations.

### arXiv API

**URL:** https://arxiv.org/api/query  
**Coverage:** Physics, math, CS, bio preprints  
**Free:** Yes, no registration  
**Rate limits:** 1 request every 3 seconds  
**Returns full text:** Yes (XML/PDF link)

Best for: CS/ML preprints, early-stage research.

### PubMed E-utilities

**URL:** https://eutils.ncbi.nlm.nih.gov/entrez/eutils/  
**Coverage:** 40M+ biomedical citations, curated MeSH indexing  
**Free:** Yes, API key optional and free  
**Rate limits:** 3 req/sec without key, 10 req/sec with key

Best for: biomedical/clinical literature, Boolean/MeSH queries.

### CORE API

**URL:** https://api.core.ac.uk/v3  
**Coverage:** 260M+ metadata records, 36M+ full-text papers  
**Free:** Yes for non-commercial academic use  
**Rate limits:** Free tier: 150 requests per 15-minute window

Best for: largest open-access corpus, full-text access.

### OpenAlex

**URL:** https://api.openalex.org  
**Coverage:** ~480M works across all disciplines  
**Free:** Yes, API key free  
**Rate limits:** 10 req/sec (polite pool with email)

Best for: broadest cross-discipline coverage, free bulk snapshots.

### Unpaywall

**URL:** https://api.unpaywall.org/v2  
**Coverage:** 120M+ articles with Crossref DOIs  
**Free:** Yes, no API key required  
**Rate limits:** 100,000 calls/day

Best for: finding legal free PDFs, checking OA status.

---

## 3. Vector Databases

### Qdrant (Recommended)

**GitHub:** https://github.com/qdrant/qdrant  
**License:** Apache 2.0

Best latency among full databases (4.55ms P50). Strong payload filtering, native hybrid search (dense plus sparse), multi-vector support, Rust-based. Handles hundreds of millions of vectors.

### ChromaDB (Prototyping)

**GitHub:** https://github.com/chroma-core/chroma  
**License:** Apache 2.0

Simplest setup, embedded or client-server, integrates with LangChain and LlamaIndex. Good for personal research paper collections up to ~1M vectors.

### FAISS (Building Block)

**GitHub:** https://github.com/facebookresearch/faiss  
**License:** MIT

Highest throughput (866 QPS on SIFT1M), GPU support, many index types. Library only — no persistence or metadata filtering. Use inside larger systems.

---

## 4. Embedding Models

### BGE-M3 (Recommended)

**Model:** BAAI/bge-m3  
**License:** MIT

Supports 100+ languages, 8192-token context, produces dense plus sparse plus multi-vector (ColBERT) embeddings in one forward pass. The production workhorse for multilingual academic RAG.

### NV-Embed-v2 (Maximum Accuracy)

**Model:** NVIDIA/NV-Embed-v2 (7B parameters)  
**MTEB:** 72.31 (leads leaderboard)  
**Context:** 32K tokens

Strongest on scientific retrieval tasks (SciFact, NFCorpus). Requires GPU with 16GB+ VRAM.

### E5-Large-v2

**Model:** intfloat/e5-large-v2  
**License:** MIT

Instruction-tuned with query and passage prefixes. 16ms latency on small variants. Balanced performance for English-only academic retrieval.

---

## 5. Citation Detection and Verification

### ValiRef

**GitHub:** https://github.com/gianthard-cyh/valiref (~83 stars)  
**License:** MIT  
**Accuracy:** 88.1% on 1000-sample benchmark  
**Detects:** Fabrication, attribution errors, irrelevance, counterfactual citations

### BibSleuth

**GitHub:** https://github.com/yy/bibsleuth  
**License:** MIT

LLM-powered analysis. Checks existence against 6 databases, detects mis-citations, suggests papers for uncited claims, surfaces contradicting evidence.

### RefChecker

**GitHub:** https://github.com/ziwenzu/refchecker  
**License:** MIT

Validates against Semantic Scholar, OpenAlex, CrossRef, DBLP. LLM-powered deep web search for hallucination detection. Supports bulk checking.

---

## 6. Existing Research Assistants (Reference)

### Scite

**URL:** https://scite.ai  
**Database:** 1B+ citations classified as supporting, contradicting, or mentioning

Unique in classifying citation context. Only tool that surfaces supporting vs. contradicting citations. Core capability for "find supporting/opposing evidence."

### Consensus

**URL:** https://consensus.app  
**Database:** 220M+ research papers

Evidence-based Q&A with "Consensus Meter" showing agreement/disagreement across studies. Best for quickly gauging how much evidence supports or opposes a claim.

### Research Rabbit

**URL:** https://www.researchrabbit.ai  
**Database:** 310M+ articles (via Semantic Scholar API)

Visual citation network mapping. Completely free. Zotero integration. Best for citation discovery and visual exploration.

### Elicit

**URL:** https://elicit.com  
**Database:** 125M+ papers, 545K+ clinical trials

Structured screening and extraction. PRISMA 2020 compliant. 95% search recall, 97% abstract screening accuracy. Best for systematic reviews.

---

## 7. Recommended RAG Architecture

```
User selects text
       |
       v
LlamaIndex Query Engine
       |
       ├──> Semantic Scholar API (citation graph, recommendations)
       ├──> OpenAlex (broad discovery)
       └──> Qdrant (local paper embeddings)
       |
       v
Retrieved papers (top-k)
       |
       v
LLM Evidence Classifier
  (supporting / opposing / neutral)
       |
       v
Citation Verifier (ValiRef or BibSleuth)
       |
       v
Overlay popup with evidence list
  (title, authors, year, snippet, stance)
```

**For "find similar papers":** Use Semantic Scholar Recommendations API with the paper's ID as seed. Supplement with BGE-M3 embedding similarity from local Qdrant index.

**For "find supporting/opposing evidence":** Use LlamaIndex SubQuestionQueryEngine to decompose the highlighted claim into sub-queries. Retrieve from Semantic Scholar and OpenAlex. Classify each retrieved paper's stance using LLM reasoning. Verify citations with ValiRef.

---

## Key Insights

1. **OpenScholar is the state of the art** — Purpose-built for this exact use case, with non-hallucinating citations. Worth studying its architecture closely.

2. **Scite's citation classification is unique** — The only tool that tells you whether later papers support or contradict a claim. This is exactly what "find supporting/opposing evidence" needs.

3. **Semantic Scholar is the best free API** — 200M+ papers, citation graphs, recommendations, SPECTER2 embeddings. Rate limits are manageable with an API key.

4. **Hybrid retrieval beats pure vector search** — Combine semantic similarity (embeddings) with keyword matching and citation graph traversal. LlamaIndex's EnsembleRetriever handles this.

5. **Citation verification is essential** — LLMs hallucinate citations 78-90% of the time (GPT-4o). Any evidence-finding feature MUST verify citations against real databases. ValiRef or BibSleuth can do this.
