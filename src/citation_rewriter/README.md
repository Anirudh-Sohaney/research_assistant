# citation_rewriter — Citation Context Analysis & Rewriting

Analyzes citation context in academic text, detects misrepresentations, verifies citations against source papers, and suggests accurate rewrites. Ensures citations faithfully represent the original work they reference.

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
from citation_rewriter import analyze_citation_context, extract_citations

# Analyze citation context in a text
result = analyze_citation_context(
    text="Smith et al. (2020) showed that quantum entanglement enables faster-than-light communication, contradicting relativity.",
    citation_format="auto",
    verify_against_source=True,
    suggest_rewrites=True,
    max_suggestions=3,
)

print(result["citations_found"])         # Detected citations
print(result["misrepresentations"])      # Misrepresented citations
print(result["rewrites"])               # Suggested corrections
print(result["overall_accuracy"])       # 0.0 - 1.0 accuracy score

# Extract citations without analysis
citations = extract_citations(
    text="As shown by Jones (2019) and Lee & Park (2021), this effect is well-documented.",
    formats=["apa", "mla"],
)

for c in citations:
    print(f"{c['citation_key']}: {c['format']} at position {c['position_start']}")
```

---

## API Reference

### `analyze_citation_context`

```python
def analyze_citation_context(
    text: str,
    citation_format: str = "auto",                    # "auto", "apa", "mla", "chicago", "bibtex", "ieee", "vancouver"
    verify_against_source: bool = True,
    suggest_rewrites: bool = True,
    max_suggestions: int = 3,
    verification_sources: list[str] | None = None,    # ["semantic_scholar", "crossref", "openalex"]
    style: str = "academic",                          # "academic", "formal", "concise", "plain"
    llm_provider: str = "ollama",
    llm_model: str = "llama3.2",
    timeout_ms: int = 10000,
) -> dict:
    """
    Analyze citation context in text, detect misrepresentations, and suggest rewrites.

    Returns:
        {
            "citations_found": list[CitationResult],
            "citation_contexts": list[CitationContext],
            "misrepresentations": list[Misrepresentation],
            "rewrites": list[RewriteSuggestion],
            "verification_results": list[VerificationResult],
            "overall_accuracy": float,              # 0.0 - 1.0
            "accuracy_breakdown": {
                "total_citations": int,
                "verified": int,
                "misrepresented": int,
                "unverifiable": int,
            },
            "processing_time_ms": float,
            "warnings": list[str],
        }

    CitationResult:
        {
            "citation_key": str,
            "citation_text": str,
            "format": str,
            "position_start": int,
            "position_end": int,
            "raw_citation": str,
            "authors": list[str],
            "year": int | None,
            "title": str | None,
            "doi": str | None,
            "paper_id": str | None,
        }

    CitationContext:
        {
            "citation_key": str,
            "surrounding_text": str,
            "claimed_assertion": str,
            "assertion_type": str,                    # "finding", "method", "statistic", "definition", "opinion"
            "confidence": float,
        }

    Misrepresentation:
        {
            "citation_key": str,
            "misrepresentation_type": str,           # "overclaim", "underclaim", "contradiction", "fabrication", "misattribution"
            "severity": str,                         # "low", "medium", "high", "critical"
            "original_claim": str,
            "actual_claims": list[str],
            "explanation": str,
            "confidence": float,
        }

    RewriteSuggestion:
        {
            "citation_key": str,
            "original_context": str,
            "rewritten_context": str,
            "changes_made": list[str],
            "confidence": float,
            "alternative_rewrites": list[str],
            "style_applied": str,
        }

    VerificationResult:
        {
            "citation_key": str,
            "is_accurate": bool,
            "accuracy_score": float,
            "source_exists": bool,
            "actual_claims": list[str],
            "claimed_vs_actual": dict,
            "discrepancy_type": str | None,
            "suggested_correction": str | None,
            "verification_source": str,
            "paper_id": str | None,
            "verification_time_ms": float,
        }
    """
```

### `extract_citations`

```python
def extract_citations(
    text: str,
    formats: list[str] | None = None,                # ["apa", "mla", "chicago", "bibtex", "ieee", "vancouver"]
    include_context: bool = False,
    context_window: int = 200,                       # Characters before/after citation
    detect_inline: bool = True,                      # Detect (Author, Year) style
    detect_footnotes: bool = True,                   # Detect footnote-style citations
    resolve_references: bool = False,                # Attempt to resolve to paper_id
    timeout_ms: int = 5000,
) -> list[dict]:
    """
    Extract citations from text using pattern matching.

    Returns list of dicts:
        {
            "citation_key": str,
            "citation_text": str,
            "format": str,
            "position_start": int,
            "position_end": int,
            "raw_citation": str,
            "authors": list[str],
            "year": int | None,
            "title": str | None,
            "doi": str | None,
            "paper_id": str | None,
            "context_before": str | None,            # If include_context=True
            "context_after": str | None,
            "citation_type": str,                    # "inline", "footnote", "parenthetical"
            "confidence": float,
        }
    """
```

### `verify_citation_accuracy`

```python
def verify_citation_accuracy(
    citation: dict,
    claimed_context: str,
    source_paper_id: str | None = None,
    verification_sources: list[str] | None = None,
    deep_verify: bool = True,                        # Check semantic match, not just existence
    fetch_abstract: bool = True,
    timeout_ms: int = 5000,
) -> dict:
    """
    Verify a citation against source databases.

    Returns:
        {
            "is_accurate": bool,
            "accuracy_score": float,                  # 0.0 - 1.0
            "source_exists": bool,
            "actual_claims": list[str],
            "claimed_vs_actual": {
                "claimed": str,
                "actual": list[str],
                "match_type": str,                    # "exact", "partial", "contradicts", "not_found"
                "semantic_similarity": float,
            },
            "discrepancy_type": str | None,           # "fabrication", "misattribution", "overclaim", "underclaim", "none"
            "suggested_correction": str | None,
            "verification_source": str,
            "paper_id": str | None,
            "paper_title": str | None,
            "paper_abstract": str | None,
            "verification_time_ms": float,
            "warnings": list[str],
        }
    """
```

### `rewrite_citation_context`

```python
def rewrite_citation_context(
    citation: dict,
    original_context: str,
    actual_claims: list[str],
    style: str = "academic",                         # "academic", "formal", "concise", "plain"
    max_suggestions: int = 3,
    preserve_citation_format: bool = True,
    llm_provider: str = "ollama",
    llm_model: str = "llama3.2",
    timeout_ms: int = 5000,
) -> dict:
    """
    Rewrite citation context to accurately represent the source.

    Returns:
        {
            "rewritten_context": str,
            "changes_made": list[str],
            "confidence": float,
            "alternative_rewrites": list[str],
            "style_applied": str,
            "processing_time_ms": float,
        }
    """
```

### `detect_misrepresentation`

```python
def detect_misrepresentation(
    citation: dict,
    claimed_context: str,
    source_claims: list[str] | None = None,
    detection_threshold: float = 0.7,
    llm_provider: str = "ollama",
    llm_model: str = "llama3.2",
    timeout_ms: int = 5000,
) -> dict:
    """
    Detect if a citation misrepresents its source.

    Returns:
        {
            "is_misrepresented": bool,
            "misrepresentation_type": str | None,    # "overclaim", "underclaim", "contradiction", "fabrication", "misattribution"
            "severity": str,                         # "low", "medium", "high", "critical"
            "original_claim": str,
            "actual_claims": list[str],
            "explanation": str,
            "confidence": float,
            "suggested_corrections": list[str],
        }
    """
```

### `batch_analyze`

```python
def batch_analyze(
    texts: list[str],
    citation_format: str = "auto",
    verify_against_source: bool = True,
    suggest_rewrites: bool = True,
    max_suggestions: int = 3,
    parallel: bool = True,
    max_workers: int = 4,
    timeout_ms: int = 30000,
) -> list[dict]:
    """
    Analyze multiple texts for citation accuracy.

    Returns list of result dicts (same structure as analyze_citation_context).
    """
```

---

## Architecture

```
Input text with citations
        |
        v
┌─────────────────────────────────────┐
│    citation_extractor.py            │
│  Regex patterns + NER for citations │
│  APA, MLA, Chicago, BibTeX, IEEE   │
│  Output: structured citation list  │
└─────────────────────────────────────┘
        |
        v
┌─────────────────────────────────────┐
│    context_analyzer.py              │
│  Extract surrounding context       │
│  Classify assertion type           │
│  Identify claimed assertions       │
└─────────────────────────────────────┘
        |
        v
┌─────────────────────────────────────┐
│    accuracy_verifier.py             │
│  Semantic Scholar / CrossRef / OA   │
│  Fetch actual paper claims         │
│  Compare claimed vs actual         │
│  Detect misrepresentations         │
└─────────────────────────────────────┘
        |
        v
┌─────────────────────────────────────┐
│    rewriter.py                      │
│  LLM-based context rewriting       │
│  Style-preserving corrections      │
│  Multiple suggestions per citation │
└─────────────────────────────────────┘
        |
        v
    Result dict
    (citations_found, misrepresentations,
     rewrites, overall_accuracy)
```

---

## Component Solutions

### Citation Extraction

| Solution | License | Accuracy | Strengths | Weaknesses |
|----------|---------|----------|-----------|------------|
| **Regex patterns (custom)** | — | ~95% (structured) | Zero dependencies, fast, full control | Brittle for edge cases, no semantic understanding |
| **citation-parser** | MIT | High | npm package, supports APA/MLA/Chicago | JavaScript only, no Python integration |
| **pybtex** | BSD | High | Python BibTeX parser, extensible | BibTeX only, no inline citation detection |
| **GROBID** | Apache-2.0 | 95%+ | ML-based PDF parsing, TEI output | Heavy dependency, slower than regex |
| **Science Parse** | Apache-2.0 | 92% | Java, good for PDF metadata extraction | JVM required, not pure Python |

**Recommendation:** Custom regex for inline citations (fast, zero deps). pybtex for BibTeX files. GROBID for PDF parsing if needed.

### Verification Sources

| Source | Coverage | Rate Limit | Strengths | Weaknesses |
|--------|----------|------------|-----------|------------|
| **Semantic Scholar API** | 200M+ papers | 1 req/sec | Citation graphs, TL;DR, SPECTER2 embeddings | Rate limited without key |
| **CrossRef API** | 150M+ records | 50 req/sec | DOI resolution, metadata, ORCID | No full-text access |
| **OpenAlex** | ~480M works | 10 req/sec | Broadest coverage, free bulk snapshots | Newer, less established |
| **DBLP** | 6M+ publications | Unlimited | Computer science focused, clean metadata | CS only |
| **PubMed** | 40M+ biomedical | 3-10 req/sec | Biomedical authority, MeSH indexing | Biomedical only |

**Recommendation:** Semantic Scholar as primary (citation graphs + verification). CrossRef for DOI resolution. OpenAlex for broad coverage.

### NLP for Context Analysis

| Tool | License | Strengths | Weaknesses |
|------|---------|-----------|------------|
| **spaCy** | MIT | Fast NER, dependency parsing, production-ready | Larger models, less customizable |
| **NLTK** | Apache-2.0 | Tokenization, POS tagging, educational | Slower, less modern |
| **transformers (Hugging Face)** | Apache-2.0 | State-of-the-art NER, zero-shot classification | GPU recommended, slower inference |
| **Stanza** | Apache-2.0 | Stanford NLP, accurate parsing | Slower than spaCy |

**Recommendation:** spaCy for NER and dependency parsing (fast, accurate). Hugging Face transformers for zero-shot assertion classification.

### LLM for Rewriting

| Solution | Cost | Privacy | Quality | Latency |
|----------|------|---------|---------|---------|
| **OpenAI GPT-4o** | $0.005/1K tokens | Cloud | Excellent | 200-500ms |
| **Claude 3.5 Sonnet** | $0.003/1K tokens | Cloud | Excellent | 300-600ms |
| **Ollama (Llama 3.2)** | Free | Local | Good | 100-300ms |
| **Ollama (Mistral)** | Free | Local | Good | 150-400ms |
| **llama.cpp (quantized)** | Free | Local | Fair | 50-200ms |

**Recommendation:** Ollama for privacy-first local rewriting. OpenAI/Claude for highest quality when privacy is less critical.

### Citation Style Support

| Style | Edition | Regex Complexity | Common Use |
|-------|---------|------------------|------------|
| **APA** | 7th | Medium | Psychology, social sciences |
| **MLA** | 9th | Medium | Humanities, literature |
| **Chicago** | 17th | High (two systems) | History, publishing |
| **IEEE** | — | Low | Engineering, CS |
| **Vancouver** | — | Low | Medical sciences |
| **BibTeX** | — | Low (structured) | LaTeX documents |

**Recommendation:** Start with APA and BibTeX (most common in academic CS). Add MLA and Chicago based on user demand.

### Reference Verification Tools

| Tool | License | Accuracy | Capabilities |
|------|---------|----------|--------------|
| **ValiRef** | MIT | 88.1% | Detects fabrication, attribution errors, counterfactual citations |
| **BibSleuth** | MIT | — | Checks 6 databases, suggests papers for uncited claims |
| **RefChecker** | MIT | — | Bulk verification, Semantic Scholar + OpenAlex + CrossRef |
| **Scite (API)** | Commercial | — | 1B+ citation classifications (supporting/contradicting) |

**Recommendation:** ValiRef for standalone verification. RefChecker for bulk checking. Scite API for citation intent classification if budget allows.

---

## Alternatives and Issues

### Citation Format Detection Challenges

Citations vary wildly across documents:

- **Mixed formats:** Single paper may use APA inline, Chicago footnotes, and BibTeX in appendices
- **Partial citations:** "(Smith, 2020)" vs "Smith et al. (2020)" vs "Smith and Jones (2020)"
- **Non-standard formatting:** Author names with diacritics, institutional authors, "ibid." references
- **In-text variations:** "recently" vs "(2020)" vs "in a 2020 study"

**Mitigations:**
1. Multi-pass extraction with format-specific regex patterns
2. Fallback to generic patterns for unrecognized formats
3. Allow manual format specification when auto-detection fails

### Partial Citation Matching

Citations may not match source papers exactly:

- **Abbreviated names:** "Smith et al." may refer to different Smith papers
- **Year ambiguity:** Multiple papers by same author in same year
- **Missing information:** No DOI, no page numbers, informal references
- **Paraphrased titles:** Title doesn't match database exactly

**Mitigations:**
1. Fuzzy matching with Levenshtein distance
2. Author + year + title similarity scoring
3. Semantic Scholar paper ID resolution when possible

### Multi-Source Verification Conflicts

Different databases may return conflicting information:

- **Metadata inconsistencies:** Different author lists, titles, years across databases
- **Version differences:** Preprint vs published version have different claims
- **Retraction lag:** Some databases don't flag retractions immediately
- **Coverage gaps:** Niche papers may only exist in one database

**Mitigations:**
1. Confidence-weighted voting across sources
2. Prefer Semantic Scholar for citation graphs, CrossRef for metadata
3. Flag unverifiable citations rather than guessing

### Style Guide Differences

Citation style rules vary significantly:

- **Author formatting:** "Smith" vs "Smith, J." vs "John Smith"
- **Year placement:** "(2020)" vs "2020" vs "(Smith 2020)"
- **Multiple authors:** "et al." threshold (3+ for APA, 4+ for MLA)
- **Capitalization:** Sentence case vs title case for references

**Mitigations:**
1. Style-specific formatting functions
2. Preserve original style when rewriting context
3. Allow user to specify target style

### Handling Preprints and Working Papers

Preprints and working papers present unique challenges:

- **Version instability:** ArXiv v1, v2, v3 may have different claims
- **No peer review:** Claims may be preliminary or incorrect
- **Citation etiquette:** Some journals discourage citing preprints
- **Cross-version linking:** ArXiv IDs vs DOIs vs published versions

**Mitigations:**
1. Track paper version when possible
2. Flag preprint citations for user review
3. Prefer published versions for verification

### LLM Hallucination in Rewrites

LLMs may introduce inaccuracies when rewriting:

- **Added claims:** LLM adds information not in original text
- **Removed nuance:** Oversimplifies complex findings
- **Style drift:** Rewritten context doesn't match paper's tone
- **Citation format errors:** Incorrectly formats citation references

**Mitigations:**
1. Constrained generation with source paper claims
2. Post-rewrite verification against source
3. Conservative rewriting (minimal changes)
4. Confidence scoring for each rewrite

---

## Codebase Structure

```
citation_rewriter/
├── __init__.py                 # Public API exports
├── citation_extractor.py       # Citation pattern matching (APA, MLA, Chicago, BibTeX)
├── context_analyzer.py         # Citation context extraction and analysis
├── accuracy_verifier.py        # Verification against academic databases
├── rewriter.py                 # Citation context rewriting with LLM
├── format_handler.py           # Multi-format citation handling and formatting
├── models.py                   # Data models (Citation, VerificationResult, etc.)
└── config.py                   # Configuration (API keys, thresholds, styles)
```

### Module Responsibilities

| Module | Responsibility | Key Dependencies |
|--------|---------------|-----------------|
| `citation_extractor.py` | Regex-based citation detection and parsing | re, spacy (optional NER) |
| `context_analyzer.py` | Extract surrounding text, classify assertions | spacy, transformers (zero-shot) |
| `accuracy_verifier.py` | Verify citations against Semantic Scholar, CrossRef, OpenAlex | httpx, semantic_scholar, crossref |
| `rewriter.py` | LLM-based context rewriting with style preservation | ollama, openai, anthropic |
| `format_handler.py` | Citation formatting and style conversion | pybtex (BibTeX) |
| `models.py` | Pydantic data models for type safety | pydantic |
| `config.py` | Configuration management | pydantic-settings |

---

## Configuration

```python
# config.py
CITATION_REWRITER_CONFIG = {
    "extraction": {
        "formats": ["apa", "mla", "chicago", "bibtex", "ieee", "vancouver"],
        "auto_detect": True,
        "include_context": True,
        "context_window": 200,
        "min_confidence": 0.6,
    },
    "verification": {
        "sources": ["semantic_scholar", "crossref", "openalex"],
        "deep_verify": True,
        "fetch_abstract": True,
        "timeout_ms": 5000,
    },
    "semantic_scholar": {
        "api_key": None,  # Set via env: SEMANTIC_SCHOLAR_API_KEY
        "rate_limit_per_sec": 1,
    },
    "crossref": {
        "email": None,  # Set via env: CROSSREF_EMAIL
        "rate_limit_per_sec": 50,
    },
    "openalex": {
        "email": None,  # Set via env: OPENALEX_EMAIL
        "rate_limit_per_sec": 10,
    },
    "rewriting": {
        "provider": "ollama",
        "model": "llama3.2",
        "api_url": "http://localhost:11434",
        "temperature": 0.3,
        "max_tokens": 512,
        "style": "academic",
        "max_suggestions": 3,
    },
    "misrepresentation": {
        "detection_threshold": 0.7,
        "severity_levels": {
            "low": 0.3,
            "medium": 0.6,
            "high": 0.8,
            "critical": 0.95,
        },
    },
    "batch": {
        "max_workers": 4,
        "timeout_ms": 30000,
    },
}
```

---

## Sources

### Citation Tools
- pybtex — https://github.com/scikit-hep/pybtex
- citation-parser — https://www.npmjs.com/package/citation-parser
- GROBID — https://github.com/kermitt2/grobid
- Science Parse — https://github.com/allenai/science-parse

### Verification Tools
- ValiRef — https://github.com/gianthard-cyh/valiref
- BibSleuth — https://github.com/yy/bibsleuth
- RefChecker — https://github.com/ziwenzu/refchecker
- Scite — https://scite.ai

### Academic APIs
- Semantic Scholar — https://api.semanticscholar.org/graph/v1
- CrossRef — https://api.crossref.org
- OpenAlex — https://api.openalex.org
- DBLP — https://dblp.org/search/publ/api

### NLP Libraries
- spaCy — https://github.com/explosion/spaCy
- NLTK — https://github.com/nltk/nltk
- Hugging Face transformers — https://github.com/huggingface/transformers
- Stanza — https://github.com/stanfordnlp/stanza

### LLM Providers
- Ollama — https://github.com/ollama/ollama
- OpenAI API — https://platform.openai.com/docs/api-reference
- Anthropic API — https://docs.anthropic.com/claude/reference

### Citation Style Guides
- APA 7th Edition — https://apastyle.apa.org/
- MLA 9th Edition — https://style.mla.org/
- Chicago Manual of Style 17th — https://www.chicagomanualofstyle.org/
- IEEE Reference Guide — https://ieeeauthorcenter.ieee.org/create-your-ieee-article/create-your-article-components/references/
