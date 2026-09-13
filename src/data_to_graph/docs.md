# Data to Graph Documentation

## Module Overview
`data_to_graph` parses raw highlighted tabular text across Markdown, LaTeX, and CSV/TSV, and renders academic-quality 300 DPI figures using a headless plotting backend.

## File Structure
- `models.py`: Data classes (`ChartType`, `ChartStyleConfig`, `ParsedTableDataset`, `RenderedChart`).
- `grapher.py`: Table parsing, unit coercion, heuristic axis inference, and headless Matplotlib rendering.
- `tests/test_data_to_graph.py`: Unit test suite testing Markdown, LaTeX, CSV/unit parsing, and chart generation.

## API Reference

### `parse_tabular_data(raw_table_text: str) -> ParsedTableDataset`
Parses raw tabular text, strips units, and infers column types.
- **`raw_table_text`**: Highlighted string containing Markdown, LaTeX, or CSV tabular data.
- **Returns**: `ParsedTableDataset(columns, rows, column_types, format_detected, suggested_chart_type)`.

### `generate_chart(dataset: ParsedTableDataset, chart_type: Optional[ChartType] = None, style: Optional[ChartStyleConfig] = None) -> RenderedChart`
Renders the dataset into 300 DPI PNG bytes and SVG XML.
- **`dataset`**: Parsed table dataset.
- **`chart_type`**: Desired chart family (`BAR_CHART`, `LINE_CHART`, `SCATTER_DOT`, `BOX_PLOT`, `HISTOGRAM`).
- **`style`**: `ChartStyleConfig(dpi, palette, title, x_label, y_label)`.
- **Returns**: `RenderedChart(png_bytes, svg_text, chart_type, dataset, available_alternatives)`.

### `toggle_chart_type(current_chart: RenderedChart, next_type: ChartType) -> RenderedChart`
Re-renders an existing chart under an alternative chart type in $<40\text{ms}$.

## Usage Example

```python
from data_to_graph import parse_tabular_data, generate_chart, ChartType

table_markdown = """
| Model | Score | Latency (ms) |
|---|---|---|
| Model A | 85.4 | 12 |
| Model B | 91.2 | 24 |
"""

dataset = parse_tabular_data(table_markdown)
print(f"Detected format: {dataset.format_detected}, Suggested: {dataset.suggested_chart_type}")

chart = generate_chart(dataset, chart_type=ChartType.BAR_CHART)
print(f"Rendered PNG ({len(chart.png_bytes)} bytes)")
# with open("figure.png", "wb") as f:
#     f.write(chart.png_bytes)
```

## Running Tests
```bash
python -m pytest data_to_graph/tests/test_data_to_graph.py -v
```
