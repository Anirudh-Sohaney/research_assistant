# Lexical Definitions Documentation

## Module Overview
`lexical_definitions` provides instantaneous, context-aware dictionary definitions and Word Sense Disambiguation (WSD) for words highlighted by authors.

## File Structure
- `models.py`: Data classes (`WordSense`, `WordDefinitionResult`).
- `definitions.py`: Harvester and root-aware WSD ranker implementation with offline academic polysemy lexicons.
- `tests/test_lexical_definitions.py`: Unit test suite testing API harvesting, offline fallbacks, polysemy resolution, and pipeline execution.

## API Reference

### `lookup_contextual_definition(target_word: str, sentence_context: str) -> WordDefinitionResult`
Harvests definitions from FreeDictionary/offline sources and prioritizes the active sense matching `sentence_context`.
- **`target_word`**: The highlighted term.
- **`sentence_context`**: The sentence enclosing the word.
- **Returns**: `WordDefinitionResult(word, phonetic_ipa, audio_url, primary_sense, secondary_senses, disambiguation_confidence, etymology)`.

### `harvest_dictionary_senses(word: str) -> Tuple[str, Optional[str], List[WordSense]]`
Harvests dictionary senses, IPA phonetics, and audio URLs.

### `disambiguate_active_sense(candidate_senses: List[WordSense], target_word: str, sentence: str) -> List[WordSense]`
Re-ranks dictionary senses by root-stem overlap with the enclosing sentence.

## Usage Example

```python
import asyncio
from lexical_definitions import lookup_contextual_definition

async def main():
    sentence = "The paper utilizes mathematical induction to prove theorem 4."
    result = await lookup_contextual_definition("induction", sentence)
    
    print(f"Term: {result.word} {result.phonetic_ipa}")
    if result.primary_sense:
        print(f"Primary Sense [{result.primary_sense.part_of_speech}]: {result.primary_sense.definition}")
        print(f"Confidence: {result.disambiguation_confidence:.2f}")

asyncio.run(main())
```

## Running Tests
```bash
python -m pytest lexical_definitions/tests/test_lexical_definitions.py -v
```
