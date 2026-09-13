# Evidence Engine Documentation

## Module Overview
`evidence_engine` retrieves papers from federated academic sources (Europe PMC, OpenAlex, CORE), extracts discussion/conclusion sections, and uses an LLM via OpenRouter to classify which sentences support a given claim.

## File Structure
- `models.py`: Frozen dataclasses (`PaperRef`, `RetrievalResult`, `EvidenceItem`, `EvidenceResult`).
- `evidence_pipeline.py`: Federated retrieval adapters, full-text section extraction, OpenRouter LLM judging, disk cache, cool-down state machine, and pipeline orchestration.
- `tests/test_evidence_pipeline.py`: Offline unit tests (27 tests) covering queries, normalizers, dedup, cache, cool-down, section extraction, and end-to-end pipeline with monkeypatched adapters.

## API Reference

### `retrieve_papers(claim: str, per_source_limit: int = 100, deadline_s: float = 8.0) -> RetrievalResult`
Fans out to Europe PMC, OpenAlex, and CORE in parallel; returns deduplicated papers with per-source status. Never raises.
- **`claim`**: Text to search for evidence (10-200 chars recommended).
- **`per_source_limit`**: Max papers per source adapter.
- **`deadline_s`**: Hard deadline in seconds.
- **Returns**: `RetrievalResult(papers, sources, wall_ms)`.

### `find_evidence(claim: str, per_source_limit: int = 100, retrieval_deadline_s: float = 8.0, top_n: int = 10) -> EvidenceResult`
Full pipeline: retrieve papers, extract discussion/conclusion sentences from full-text, judge with LLM, return top N evidence items.
- **`claim`**: Assertive sentence to find supporting evidence for.
- **`top_n`**: Number of top evidence items to return.
- **Returns**: `EvidenceResult(claim, items, total_papers, total_sentences, wall_ms)`.

### `find_evidence_sync(claim: str, **kwargs) -> EvidenceResult`
Synchronous wrapper around `find_evidence`.

### `build_queries(claim: str) -> list[str]`
Returns two query variants: keyword (stopword-free) and natural-language claim.

### `dedupe_papers(papers: list[PaperRef]) -> list[PaperRef]`
Collapses duplicates by DOI first, normalized title+year fallback.

## Usage Example

```python
from evidence_engine import find_evidence_sync

result = find_evidence_sync(
    "MLP is a strong choice for learning-based inverse kinematics"
)

print(result.summary())
for item in result.items:
    print(f"[{item.confidence:.2f}] {item.quote[:100]}...")
    print(f"  Paper: {item.paper.title}")
    print(f"  Source: {item.paper.url}")
```

## Environment Variables
| Variable | Required | Purpose |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | OpenRouter LLM API key for sentence judging |
| `CORE_API_KEY` | Yes | CORE API key for open-access paper retrieval |
| `OPENALEX_API_KEY` | No | OpenAlex API key (raises free-tier limit) |

## Running Tests
```bash
PYTHONPATH=src python -m pytest evidence_engine/tests/test_evidence_pipeline.py -v
```
