# Paper Analysis Subsystem

`paper_analysis` runs eight independent academic-editor judges over the complete selected text. The judges cover consistency, grammar, clarity, organization, evidence, academic style, methodology, and contribution. Each call returns a 1–100 raw quality estimate plus 3–6 excerpt-specific findings with repair instructions.

The displayed score uses a curved quality calibration with a 50-point floor: 50 represents multiple issues, 90 represents publishable quality, and 100 represents perfection. Alt+J opens one results section: judges appear as they finish, and clicking a judge replaces the list with full-width details. `Backspace` returns to the judge list. Empty, malformed, or under-specified judge responses receive up to three retries.

## Files

- `analysis.py`: Judge rubrics, parallel provider calls, JSON parsing, score calibration, and result models.
- `overlay.py`: Clickable score/detail PyQt overlay.
- `tests/test_analysis.py`: Mocked multi-judge and full-text propagation tests.
