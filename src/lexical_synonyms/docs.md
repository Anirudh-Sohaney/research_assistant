# Lexical Synonyms Documentation

## Module Overview
`lexical_synonyms` discovers, inflects, and ranks contextually accurate academic synonyms for highlighted words using a simplified dictionary harvesting + spaCy morphological inflection + SentenceTransformer contextual re-ranking pipeline.

## File Structure
- `models.py`: Data classes (`RawCandidate`, `SynonymItem`, `SynonymGroupResult`).
- `synonyms.py`: Harvester and ranker implementation with built-in AWL registry, offline fallback dictionaries, irregular verb tables, spaCy tense aligner, and SentenceTransformer scorer.
- `tests/test_lexical_synonyms.py`: Unit test suite validating harvesting, register scoring, morphological alignment, tense preservation, and full pipeline execution.

## API Reference

### `find_contextual_synonyms(target_word: str, sentence_context: str, limit: int = 12, use_llm: bool = True) -> SynonymGroupResult`
Executes contextual academic synonym discovery. Primary generation uses OpenAI `gpt-5.6-luna` (configurable via `OPENAI_SYNONYM_MODEL`) executed with low reasoning effort (`reasoning_effort="low"`) and fast generation bounds (`max_completion_tokens=120`) using the extracted OAuth bearer credentials from `api_gateway`. Gracefully falls back to local `Qwen2.5-1.5B-Instruct` in `bfloat16` and Datamuse dictionary harvesting + spaCy tense inflection + SentenceTransformer cosine ranking if offline or quota-limited.
- **`target_word`**: The highlighted word.
- **`sentence_context`**: Surrounding sentence string.
- **`limit`**: Maximum ranked synonyms to return (default: 12).
- **`use_llm`**: Whether to query the LLM engine before falling back to dictionary (default: True).
- **Returns**: `SynonymGroupResult(query_word, sentence, ranked_synonyms, antonyms, inference_latency_ms)`.

### `harvest_candidate_synonyms(word: str, lemma: Optional[str] = None, pos: Optional[str] = None) -> List[RawCandidate]`
Harvests raw candidates from Datamuse dictionary API and curated offline academic fallback lexicons:
- **`ml` Tag Validation**: Demands `syn` or `results_type:primary_rel` on means-like queries to exclude loose co-occurrence matches (e.g. `normal` for `objective`).
- **Antonym Suppression**: Deterministically drops polar opposites via `KNOWN_ANTONYMS` (e.g. `subjective` for `objective`).
- **POS Disambiguation**: Employs lemma-based queries for verbs to avoid adjective homographs.

### `inflect_candidate(lemma: str, target_tag: str) -> str`
Inflects candidate lemmas to target tense/number tags (`VBZ`, `VBD`, `VBN`, `VBG`, `NNS`), handling both regular and irregular verbs.

### `rank_candidates_in_context(candidates: List[RawCandidate], target_word: str, sentence: str) -> List[SynonymItem]`
Scores and sorts candidates using sentence-transformer cosine similarity (75%), academic register weighting (20%), and corpus frequency (5%).

## Usage Example

```python
import asyncio
from lexical_synonyms import find_contextual_synonyms

async def main():
    sentence = "In modern distributed systems, network partitions have become ubiquitous."
    result = await find_contextual_synonyms("ubiquitous", sentence, limit=5)
    
    print(f"Top synonyms for '{result.query_word}':")
    for item in result.ranked_synonyms:
        print(f" - {item.word} (score: {item.composite_score:.2f}, pos: {item.part_of_speech})")

asyncio.run(main())
```

## Running Tests
```bash
python -m pytest lexical_synonyms/tests/test_lexical_synonyms.py -v
```
