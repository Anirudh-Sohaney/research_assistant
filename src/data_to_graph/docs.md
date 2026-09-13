# Data to Graph Documentation

## Module Overview
`data_to_graph` is a 100% zero-token tabular parsing and academic visualization engine. It parses raw highlighted tabular text across Markdown, LaTeX, Unicode/ASCII box tables, JSON, and CSV/TSV, coercing units and currency, and rendering publication-grade 300 DPI figures using a headless Matplotlib backend.

## File Structure
- `models.py`: Data classes (`ChartType`, `ChartStyleConfig`, `ParsedTableDataset`, `RenderedChart`, `ChartCollection`).
- `chart_selector.py`: Top 20 chart selection rules, strict compatibility filters, and intent detection.
- `segmenter.py`: 4-stage table segmentation pipeline for multi-heading and multi-dataset tables.
- `overlay.py`: Interactive PyQt popup overlay imitating RewordOverlay cyber-monospace UI.
- `grapher.py`: Multi-format table parsing, unit/uncertainty coercion, heuristic chart inference, and headless Matplotlib rendering.
- `tests/test_data_to_graph.py`: Comprehensive test suite testing all 20 chart types, formatting, and rendering.
- `tests/test_overlay.py`: Unit and integration tests for TableGraphOverlay navigation and keyboard shortcuts.

## API Reference

### `parse_tabular_data(raw_table_text: str) -> ParsedTableDataset`
Parses raw tabular text across Markdown, LaTeX tabular, Unicode/ASCII boxes, JSON, and CSV/TSV, strips units and currencies, handles uncertainties (`±`), and infers column types and chart recommendations.
- **`raw_table_text`**: Highlighted string containing tabular data.
- **Returns**: `ParsedTableDataset(columns, rows, column_types, format_detected, suggested_chart_type, column_units, uncertainties)`.

### `generate_chart(dataset: ParsedTableDataset, chart_type: Optional[ChartType] = None, style: Optional[ChartStyleConfig] = None) -> RenderedChart`
Renders the dataset into 300 DPI PNG bytes and SVG XML markup.
- **`dataset`**: Parsed table dataset.
- **`chart_type`**: Desired chart family (`BAR_CHART`, `HORIZONTAL_BAR`, `LINE_CHART`, `SCATTER_DOT`, `BOX_PLOT`, `HISTOGRAM`, `HEATMAP`, `AREA_CHART`).
- **`style`**: `ChartStyleConfig(dpi, palette, title, x_label, y_label, dark_mode, show_grid, show_values, figure_size)`.
  - Available palettes: `"academic"`, `"colorblind"`, `"scifi"`, `"grayscale"`, `"seaborn"`.
- **Returns**: `RenderedChart(png_bytes, svg_text, chart_type, dataset, available_alternatives)`.

### `toggle_chart_type(current_chart: RenderedChart, next_type: ChartType) -> RenderedChart`
Re-renders an existing chart under an alternative chart type preserving dataset state.

## Supported Formats
1. **Markdown Tables**: Standard pipe tables with optional outer borders, alignment indicators, and inline styling (`**bold**`, `*italic*`, `` `code` ``).
2. **LaTeX Environments**: `\begin{tabular}`, rules (`\toprule`, `\midrule`, `\bottomrule`, `\hline`), macros (`\textbf`, `\textsc`, `\emph`), comments (`%`), and math symbols (`$\pm$`).
3. **Unicode / ASCII Boxes**: Bordered tables from CLI tools (Pandas `to_markdown()`, Rich, PrettyTable) using `+---+---+` or `┌──┬──┐`.
4. **JSON**: Arrays of objects `[{"col1": val, ...}]` or dictionary of columns `{"col1": [...]}`.
5. **CSV / TSV / Semicolon**: Comma, tab, and European semicolon delimiters.

## Usage Example

```python
from data_to_graph import parse_tabular_data, generate_chart, ChartType, ChartStyleConfig

table_markdown = """
| Model | Accuracy (%) | Latency (ms) |
|---|---|---|
| DeBERTa-v3 | 72.8 ± 0.4 | 14ms |
| MiniLM-L6 | 68.1 ± 0.2 | 5ms |
| ModernBERT | 75.4 ± 0.3 | 26ms |
"""

dataset = parse_tabular_data(table_markdown)
print(f"Detected format: {dataset.format_detected}, Suggested: {dataset.suggested_chart_type}")

# Render with academic palette
chart = generate_chart(dataset, chart_type=ChartType.BAR_CHART, style=ChartStyleConfig(palette="academic"))
print(f"Rendered PNG ({len(chart.png_bytes)} bytes)")
```

## Running Tests
```bash
python -m pytest src/data_to_graph/tests/ -v
```

## Interactive Cyber-Academic Overlay (`TableGraphOverlay`)
Triggered globally via `Ctrl + Shift + G` when tabular text is highlighted.

### Keyboard Shortcuts:
- **`Enter`**: Navigates immediately past the table (`VK_RIGHT` extended + `VK_RETURN`) and pastes the rendered graph directly below the table into the active application.
- **`Shift + Enter`**: Copies and pastes both the original table and the chart figure below it.
- **`1` - `9`**: Instantly switches between compatible chart types.
- **`Tab` / `T`**: Cycles forward through compatible charts (`Shift + Tab` cycles backward).
- **`←` / `→`**: Navigates between segmented datasets for multi-heading tables.
- **`C`**: Copies the figure across all 4 clipboard formats without closing.
- **`Esc`**: Dismisses the overlay.

### Multi-Format Clipboard Integration:
When copying or pasting, the overlay populates the Windows clipboard simultaneously with:
1. **`CF_DIB` / `CF_BITMAP`**: Direct high-res bitmap for Microsoft Word, OneNote, WordPad, and PowerPoint.
2. **`CF_HDROP`**: Temp file drop (`%TEMP%/research_assistant_chart.png`) for Slack, Discord, Teams, Obsidian, and Notion.
3. **`CF_UNICODETEXT`**: Markdown image tag `![Chart](file:///path/to/chart.png)` for Notepad, VSCode, and Markdown editors.
4. **`HTML Format`**: Web-compatible embedded image for Google Docs and browser rich-text editors.
