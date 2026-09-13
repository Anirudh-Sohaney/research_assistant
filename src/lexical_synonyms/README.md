# Lexical Synonyms Subsystem

## 1. Final Deliverable
A high-precision academic synonym discovery and contextual ranking engine (`lexical_synonyms`) providing:
- **Temporary Primary Engine: OpenAI `gpt-5.6-luna`**: High-speed cloud LLM integration queried with low reasoning effort (`reasoning_effort="low"`) and tight token bounds (`max_completion_tokens=120`) to produce 8–12 context-perfect, tense-aligned academic synonyms at maximum throughput.
- **Local Instruction-Tuned Fallback (`Qwen2.5-1.5B-Instruct`)**: Runs locally in `bfloat16` when offline or if cloud credits are exhausted, generating tense-aligned academic synonyms with 0 cloud tokens.
- **Candidate Synonym Harvesting Fallback (`harvest_candidate_synonyms()`)**: Multi-source dictionary harvesting via Datamuse REST API (`rel_syn`, `rel_spc`, `ml` with strict `syn` tag validation) and offline fallback lexicons.
- **Contextual and Scholarly Register Re-Ranking (`rank_candidates_in_context()`)**: Evaluates morphological alignment, SentenceTransformer cosine similarity, and Academic Word List (AWL) fitness.
- **Top-1 Selection & Cycling Pipeline**: Automatically provides candidates for immediate word substitution and stationary cursor synonym cycling.

## 2. Algorithm Used
**Multi-Tier Contextual Academic Synonym Architecture**:
1. **Primary Generation: OpenAI `gpt-5.6-luna` (Temporary Swap)**:
   - Queries OpenAI `gpt-5.6-luna` (customizable via `OPENAI_SYNONYM_MODEL` environment variable).
   - **Low Reasoning Optimization**: Sets `reasoning_effort="low"` in the Chat Completions payload to minimize internal chain-of-thought overhead, providing ultra-low generation latency.
   - **Highest Speed Bounding**: Constrains `max_completion_tokens=120` and enforces a rapid 10.0s network timeout.
   - **Bearer Authentication**: Seamlessly authenticates using the verified OAuth token loaded via `api_gateway.oauth.get_valid_openai_token()`.
   - Returns 8–12 contextually ranked academic synonyms formatted as a JSON array.
2. **Secondary Generation (Local Qwen2.5-1.5B Fallback)**:
   - If OpenAI returns an error (such as quota exhaustion HTTP 429 or network disconnect), the engine automatically and silently falls back to local `Qwen/Qwen2.5-1.5B-Instruct` in `bfloat16`.
   - Formats a constrained instruction prompt with the exact target word, part-of-speech rules, and surrounding sentence context.
3. **Stage 1 Dictionary Fallback (Harvesting & Antonym Purging)**:
   - Queries Datamuse REST API (`/words?rel_syn={base_lemma}&md=p,f` and `/words?ml={base_lemma}&md=p,f`) via `src/api_gateway/`.
   - **Strict `syn` Tag Filtering**: On means-like (`ml`) queries, strictly requires `syn` or `results_type:primary_rel` tags, eliminating loose co-occurrence associations.
   - **Polarity Antonym Blacklisting (`KNOWN_ANTONYMS`)**: Deterministically purges polar opposite terms at 0ms latency.
   - Merges curated offline academic fallback dictionaries (`OFFLINE_FALLBACK_LEXICON`) supporting explicit POS tuples (e.g. `("unbiased", "adj")`, `("goal", "noun")`).
3. **Stage 2 Fallback (Grammatical POS & Bidirectional Tense Preservation)**:
   - Uses local `spaCy` (`en_core_web_sm`) to tag part-of-speech and tense (`VBZ`, `VBD`, `VBN`, `VBG`, `NNS`).
   - **Bidirectional POS Gating**: Rejects nouns in adjective contexts and adjectives in noun contexts.
   - Automatically inflects candidate lemmas to strictly match target tense and number.
4. **Stage 3 Fallback (SentenceTransformer Contextual Re-Ranking)**:
   - Uses local `SentenceTransformer('all-MiniLM-L6-v2')` to embed candidate-substituted sentences.
   - **Composite Ranking Formulation**:
     $$\text{Score}(w) = 0.75 \cdot \text{CosineSimilarity}(s_{\text{orig}}, s_{w}) + 0.20 \cdot \text{AcademicRegister}(w) + 0.05 \cdot \text{Frequency}(w)$$

## 3. Description
The `lexical_synonyms` subsystem enables researchers and essay writers in Word, Google Docs, and LaTeX to discover and substitute high-precision academic vocabulary with fast local inference, perfect tense preservation, and zero LLM token consumption.

