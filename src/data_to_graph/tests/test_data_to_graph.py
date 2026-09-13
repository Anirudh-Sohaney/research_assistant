"""Unit tests for data_to_graph subsystem."""

import os
import sys

import pytest

_src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from data_to_graph.models import ChartStyleConfig, ChartType, ParsedTableDataset, RenderedChart
from data_to_graph.grapher import (
    TableGraphEngine,
    parse_tabular_data,
    generate_chart,
    toggle_chart_type,
)


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
