# Paper Analysis Documentation

## Workflow

Alt+J extracts the highlighted text, opens the analysis overlay, and launches eight concurrent language-model calls. Every call receives the full selected text plus one isolated rubric. The calls are independent so one judge cannot anchor another judge's assessment. Results stream into the overlay as calls finish rather than waiting for all judges.

## Judge dimensions

1. Consistency — terminology, notation, tense, numbers, and definitions.
2. Grammar — agreement, sentence construction, punctuation, articles, and tense.
3. Clarity — ambiguity, vague references, readability, and overloaded sentences.
4. Organization — sequence, transitions, paragraph purpose, and argument progression.
5. Evidence — support for claims, evidence/conclusion alignment, and overclaiming.
6. Academic Style — register, precision, vocabulary, and discipline conventions.
7. Methodology — reproducibility, variables, samples, controls, and evaluation design.
8. Contribution — novelty, significance, limitations, and conclusion alignment.

Each judge must return strict JSON with a raw score and 3–6 findings. Each finding contains the exact sentence or paragraph with the issue, a 100–200 word explanation of the issue and correction, a concrete repair instruction, and a direct rewrite. The rewrite is an empty string when deletion is the correct fix. Empty, malformed, or under-specified responses receive up to three larger-budget retries. Invalid or failed judges remain visible as errors rather than receiving fabricated findings.

## API

`analyze_paper(selected_text: str) -> PaperAnalysisResult` runs the eight calls concurrently. The configured LLM endpoint is used through `src/api_gateway`; `PAPER_ANALYSIS_MODEL` and `PAPER_ANALYSIS_TIMEOUT` may override the defaults.

## UI navigation

The overlay uses one compact content section with three navigation levels: judge scores, that judge's explanation list, and a selected explanation's replacement detail. Clicking a judge shows only its explanations. Clicking an explanation shows the exact text to replace, the direct replacement (or a deletion instruction), the issue, and the recommended fix. `Backspace` moves back one level and `Esc` closes the overlay.
