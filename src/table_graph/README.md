# table_graph

Table parsing, data extraction, and chart generation module for the Research Aid Desktop Assistant.

## Overview

The `table_graph` module provides end-to-end functionality for:

- Parsing tables from text, CSV, TSV, Markdown, and HTML
- Detecting column types and data structures
- Suggesting appropriate chart types based on data characteristics
- Generating publication-quality charts (bar, line, pie, scatter, etc.)
- Rendering images for injection into text editors

## Function Signatures

### parse_table

```python
def parse_table(
    table_input: str,
    input_format: str = "auto",
    delimiter: str = None,
    has_header: bool = True,
    detect_types: bool = True
) -> dict:
    """
    Parse raw table text into structured data.

    Args:
        table_input: Raw table text (CSV, TSV, Markdown, HTML, or plain text)
        input_format: One of "auto", "csv", "tsv", "markdown", "html", "plaintext"
        delimiter: Custom delimiter (overrides auto-detection)
        has_header: Whether first row contains column headers
        detect_types: Whether to infer column data types

    Returns:
        dict with keys:
            - headers: list[str] - Column names
            - rows: list[list] - Row data as lists
            - column_types: dict[str, str] - Column name to type mapping (str, int, float, date, bool)
            - row_count: int - Number of data rows
            - column_count: int - Number of columns
            - parse_confidence: float - Confidence score 0.0-1.0
            - raw_data: str - Original input text
            - warnings: list[str] - Parse warnings (e.g., inconsistent columns)

    Raises:
        ParseError: When input cannot be parsed as a table
    """
```

### table_to_graph

```python
def table_to_graph(
    table_data: dict,
    chart_type: str = "auto",
    x_column: str = None,
    y_columns: list = None,
    title: str = None,
    output_format: str = "png",
    width: int = 800,
    height: int = 600,
    style: str = "default",
    color_scheme: str = "default"
) -> dict:
    """
    Generate a chart image from parsed table data.

    Args:
        table_data: Output from parse_table()
        chart_type: One of "auto", "bar", "line", "pie", "scatter", "histogram",
                    "box", "heatmap", "area", "stacked_bar"
        x_column: Column name for X axis (None = first column or index)
        y_columns: Column names for Y axis (None = all numeric columns)
        title: Chart title (None = auto-generated)
        output_format: One of "png", "svg", "pdf", "jpg"
        width: Image width in pixels
        height: Image height in pixels
        style: Chart style preset ("default", "minimal", "publication", "dark", "light")
        color_scheme: Color palette ("default", "colorblind", "grayscale", "pastel", "vibrant", "custom")

    Returns:
        dict with keys:
            - image_path: str - Path to rendered image file
            - image_bytes: bytes - Raw image data (for direct injection)
            - chart_type_used: str - Actual chart type rendered
            - data_points: int - Number of data points plotted
            - rendering_time_ms: float - Render duration in milliseconds
            - warnings: list[str] - Rendering warnings
    """
```

### suggest_chart_type

```python
def suggest_chart_type(table_data: dict) -> list:
    """
    Analyze table data and suggest appropriate chart types.

    Performs statistical analysis on column types, cardinality, and distribution
    to recommend chart types ranked by suitability.

    Args:
        table_data: Output from parse_table()

    Returns:
        list[dict] sorted by suitability_score descending, each with:
            - chart_type: str - Chart type name
            - confidence: float - Confidence score 0.0-1.0
            - reason: str - Human-readable explanation
            - suitability_score: float - Weighted score 0.0-1.0
    """
```

### format_table_for_display

```python
def format_table_for_display(
    table_data: dict,
    max_rows: int = 20,
    max_col_width: int = 30,
    alignment: str = "left",
    show_types: bool = False,
    ellipsis: str = "..."
) -> str:
    """
    Format parsed table data as a readable string for overlay display.

    Args:
        table_data: Output from parse_table()
        max_rows: Maximum rows to display (truncates with row count indicator)
        max_col_width: Maximum character width per column
        alignment: Column alignment ("left", "right", "center", "numeric")
        show_types: Whether to append type indicators to headers
        ellipsis: String used for truncation indicator

    Returns:
        Formatted table string with borders and alignment
    """
```

## Solution Landscape

### Table Parsing

| Library | License | Strengths | Weaknesses |
|---------|---------|-----------|------------|
| `pandas` | BSD-3 | Full-featured, handles all formats | Heavy dependency |
| `csv` (stdlib) | PSF | Zero dependencies, fast | No HTML/Markdown |
| `tabulate` | MIT | Excellent Markdown pipe tables | No HTML parsing |
| `beautifulsoup4` | MIT | Robust HTML parsing | Overkill for non-HTML |
| `html5lib` | MIT | Spec-compliant parser | Slower than BeautifulSoup |

**Recommendation:** Use `csv` for CSV/TSV, `beautifulsoup4` for HTML, and a custom Markdown parser.

### Chart Generation

| Library | License | Strengths | Weaknesses |
|---------|---------|-----------|------------|
| `matplotlib` | PSF | Most chart types, publication quality | Verbose API, static only |
| `plotly` | MIT | Interactive, web-friendly | Larger output files |
| `vega-lite` | BSD | Declarative JSON spec | Limited Python integration |
| `chart.js` | MIT | Lightweight, web-focused | Browser-only |
| `bokeh` | BSD | Interactive server, streaming | Complex setup |

**Recommendation:** `matplotlib` for static images. Consider `plotly` with `kaleido` for interactive HTML export.

### Image Rendering

| Library | License | Strengths | Weaknesses |
|---------|---------|-----------|------------|
| `Pillow` | MIT | Fast rasterization, format support, simple API | No vector output |
| `cairo` | LGPL | High-quality vector rendering, anti-aliasing | System dependency, complex install |
| `svglib` | BSD | SVG manipulation, round-trip conversion | Limited rendering capabilities |

**Recommendation:** `Pillow` for PNG/JPG output. `cairo` only if vector quality is critical.

### Supported Chart Types

- **Bar** — Categorical comparison, single/multi-series
- **Line** — Time series, trends, continuous data
- **Pie** — Part-to-whole (≤8 segments recommended)
- **Scatter** — Correlation between two numeric variables
- **Histogram** — Distribution of a single numeric variable
- **Box Plot** — Statistical distribution with quartiles
- **Heatmap** — Matrix/cross-tabulation visualization
- **Area** — Cumulative trends, stacked comparisons

## Design Considerations

### Input Format Detection

Formats detected via pattern matching (in priority order):

1. **HTML** — `<table>` tags detected
2. **Markdown** — Pipe-delimited rows (`| col | col |`)
3. **TSV** — Tab characters between fields
4. **CSV** — Comma-delimited with consistent column counts
5. **Plain text** — Whitespace-aligned columns (heuristic)

Fallback: If detection confidence < 0.6, prompt user for format specification.

### Large Dataset Handling

- Tables >10,000 rows: Sampling for chart suggestions (first 1,000 rows)
- Tables >100,000 rows: Warn about render time, offer downsampling
- Memory: Streaming parser for CSV, DOM limit for HTML

### Color Accessibility

Default palettes conform to WCAG 2.1 AA contrast requirements. The `colorblind` scheme uses the Okabe-Ito palette (8 distinguishable colors safe for protanopia, deuteranopia, tritanopia).

### Unicode Handling

All parsers normalize input to NFC Unicode. Column headers and data support full Unicode range. Chart labels handle CJK, Arabic, and RTL text via matplotlib's font fallback system.

## Codebase Structure

```
table_graph/
├── __init__.py              # Public API exports
├── table_parser.py          # Table input parsing
├── chart_generator.py       # Chart/graph generation
├── chart_suggester.py       # Auto chart type suggestion
├── image_renderer.py        # Image rendering and format conversion
├── formatters.py            # Table formatting for overlay display
├── models.py                # Data models (TableData, ChartConfig)
├── config.py                # Module configuration
└── _parsers/                # Format-specific parsers
    ├── csv_parser.py
    ├── html_parser.py
    ├── markdown_parser.py
    └── plaintext_parser.py
```

## Usage Examples

```python
from table_graph import parse_table, table_to_graph, suggest_chart_type

# Parse CSV input
result = parse_table("Name,Age,City\nAlice,30,NYC\nBob,25,LA\n", input_format="csv")

# Get chart suggestions
suggestions = suggest_chart_type(result)
# [{"chart_type": "bar", "confidence": 0.9, ...}, ...]

# Generate chart
chart = table_to_graph(result, chart_type="bar", x_column="Name", y_columns=["Age"])

# Inject image into editor
editor.insert_image(chart["image_bytes"], format="png")
```

## Sources

- [pandas](https://pandas.pydata.org/docs/)
- [matplotlib](https://matplotlib.org/stable/contents.html)
- [beautifulsoup4](https://www.crummy.com/software/BeautifulSoup/bs4/doc/)
- [tabulate](https://pypi.org/project/tabulate/)
- [Pillow](https://pillow.readthedocs.io/)
- [plotly](https://plotly.com/python/)
- [Okabe-Ito color palette](https://jfly.uni-koeln.de/color/)
