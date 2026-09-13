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

Each judge must return strict JSON with a raw score and 3–6 findings. Findings contain an exact excerpt, the issue, and a concrete fix. Empty, malformed, or under-specified responses receive up to three larger-budget retries. Invalid or failed judges remain visible as errors rather than receiving fabricated findings.

## API

`analyze_paper(selected_text: str) -> PaperAnalysisResult` runs the eight calls concurrently. The configured LLM endpoint is used through `src/api_gateway`; `PAPER_ANALYSIS_MODEL` and `PAPER_ANALYSIS_TIMEOUT` may override the defaults.

## UI navigation

The overlay uses one content section. It lists judges as they complete; selecting a row replaces the list with the judge's score, excerpts, issues, and repair instructions. `Backspace` returns to the list and `Esc` closes the overlay.
