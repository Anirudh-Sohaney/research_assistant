# Data to Graph Subsystem

## 1. Final Deliverable
A 100% zero-LLM-token table parsing and publication-ready academic chart rendering engine (`data_to_graph`) providing:
- Multi-format tabular data parsing (`parse_tabular_data()`) supporting Markdown pipe tables, LaTeX `tabular` environments, CSV, TSV, and ASCII columns.
- Automatic unit, percentage, and currency coercion with statistical type inference (`NUMERICAL` vs `CATEGORICAL`).
- Headless vector and raster chart rendering (`generate_chart()`) producing 300 DPI PNG bytes and SVG markup across Bar, Line, Scatter, Box Plot, and Histogram charts.
- Sub-40ms chart type switching (`toggle_chart_type()`) preserving dataset state.

## 2. Algorithm Used
**Deterministic Statistical Schema Inference & Headless Vector Rendering**:
1. **Multi-Format Delimiter Sniffing**: Detects LaTeX environments (`\begin{tabular}`, `&`, `\\`), Markdown pipe tables (`|`), comma/tab delimiters, or whitespace boundaries. Strips padding and border rows.
2. **Cell Normalization**: Coerces currency (`$`), percentages (`%`), and metrics (`ms`, `kb`, `mb`, `gb`) into native integers or floating-point values while preserving units into axis labels.
3. **Statistical Heuristic Chart Selection**:
   - $\text{Categorical } X + \text{Numerical } Y \longrightarrow \text{Bar Chart}$
   - $\text{Sequential/Temporal } X + \text{Continuous } Y \longrightarrow \text{Line Graph}$
   - $\text{Two Continuous Numerical Series} \longrightarrow \text{Scatter Plot}$
4. **Headless Academic Visualization**: Matplotlib Agg engine renders scholarly figures with clean minimalist spines, high-contrast palettes, and zero window manager dependencies.

## 3. Description
The `data_to_graph` subsystem translates raw numeric tables copied or highlighted in manuscript drafts directly into publication-quality academic figures without sending data to external LLMs or opening third-party plotting software.
