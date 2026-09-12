# Writing Assistance — Synonyms, Definitions, Paraphrasing, Grammar

## The Problem

The research aid needs to function as a full writing assistant — not just a research tool. The core writing features are: synonym lookup, definition lookup, text rewording/paraphrasing, and grammar checking. All must work locally (or with minimal API calls), trigger via keybinds, and inject results back into the editor.

---

## 1. Synonym Lookup

### Datamuse API (Recommended for Online)

**URL:** https://www.datamuse.com/api/  
**Free:** Yes, no API key required

REST API for word relationships:
- `rel_syn` — synonyms
- `rel_ant` — antonyms
- `rel_trg` — triggers (associated words)
- `rel_rhy` — rhymes
- `rel_hom` — homophones
- `rel_cns` — "consonant match"
- `rel_spc` — "more specific than" (hypernyms)
- `rel_gen` — "more general than" (hyponyms)

**Python client:** `datamuse-python` on PyPI

**Example request:**
```
GET https://api.datamuse.com/words?rel_syn=run
Returns: [{"word":"run","score":2897}, {"word":"run along","score":1921}, ...]
```

**For the research aid:** Ideal for real-time synonym lookup — no API key, fast response, rich relationship data. Can combine with LLM to filter contextually appropriate synonyms.

### WordNet via NLTK (Recommended for Offline)

**GitHub:** https://github.com/nltk/nltk (Apache-2.0)  
**Python:** `from nltk.corpus import wordnet as wn`

Provides synsets, synonyms, antonyms, hypernyms, hyponyms, holonyms, meronyms. Multilingual via Open Multilingual Wordnet. Fully offline after `nltk.download('wordnet')`.

**Example:**
```python
from nltk.corpus import wordnet as wn
synsets = wn.synsets('happy')
synonyms = [lemma.name() for syn in synsets for lemma in syn.lemmas()]
# Returns: ['happy', 'felicitous', 'glad', 'well-chosen', ...]
```

**For the research aid:** Best for fully offline synonym lookup. WordNet's hierarchical structure (hypernyms/hyponyms) is useful for finding more precise or more general terms.

### PyDictionary

**GitHub:** https://github.com/geekpradd/PyDictionary (MIT, 285 stars)

Python module wrapping WordNet for meanings, synonyms, antonyms, translations. Simple API: `dictionary.meaning("word")`, `dictionary.synonym("word")`.

**Limitation:** Depends on web scraping for synonyms/translations; can break.

---

## 2. Definition Lookup

### FreeDictionary API (Recommended)

**URL:** https://api.freedictionary.dev/  
**License:** MIT  
**GitHub:** https://github.com/ngocsangyem/freedictionaryapi (MIT, 23 stars)

Open-source API based on Wiktionary. 700k+ definitions. Returns phonetics, audio pronunciations, definitions, examples, synonyms, antonyms, word forms.

**Example request:**
```
GET https://api.dictionaryapi.dev/api/v2/entries/en/hello
Returns: [{word: "hello", phonetics: [...], meanings: [...]}]
```

### WordNet (Offline)

Same as above — WordNet provides definitions via synsets.

```python
wn.synset('happy.a.01').definition()
# Returns: "enjoying or showing or marked by joy or pleasure"
```

### NLTK WordNet + Flask (Self-Hosted)

**GitHub:** https://github.com/cartertemm/dictionary-api

Flask app wrapping NLTK WordNet with a REST API and CLI. Self-hostable. Returns definitions, synonyms, antonyms, hypernyms/hyponyms.

---

## 3. Text Rewording / Paraphrasing

### T5_Paraphrase_Paws (Recommended)

**GitHub:** https://github.com/Vamsi995/Paraphrase-Generator  
**License:** MIT  
**Stars:** 321

Trained on Google's PAWS dataset. Provides `T5ForConditionalGeneration` via HuggingFace Transformers. Small model (~500MB), local inference.

**Example:**
```python
from transformers import T5ForConditionalGeneration, T5Tokenizer
model = T5ForConditionalGeneration.from_pretrained("Vamsi/T5_Paraphrase_Paws")
tokenizer = T5Tokenizer.from_pretrained("Vamsi/T5_Paraphrase_Paws")

input_text = "paraphrase: The quick brown fox jumps over the lazy dog."
input_ids = tokenizer.encode(input_text, return_tensors="pt", max_length=512)
outputs = model.generate(input_ids, max_length=512, num_beams=5, num_return_sequences=3)
# Returns 3 paraphrased variants
```

**For the research aid:** Can generate multiple paraphrase variants with beam search. User can cycle through different rewords until satisfied. The `num_return_sequences` parameter controls how many variants to generate.

### PEGASUS Paraphraser

**HuggingFace:** tuner007/pegasus_paraphrase  
**Base:** Google Research PEGASUS (Apache-2.0, 1.6k stars)

PEGASUS model fine-tuned specifically for paraphrasing. Uses beam search with length penalty. Originally for summarization but fine-tuned variants handle paraphrasing well.

### PracticalParaphrase (Prithiviraj Damodaran)

Feature-rich paraphrasing framework for augmenting NLU training data. Multiple paraphrase strategies (lexical, syntactic, semantic).

### Humanizer

**GitHub:** https://github.com/vardhin/Humanizer

Multi-model paraphraser using T5, BART, and Pegasus. Includes AI detection capabilities.

**For the research aid:** The T5 approach is recommended because:
1. Model is small (~500MB) — runs locally on any machine
2. MIT license — no restrictions
3. Simple API — 4 lines of inference code
4. Can generate multiple variants — user can cycle through
5. Beam search controls quality vs. diversity tradeoff

---

## 4. Grammar Checking

### LanguageTool (Recommended)

**GitHub:** https://github.com/languagetool-org/languagetool  
**License:** LGPL-2.1 (core)

Full grammar, spelling, punctuation, and style checker. 30+ languages. Runs as local server or HTTP API. Browser extensions, desktop apps, plugins for LibreOffice, Word, Google Docs.

**For the research aid:** Could analyze selected text in real-time, suggest corrections, and the corrected text could be auto-typed back via keyboard simulation. The HTTP API makes integration straightforward.

**Limitation:** Premium features (paraphrasing, advanced style) behind paywall. Server requires Java and significant RAM.

### Vale (Style Linter)

**GitHub:** https://github.com/errata-ai/vale  
**License:** MIT

Markup-aware prose linter. Enforces editorial style guides (Microsoft, Google, etc.) or custom YAML-based rules. Extremely fast (Go-based). Integrates with VS Code, Neovim, Sublime, Zed.

**For the research aid:** Detects style issues on selected text and presents suggestions in popup overlay. Good for enforcing consistent tone.

### textlint

**GitHub:** https://github.com/textlint/textlint  
**License:** MIT

Pluggable natural language linter (ESLint for text). JavaScript/TypeScript ecosystem. Can auto-fix with `--fix`. Can run as MCP server for AI assistant integration.

---

## 5. Context-Aware Rewording (Feature E Detail)

The user's requirement for "reword" is more sophisticated than simple paraphrasing. It needs to:
1. Accept a selected sentence
2. Consider the text before and after for context
3. Generate multiple reworded variants
4. Allow user to cycle through options
5. Inject the chosen variant back into the editor

**Proposed implementation:**

```
User selects sentence S in document D
       |
       v
Extract context: [S_before, S, S_after]
       |
       v
T5_Paraphrase_Paws generates N variants of S
       |
       v
LLM filters/modifies variants for consistency
  with S_before and S_after
       |
       v
Overlay shows variants in list
  [1] variant A
  [2] variant B
  [3] variant C
       |
       v
User picks variant (or presses key to cycle)
       |
       v
Text injection replaces S with chosen variant
```

**Key technical challenge:** Maintaining coherence with surrounding text. The T5 model generates paraphrases without context. To address this:
- Option 1: Prepend context to the paraphrase prompt ("paraphrase this sentence while maintaining consistency with: ...")
- Option 2: Use LLM (local Ollama) to refine T5 output based on context
- Option 3: Fine-tune T5 on context-aware paraphrase datasets

Option 1 is simplest and may work well enough. Option 2 adds latency but improves quality.

---

## Integration with Text Injection

All writing assistance features follow the same injection pattern:
1. User selects text (selection-hook detects)
2. Keybind triggers feature (pynput global hotkey)
3. Feature processes text (synonym/definition/paraphrase/grammar)
4. Overlay shows results (Tauri transparent window)
5. User picks result
6. Text injected into original application (clipboard + paste fallback chain)

This pattern is identical for all features — only the processing step differs. The infrastructure (selection detection, overlay, injection) is shared.
