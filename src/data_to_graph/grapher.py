"""Table Parsing and Academic Graphic Rendering Engine (100% Zero-Token)."""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from data_to_graph.models import (
    ChartStyleConfig,
    ChartType,
    ParsedTableDataset,
    RenderedChart,
)

log = logging.getLogger("data_to_graph")


def _clean_cell(val: str) -> Any:
    """Strip units, currency, whitespace, and coerce to float/int if possible."""
    s = val.strip().replace("$", "").replace("%", "").replace(",", "")
    # Strip common units like ms, s, kb, mb, gb
    s_no_unit = re.sub(r"(?i)\b(ms|s|kb|mb|gb|kg|m|cm|mm)\b", "", s).strip()
    try:
        if "." in s_no_unit:
            return float(s_no_unit)
        return int(s_no_unit)
    except (ValueError, TypeError):
        return val.strip()


class TableGraphEngine:
    """Parses raw table text across Markdown, LaTeX, CSV, TSV and renders academic figures."""

    def parse_tabular_data(self, raw_table_text: str) -> ParsedTableDataset:
        """Parses multi-format tabular text into columns, rows, and inferred types."""
        text = raw_table_text.strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ParsedTableDataset(columns=[], rows=[], format_detected="EMPTY")

        format_detected = "CSV"
        raw_rows: List[List[str]] = []

        # 1. LaTeX Tabular Sniffer
        if "\\begin{tabular}" in text or any("&" in line and "\\\\" in line for line in lines):
            format_detected = "LATEX"
            for line in lines:
                if any(kw in line for kw in ("\\begin{tabular}", "\\end{tabular}", "\\hline", "\\toprule", "\\midrule", "\\bottomrule")):
                    continue
                clean_line = line.replace("\\\\", "").strip()
                if clean_line:
                    cells = [c.strip() for c in clean_line.split("&")]
                    raw_rows.append(cells)

        # 2. Markdown Pipe Table Sniffer
        elif any("|" in line for line in lines):
            format_detected = "MARKDOWN"
            for line in lines:
                if re.match(r"^\|?[\s\-:|]+\|?$", line):
                    continue  # Separator line like |---|---|
                cells = [c.strip() for c in line.split("|")]
                if cells and cells[0] == "":
                    cells.pop(0)
                if cells and cells[-1] == "":
                    cells.pop()
                if cells:
                    raw_rows.append(cells)

        # 3. TSV / CSV / Whitespace Fallback
        else:
            delimiter = "\t" if "\t" in lines[0] else "," if "," in lines[0] else None
            if delimiter:
                format_detected = "TSV" if delimiter == "\t" else "CSV"
                reader = csv.reader(lines, delimiter=delimiter)
                raw_rows = [[c.strip() for c in r] for r in reader if r]
            else:
                format_detected = "WHITESPACE"
                for line in lines:
                    cells = re.split(r"\s{2,}|\t", line)
                    raw_rows.append([c.strip() for c in cells if c.strip()])

        if not raw_rows:
            return ParsedTableDataset(columns=[], rows=[], format_detected=format_detected)

        # Separate header and data
        header = raw_rows[0]
        data_rows = raw_rows[1:] if len(raw_rows) > 1 else raw_rows

        columns = [str(h) if h else f"Col_{i}" for i, h in enumerate(header)]
        parsed_rows: List[List[Any]] = []

        for row in data_rows:
            # Pad or truncate row to header length
            row_padded = row + [""] * max(0, len(columns) - len(row))
            parsed_rows.append([_clean_cell(c) for c in row_padded[: len(columns)]])

        # Infer column types
        column_types: Dict[str, str] = {}
        for col_idx, col_name in enumerate(columns):
            values = [r[col_idx] for r in parsed_rows if r[col_idx] != ""]
            num_count = sum(1 for v in values if isinstance(v, (int, float)))
            if values and num_count / len(values) >= 0.7:
                column_types[col_name] = "NUMERICAL"
            else:
                column_types[col_name] = "CATEGORICAL"

        # Heuristic chart type selection
        suggested = ChartType.BAR_CHART
        types_list = [column_types.get(c) for c in columns]
        if len(types_list) >= 2:
            if types_list[0] == "CATEGORICAL" and any(t == "NUMERICAL" for t in types_list[1:]):
                suggested = ChartType.BAR_CHART
            elif types_list[0] == "NUMERICAL" and types_list[1] == "NUMERICAL":
                suggested = ChartType.SCATTER_DOT

        return ParsedTableDataset(
            columns=columns,
            rows=parsed_rows,
            column_types=column_types,
            format_detected=format_detected,
            suggested_chart_type=suggested,
        )

    def generate_chart(
        self,
        dataset: ParsedTableDataset,
        chart_type: Optional[ChartType] = None,
        style: Optional[ChartStyleConfig] = None,
    ) -> RenderedChart:
        """Renders publication-ready 300 DPI PNG and SVG vector graphics."""
        target_type = chart_type or dataset.suggested_chart_type
        cfg = style or ChartStyleConfig()

        fig, ax = plt.subplots(figsize=(6.5, 4.0), dpi=cfg.dpi)
        fig.patch.set_facecolor("white")
        ax.set_facecolor("#FAFAFA")
        ax.grid(True, linestyle="--", alpha=0.5, color="#CCCCCC", zorder=0)

        # Identify axes
        cat_cols = [c for c, t in dataset.column_types.items() if t == "CATEGORICAL"]
        num_cols = [c for c, t in dataset.column_types.items() if t == "NUMERICAL"]

        x_col = cat_cols[0] if cat_cols else (num_cols[0] if num_cols else dataset.columns[0])
        x_idx = dataset.columns.index(x_col)
        y_cols = [c for c in num_cols if c != x_col]
        if not y_cols and len(dataset.columns) > 1:
            y_cols = [dataset.columns[1]]

        x_vals = [str(r[x_idx]) for r in dataset.rows]

        # Render Chart Variety
        colors = ["#2B5C8F", "#D95F02", "#7570B3", "#1B9E77", "#E7298A"]

        if target_type == ChartType.BAR_CHART:
            y_col = y_cols[0] if y_cols else dataset.columns[-1]
            y_idx = dataset.columns.index(y_col)
            y_vals = [float(r[y_idx]) if isinstance(r[y_idx], (int, float)) else 0.0 for r in dataset.rows]
            bars = ax.bar(x_vals, y_vals, color=colors[0], alpha=0.88, zorder=3, width=0.55)
            ax.set_ylabel(y_col)

        elif target_type == ChartType.LINE_CHART:
            for idx, y_col in enumerate(y_cols[:3]):
                y_idx = dataset.columns.index(y_col)
                y_vals = [float(r[y_idx]) if isinstance(r[y_idx], (int, float)) else 0.0 for r in dataset.rows]
                ax.plot(x_vals, y_vals, marker="o", color=colors[idx % len(colors)], label=y_col, zorder=3)
            if len(y_cols) > 1:
                ax.legend(frameon=True)

        elif target_type == ChartType.SCATTER_DOT:
            x_num = [float(r[x_idx]) if isinstance(r[x_idx], (int, float)) else i for i, r in enumerate(dataset.rows)]
            y_col = y_cols[0] if y_cols else dataset.columns[-1]
            y_idx = dataset.columns.index(y_col)
            y_vals = [float(r[y_idx]) if isinstance(r[y_idx], (int, float)) else 0.0 for r in dataset.rows]
            ax.scatter(x_num, y_vals, color=colors[1], s=60, edgecolors="black", alpha=0.85, zorder=3)
            ax.set_ylabel(y_col)

        elif target_type == ChartType.HISTOGRAM:
            y_col = y_cols[0] if y_cols else (num_cols[0] if num_cols else dataset.columns[0])
            y_idx = dataset.columns.index(y_col)
            y_vals = [float(r[y_idx]) for r in dataset.rows if isinstance(r[y_idx], (int, float))]
            ax.hist(y_vals, bins=max(3, len(y_vals) // 2), color=colors[2], edgecolor="white", zorder=3)
            ax.set_xlabel(y_col)
            ax.set_ylabel("Frequency")

        elif target_type == ChartType.BOX_PLOT:
            y_data = []
            for y_col in y_cols[:4]:
                y_idx = dataset.columns.index(y_col)
                vals = [float(r[y_idx]) for r in dataset.rows if isinstance(r[y_idx], (int, float))]
                if vals:
                    y_data.append(vals)
            if y_data:
                ax.boxplot(y_data, tick_labels=y_cols[: len(y_data)], zorder=3)

        # Styling titles and clean academic spines
        ax.set_title(cfg.title or f"{target_type.value.replace('_', ' ').title()}", fontsize=11, fontweight="bold")
        ax.set_xlabel(cfg.x_label or x_col)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        plt.xticks(rotation=20 if len(x_vals) > 4 else 0, ha="right" if len(x_vals) > 4 else "center")
        plt.tight_layout()

        # Render outputs to memory buffers
        png_buf = io.BytesIO()
        svg_buf = io.StringIO()
        fig.savefig(png_buf, format="png", dpi=cfg.dpi)
        fig.savefig(svg_buf, format="svg")
        plt.close(fig)

        alternatives = [
            t for t in [ChartType.BAR_CHART, ChartType.LINE_CHART, ChartType.SCATTER_DOT, ChartType.BOX_PLOT]
            if t != target_type
        ]

        return RenderedChart(
            png_bytes=png_buf.getvalue(),
            svg_text=svg_buf.getvalue(),
            chart_type=target_type,
            dataset=dataset,
            available_alternatives=alternatives,
        )

    def toggle_chart_type(
        self, current_chart: RenderedChart, next_type: ChartType
    ) -> RenderedChart:
        """Sub-40ms re-rendering of existing dataset under an alternative chart type."""
        return self.generate_chart(current_chart.dataset, chart_type=next_type)


_global_table_graph_engine = TableGraphEngine()


def parse_tabular_data(raw_table_text: str) -> ParsedTableDataset:
    return _global_table_graph_engine.parse_tabular_data(raw_table_text)


def generate_chart(
    dataset: ParsedTableDataset,
    chart_type: Optional[ChartType] = None,
    style: Optional[ChartStyleConfig] = None,
) -> RenderedChart:
    return _global_table_graph_engine.generate_chart(dataset, chart_type, style)


def toggle_chart_type(current_chart: RenderedChart, next_type: ChartType) -> RenderedChart:
    return _global_table_graph_engine.toggle_chart_type(current_chart, next_type)
