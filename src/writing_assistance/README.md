# Writing Assistance Module

Synonym lookup, definition lookup, text rewording, grammar checking, and context-aware paraphrasing for the Research Aid Desktop Assistant. Each feature follows the same pipeline: receive selected text, process algorithmically, return structured results for overlay display, and inject the user's chosen result back into the editor.

## Module Structure

```
writing_assistance/
├── __init__.py
├── synonym_finder.py       # Synonym/antonym lookup
├── definition_finder.py    # Word definitions, phonetics
├── paraphraser.py          # Text rewording/paraphrasing
├── grammar_checker.py      # Grammar, spelling, style
├── context_processor.py    # Context-aware rewording wrapper
├── models.py               # Data models
└── config.py               # Configuration and defaults
```

## 1. Function Signatures

### `find_synonyms`

```python
def find_synonyms(
    word: str,
    part_of_speech: str | None = None,       # "noun", "verb", "adjective", "adverb"
    max_results: int = 10,
    include_antonyms: bool = False,
    context_text: str | None = None,          # for LLM filtering
    use_llm_filter: bool = False,
    offline_only: bool = False
) -> dict:
    """
    Returns:
        synonyms: list[dict]         # [{"word": str, "score": float, "source": str}]
        antonyms: list[dict]
        related_words: list[dict]    # hypernyms, hyponyms, triggers
        part_of_speech: str
        confidence: float            # 0.0-1.0, source agreement
        sources: list[str]           # ["datamuse", "wordnet"]
    """
```

### `find_definition`

```python
def find_definition(
    word: str,
    include_examples: bool = True,
    include_pronunciation: bool = True,
    max_definitions: int = 5,
    part_of_speech: str | None = None,
    use_llm_expansion: bool = False
) -> dict:
    """
    Returns:
        definitions: list[dict]      # [{"text": str, "pos": str, "examples": list[str]}]
        phonetics: dict              # {"ipa": str, "text": str}
        audio_url: str | None
        examples: list[str]
        word_forms: list[str]
        synonyms: list[str]
        antonyms: list[str]
        source: str
    """
```

### `reword_text`

```python
def reword_text(
    text: str,
    context_before: str | None = None,
    context_after: str | None = None,
    num_variants: int = 3,
    style: str = "academic",                  # "academic", "casual", "formal", "concise"
    preserve_technical: bool = True,
    use_llm_refinement: bool = True,
    max_length: int | None = None,
    preserve_structure: bool = True
) -> dict:
    """
    Returns:
        variants: list[dict]        # [{"text": str, "score": float, "changes": list[str]}]
        original_text: str
        style_applied: str
        word_count_change: dict     # {"original": int, "variants": list[int]}
    """
```

### `check_grammar`

```python
def check_grammar(
    text: str,
    language: str = "en",
    check_style: bool = True,
    style_guide: str = "academic",            # "academic", "apa", "chicago", "plain"
    max_suggestions: int = 3,
    include_typos: bool = True,
    check_punctuation: bool = True,
    check_readability: bool = False
) -> dict:
    """
    Returns:
        corrections: list[dict]     # [{"offset": int, "length": int, "message": str,
                                    #   "replacements": list[str], "rule": str}]
        style_suggestions: list[dict]
        overall_score: float        # 0.0-1.0
        issues_count: dict          # {"grammar": int, "style": int, "typo": int}
    """
```

### `process_context_reword`

```python
def process_context_reword(
    selected_text: str,
    context_before: str = "",
    context_after: str = "",
    num_variants: int = 3,
    style: str = "academic",
    preserve_technical: bool = True
) -> dict:
    """
    Wraps reword_text with context-awareness. Prepends context to T5 prompt
    and uses LLM refinement for coherence with surrounding text.

    Returns:
        variants: list[dict]        # [{"text": str, "coherence_score": float}]
        original_text: str
        context_used: dict
    """
```

## 2. Potential Solutions

### Synonym Lookup

| Solution | License | Offline | Notes |
|----------|---------|---------|-------|
| **Datamuse API** | Free (no key) | No | REST API, rich relationships (syn, ant, trigger, hypernym). |
| **WordNet via NLTK** | Apache-2.0 | Yes | Full synset hierarchy. `nltk.download('wordnet')` required. |
| **PyDictionary** | MIT | Partial | Wraps WordNet but uses web scraping. Fragile. |
| **Datamuse + WordNet** | Mixed | Fallback | **Recommended.** Online primary, offline fallback. |
| **LLM contextual filter** | Depends | No | Ollama ranks by contextual fit. |

### Definition Lookup

| Solution | License | Offline | Notes |
|----------|---------|---------|-------|
| **FreeDictionary API** | MIT | No | Wiktionary-based, 700k+ definitions, phonetics, audio. |
| **WordNet via NLTK** | Apache-2.0 | Yes | Definitions via synsets. No audio pronunciation. |
| **NLTK + Flask** | Apache-2.0 | Yes | REST wrapper around WordNet. Requires running a server. |
| **Wiktionary scraper** | CC BY-SA | Yes | Full offline from dumps. Periodic updates needed. |

**Recommended:** FreeDictionary API (primary) + WordNet (offline fallback).

### Paraphrasing

| Solution | License | Size | Notes |
|----------|---------|------|-------|
| **T5_Paraphrase_Paws** | MIT | ~500MB | Google PAWS trained. Beam search. 4-line inference. |
| **PEGASUS Paraphraser** | Apache-2.0 | ~1.6GB | Higher quality, larger model. |
| **PracticalParaphrase** | MIT | Varies | Multi-strategy. Complex API. |
| **Humanizer** | MIT | ~1GB | Multi-model + AI detection. Overkill. |
| **LLM rewording (Ollama)** | Depends | Varies | Best quality, slowest (~2-5s). |
| **T5 + LLM refinement** | Mixed | ~500MB | **Recommended.** T5 candidates, LLM coherence filter. |

### Grammar Checking

| Solution | License | Size | Notes |
|----------|---------|------|-------|
| **LanguageTool** | LGPL-2.1 | ~2GB | Full grammar, 30+ languages. Premium paywalled. |
| **Vale** | MIT | ~5MB | Style linter only. No grammar correction. |
| **textlint** | MIT | ~50MB | Pluggable JS linter. MCP server available. |
| **LanguageTool + Vale** | Mixed | ~2GB | **Recommended.** LanguageTool grammar, Vale style. |

## 3. Alternatives and Issues

### Context-Aware Rewording

T5 generates paraphrases in isolation. Approaches:

1. **Prompt prepending** — Prepend context to T5 input. Simplest.
2. **LLM refinement** (recommended) — T5 candidates, LLM coherence filter. +1-3s latency.
3. **Fine-tuned model** — Train T5 on PAWSX. Best quality, needs training infra.

### T5 Model Limitations

- **No context window.** One sentence only. Inputs >512 tokens truncated.
- **Fixed style.** Paraphrase detection, not style transfer.
- **Beam search tradeoff.** Higher `num_beams` = better quality, more latency.

### LLM Refinement Tradeoffs

| Approach | Latency | Quality | Use Case |
|----------|---------|---------|----------|
| T5 only | <500ms | Good | Fast paraphrasing, no context needed |
| T5 + LLM filter | 1-3s | Better | Context-aware paraphrasing |
| LLM only | 2-5s | Best | High-quality rewording, style transfer |

### Offline vs Online

| Feature | Online | Offline | Strategy |
|---------|--------|---------|----------|
| Synonyms | Datamuse | WordNet | Auto-fallback on network error |
| Definitions | FreeDictionary | WordNet | Cache last 1000 lookups |
| Paraphrasing | N/A | T5 model | Always offline |
| Grammar | LT Online | LT Local | Self-hosted server |

### Style Guide Enforcement

Vale handles style rules (academic, APA, Chicago, plain) via YAML rule sets. LanguageTool handles grammar. They complement each other.

## 4. Sources

| Tool | URL | License |
|------|-----|---------|
| Datamuse API | https://www.datamuse.com/api/ | Free |
| NLTK WordNet | https://github.com/nltk/nltk | Apache-2.0 |
| FreeDictionary | https://api.dictionaryapi.dev/ | MIT |
| FreeDictionary (GH) | https://github.com/ngocsangyem/freedictionaryapi | MIT |
| PyDictionary | https://github.com/geekpradd/PyDictionary | MIT |
| T5_Paraphrase_Paws | https://github.com/Vamsi995/Paraphrase-Generator | MIT |
| PEGASUS Paraphraser | https://huggingface.co/tuner007/pegasus_paraphrase | Apache-2.0 |
| PracticalParaphrase | https://github.com/PrithivirajDamodaran/Paraphrase_Sentence_Pairs | MIT |
| Humanizer | https://github.com/vardhin/Humanizer | MIT |
| Google PAWS | https://github.com/google-research-datasets/paws | CC BY 4.0 |
| LanguageTool | https://github.com/languagetool-org/languagetool | LGPL-2.1 |
| Vale | https://github.com/errata-ai/vale | MIT |
| textlint | https://github.com/textlint/textlint | MIT |

## 5. Configuration

Defaults in `config.py`. Key settings: `primary_source`, `offline_only`, `use_llm_filter`, `num_beams`, `style_guide`, `lt_server_url`.

## 6. Usage Examples

```python
from writing_assistance import find_synonyms, find_definition, reword_text, check_grammar

result = find_synonyms("ubiquitous", part_of_speech="adjective")
result = find_definition("ephemeral", include_examples=True)
result = reword_text("The results demonstrate a significant correlation.",
    context_before="In our analysis of 500 participants,", num_variants=3)
result = check_grammar("Their is many factors to considers.", style_guide="academic")
# result["overall_score"] → 0.42
```
