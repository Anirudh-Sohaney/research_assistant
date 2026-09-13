# Source Summary Documentation

## Module Overview
`source_summary` extracts structural architecture from codebases and statistical distributions from tabular datasets, generating methodology summaries and enabling local RAG Q&A.

## File Structure
- `models.py`: Data classes (`SourceType`, `ScreenCorner`, `SourceSummaryReport`, `SourceAnswer`, `InspectorHandle`).
- `profiler.py`: Codebase AST parser, tabular dataset profiler, RAG index bridge, and methodology synthesizer.
- `tests/test_source_summary.py`: Unit test suite testing Python AST analysis, dataset profiling, schema Q&A, and inspector handles.

## API Reference

### `profile_external_source(target_path_or_url: str, source_type: Optional[SourceType] = None) -> SourceSummaryReport`
Inspects a directory path or dataset file and generates a structured summary.
- **`target_path_or_url`**: Path to local directory or dataset file.
- **Returns**: `SourceSummaryReport(source_id, title, source_type, executive_summary, methodology_bullet_points, statistics)`.

### `query_source_context(source_id: str, user_question: str) -> SourceAnswer`
Performs localized RAG search over the indexed codebase or dataset schema.
- **Returns**: `SourceAnswer(markdown_answer, cited_files_or_columns, confidence)`.

### `render_floating_inspector(report: SourceSummaryReport, preferred_corner: ScreenCorner = ScreenCorner.TOP_RIGHT) -> InspectorHandle`
Returns control handle for persistent corner overlay.

## Usage Example

```python
from source_summary import profile_external_source, query_source_context

# Profile a codebase or dataset
report = profile_external_source("./src")
print(f"Profiled {report.title}: {report.statistics['total_files']} files, {report.statistics['lines_of_code']} LoC")

print("\nMethodology Bullets:")
for bullet in report.methodology_bullet_points:
    print(f" • {bullet}")

# Ask questions about the source
answer = query_source_context(report.source_id, "What are the core classes?")
print(f"\nAnswer: {answer.markdown_answer}")
```

## Running Tests
```bash
python -m pytest source_summary/tests/test_source_summary.py -v
```
