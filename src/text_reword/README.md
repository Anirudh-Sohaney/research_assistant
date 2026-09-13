# Text Reword Subsystem

## 1. Final Deliverable
A token-budgeted scholarly text rewording and entity-shielding engine (`text_reword`) providing:
- Citation and LaTeX formula shielding (`mask_scholarly_entities()`) and reconstruction (`restore_scholarly_entities()`).
- Token-budgeted sentence and paragraph rewording (`reword_text_segment()`) through the configured language model across explicit modes: fully restructure while preserving meaning and improving English (`ACADEMIC_FORMAL`), keep the structure recognizable while adding detail (`EXPANDED_ARGUMENT`), or preserve the ideas with simpler words and constructions (`SIMPLIFIED_CLARITY`). Sentence and paragraph requests allow 1,800 and 2,200 completion tokens respectively so internal reasoning does not consume the output budget.
- LLM-only execution: if the provider is unavailable, times out, or returns unusable/unchanged output, the engine makes one bounded LLM retry before the popup reports the failure and allows regeneration with `R`; no local hard-coded rewriting is applied. Interactive Alt+P requests bypass the semantic cache so the initial selection always reaches the language model. The request timeout is 120 seconds by default.
- Integration with local semantic prompt cache and token metering via `src/api_gateway/`.

## 2. Algorithm Used
**Scholarly Entity Shielding & Token-Budgeted Context Rewording**:
1. **Entity Masking / Shielding**: Pre-compiled regex patterns identify in-text citations (e.g. `(Bohr et al., 2020)`, `[12]`) and LaTeX formulas (`$...$`), replacing them with atomic placeholders (`__CITE_0__`, `__MATH_0__`). This conserves tokens and guarantees citation dates and formulas cannot be hallucinated or altered.
2. **Context Bounding & Prompt Dispatch**: Passes only the isolated selection and adjacent context sentences to the LLM via `src/api_gateway/` under strict ceilings (`max_tokens: 180` for sentences, `350` for paragraphs).
3. **Citation & Formula Unmasking**: Restores authentic citations and math into the generated primary and alternative variant sentences with 100% character fidelity.
4. **LLM-only generation**: If the provider is unavailable, times out, or returns unusable/unchanged output, the caller receives an explicit error result; no hard-coded rewording is substituted.

## 3. Description
The `text_reword` subsystem enhances the academic tone, clarity, and conciseness of text highlighted in Microsoft Word, Google Docs, or LaTeX. It prevents token abuse through context isolation and entity masking, producing publication-grade alternatives without corrupting citations.
