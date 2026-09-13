# Paper Analysis Subsystem

`paper_analysis` runs eight independent academic-editor judges over the complete selected text. The judges cover consistency, grammar, clarity, organization, evidence, academic style, methodology, and contribution. Each call returns a 1–100 raw quality estimate plus ideally three excerpt-specific findings, with at least one when only one issue is supported.

The displayed score uses a calibrated 50–100 quality scale: 50 represents multiple issues, 90 represents publishable quality, and 100 represents perfection. Alt+J opens one compact results section: judges appear as they finish, clicking a judge shows only its explanations, and clicking an explanation shows the exact text to replace and the direct replacement. Every finding contains the exact affected sentence or paragraph, a 100–200 word explanation, a repair instruction, and a direct rewrite; the rewrite is empty when deletion is the correct fix. `Backspace` navigates one level back. Empty, malformed, or under-specified judge responses receive up to three retries.

## Files

- `analysis.py`: Judge rubrics, parallel provider calls, JSON parsing, score calibration, and result models.
- `overlay.py`: Clickable score/detail PyQt overlay.
- `tests/test_analysis.py`: Mocked multi-judge and full-text propagation tests.
