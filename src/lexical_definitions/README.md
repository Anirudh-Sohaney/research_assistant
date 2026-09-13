# Lexical Definitions Subsystem

## 1. Final Deliverable
A 100% zero-LLM-token contextual dictionary lookup and Word Sense Disambiguation (WSD) engine (`lexical_definitions`) providing:
- Multi-source dictionary harvesting (`harvest_dictionary_senses()`) via FreeDictionary REST API and offline academic lexicons.
- Contextual Word Sense Disambiguation (`disambiguate_active_sense()`) scoring definition glosses against active sentence context.
- End-to-end definition retrieval pipeline (`lookup_contextual_definition()`) returning structured `WordDefinitionResult` with phonetic IPA and confidence metrics.

## 2. Algorithm Used
**Morphological Root-Matching Word Sense Disambiguation (WSD)**:
1. **Stage 1 (Harvesting)**:
   - Queries FreeDictionary API (`/api/v2/entries/en/{word}`) via `src/api_gateway/` at 0 LLM tokens, extracting definitions, phonetics, parts of speech, and audio URLs.
   - Falls back to built-in offline academic lexicons for core polysemous terms when offline.
2. **Stage 2 (Root-Aware Disambiguation)**:
   - **Root Stemming**: Normalizes sentence and definition tokens using morphological suffix stripping (`-ical`, `-ial`, `-tion`, `-ing`, `-ed`, `-ia`, `-um`) and 5-character prefix hashing.
   - **Gloss-Sentence Cross-Entropy**:
     $$\text{Score}(\text{Sense}_j) = 0.10 + 0.45 \cdot |\text{Tokens}_{\text{sentence}} \cap \text{Tokens}_{\text{def}}| + 0.35 \cdot |\text{Stems}_{\text{sentence}} \cap \text{Stems}_{\text{def}}|$$
   - Orders candidate senses descending by confidence, placing the primary active sense at index 0.

## 3. Description
The `lexical_definitions` subsystem resolves the exact semantic meaning of polysemous words (e.g. distinguishing mathematical induction from electromagnetic induction or social culture from biological culture) in the user's active manuscript with sub-millisecond execution and zero LLM token costs.
