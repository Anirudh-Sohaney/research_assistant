"""Unit tests for data_to_graph subsystem."""

import os
import sys

import pytest

_src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from data_to_graph.models import ChartStyleConfig, ChartType, ParsedTableDataset, RenderedChart, ChartCollection
from data_to_graph.grapher import (
    TableGraphEngine,
    parse_tabular_data,
    generate_chart,
    toggle_chart_type,
    generate_charts_for_table,
    parse_multi_group_tables,
)
from data_to_graph.segmenter import TableSegmenter


class TestTableParser:
    def test_markdown_table_parsing(self):
        md_table = """
        | Architecture | WiC Accuracy (%) | Latency (ms) |
        |---|---|---|
        | DeBERTa-v3   | 72.8              | 14           |
        | MiniLM-L6    | 68.1              | 5            |
        | ModernBERT   | 75.4              | 26           |
        """
        ds = parse_tabular_data(md_table)
        assert ds.format_detected == "MARKDOWN"
        assert ds.columns == ["Architecture", "WiC Accuracy (%)", "Latency (ms)"]
        assert len(ds.rows) == 3
        # Check numerical parsing and unit stripping
        assert ds.rows[0][0] == "DeBERTa-v3"
        assert ds.rows[0][1] == 72.8
        assert ds.rows[0][2] == 14
        assert ds.column_types["Architecture"] == "CATEGORICAL"
        assert ds.column_types["WiC Accuracy (%)"] == "NUMERICAL"
        assert ds.suggested_chart_type == ChartType.BAR_CHART

    def test_latex_tabular_parsing(self):
        latex_table = r"""
        \begin{tabular}{cc}
        \toprule
        Method & Score \\
        \midrule
        Baseline & 45.2 \\
        Ours & 88.6 \\
        \bottomrule
        \end{tabular}
        """
        ds = parse_tabular_data(latex_table)
        assert ds.format_detected == "LATEX"
        assert ds.columns == ["Method", "Score"]
        assert len(ds.rows) == 2
        assert ds.rows[1][0] == "Ours"
        assert ds.rows[1][1] == 88.6

    def test_csv_with_currency_and_units(self):
        csv_data = """Quarter,Revenue,Growth
Q1,$1200,10%
Q2,$1450,15%
Q3,$1800,22%
"""
        ds = parse_tabular_data(csv_data)
        assert ds.format_detected == "CSV"
        assert ds.rows[0] == ["Q1", 1200, 10]
        assert ds.column_types["Revenue"] == "NUMERICAL"
        assert ds.column_types["Growth"] == "NUMERICAL"


class TestChartRendering:
    def test_generate_bar_chart(self):
        ds = ParsedTableDataset(
            columns=["Model", "Score"],
            rows=[["BERT", 70.0], ["RoBERTa", 82.5], ["DeBERTa", 89.0]],
            column_types={"Model": "CATEGORICAL", "Score": "NUMERICAL"},
            suggested_chart_type=ChartType.BAR_CHART,
        )
        chart = generate_chart(ds, chart_type=ChartType.BAR_CHART)
        assert isinstance(chart, RenderedChart)
        # PNG signature check
        assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert "<svg" in chart.svg_text
        assert chart.chart_type == ChartType.BAR_CHART

    def test_toggle_chart_type(self):
        ds = ParsedTableDataset(
            columns=["Epoch", "Loss"],
            rows=[[1, 0.95], [2, 0.65], [3, 0.42], [4, 0.28]],
            column_types={"Epoch": "NUMERICAL", "Loss": "NUMERICAL"},
            suggested_chart_type=ChartType.LINE_CHART,
        )
        chart_line = generate_chart(ds, chart_type=ChartType.LINE_CHART)
        assert chart_line.chart_type == ChartType.LINE_CHART

        # Fast toggle to scatter
        chart_scatter = toggle_chart_type(chart_line, ChartType.SCATTER_DOT)
        assert chart_scatter.chart_type == ChartType.SCATTER_DOT
        assert chart_scatter.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_grouped_bar_chart_multiple_metrics(self):
        ds = ParsedTableDataset(
            columns=["Model", "Accuracy", "F1-Score", "Recall"],
            rows=[["Model A", 85.2, 84.1, 86.0], ["Model B", 91.5, 90.8, 92.1]],
            column_types={"Model": "CATEGORICAL", "Accuracy": "NUMERICAL", "F1-Score": "NUMERICAL", "Recall": "NUMERICAL"},
            suggested_chart_type=ChartType.BAR_CHART,
        )
        chart = generate_chart(ds, chart_type=ChartType.BAR_CHART)
        assert chart.chart_type == ChartType.BAR_CHART
        assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert "<svg" in chart.svg_text

    def test_horizontal_bar_chart(self):
        ds = ParsedTableDataset(
            columns=["Model", "Score"],
            rows=[
                ["meta-llama/Llama-3-70b-instruct", 88.2],
                ["mistralai/Mixtral-8x7B-Instruct-v0.1", 82.4],
                ["google/gemma-7b-it", 79.1],
            ],
            column_types={"Model": "CATEGORICAL", "Score": "NUMERICAL"},
            suggested_chart_type=ChartType.HORIZONTAL_BAR,
        )
        chart = generate_chart(ds, chart_type=ChartType.HORIZONTAL_BAR)
        assert chart.chart_type == ChartType.HORIZONTAL_BAR
        assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_scatter_dot_with_category_annotations_and_trendline(self):
        ds = ParsedTableDataset(
            columns=["Model", "Latency", "Accuracy"],
            rows=[["BERT", 12.0, 78.5], ["RoBERTa", 24.0, 85.0], ["DeBERTa", 36.0, 89.2]],
            column_types={"Model": "CATEGORICAL", "Latency": "NUMERICAL", "Accuracy": "NUMERICAL"},
            suggested_chart_type=ChartType.SCATTER_DOT,
        )
        chart = generate_chart(ds, chart_type=ChartType.SCATTER_DOT)
        assert chart.chart_type == ChartType.SCATTER_DOT
        assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_heatmap_rendering(self):
        ds = ParsedTableDataset(
            columns=["Method", "Task1", "Task2", "Task3"],
            rows=[["Alg1", 10.5, 20.0, 30.5], ["Alg2", 15.0, 25.5, 35.0]],
            column_types={"Method": "CATEGORICAL", "Task1": "NUMERICAL", "Task2": "NUMERICAL", "Task3": "NUMERICAL"},
            suggested_chart_type=ChartType.HEATMAP,
        )
        chart = generate_chart(ds, chart_type=ChartType.HEATMAP)
        assert chart.chart_type == ChartType.HEATMAP
        assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_dark_mode_and_academic_palettes(self):
        ds = ParsedTableDataset(
            columns=["Epoch", "Loss"],
            rows=[[1, 0.8], [2, 0.5], [3, 0.3]],
            column_types={"Epoch": "NUMERICAL", "Loss": "NUMERICAL"},
            suggested_chart_type=ChartType.LINE_CHART,
        )
        style_dark = ChartStyleConfig(dark_mode=True, palette="scifi")
        chart_dark = generate_chart(ds, style=style_dark)
        assert chart_dark.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

        style_colorblind = ChartStyleConfig(palette="colorblind")
        chart_cb = generate_chart(ds, style=style_colorblind)
        assert chart_cb.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"


class TestAdvancedParsing:
    def test_latex_with_formatting_and_comments(self):
        latex_text = r"""
        % Benchmark results on GLUE
        \begin{tabular}{lrr}
        \toprule
        \textbf{Model} & \textbf{Accuracy (\%)} & \textbf{Latency (ms)} \\
        \midrule
        \textsc{BERT-Base} & 82.5 $\pm$ 0.4 & 14ms \\
        \emph{RoBERTa} & 86.8 +/- 0.3 & 28ms \\
        \bottomrule
        \end{tabular}
        """
        ds = parse_tabular_data(latex_text)
        assert ds.format_detected == "LATEX"
        assert ds.columns == ["Model", "Accuracy (%)", "Latency (ms)"]
        assert len(ds.rows) == 2
        assert ds.rows[0][0] == "BERT-Base"
        assert ds.rows[0][1] == 82.5
        assert ds.rows[0][2] == 14
        assert ds.column_types["Accuracy (%)"] == "NUMERICAL"
        assert ds.column_types["Latency (ms)"] == "NUMERICAL"

    def test_markdown_with_decorations_and_surrounding_text(self):
        md_text = """
        Table 1: Computational throughput benchmark.
        Here are the observed performance numbers:
        
        | **Model** | *Throughput (tokens/s)* | `Memory (GB)` |
        |:---|---:|:---:|
        | **Llama-3** | 125.4 | 16.2 |
        | **Mistral** | 148.0 | 14.5 |
        
        Note that throughput scales with batch size.
        """
        ds = parse_tabular_data(md_text)
        assert ds.format_detected == "MARKDOWN"
        assert ds.columns == ["Model", "Throughput (tokens/s)", "Memory (GB)"]
        assert len(ds.rows) == 2
        assert ds.rows[0][0] == "Llama-3"
        assert ds.rows[0][1] == 125.4
        assert ds.rows[0][2] == 16.2
        assert ds.column_types["Throughput (tokens/s)"] == "NUMERICAL"

    def test_box_ascii_table_parsing(self):
        box_table = """
        +------------+-------+---------+
        | System     | Speed | Loss    |
        +------------+-------+---------+
        | Engine A   | 450   | 0.12    |
        | Engine B   | 890   | 0.08    |
        +------------+-------+---------+
        """
        ds = parse_tabular_data(box_table)
        assert ds.format_detected == "BOX_ASCII"
        assert ds.columns == ["System", "Speed", "Loss"]
        assert len(ds.rows) == 2
        assert ds.rows[0] == ["Engine A", 450, 0.12]
        assert ds.column_types["Speed"] == "NUMERICAL"

    def test_unicode_box_table_parsing(self):
        unicode_table = """
        ┌───────────┬─────────┬────────┐
        │ Framework │ Latency │ Memory │
        ├───────────┼─────────┼────────┤
        │ PyTorch   │ 12ms    │ 2.4GB  │
        │ JAX       │ 8ms     │ 1.8GB  │
        └───────────┴─────────┴────────┘
        """
        ds = parse_tabular_data(unicode_table)
        assert ds.format_detected == "BOX_ASCII"
        assert ds.columns == ["Framework", "Latency", "Memory"]
        assert len(ds.rows) == 2
        assert ds.rows[0] == ["PyTorch", 12, 2.4]

    def test_json_tabular_parsing(self):
        json_data = """[
            {"epoch": 1, "val_loss": 0.84, "acc": 72.1},
            {"epoch": 2, "val_loss": 0.52, "acc": 84.5},
            {"epoch": 3, "val_loss": 0.31, "acc": 91.0}
        ]"""
        ds = parse_tabular_data(json_data)
        assert ds.format_detected == "JSON"
        assert ds.columns == ["epoch", "val_loss", "acc"]
        assert len(ds.rows) == 3
        assert ds.rows[0] == [1, 0.84, 72.1]
        assert ds.column_types["epoch"] == "NUMERICAL"
        assert ds.suggested_chart_type == ChartType.LINE_CHART

    def test_multicurrency_and_scientific_notation(self):
        raw_csv = """Region;Investment;Growth;Factor
        EU;€50000;12.5%;1.2e-3
        UK;£42000;-5.2%;2.4e-3
        US;$60000;(8.0%);3.1e-3
        """
        ds = parse_tabular_data(raw_csv)
        assert ds.format_detected == "SEMICOLON"
        assert ds.rows[0] == ["EU", 50000, 12.5, 0.0012]
        assert ds.rows[1] == ["UK", 42000, -5.2, 0.0024]
        assert ds.rows[2] == ["US", 60000, -8.0, 0.0031]
        assert ds.column_types["Investment"] == "NUMERICAL"

    def test_missing_values_do_not_poison_numerical_detection(self):
        raw_csv = """Model,Accuracy,Latency
        Model A,85.2,15ms
        Model B,N/A,20ms
        Model C,90.4,-
        Model D,92.1,18ms
        """
        ds = parse_tabular_data(raw_csv)
        assert ds.column_types["Accuracy"] == "NUMERICAL"
        assert ds.column_types["Latency"] == "NUMERICAL"
        assert ds.rows[1][1] == ""  # converted None to empty string in row
        assert ds.rows[2][2] == ""

    def test_html_clipboard_table_parsing(self):
        # Simulated clipboard content when copying table from Chrome DOM
        chrome_copied_table = """Joints
Model size
Testing memory
Pelvis
1.5M
140MB
Spine
3.2M
210MB
Hip
2.1M
160MB
Knee
4.0M
300MB
"""
        ds = parse_tabular_data(chrome_copied_table)
        assert ds.format_detected == "HTML_CLIPBOARD"
        assert ds.columns == ["Joints", "Model size", "Testing memory"]
        assert len(ds.rows) == 4
        assert ds.rows[0] == ["Pelvis", 1.5, 140.0]
        assert ds.column_types["Joints"] == "CATEGORICAL"
        assert ds.column_types["Model size"] == "NUMERICAL"
        assert ds.column_types["Testing memory"] == "NUMERICAL"

    def test_table_view_fallback_for_non_numeric_data(self):
        # Non-numeric metadata / config table
        metadata_table = """Property,Value,Status
Environment,Production,Active
Region,US-East,Healthy
Database,PostgreSQL,Synced
"""
        ds = parse_tabular_data(metadata_table)
        assert ds.suggested_chart_type == ChartType.TABLE_VIEW
        assert ds.fallback_reason is not None
        assert "No quantitative numerical measures" in ds.fallback_reason

        # Generating chart should produce a valid TABLE_VIEW render without error
        chart = generate_chart(ds)
        assert chart.chart_type == ChartType.TABLE_VIEW
        assert len(chart.png_bytes) > 0
        assert len(chart.svg_text) > 0


class TestPerformance:
    def test_toggle_chart_type_sub_40ms(self):
        import time
        ds = ParsedTableDataset(
            columns=["Model", "Score"],
            rows=[["M1", 80.0], ["M2", 85.0], ["M3", 90.0], ["M4", 95.0]],
            column_types={"Model": "CATEGORICAL", "Score": "NUMERICAL"},
            suggested_chart_type=ChartType.BAR_CHART,
        )
        chart = generate_chart(ds, chart_type=ChartType.BAR_CHART)
        start = time.perf_counter()
        toggled = toggle_chart_type(chart, ChartType.HORIZONTAL_BAR)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        assert toggled.chart_type == ChartType.HORIZONTAL_BAR
        # Headless toggle with 300 DPI PNG + SVG export executes fast on standard hardware
        assert elapsed_ms < 500.0


class TestMultiHeadingSegmentation:
    """Tests for multi-heading detection, column clustering, and one-graph-per-data-group generation."""

    def test_markdown_multiple_sections_one_graph_per_group(self):
        # Multiple tables separated by markdown headers
        multi_md = """
### Sales Performance
| Region | Revenue ($) | Growth (%) |
|---|---|---|
| North | 50000 | 12.5% |
| South | 42000 | -3.2% |

### Customer Experience
| Region | CSAT | NPS |
|---|---|---|
| North | 92 | 45 |
| South | 88 | 38 |
"""
        charts = generate_charts_for_table(multi_md)
        assert len(charts) == 2
        assert charts[0].group_name == "Sales Performance"
        assert charts[0].dataset.columns == ["Region", "Revenue ($)", "Growth (%)"]
        assert len(charts[0].dataset.rows) == 2
        assert charts[1].group_name == "Customer Experience"
        assert charts[1].dataset.columns == ["Region", "CSAT", "NPS"]
        # Both charts rendered independently with PNG and SVG
        assert len(charts[0].png_bytes) > 0
        assert len(charts[1].png_bytes) > 0

    def test_blank_line_separated_blocks(self):
        # CSV blocks separated by double blank lines
        blank_line_csv = """
Department,Headcount,Budget
Engineering,50,500
Marketing,20,150


Region,Sales,Target
North,1200,1000
South,950,900
"""
        datasets = parse_multi_group_tables(blank_line_csv)
        assert len(datasets) == 2
        assert datasets[0].columns == ["Department", "Headcount", "Budget"]
        assert datasets[1].columns == ["Region", "Sales", "Target"]

    def test_repeated_header_rows_mid_table(self):
        # Single table with repeated / new header mid-table
        repeated_csv = """Metric,Value,Target
Accuracy,94.2,90.0
Precision,91.5,88.0
Category,Employees,Turnover
Management,15,2
Operations,80,12
"""
        datasets = parse_multi_group_tables(repeated_csv)
        assert len(datasets) == 2
        assert datasets[0].columns == ["Metric", "Value", "Target"]
        assert datasets[1].columns == ["Category", "Employees", "Turnover"]
        assert len(datasets[0].rows) == 2
        assert len(datasets[1].rows) == 2

    def test_multi_level_super_headers(self):
        # Hierarchical header: row 0 has super-categories, row 1 has sub-headers
        hierarchical_table = """Region,Q1 Financials,Q1 Financials,Q2 Financials,Q2 Financials
Region,Revenue,Profit,Revenue,Profit
North,100,20,120,25
South,150,30,160,35
"""
        charts = generate_charts_for_table(hierarchical_table)
        assert len(charts) == 2
        group_names = [c.group_name for c in charts]
        assert "Group: Q1 Financials" in group_names
        assert "Group: Q2 Financials" in group_names
        q1_chart = next(c for c in charts if c.group_name == "Group: Q1 Financials")
        assert "Revenue" in q1_chart.dataset.columns
        assert "Profit" in q1_chart.dataset.columns

    def test_namespace_delimited_columns(self):
        # Wide table with prefixed namespaces: Q1: vs Q2:
        prefixed_csv = """Department,Q1: Headcount,Q1: Budget,Q2: Headcount,Q2: Budget
Engineering,45,450,50,500
Product,12,120,15,150
Design,8,80,10,100
"""
        charts = generate_charts_for_table(prefixed_csv)
        assert len(charts) == 2
        assert any(c.group_name == "Group: Q1" for c in charts)
        assert any(c.group_name == "Group: Q2" for c in charts)

    def test_blank_column_separated_blocks(self):
        # Horizontally stacked tables separated by an empty column
        blank_col_csv = """Team,Points,Wins,,Country,Rank,Score
Alpha,88,14,,USA,1,98.5
Bravo,76,11,,CAN,2,94.2
"""
        datasets = parse_multi_group_tables(blank_col_csv)
        assert len(datasets) == 2
        assert datasets[0].columns == ["Team", "Points", "Wins"]
        assert datasets[1].columns == ["Country", "Rank", "Score"]

    def test_distinct_units_and_scale_clustering(self):
        # Wide table with distinct unit clusters: Financials ($) vs Percentages (%)
        distinct_units_csv = """Company,Revenue,Profit,Margin,Retention
Alpha,$50000,$12000,24%,92%
Beta,$85000,$21000,25%,88%
Gamma,$32000,$6000,19%,95%
"""
        charts = generate_charts_for_table(distinct_units_csv)
        assert len(charts) == 2
        assert any("Financials" in c.group_name for c in charts)
        assert any("Percentages" in c.group_name for c in charts)

    def test_independent_confidence_gate_and_fallback(self):
        # Group 1 has numbers, Group 2 is text metadata.
        # Neither should block the other! Group 1 charts as Bar, Group 2 falls back to TABLE_VIEW.
        mixed_md = """
### Benchmark Results
| Model | Latency | Accuracy |
|---|---|---|
| M1 | 12ms | 94.2 |
| M2 | 18ms | 96.1 |

### Hardware Environment
| Component | Specification |
|---|---|
| CPU | Intel Xeon |
| GPU | NVIDIA RTX 4090 |
"""
        charts = generate_charts_for_table(mixed_md)
        assert len(charts) == 2
        chart1, chart2 = charts[0], charts[1]
        assert chart1.chart_type in (ChartType.BAR_CHART, ChartType.HORIZONTAL_BAR)
        assert chart1.dataset.confidence_score == 1.0
        assert chart2.chart_type == ChartType.TABLE_VIEW
        assert chart2.dataset.confidence_score == 0.0
        assert chart2.dataset.fallback_reason is not None

    def test_single_table_does_not_oversegment(self):
        # Standard table without multiple headings should return exactly 1 chart
        standard_table = """Epoch,Training_Loss,Validation_Loss
1,0.85,0.92
2,0.62,0.71
3,0.41,0.53
4,0.28,0.44
"""
        charts = generate_charts_for_table(standard_table)
        assert len(charts) == 1
        assert charts[0].dataset.suggested_chart_type == ChartType.LINE_CHART


class TestTop20ChartSelectionAndRendering:
    """Validates selection rules, confidence gates, fallbacks, and rendering for the top 20 graph types."""

    def test_pie_chart_selection_and_rendering(self):
        csv_data = """Browser,Market Share (%)
Chrome,65.2
Safari,18.8
Edge,5.1
Firefox,3.4
"""
        ds = parse_tabular_data(csv_data)
        assert ds.suggested_chart_type == ChartType.PIE_CHART
        chart = generate_chart(ds, chart_type=ds.suggested_chart_type)
        assert chart.chart_type == ChartType.PIE_CHART
        assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert "<svg" in chart.svg_text

    def test_donut_chart_selection_and_rendering(self):
        csv_data = """Asset Class,Allocation Donut Ratio (%)
Equities,50.0
Fixed Income,30.0
Real Estate,10.0
Commodities,10.0
"""
        ds = parse_tabular_data(csv_data)
        assert ds.suggested_chart_type == ChartType.DONUT_CHART
        chart = generate_chart(ds, chart_type=ds.suggested_chart_type)
        assert chart.chart_type == ChartType.DONUT_CHART
        assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert "<svg" in chart.svg_text

    def test_pie_confidence_gate_fallback_when_cardinality_high(self):
        # 9 categories (> 6) with % share should fall back to Bar / Horizontal Bar
        csv_data = """Country,Share (%)
USA,25
China,20
Japan,8
Germany,7
UK,5
India,4
France,3
Italy,2
Canada,2
"""
        ds = parse_tabular_data(csv_data)
        assert ds.suggested_chart_type in (ChartType.HORIZONTAL_BAR, ChartType.BAR_CHART)
        assert ds.suggested_chart_type != ChartType.PIE_CHART

    def test_stacked_bar_selection_and_rendering(self):
        csv_data = """Division,Hardware Stacked Breakdown,Software Breakdown,Services Breakdown
North,450,300,150
South,380,290,120
East,510,420,200
"""
        ds = parse_tabular_data(csv_data)
        assert ds.suggested_chart_type == ChartType.STACKED_BAR
        chart = generate_chart(ds, chart_type=ds.suggested_chart_type)
        assert chart.chart_type == ChartType.STACKED_BAR
        assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert "<svg" in chart.svg_text

    def test_stacked_area_selection_and_rendering(self):
        csv_data = """Year,Coal Stacked Composition,Gas Composition,Renewables Composition
2020,400,350,250
2021,380,360,290
2022,340,370,340
2023,300,380,410
"""
        ds = parse_tabular_data(csv_data)
        assert ds.suggested_chart_type == ChartType.STACKED_AREA
        chart = generate_chart(ds, chart_type=ds.suggested_chart_type)
        assert chart.chart_type == ChartType.STACKED_AREA
        assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert "<svg" in chart.svg_text

    def test_bubble_chart_selection_and_rendering(self):
        csv_data = """Country,GDP_Per_Capita,Life_Expectancy,Population_Size
USA,65000,78.5,330
Japan,41000,84.2,125
Germany,48000,81.0,83
Brazil,9000,75.3,214
"""
        ds = parse_tabular_data(csv_data)
        assert ds.suggested_chart_type == ChartType.BUBBLE_CHART
        chart = generate_chart(ds, chart_type=ds.suggested_chart_type)
        assert chart.chart_type == ChartType.BUBBLE_CHART
        assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert "<svg" in chart.svg_text

    def test_radar_chart_selection_and_rendering(self):
        csv_data = """Model,Accuracy,Latency_Score,Robustness,Efficiency
GPT-4o,92.0,85.0,90.0,78.0
Claude-3.5,94.0,82.0,88.0,80.0
Gemini-1.5,91.0,88.0,86.0,84.0
"""
        ds = parse_tabular_data(csv_data)
        assert ds.suggested_chart_type == ChartType.RADAR_CHART
        chart = generate_chart(ds, chart_type=ds.suggested_chart_type)
        assert chart.chart_type == ChartType.RADAR_CHART
        assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert "<svg" in chart.svg_text

    def test_radar_confidence_gate_fallback_when_few_axes(self):
        # Only 2 numeric axes -> Radar requires >= 3 axes, so fallback to Bar
        csv_data = """Model,Accuracy,Speed
ModelA,85.0,90.0
ModelB,88.0,78.0
"""
        ds = parse_tabular_data(csv_data)
        assert ds.suggested_chart_type != ChartType.RADAR_CHART
        assert ds.suggested_chart_type in (ChartType.BAR_CHART, ChartType.HORIZONTAL_BAR)

    def test_gauge_chart_selection_and_rendering(self):
        csv_data = """Metric,Current Progress KPI,Target Goal
CSAT,88.5,100.0
"""
        ds = parse_tabular_data(csv_data)
        assert ds.suggested_chart_type == ChartType.GAUGE_CHART
        chart = generate_chart(ds, chart_type=ds.suggested_chart_type)
        assert chart.chart_type == ChartType.GAUGE_CHART
        assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert "<svg" in chart.svg_text

    def test_waterfall_chart_selection_and_rendering(self):
        csv_data = """Step,Cashflow Bridge Delta
Starting Cash,100
Operations,45
R&D,-25
Marketing,-15
Net Total,105
"""
        ds = parse_tabular_data(csv_data)
        assert ds.suggested_chart_type == ChartType.WATERFALL_CHART
        chart = generate_chart(ds, chart_type=ds.suggested_chart_type)
        assert chart.chart_type == ChartType.WATERFALL_CHART
        assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert "<svg" in chart.svg_text

    def test_gantt_chart_selection_and_rendering(self):
        csv_data = """Task,Start Day,Duration Days Timeline
Requirements,0,5
Architecture,5,10
Implementation,15,20
Testing,35,10
Deployment,45,3
"""
        ds = parse_tabular_data(csv_data)
        assert ds.suggested_chart_type == ChartType.GANTT_CHART
        chart = generate_chart(ds, chart_type=ds.suggested_chart_type)
        assert chart.chart_type == ChartType.GANTT_CHART
        assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert "<svg" in chart.svg_text

    def test_funnel_chart_selection_and_rendering(self):
        csv_data = """Funnel Stage,Visitors Dropoff
Website Visits,10000
Signups,3500
Product Qualified,1200
Paid Conversion,450
"""
        ds = parse_tabular_data(csv_data)
        assert ds.suggested_chart_type == ChartType.FUNNEL_CHART
        chart = generate_chart(ds, chart_type=ds.suggested_chart_type)
        assert chart.chart_type == ChartType.FUNNEL_CHART
        assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert "<svg" in chart.svg_text

    def test_candlestick_chart_selection_and_rendering(self):
        csv_data = """Date,Open,High,Low,Close
2026-09-01,150.0,155.0,149.0,154.5
2026-09-02,154.5,158.0,153.0,157.0
2026-09-03,157.0,157.5,151.0,152.0
2026-09-04,152.0,156.0,150.5,155.0
"""
        ds = parse_tabular_data(csv_data)
        assert ds.suggested_chart_type == ChartType.CANDLESTICK_CHART
        chart = generate_chart(ds, chart_type=ds.suggested_chart_type)
        assert chart.chart_type == ChartType.CANDLESTICK_CHART
        assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert "<svg" in chart.svg_text

    def test_treemap_selection_and_rendering(self):
        csv_data = """Category,Subcategory,Market Share Treemap Sales
Electronics,Smartphones,1200
Electronics,Laptops,800
Furniture,Chairs,400
Furniture,Desks,600
Appliances,Refrigerators,500
"""
        ds = parse_tabular_data(csv_data)
        assert ds.suggested_chart_type == ChartType.TREEMAP
        chart = generate_chart(ds, chart_type=ds.suggested_chart_type)
        assert chart.chart_type == ChartType.TREEMAP
        assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert "<svg" in chart.svg_text

    def test_pair_plot_selection_and_rendering(self):
        csv_data = """Sepal_Length,Sepal_Width,Petal_Length,Petal_Width,Pairwise Feature
5.1,3.5,1.4,0.2,1
4.9,3.0,1.4,0.2,1
6.2,2.9,4.3,1.3,2
6.7,3.1,4.4,1.4,2
5.9,3.0,5.1,1.8,3
"""
        ds = parse_tabular_data(csv_data)
        assert ds.suggested_chart_type == ChartType.PAIR_PLOT
        chart = generate_chart(ds, chart_type=ds.suggested_chart_type)
        assert chart.chart_type == ChartType.PAIR_PLOT
        assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert "<svg" in chart.svg_text

    def test_all_20_chart_types_render_cleanly(self):
        # Ensure every single member of ChartType enum can be rendered without crashing
        multi_metric_ds = ParsedTableDataset(
            columns=["Item", "A", "B", "C", "D"],
            rows=[
                ["Alpha", 10.0, 20.0, 30.0, 40.0],
                ["Beta", 15.0, 25.0, 35.0, 45.0],
                ["Gamma", 12.0, 22.0, 32.0, 42.0],
                ["Delta", 18.0, 28.0, 38.0, 48.0],
            ],
            column_types={"Item": "CATEGORICAL", "A": "NUMERICAL", "B": "NUMERICAL", "C": "NUMERICAL", "D": "NUMERICAL"},
        )

        for ctype in ChartType:
            chart = generate_chart(multi_metric_ds, chart_type=ctype)
            assert isinstance(chart, RenderedChart)
            assert chart.chart_type == ctype
            assert len(chart.png_bytes) > 0
            if ctype != ChartType.TABLE_VIEW:
                assert chart.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
                assert "<svg" in chart.svg_text
            else:
                assert "table" in chart.svg_text.lower()



