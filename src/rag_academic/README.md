# rag_academic — Academic RAG Pipelines

Retrieval-Augmented Generation over academic paper corpora. Finds supporting/opposing evidence for claims, discovers similar papers, and verifies citations against real databases.

Part of the [Research Aid Desktop Assistant](../../brainstorm/00-project-overview.md).

## Table of Contents

- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Architecture](#architecture)
- [Component Solutions](#component-solutions)
- [Alternatives and Issues](#alternatives-and-issues)
- [Codebase Structure](#codebase-structure)
- [Configuration](#configuration)
- [Sources](#sources)

---

## Quick Start

```python
from rag_academic import find_academic_evidence, find_similar_papers

# Find supporting and opposing evidence for a claim
result = find_academic_evidence(
    query_text="Quantum entanglement enables faster-than-light communication",
    evidence_type="both",
    max_results=10,
    sources=["semantic_scholar", "openalex"],
)

print(result["supporting_papers"])   # Papers supporting the claim
print(result["opposing_papers"])     # Papers contradicting the claim
print(result["citations_verified"])  # How many citations passed verification

# Find papers similar to a known paper
similar = find_similar_papers(
    paper_id="204e3073870fae3d05bcbc2f6a8e263d9b72e776",
    max_results=5,
    method="recommendation",
)

print(similar["similar_papers"])
print(similar["reasoning"])
```

---

## API Reference

### `find_academic_evidence`

```python
def find_academic_evidence(
    query_text: str,
    evidence_type: str = "both",          # "supporting", "opposing", "both"
    max_results: int = 10,
    sources: list[str] | None = None,     # ["semantic_scholar", "arxiv", "pubmed", "core", "openalex"]
    embedding_model: str = "bge-m3",
    vector_db: str = "qdrant",
    classify_stance: bool = True,
    verify_citations: bool = True,
    min_year: int | None = None,
    max_year: int | None = None,
    fields_of_study: list[str] | None = None,  # ["Computer Science", "Physics", "Medicine"]
    open_access_only: bool = False,
    citation_graph_depth: int = 1,        # How many hops into citation graph
    min_citation_count: int = 0,
    llm_provider: str = "ollama",
    llm_model: str = "llama3.2",
    timeout_ms: int = 5000,
) -> dict:
    """
    Retrieve papers supporting or opposing a textual claim, classify stance, and verify citations.

    Returns:
        {
            "supporting_papers": list[PaperResult],
            "opposing_papers": list[PaperResult],
            "neutral_papers": list[PaperResult],
            "similar_papers": list[PaperResult],
            "citations_verified": int,
            "citations_total": int,
            "total_retrieved": int,
            "processing_time_ms": float,
            "query_decomposition": list[str],  # Sub-queries generated from the claim
            "source_breakdown": dict[str, int],
            "warnings": list[str],
        }

    Each PaperResult:
        {
            "paper_id": str,
            "title": str,
            "authors": list[str],
            "year": int,
            "venue": str,
            "abstract": str,
            "citation_count": int,
            "url": str,
            "doi": str | None,
            "open_access_pdf": str | None,
            "stance": str,                    # "supporting", "opposing", "neutral"
            "stance_confidence": float,       # 0.0 - 1.0
            "evidence_snippet": str,          # Relevant passage from the paper
            "citation_verified": bool,
            "verification_details": dict | None,
            "source": str,                    # Which API returned this paper
            "semantic_similarity": float,
            "retrieval_score": float,
        }
    """
```

### `find_similar_papers`

```python
def find_similar_papers(
    paper_id: str | None = None,
    paper_title: str | None = None,
    paper_abstract: str | None = None,
    max_results: int = 10,
    method: str = "recommendation",        # "recommendation", "embedding", "citation", "hybrid"
    embedding_model: str = "bge-m3",
    vector_db: str = "qdrant",
    min_year: int | None = None,
    fields_of_study: list[str] | None = None,
    open_access_only: bool = False,
    timeout_ms: int = 5000,
) -> dict:
    """
    Find papers similar to a given paper or text.

    At least one of paper_id, paper_title, or paper_abstract must be provided.

    Returns:
        {
            "similar_papers": list[PaperResult],
            "similarity_scores": list[float],
            "method_used": str,
            "reasoning": str,                # LLM explanation of why these are similar
            "processing_time_ms": float,
        }
    """
```

### `verify_citations`

```python
def verify_citations(
    citations: list[dict],
    sources: list[str] | None = None,
    deep_verify: bool = False,             # Check content match, not just existence
    timeout_ms: int = 3000,
) -> dict:
    """
    Verify that cited papers actually exist and match the claimed content.

    Each citation dict:
        {"title": str, "authors": list[str], "year": int, "doi": str | None, "claim": str | None}

    Returns:
        {
            "results": list[{
                "citation": dict,
                "exists": bool,
                "matched_paper": PaperResult | None,
                "content_match": bool | None,   # If deep_verify=True
                "errors": list[str],
            }],
            "verified_count": int,
            "total_count": int,
            "processing_time_ms": float,
        }
    """
```

### `retrieve_papers`

```python
def retrieve_papers(
    query: str,
    sources: list[str] | None = None,
    max_results: int = 20,
    min_year: int | None = None,
    max_year: int | None = None,
    fields_of_study: list[str] | None = None,
    open_access_only: bool = False,
    sort_by: str = "relevance",            # "relevance", "citations", "year"
    timeout_ms: int = 3000,
) -> dict:
    """
    Low-level paper retrieval from multiple academic sources.

    Returns:
        {
            "papers": list[PaperResult],
            "source_breakdown": dict[str, int],
            "processing_time_ms": float,
        }
    """
```

---

## Architecture

```
User selects text (claim or paper)
        |
        v
┌─────────────────────────────────────┐
│     query_decomposer.py             │
│  LLM breaks claim into sub-queries  │
│  "X causes Y" → ["X Y effect",     │
│   "X Y mechanism", "X Y meta"]     │
└─────────────────────────────────────┘
        |
        v
┌─────────────────────────────────────┐
│      paper_retriever.py             │
│  Fan-out to multiple sources:       │
│  ├── Semantic Scholar (citation     │
│  │   graph + recommendations)       │
│  ├── OpenAlex (broad discovery)     │
│  ├── arXiv (preprints)              │
│  ├── PubMed (biomedical)            │
│  └── CORE (open-access full-text)   │
│  Deduplicate by paper_id            │
└─────────────────────────────────────┘
        |
        v
┌─────────────────────────────────────┐
│      embedding_engine.py            │
│  BGE-M3 encodes retrieved papers    │
│  Semantic similarity to original    │
│  query; optionally re-rank with     │
│  cross-encoder                      │
└─────────────────────────────────────┘
        |
        v
┌─────────────────────────────────────┐
│     stance_classifier.py            │
│  LLM classifies each paper:         │
│  supporting / opposing / neutral    │
│  Outputs confidence score per paper │
└─────────────────────────────────────┘
        |
        v
┌─────────────────────────────────────┐
│     citation_verifier.py            │
│  ValiRef / BibSleuth validates      │
│  that cited papers exist and match  │
│  Detects fabrication, mis-attrib,   │
│  counterfactual citations           │
└─────────────────────────────────────┘
        |
        v
    Result dict
    (supporting_papers, opposing_papers,
     similar_papers, citations_verified)
```

---

## Component Solutions

### RAG Frameworks

| Framework | License | Stars | Strengths | Weaknesses |
|-----------|---------|-------|-----------|------------|
| **LlamaIndex** | MIT | 51K | Best document retrieval, hierarchical chunking, SubQuestion/HyDE/RAG Fusion built in | Heavier than raw LangChain for simple chains |
| **LangChain** | MIT | 142K | Broadest integration (100+ vector stores, 60+ LLMs), LangGraph for stateful agents | Abstraction overhead, fast-moving API changes |
| **Haystack** | Apache-2.0 | 26K | Typed pipelines, YAML serialization, auditable/compliance-friendly | Smaller community, steeper learning curve |
| **OpenScholar** | Apache-2.0 | 1.6K | Purpose-built for scientific synthesis, 45M papers, self-feedback loop, outperforms GPT-4o by 6.1% | Newer, smaller community, fixed datastore |

**Recommendation:** LlamaIndex for retrieval core. OpenScholar's self-feedback inference pattern is worth adopting for iterative evidence refinement.

### Academic Sources

| Source | Coverage | Rate Limit | Best For |
|--------|----------|------------|----------|
| **Semantic Scholar API** | 200M+ papers | 1 req/sec (with key) | Citation graphs, recommendations, TL;DR summaries, SPECTER2 embeddings |
| **arXiv API** | Physics, math, CS preprints | 1 req / 3 sec | CS/ML preprints, full text XML/PDF |
| **PubMed E-utilities** | 40M+ biomedical | 3-10 req/sec | Biomedical/clinical, MeSH Boolean queries |
| **CORE API** | 260M+ records, 36M+ full-text | 150 req / 15 min | Largest open-access corpus, full-text |
| **OpenAlex** | ~480M works | 10 req/sec (polite) | Broadest cross-discipline, free bulk snapshots |
| **Unpaywall** | 120M+ articles | 100K calls/day | Legal free PDFs, OA status checks |

**Recommendation:** Semantic Scholar as primary (citation graphs + recommendations). OpenAlex for broad discovery. PubMed for biomedical domains.

### Vector Databases

| Database | License | Latency | Throughput | Best For |
|----------|---------|---------|------------|----------|
| **Qdrant** | Apache-2.0 | 4.55ms P50 | High | Production: payload filtering, hybrid search, native sparse+dense |
| **ChromaDB** | Apache-2.0 | Medium | Medium | Prototyping: simplest setup, embedded mode, <1M vectors |
| **FAISS** | MIT | Lowest | 866 QPS (SIFT1M) | Building block: GPU support, no persistence/metadata, use inside larger systems |

**Recommendation:** Qdrant for production. ChromaDB for local dev/testing. FAISS as internal加速器 inside hybrid retrieval.

### Embedding Models

| Model | License | Params | Context | Strengths |
|-------|---------|--------|---------|-----------|
| **BGE-M3** | MIT | 568M | 8192 | Multilingual (100+ langs), dense+sparse+ColBERT in one pass |
| **NV-Embed-v2** | — | 7B | 32K | MTEB 72.31 (leaderboard top), strongest on SciFact/NFCorpus. Requires GPU 16GB+ |
| **E5-Large-v2** | MIT | 335M | 512 | Instruction-tuned, 16ms latency, balanced English performance |

**Recommendation:** BGE-M3 for multilingual production. NV-Embed-v2 for maximum accuracy when GPU is available. E5-Large-v2 for low-latency English-only fallback.

### Citation Verification

| Tool | License | Accuracy | Capabilities |
|------|---------|----------|--------------|
| **ValiRef** | MIT | 88.1% | Detects fabrication, attribution errors, irrelevance, counterfactual citations |
| **BibSleuth** | MIT | — | Checks against 6 databases, suggests papers for uncited claims, surfaces contradictions |
| **RefChecker** | MIT | — | Validates against Semantic Scholar, OpenAlex, CrossRef, DBLP; bulk checking |

**Recommendation:** ValiRef for standalone verification. BibSleuth for deeper content-level analysis.

### Reference Tools (External, for Benchmarking)

| Tool | Database | Unique Capability |
|------|----------|-------------------|
| **Scite** | 1B+ citations | Classifies citations as supporting/contradicting/mentioning |
| **Consensus** | 220M+ papers | "Consensus Meter" showing agreement across studies |
| **Research Rabbit** | 310M+ articles | Visual citation network mapping, free, Zotero integration |
| **Elicit** | 125M+ papers | PRISMA 2020 compliant, 95% search recall, systematic reviews |

---

## Alternatives and Issues

### Rate Limiting Strategies

API rate limits require careful orchestration when fan-out querying multiple sources:

- **Request queuing:** Token bucket per source (1/sec Semantic Scholar, 10/sec OpenAlex)
- **Batch endpoints:** Semantic Scholar batch API (500 papers per request) reduces round trips
- **Local cache:** Cache embeddings and metadata in Qdrant to avoid re-fetching known papers
- **Graceful degradation:** If a source is rate-limited, continue with remaining sources and fill gaps from cache

### Citation Hallucination Prevention

LLMs hallucinate 78–90% of citations (GPT-4o benchmark). This is the single biggest risk in evidence-finding features.

**Mitigations:**
1. **Never trust LLM-generated citations.** Always verify against Semantic Scholar, OpenAlex, or CrossRef.
2. **ValiRef** catches fabrication, mis-attribution, and counterfactual citations at 88.1% accuracy.
3. **OpenScholar's self-feedback loop** iteratively refines citations against its datastore.
4. **Display citations with verification status** — show users which citations are confirmed vs. unverified.

### Hybrid Retrieval

Pure vector search misses keyword-specific matches and citation relationships. Combine three signals:

1. **Semantic similarity** — BGE-M3 dense embeddings via Qdrant
2. **Keyword matching** — BM25 sparse retrieval (Qdrant sparse vectors or Elasticsearch)
3. **Citation graph** — Semantic Scholar citation graph traversal (papers citing the same seeds)

LlamaIndex `EnsembleRetriever` merges results from all three with configurable weights. Typical weights: 0.4 semantic, 0.3 keyword, 0.3 citation graph.

### Latency Targets

| Operation | Target | Strategy |
|-----------|--------|----------|
| Evidence finding | <5s | Pre-computed embeddings, async source fan-out, streaming LLM classification |
| Similar papers | <5s | Semantic Scholar Recommendations API (single call) + local Qdrant re-rank |
| Citation verification | <3s | Async verification, display unverified results immediately, verify in background |
| Paper retrieval | <2s | Parallel API calls, deduplicate in-memory, cache frequent queries |

### Cost Considerations

| Component | API Cost | Local Alternative |
|-----------|----------|-------------------|
| Embeddings | Free (BGE-M3 self-hosted) | Self-hosted BGE-M3 on GPU |
| Semantic Scholar | Free (with rate limits) | Bulk download (S2ORC snapshot) |
| OpenAlex | Free | Bulk snapshot (~300GB) |
| LLM classification | Ollama = free, API = $0.01-0.10/classification | Local Llama 3.2 via Ollama |
| Citation verification | ValiRef/BibSleuth = free (self-hosted) | — |

**For offline/local-first:** Download OpenAlex bulk snapshot + BGE-M3 model + Qdrant embedded. Full functionality without internet.

---

## Codebase Structure

```
rag_academic/
├── __init__.py                 # Public API exports
├── config.py                   # Configuration (sources, models, thresholds)
├── models.py                   # Data models (Paper, PaperResult, Citation, Evidence)
│
├── evidence_finder.py          # Main evidence pipeline (orchestrator)
├── similar_papers.py           # Paper similarity and recommendations
├── paper_retriever.py          # Multi-source paper retrieval with deduplication
├── citation_verifier.py        # Citation existence and content verification
├── stance_classifier.py        # Supporting/opposing/neutral classification
├── embedding_engine.py         # BGE-M3, NV-Embed-v2, E5 embedding pipelines
├── vector_store.py             # Qdrant integration (index, search, filter)
├── query_decomposer.py         # LLM-based claim decomposition into sub-queries
│
├── sources/                    # Academic API clients
│   ├── __init__.py
│   ├── semantic_scholar.py     # Semantic Scholar API client
│   ├── openalex.py             # OpenAlex API client
│   ├── arxiv.py                # arXiv API client
│   ├── pubmed.py               # PubMed E-utilities client
│   ├── core.py                 # CORE API client
│   └── unpaywall.py            # Unpaywall API client
│
└── utils/                      # Shared utilities
    ├── __init__.py
    ├── rate_limiter.py         # Token bucket rate limiting per source
    ├── deduplication.py        # Paper deduplication across sources
    └── text_processing.py      # Claim cleaning, snippet extraction
```

### Module Responsibilities

| Module | Responsibility | Key Dependencies |
|--------|---------------|-----------------|
| `evidence_finder.py` | Orchestrates the full evidence pipeline: decompose → retrieve → embed → classify → verify | All other modules |
| `similar_papers.py` | Finds similar papers via recommendations API, embedding similarity, or citation graph | Semantic Scholar, Qdrant, embedding_engine |
| `paper_retriever.py` | Fans out queries to multiple sources, deduplicates results | sources/*, deduplication |
| `citation_verifier.py` | Verifies citations exist and match claimed content | ValiRef, BibSleuth, sources/* |
| `stance_classifier.py` | Classifies paper stance relative to a claim | LLM (Ollama or API) |
| `embedding_engine.py` | Encodes text/papers into vectors | BGE-M3, NV-Embed-v2, E5-Large-v2 |
| `vector_store.py` | Stores/retrieves embeddings from Qdrant | qdrant-client |
| `query_decomposer.py` | Breaks complex claims into retrievable sub-queries | LLM (Ollama or API) |

---

## Configuration

```python
# config.py
RAG_CONFIG = {
    "sources": {
        "semantic_scholar": {
            "enabled": True,
            "api_key": None,  # Set via env: SEMANTIC_SCHOLAR_API_KEY
            "rate_limit_per_sec": 1,
            "batch_size": 500,
        },
        "openalex": {
            "enabled": True,
            "email": None,  # Set via env: OPENALEX_EMAIL (for polite pool)
            "rate_limit_per_sec": 10,
        },
        "arxiv": {"enabled": True, "rate_limit_per_sec": 0.33},
        "pubmed": {"enabled": False, "api_key": None, "rate_limit_per_sec": 3},
        "core": {"enabled": False, "api_key": None, "rate_limit_per_sec": 1.67},
        "unpaywall": {"enabled": False, "email": None, "rate_limit_per_sec": 1.16},
    },
    "embeddings": {
        "model": "BAAI/bge-m3",
        "device": "auto",  # "cpu", "cuda", "mps"
        "dimension": 1024,
        "batch_size": 32,
    },
    "vector_db": {
        "provider": "qdrant",
        "url": "http://localhost:6333",
        "collection": "academic_papers",
        "distance": "cosine",
    },
    "llm": {
        "provider": "ollama",
        "model": "llama3.2",
        "api_url": "http://localhost:11434",
        "temperature": 0.1,
        "max_tokens": 512,
    },
    "retrieval": {
        "semantic_weight": 0.4,
        "keyword_weight": 0.3,
        "citation_graph_weight": 0.3,
        "reranker": "cross-encoder/ms-marco-MiniLM-L-6-v2",
    },
    "verification": {
        "enabled": True,
        "deep_verify": False,
        "sources": ["semantic_scholar", "openalex", "crossref"],
    },
    "latency": {
        "evidence_timeout_ms": 5000,
        "similar_papers_timeout_ms": 5000,
        "verification_timeout_ms": 3000,
    },
}
```

---

## Sources

### RAG Frameworks
- LlamaIndex — https://github.com/run-llama/llama_index
- LangChain — https://github.com/langchain-ai/langchain
- Haystack — https://github.com/deepset-ai/haystack
- OpenScholar — https://github.com/AkariAsai/OpenScholar

### Academic APIs
- Semantic Scholar — https://api.semanticscholar.org/graph/v1
- arXiv — https://arxiv.org/api/query
- PubMed E-utilities — https://eutils.ncbi.nlm.nih.gov/entrez/eutils/
- CORE — https://api.core.ac.uk/v3
- OpenAlex — https://api.openalex.org
- Unpaywall — https://api.unpaywall.org/v2

### Vector Databases
- Qdrant — https://github.com/qdrant/qdrant
- ChromaDB — https://github.com/chroma-core/chroma
- FAISS — https://github.com/facebookresearch/faiss

### Embedding Models
- BGE-M3 — https://huggingface.co/BAAI/bge-m3
- NV-Embed-v2 — https://huggingface.co/NVIDIA/NV-Embed-v2
- E5-Large-v2 — https://huggingface.co/intfloat/e5-large-v2

### Citation Verification
- ValiRef — https://github.com/gianthard-cyh/valiref
- BibSleuth — https://github.com/yy/bibsleuth
- RefChecker — https://github.com/ziwenzu/refchecker

### Reference Tools
- Scite — https://scite.ai (1B+ citation classifications)
- Consensus — https://consensus.app (220M+ papers)
- Research Rabbit — https://www.researchrabbit.ai (310M+ articles)
- Elicit — https://elicit.com (125M+ papers, PRISMA-compliant)
