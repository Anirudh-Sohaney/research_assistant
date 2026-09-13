# Text Reword Documentation

## Module Overview
`text_reword` rewrites highlighted sentences and paragraphs exclusively through OpenRouter's Nemotron model (`nvidia/nemotron-3-ultra-550b-a55b:free` by default) to improve academic tone, add detail, or simplify language while shielding citations and math expressions. The interactive Alt+P popup exposes these three modes and previews the generated replacement before injection. There is no hard-coded local rewrite fallback: unavailable, invalid, or unchanged model output is reported and can be retried with `R`.

## File Structure
- `models.py`: Data classes (`RewordStyle`, `SurroundingContext`, `EntityMaskReport`, `RewordResult`).
- `reword.py`: Entity masking/unmasking, prompt assembly, token budgeting, and OpenRouter response parsing.
- `tests/test_text_reword.py`: Unit test suite testing citation shielding, math protection, unavailable-service handling, and LLM output parsing.

## API Reference

### `reword_text_segment(selected_text: str, context: Optional[SurroundingContext] = None, style: RewordStyle = RewordStyle.ACADEMIC_FORMAL, bypass_cache: bool = False) -> RewordResult`
Rewords the selected text under the requested academic style profile.
- **`selected_text`**: Raw highlighted text in editor.
- **`context`**: Optional surrounding sentence context (`preceding_sentence`, `following_sentence`).
- **`style`**: `RewordStyle` enum (`ACADEMIC_FORMAL`, `CONCISE_FLOW`, `SIMPLIFIED_CLARITY`, `EXPANDED_ARGUMENT`). Sentence and paragraph budgets are 700 and 900 completion tokens respectively so Nemotron can finish its response after internal reasoning. Set `OPENROUTER_REWORD_MODEL` to select another OpenRouter model.
- **Interactive modes**: `ACADEMIC_FORMAL` fully rewrites and restructures the wording while preserving the idea; `EXPANDED_ARGUMENT` keeps the original progression recognizable while adding useful detail; `SIMPLIFIED_CLARITY` preserves the ideas while using simpler words and constructions. `bypass_cache=True` forces a fresh generation for popup regeneration with `R`.
- **Returns**: `RewordResult(primary_replacement, alternative_variants, tokens_used, style_applied, cached)`.

### `mask_scholarly_entities(raw_text: str) -> EntityMaskReport`
Replaces citations and LaTeX formulas with atomic tokens (`__CITE_0__`, `__MATH_0__`).

### `restore_scholarly_entities(masked_text: str, mask_map: Dict[str, str]) -> str`
Re-inserts original citations and formulas into transformed text.

## Usage Example

```python
import asyncio
from text_reword import reword_text_segment, RewordStyle

async def main():
    text = "We need to look into a lot of options (Smith et al., 2021) to make sure this works."
    result = await reword_text_segment(text, style=RewordStyle.ACADEMIC_FORMAL)
    
    print(f"Original: {text}")
    print(f"Reworded: {result.primary_replacement}")
    print(f"Tokens used: {result.tokens_used}")

asyncio.run(main())
```

## Running Tests
```bash
python -m pytest text_reword/tests/test_text_reword.py -v
```
