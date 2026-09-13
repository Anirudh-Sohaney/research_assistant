# Text Reword Subsystem

## 1. Final Deliverable
A token-budgeted scholarly text rewording and entity-shielding engine (`text_reword`) providing:
- Citation and LaTeX formula shielding (`mask_scholarly_entities()`) and reconstruction (`restore_scholarly_entities()`).
- Token-budgeted sentence and paragraph rewording (`reword_text_segment()`) through OpenRouter's `inclusionai/ling-3.0-flash-fin:free` model by default (override with `OPENROUTER_REWORD_MODEL`) across explicit modes: fully restructure while preserving meaning and improving English (`ACADEMIC_FORMAL`), keep the structure recognizable while adding detail (`EXPANDED_ARGUMENT`), or preserve the ideas with simpler words and constructions (`SIMPLIFIED_CLARITY`). Sentence and paragraph requests allow 1,800 and 2,200 completion tokens respectively so Ling's internal reasoning does not consume the output budget.
- LLM-only execution: if OpenRouter is unavailable, times out, or returns unusable/unchanged output, the popup reports the failure and allows regeneration with `R`; no local hard-coded rewriting is applied. Ling requests use a 120-second timeout by default, configurable with `OPENROUTER_REWORD_TIMEOUT`.
- Integration with local semantic prompt cache and token metering via `src/api_gateway/`.

## 2. Algorithm Used
**Scholarly Entity Shielding & Token-Budgeted Context Rewording**:
1. **Entity Masking / Shielding**: Pre-compiled regex patterns identify in-text citations (e.g. `(Bohr et al., 2020)`, `[12]`) and LaTeX formulas (`$...$`), replacing them with atomic placeholders (`__CITE_0__`, `__MATH_0__`). This conserves tokens and guarantees citation dates and formulas cannot be hallucinated or altered.
2. **Context Bounding & Prompt Dispatch**: Passes only the isolated selection and adjacent context sentences to the LLM via `src/api_gateway/` under strict ceilings (`max_tokens: 180` for sentences, `350` for paragraphs).
3. **Citation & Formula Unmasking**: Restores authentic citations and math into the generated primary and alternative variant sentences with 100% character fidelity.
4. **LLM-only generation**: If OpenRouter is unavailable, times out, or returns unusable/unchanged output, the caller receives an explicit error result; no hard-coded rewording is substituted.

## 3. Description
The `text_reword` subsystem enhances the academic tone, clarity, and conciseness of text highlighted in Microsoft Word, Google Docs, or LaTeX. It prevents token abuse through context isolation and entity masking, producing publication-grade alternatives without corrupting citations.
