# Paper Discovery Documentation

## Module Overview
`paper_discovery` searches academic literature databases (Semantic Scholar, OpenAlex) and local indexes to surface peer-reviewed papers relevant to active draft assertions.

## File Structure
- `models.py`: Data classes (`SearchScope`, `TraversalDirection`, `AcademicPaperRecommendation`, `PaperDiscoveryResult`, `LiteratureSynthesis`, `CitationGraphResult`).
- `discovery.py`: Keyphrase extraction, federated API querying, offline matching, BibTeX key formatting, and synthesis drafting.
- `tests/test_paper_discovery.py`: Unit test suite verifying Semantic Scholar parsing, offline fallback, BibTeX key generation, and literature synthesis.

## API Reference

### `discover_similar_papers(seed_text: str, scope: Optional[SearchScope] = None, limit: int = 5) -> PaperDiscoveryResult`
Discovers and ranks candidate papers matching `seed_text`.
- **`seed_text`**: Selected sentence, paragraph, or draft abstract.
- **`scope`**: Filter options (`disciplines`, `min_year`, `open_access_only`).
- **`limit`**: Maximum papers to shortlist.
- **Returns**: `PaperDiscoveryResult(query_summary, papers)`.

### `synthesize_literature_context(seed_text: str, candidate_papers: List[AcademicPaperRecommendation]) -> LiteratureSynthesis`
Generates a synthesised related work paragraph connecting candidate papers to the seed text.

### `traverse_citation_network(seed_paper_id: str, direction: TraversalDirection = TraversalDirection.CITED_BY_OUTWARD, limit: int = 8) -> CitationGraphResult`
Retrieves inward (cited by) or outward (references) citation graphs for a given paper ID.

## Usage Example

```python
import asyncio
from paper_discovery import discover_similar_papers, synthesize_literature_context

async def main():
    claim = "Transformers eliminate recurrent neural networks through self-attention."
    result = await discover_similar_papers(claim, limit=3)
    
    print(f"Discovered {len(result.papers)} papers for query: '{result.query_summary}'")
    for p in result.papers:
        print(f" - [{p.suggested_citation_key}] {p.title} ({p.year}) - {p.citation_count} citations")
    
    synthesis = synthesize_literature_context(claim, result.papers)
    print("\nSynthesis Paragraph:")
    print(synthesis.synthesis_paragraph)

asyncio.run(main())
```

## Running Tests
```bash
python -m pytest paper_discovery/tests/test_paper_discovery.py -v
```
