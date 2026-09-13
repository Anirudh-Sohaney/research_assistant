"""Table Parsing and Academic Graphic Rendering Engine (100% Zero-Token)."""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from data_to_graph.models import (
    ChartStyleConfig,
    ChartType,
    ParsedTableDataset,
    RenderedChart,
)

log = logging.getLogger("data_to_graph")

# Scholarly Palettes (High-contrast, publication-grade)
PALETTES: Dict[str, List[str]] = {
    "academic": ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f"],
    "colorblind": ["#0072B2", "#D55E00", "#009E73", "#F0E442", "#CC79A7", "#56B4E9", "#E69F00", "#000000"],
    "scifi": ["#00E5FF", "#FF0055", "#00FF66", "#FFEA00", "#D500F9", "#76FF03", "#E040FB", "#FF6D00"],
    "grayscale": ["#1A1A1A", "#4A4A4A", "#7A7A7A", "#A0A0A0", "#C5C5C5", "#E0E0E0"],
    "seaborn": ["#2B5C8F", "#D95F02", "#7570B3", "#1B9E77", "#E7298A", "#66A61E", "#E6AB02"],
}

# Common units stripped from cell numbers (matches both "12ms" and "12 ms")
UNITS_REGEX = re.compile(
    r"(?i)(?:(?<=\d|\s)|(?<=^))(?:ms|s|sec|secs|min|mins|hr|hrs|hours|ns|us|μs|"
    r"kb|mb|gb|tb|pb|b|kib|mib|gib|"
    r"bps|kbps|mbps|gbps|"
    r"hz|khz|mhz|ghz|"
    r"m|cm|mm|um|μm|nm|km|"
    r"kg|g|mg|ug|"
    r"v|mv|a|ma|w|kw|mw|"
    r"db|dbm|px|pt|x)\b"
)

CURRENCY_REGEX = re.compile(r"[$€£¥₹₩]|CHF|USD|EUR")
NULL_SENTINELS = {"n/a", "na", "-", "—", "none", "null", "nan", "?", ""}


def _clean_latex_text(text: str) -> str:
    """Strips common LaTeX markup tags and preserves raw textual labels."""
    s = text.strip()
    # Unescape escaped special characters
    s = s.replace(r"\&", "&").replace(r"\%", "%").replace(r"\$", "$").replace(r"\_", "_")
    # Convert math symbols like \pm to unicode
    s = s.replace(r"\pm", "±").replace(r"\times", "x")
    s = re.sub(r"\$([^$]*)\$", r"\1", s)  # strip math mode $...$
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\\\.*$", "", s)
    return s.strip()


def _clean_markdown_text(text: str) -> str:
    """Strips Markdown bold, italic, and code decorations."""
    s = text.strip()
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"\*([^*]+)\*", r"\1", s)
    s = re.sub(r"__([^_]+)__", r"\1", s)
    s = re.sub(r"_([^_]+)_", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    return s.strip()


def _is_numeric_token(s: str) -> bool:
    """Fast check if a string token is primarily numeric (ignoring currencies, commas, units)."""
    cleaned = s.replace(",", "").replace("$", "").replace("€", "").replace("£", "").replace("¥", "").replace("%", "").strip()
    return bool(re.match(r"^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$", cleaned))


def _detect_linear_html_table(lines: List[str]) -> Optional[Tuple[List[str], List[List[str]]]]:
    """Detects if lines represent a single-column linear sequence copied from an HTML table."""
    clean_lines = [l.strip() for l in lines if l.strip()]
    if len(clean_lines) < 4:
        return None

    first_num_idx = next((i for i, l in enumerate(clean_lines) if _is_numeric_token(l)), None)
    candidate_ks = []
    if first_num_idx and 1 <= first_num_idx <= 12:
        candidate_ks.append(first_num_idx)

    for k in range(2, min(9, len(clean_lines) // 2 + 1)):
        if k not in candidate_ks:
            candidate_ks.append(k)

    best_k = None
    best_score = -1.0

    for k in candidate_ks:
        rem = (len(clean_lines) - k) % k
        if rem == 0 and (len(clean_lines) - k) >= k:
            rows_count = (len(clean_lines) - k) // k
            header_text_count = sum(1 for h in clean_lines[:k] if not _is_numeric_token(h))
            consistent_cols = 0
            for col_idx in range(k):
                col_vals = [clean_lines[k + r * k + col_idx] for r in range(rows_count)]
                num_ratio = sum(1 for v in col_vals if _is_numeric_token(v)) / rows_count
                if num_ratio >= 0.8 or num_ratio <= 0.2:
                    consistent_cols += 1

            score = (header_text_count / k) * 2.0 + (consistent_cols / k) * 3.0
            if first_num_idx == k:
                score += 5.0

            if score > best_score and consistent_cols >= 1:
                best_score = score
                best_k = k

    if best_k is not None:
        header = clean_lines[:best_k]
        rows = [clean_lines[best_k + r * best_k : best_k + (r + 1) * best_k] for r in range((len(clean_lines) - best_k) // best_k)]
        return header, rows

    return None


def _clean_cell_with_meta(val: str) -> Tuple[Any, Optional[str], Optional[float]]:
    """Extracts numeric value, detected unit, and uncertainty/standard error if present."""
    raw = val.strip()
    if raw.lower() in NULL_SENTINELS:
        return None, None, None

    # Check for uncertainty / standard deviation: e.g. "85.4 ± 1.2" or "85.4 +/- 1.2"
    uncertainty: Optional[float] = None
    std_match = re.search(r"(\s*(?:±|\+\/-)\s*)([\d.]+)", raw)
    if std_match:
        try:
            uncertainty = float(std_match.group(2))
        except ValueError:
            pass
        raw = raw[: std_match.start()] + raw[std_match.end() :]

    detected_unit: Optional[str] = None

    # Detect currency
    cur_match = CURRENCY_REGEX.search(raw)
    if cur_match:
        detected_unit = cur_match.group(0).strip()
        raw = CURRENCY_REGEX.sub("", raw).strip()

    # Detect percentage
    if "%" in raw:
        detected_unit = "%"
        raw = raw.replace("%", "").strip()

    # Detect accounting negative: (123.45) -> -123.45
    is_paren_negative = False
    if raw.startswith("(") and raw.endswith(")"):
        is_paren_negative = True
        raw = raw[1:-1].strip()

    # Detect metric units
    unit_match = UNITS_REGEX.search(raw)
    if unit_match and not detected_unit:
        detected_unit = unit_match.group(0).strip()

    # Strip units and formatting
    cleaned = raw.replace(",", "").replace("$", "").replace("%", "").strip()
    cleaned_no_unit = UNITS_REGEX.sub("", cleaned).strip()

    if is_paren_negative:
        cleaned_no_unit = f"-{cleaned_no_unit}"

    try:
        # Explicit checks for int vs float
        if re.match(r"^-?\d+\.\d+$", cleaned_no_unit) or (
            "." in cleaned_no_unit and re.match(r"^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$", cleaned_no_unit)
        ):
            return float(cleaned_no_unit), detected_unit, uncertainty
        if re.match(r"^-?\d+$", cleaned_no_unit):
            return int(cleaned_no_unit), detected_unit, uncertainty
        if re.match(r"^-?\d+[eE][+-]?\d+$", cleaned_no_unit):
            return float(cleaned_no_unit), detected_unit, uncertainty
    except (ValueError, TypeError):
        pass

    return val.strip(), detected_unit, uncertainty


def _clean_cell(val: str) -> Any:
    """Backward-compatible helper: coerce cell to native float/int if possible."""
    res, _, _ = _clean_cell_with_meta(val)
    return val.strip() if res is None and val.strip().lower() not in NULL_SENTINELS else res


def _extract_table_heading(raw_text: str) -> Tuple[Optional[str], str]:
    """Extracts any table heading or caption directly attached above the table."""
    lines = raw_text.strip().splitlines()
    if not lines:
        return None, raw_text

    extracted_title = None
    remaining_lines = []

    for i, line in enumerate(lines):
        trimmed = line.strip()
        if not trimmed:
            continue

        # Check for LaTeX \caption{...} or \caption*{...}
        caption_match = re.search(r"\\caption\*?\{([^}]+)\}", trimmed)
        if caption_match:
            extracted_title = _clean_latex_text(caption_match.group(1)).strip()
            continue

        # Check for Markdown headers: #, ##, ###, ####, etc.
        md_match = re.match(r"^#{1,6}\s+(.+)$", trimmed)
        if md_match and extracted_title is None and not any(delim in trimmed for delim in ("|", "\t")):
            extracted_title = _clean_markdown_text(md_match.group(1)).strip()
            continue

        # Check for [Table: Title] or [Table N: Title] or Table N: Title
        tbl_match = re.match(r"^\[?(?:Table|Figure|Tab\.)\s*[\d.:\-]*\s*[:\-–—]?\s*(.+?)\]?$", trimmed, re.IGNORECASE)
        if tbl_match and extracted_title is None and not any(delim in trimmed for delim in ("|", "\t")):
            extracted_title = _clean_markdown_text(tbl_match.group(1)).strip()
            continue

        # Check for leading non-delimited title line (e.g. "Sales by Region")
        if (
            i == 0
            and len(lines) > 1
            and extracted_title is None
            and len(trimmed) >= 3
            and any(c.isalnum() for c in trimmed)
            and not trimmed.startswith(("[", "{", "("))
        ):
            next_lines = [l.strip() for l in lines[1:4] if l.strip()]
            if next_lines and any(d in next_lines[0] for d in ("|", ",", "\t", "\\begin")):
                if not any(delim in trimmed for delim in ("|", ",", "\t", "\\")):
                    extracted_title = _clean_markdown_text(trimmed)
                    continue

        remaining_lines.append(line)

    cleaned_text = "\n".join(remaining_lines).strip()
    return extracted_title, cleaned_text if cleaned_text else raw_text


class TableGraphEngine:
    """Parses raw table text across Markdown, LaTeX, CSV, TSV, JSON, ASCII and renders academic figures."""

    def parse_tabular_data(self, raw_table_text: str) -> ParsedTableDataset:
        """Parses multi-format tabular text into columns, rows, and inferred types."""
        extracted_title, text = _extract_table_heading(raw_table_text)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ParsedTableDataset(columns=[], rows=[], format_detected="EMPTY", group_name=extracted_title)

        format_detected = "CSV"
        raw_rows: List[List[str]] = []

        # 1. JSON Array of Objects / Dictionary Sniffer
        if (text.startswith("[") and text.endswith("]")) or (text.startswith("{") and text.endswith("}")):
            try:
                parsed_json = json.loads(text)
                if isinstance(parsed_json, list) and parsed_json and isinstance(parsed_json[0], dict):
                    format_detected = "JSON"
                    keys = list(parsed_json[0].keys())
                    raw_rows.append(keys)
                    for item in parsed_json:
                        raw_rows.append([str(item.get(k, "")) for k in keys])
                elif isinstance(parsed_json, dict) and parsed_json:
                    format_detected = "JSON"
                    keys = list(parsed_json.keys())
                    first_val = parsed_json[keys[0]]
                    if isinstance(first_val, list):
                        raw_rows.append(keys)
                        max_len = max(len(v) for v in parsed_json.values() if isinstance(v, list))
                        for i in range(max_len):
                            raw_rows.append([str(parsed_json[k][i]) if i < len(parsed_json[k]) else "" for k in keys])
            except Exception:
                pass

        # 2. LaTeX Tabular Sniffer
        if not raw_rows and (
            "\\begin{tabular}" in text or any("&" in line and ("\\\\" in line or line.endswith("\\")) for line in lines)
        ):
            format_detected = "LATEX"
            for line in lines:
                if line.startswith("%"):
                    continue
                if any(
                    kw in line
                    for kw in (
                        "\\begin{tabular}",
                        "\\end{tabular}",
                        "\\hline",
                        "\\toprule",
                        "\\midrule",
                        "\\bottomrule",
                        "\\cline",
                    )
                ):
                    continue
                clean_line = re.sub(r"(?<!\\)%.*$", "", line)
                clean_line = clean_line.replace("\\\\", "").strip()
                if clean_line and "&" in clean_line:
                    cells = [_clean_latex_text(c) for c in clean_line.split("&")]
                    raw_rows.append(cells)

        # 3. Unicode & ASCII Box-Drawing Table Sniffer
        if not raw_rows and any(
            any(char in line for char in ("┌", "┬", "┐", "├", "┼", "┤", "└", "┴", "┘", "│", "═", "║"))
            or (line.startswith("+") and "-" in line)
            for line in lines
        ):
            format_detected = "BOX_ASCII"
            for line in lines:
                if re.match(r"^[\s\+\-\=\|\#\:\.\_┌┬┐├┼┤└┴┘─═║]+$", line) and not re.search(r"[a-zA-Z0-9]", line):
                    continue
                split_char = "│" if "│" in line else "|" if "|" in line else None
                if split_char:
                    cells = [c.strip() for c in line.split(split_char)]
                    if cells and cells[0] == "":
                        cells.pop(0)
                    if cells and cells[-1] == "":
                        cells.pop()
                    if cells:
                        raw_rows.append(cells)

        # 4. Markdown Pipe Table Sniffer
        if not raw_rows and any("|" in line for line in lines):
            format_detected = "MARKDOWN"
            table_lines = [l for l in lines if "|" in l]
            for line in table_lines:
                if re.match(r"^\|?[\s\-:|]+\|?$", line):
                    continue
                cells = [_clean_markdown_text(c) for c in line.split("|")]
                if cells and cells[0] == "":
                    cells.pop(0)
                if cells and cells[-1] == "":
                    cells.pop()
                if cells:
                    raw_rows.append(cells)

        # 5. TSV / Semicolon / CSV / Whitespace / HTML-Clipboard Fallback
        if not raw_rows:
            delimiter = "\t" if "\t" in lines[0] else ";" if ";" in lines[0] else "," if "," in lines[0] else None
            if delimiter:
                format_detected = "TSV" if delimiter == "\t" else "SEMICOLON" if delimiter == ";" else "CSV"
                reader = csv.reader(lines, delimiter=delimiter)
                raw_rows = [[c.strip() for c in r] for r in reader if r]
            else:
                linear_res = _detect_linear_html_table(lines)
                if linear_res:
                    format_detected = "HTML_CLIPBOARD"
                    l_hdr, l_rows = linear_res
                    raw_rows = [l_hdr] + l_rows
                else:
                    format_detected = "WHITESPACE"
                    for line in lines:
                        cells = re.split(r"\s{2,}|\t", line)
                        raw_rows.append([c.strip() for c in cells if c.strip()])

        if not raw_rows:
            return ParsedTableDataset(columns=[], rows=[], format_detected=format_detected)

        header = raw_rows[0]
        data_rows = raw_rows[1:] if len(raw_rows) > 1 else raw_rows

        seen_cols: Dict[str, int] = {}
        columns: List[str] = []
        for i, h in enumerate(header):
            col_name = str(h).strip() if h else f"Col_{i}"
            if col_name in seen_cols:
                seen_cols[col_name] += 1
                columns.append(f"{col_name}_{seen_cols[col_name]}")
            else:
                seen_cols[col_name] = 0
                columns.append(col_name)

        parsed_rows: List[List[Any]] = []
        uncertainties: Dict[int, List[Optional[float]]] = {i: [] for i in range(len(columns))}
        detected_units: Dict[int, List[str]] = {i: [] for i in range(len(columns))}

        for row in data_rows:
            row_padded = row + [""] * max(0, len(columns) - len(row))
            parsed_row = []
            for col_idx, cell in enumerate(row_padded[: len(columns)]):
                val, unit, unc = _clean_cell_with_meta(cell)
                parsed_row.append(val if val is not None else "")
                uncertainties[col_idx].append(unc)
                if unit:
                    detected_units[col_idx].append(unit)
            parsed_rows.append(parsed_row)

        column_types: Dict[str, str] = {}
        column_units: Dict[str, str] = {}
        for col_idx, col_name in enumerate(columns):
            values = [r[col_idx] for r in parsed_rows if r[col_idx] != ""]
            num_count = sum(1 for v in values if isinstance(v, (int, float)) and not isinstance(v, bool))
            if values and num_count / len(values) >= 0.7:
                column_types[col_name] = "NUMERICAL"
            else:
                column_types[col_name] = "CATEGORICAL"

            units_list = detected_units.get(col_idx, [])
            if units_list:
                from collections import Counter
                dominant_unit, count = Counter(units_list).most_common(1)[0]
                if count / max(1, len(values)) >= 0.4:
                    column_units[col_name] = dominant_unit

        temp_ds = ParsedTableDataset(
            columns=columns,
            rows=parsed_rows,
            column_types=column_types,
            format_detected=format_detected,
            suggested_chart_type=ChartType.BAR_CHART,
            column_units=column_units,
            uncertainties=uncertainties,
            group_name=extracted_title,
        )
        from data_to_graph.chart_selector import select_chart_type
        selection_res = select_chart_type(temp_ds)

        return ParsedTableDataset(
            columns=columns,
            rows=parsed_rows,
            column_types=column_types,
            format_detected=format_detected,
            suggested_chart_type=selection_res.suggested_chart_type,
            column_units=column_units,
            uncertainties=uncertainties,
            confidence_score=selection_res.confidence_score,
            fallback_reason=selection_res.fallback_reason,
            group_name=extracted_title,
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

        fig_size = getattr(cfg, "figure_size", (6.5, 4.0))
        fig, ax = plt.subplots(figsize=fig_size, dpi=cfg.dpi)

        is_dark = getattr(cfg, "dark_mode", False)
        bg_color = "#121212" if is_dark else "white"
        ax_bg_color = "#1E1E1E" if is_dark else "#FAFAFA"
        text_color = "#E0E0E0" if is_dark else "#222222"
        grid_color = "#333333" if is_dark else "#E5E5E5"
        spine_color = "#555555" if is_dark else "#888888"

        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(ax_bg_color)
        if getattr(cfg, "show_grid", True):
            ax.grid(True, linestyle="--", alpha=0.6, color=grid_color, zorder=0)

        palette_key = getattr(cfg, "palette", "academic")
        if palette_key not in PALETTES:
            palette_key = "scifi" if is_dark else "academic"
        colors = PALETTES[palette_key]

        cat_cols = [c for c, t in dataset.column_types.items() if t == "CATEGORICAL"]
        num_cols = [c for c, t in dataset.column_types.items() if t == "NUMERICAL"]

        if not dataset.columns:
            ax.text(0.5, 0.5, "No Tabular Data Provided", ha="center", va="center", color=text_color, fontsize=12)
            png_buf = io.BytesIO()
            svg_buf = io.StringIO()
            fig.savefig(png_buf, format="png", dpi=cfg.dpi, bbox_inches="tight")
            fig.savefig(svg_buf, format="svg", bbox_inches="tight")
            plt.close(fig)
            return RenderedChart(
                png_bytes=png_buf.getvalue(),
                svg_text=svg_buf.getvalue(),
                chart_type=target_type,
                dataset=dataset,
                available_alternatives=[],
            )

        # Determine independent X axis and dependent Y metrics with high correlation
        col0 = dataset.columns[0]
        from data_to_graph.chart_selector import is_datetime_or_sequential
        col0_vals = [r[0] for r in dataset.rows if r]
        is_col0_seq = is_datetime_or_sequential(col0, col0_vals)

        if dataset.column_types.get(col0) == "CATEGORICAL" or is_col0_seq or not cat_cols:
            x_col = col0
        else:
            x_col = cat_cols[0]

        x_idx = dataset.columns.index(x_col)
        y_cols = [c for c in num_cols if c != x_col]
        if not y_cols and len(dataset.columns) > 1:
            y_cols = [c for c in dataset.columns if c != x_col]

        x_vals = [str(r[x_idx]) if r[x_idx] != "" else f"Item_{i+1}" for i, r in enumerate(dataset.rows)]
        x_unit = dataset.column_units.get(x_col, "")
        x_label_text = cfg.x_label or (f"{x_col} ({x_unit})" if x_unit and f"({x_unit})" not in x_col else x_col)
        active_y_cols = y_cols[:4] if len(y_cols) > 1 else (y_cols[:1] if y_cols else [dataset.columns[-1]])

        if target_type == ChartType.BAR_CHART:
            active_y_cols = y_cols[:4] if len(y_cols) > 1 else (y_cols[:1] if y_cols else [dataset.columns[-1]])
            n_series = len(active_y_cols)
            n_rows = len(dataset.rows)
            indices = np.arange(n_rows)
            bar_width = 0.75 / max(1, n_series)

            for s_idx, col_name in enumerate(active_y_cols):
                c_idx = dataset.columns.index(col_name)
                y_vals = [float(r[c_idx]) if isinstance(r[c_idx], (int, float)) else 0.0 for r in dataset.rows]
                y_errs = dataset.uncertainties.get(c_idx, [])
                err_arr = [float(e) if isinstance(e, (int, float)) else 0.0 for e in y_errs] if any(y_errs) else None

                offset = (s_idx - (n_series - 1) / 2.0) * bar_width
                color = colors[s_idx % len(colors)]
                bars = ax.bar(
                    indices + offset,
                    y_vals,
                    width=bar_width,
                    color=color,
                    label=col_name,
                    alpha=0.9,
                    edgecolor=bg_color,
                    linewidth=0.5,
                    yerr=err_arr if err_arr and any(err_arr) else None,
                    capsize=3 if err_arr and any(err_arr) else 0,
                    zorder=3,
                )

                if (getattr(cfg, "show_values", False) or n_rows <= 8) and n_series <= 2:
                    for bar in bars:
                        h = bar.get_height()
                        if not math.isnan(h) and abs(h) > 0.001:
                            val_str = f"{h:.1f}" if isinstance(h, float) and not h.is_integer() else f"{int(h)}"
                            va = "bottom" if h >= 0 else "top"
                            ax.annotate(
                                val_str,
                                xy=(bar.get_x() + bar.get_width() / 2, h),
                                xytext=(0, 2 if h >= 0 else -6),
                                textcoords="offset points",
                                ha="center",
                                va=va,
                                fontsize=7.5,
                                color=text_color,
                            )

            ax.set_xticks(indices)
            ax.set_xticklabels(x_vals)
            y_unit = dataset.column_units.get(active_y_cols[0], "")
            y_col_title = active_y_cols[0] if len(active_y_cols) == 1 else "Values"
            ax.set_ylabel(
                cfg.y_label or (f"{y_col_title} ({y_unit})" if y_unit and f"({y_unit})" not in y_col_title else y_col_title),
                color=text_color,
            )
            if n_series > 1:
                ax.legend(frameon=True, facecolor=ax_bg_color, edgecolor=grid_color, fontsize=8)

        elif target_type == ChartType.HORIZONTAL_BAR:
            y_col = y_cols[0] if y_cols else dataset.columns[-1]
            y_idx = dataset.columns.index(y_col)
            y_vals = [float(r[y_idx]) if isinstance(r[y_idx], (int, float)) else 0.0 for r in dataset.rows]
            y_pos = np.arange(len(x_vals))

            ax.barh(y_pos, y_vals, color=colors[0], alpha=0.9, edgecolor=bg_color, linewidth=0.5, zorder=3)
            ax.set_yticks(y_pos)
            ax.set_yticklabels(x_vals, color=text_color, fontsize=8)
            ax.invert_yaxis()
            y_unit = dataset.column_units.get(y_col, "")
            ax.set_xlabel(
                cfg.y_label or (f"{y_col} ({y_unit})" if y_unit and f"({y_unit})" not in y_col else y_col),
                color=text_color,
            )
            max_v = max(y_vals) if y_vals and max(y_vals) > 0 else 1.0
            for i, v in enumerate(y_vals):
                val_str = f"{v:.1f}" if isinstance(v, float) and not v.is_integer() else f"{int(v)}"
                ax.text(v + (max_v * 0.015), y_pos[i], f" {val_str}", va="center", ha="left", color=text_color, fontsize=8, fontweight="bold")
            ax.set_xlim(0, max_v * 1.15 if max_v > 0 else 1.0)

        elif target_type == ChartType.LINE_CHART:
            active_y_cols = y_cols[:5] if y_cols else [dataset.columns[-1]]
            markers = ["o", "s", "^", "D", "v"]

            is_x_num = dataset.column_types.get(x_col) == "NUMERICAL" and not is_datetime_or_sequential(x_col, [r[x_idx] for r in dataset.rows if r])
            if is_x_num:
                x_numeric = [float(r[x_idx]) if isinstance(r[x_idx], (int, float)) else i for i, r in enumerate(dataset.rows)]
                sort_order = np.argsort(x_numeric)
                x_plot = np.array(x_numeric)[sort_order]
            else:
                sort_order = np.arange(len(dataset.rows))
                x_plot = np.array(x_vals)

            for idx, y_c in enumerate(active_y_cols):
                y_idx = dataset.columns.index(y_c)
                y_vals = [float(r[y_idx]) if isinstance(r[y_idx], (int, float)) else 0.0 for r in dataset.rows]
                y_plot = np.array(y_vals)[sort_order]
                color = colors[idx % len(colors)]
                ax.plot(
                    x_plot,
                    y_plot,
                    marker=markers[idx % len(markers)],
                    markersize=5,
                    linewidth=1.8,
                    color=color,
                    label=y_c,
                    zorder=3,
                )
                if len(active_y_cols) == 1:
                    ax.fill_between(x_plot, y_plot, alpha=0.15, color=color, zorder=2)
                    if len(x_plot) <= 10:
                        for px, py in zip(x_plot, y_plot):
                            v_str = f"{py:.1f}" if isinstance(py, float) and not py.is_integer() else f"{int(py)}"
                            ax.annotate(v_str, (px, py), xytext=(0, 5), textcoords="offset points", ha="center", fontsize=7.5, color=text_color, fontweight="bold")

            y_unit = dataset.column_units.get(active_y_cols[0], "")
            ax.set_ylabel(
                cfg.y_label or (f"{active_y_cols[0]} ({y_unit})" if y_unit and f"({y_unit})" not in active_y_cols[0] else active_y_cols[0]),
                color=text_color,
            )
            if len(active_y_cols) > 1:
                ax.legend(frameon=True, facecolor=ax_bg_color, edgecolor=grid_color, fontsize=8)

        elif target_type == ChartType.SCATTER_DOT:
            x_num_col = x_col if dataset.column_types.get(x_col) == "NUMERICAL" else (num_cols[0] if num_cols else dataset.columns[0])
            x_c_idx = dataset.columns.index(x_num_col)
            y_col = y_cols[0] if y_cols and y_cols[0] != x_num_col else (num_cols[1] if len(num_cols) > 1 else dataset.columns[-1])
            y_idx = dataset.columns.index(y_col)

            x_nums = [float(r[x_c_idx]) if isinstance(r[x_c_idx], (int, float)) else i for i, r in enumerate(dataset.rows)]
            y_nums = [float(r[y_idx]) if isinstance(r[y_idx], (int, float)) else 0.0 for r in dataset.rows]

            ax.scatter(
                x_nums,
                y_nums,
                color=colors[1 % len(colors)],
                s=65,
                edgecolors=bg_color,
                linewidth=0.8,
                alpha=0.9,
                zorder=4,
            )

            if cat_cols and len(dataset.rows) <= 15:
                cat_idx = dataset.columns.index(cat_cols[0])
                for i, r in enumerate(dataset.rows):
                    label = str(r[cat_idx])
                    if label:
                        ax.annotate(
                            label,
                            (x_nums[i], y_nums[i]),
                            xytext=(4, 4),
                            textcoords="offset points",
                            fontsize=7.5,
                            color=text_color,
                            alpha=0.85,
                        )

            if len(x_nums) >= 3 and len(set(x_nums)) > 1:
                try:
                    slope, intercept = np.polyfit(x_nums, y_nums, 1)
                    x_trend = np.linspace(min(x_nums), max(x_nums), 50)
                    y_trend = slope * x_trend + intercept
                    ax.plot(x_trend, y_trend, linestyle="--", color=colors[0], alpha=0.5, linewidth=1.2, zorder=2)
                except Exception:
                    pass

            ax.set_xlabel(cfg.x_label or x_num_col, color=text_color)
            ax.set_ylabel(cfg.y_label or y_col, color=text_color)

        elif target_type == ChartType.HISTOGRAM:
            target_col = num_cols[0] if num_cols else dataset.columns[0]
            col_idx = dataset.columns.index(target_col)
            vals = [float(r[col_idx]) for r in dataset.rows if isinstance(r[col_idx], (int, float))]
            if not vals:
                vals = [0.0]
            bins = max(3, min(25, int(math.sqrt(len(vals)))))
            ax.hist(vals, bins=bins, color=colors[2 % len(colors)], edgecolor=bg_color, alpha=0.85, zorder=3)
            ax.set_xlabel(cfg.x_label or target_col, color=text_color)
            ax.set_ylabel("Frequency", color=text_color)

        elif target_type == ChartType.BOX_PLOT:
            active_cols = num_cols[:5] if num_cols else dataset.columns[1:6]
            box_data = []
            valid_labels = []
            for col in active_cols:
                c_idx = dataset.columns.index(col)
                vals = [float(r[c_idx]) for r in dataset.rows if isinstance(r[c_idx], (int, float))]
                if vals:
                    box_data.append(vals)
                    valid_labels.append(col)

            if box_data:
                bp = ax.boxplot(
                    box_data,
                    tick_labels=valid_labels,
                    patch_artist=True,
                    zorder=3,
                    medianprops=dict(color=colors[1 % len(colors)], linewidth=2),
                )
                for patch in bp["boxes"]:
                    patch.set_facecolor(colors[0])
                    patch.set_alpha(0.7)
            ax.set_ylabel(cfg.y_label or "Distribution", color=text_color)

        elif target_type == ChartType.HEATMAP:
            active_cols = num_cols[:8] if num_cols else dataset.columns[1:9]
            matrix = []
            row_labels = x_vals[:12]
            for r in dataset.rows[:12]:
                row_vals = []
                for c in active_cols:
                    c_idx = dataset.columns.index(c)
                    val = float(r[c_idx]) if isinstance(r[c_idx], (int, float)) else 0.0
                    row_vals.append(val)
                matrix.append(row_vals)

            if matrix and active_cols:
                mat_np = np.array(matrix)
                im = ax.imshow(mat_np, cmap="Blues" if not is_dark else "magma", aspect="auto")
                cbar = fig.colorbar(im, ax=ax, shrink=0.8)
                cbar.ax.tick_params(labelsize=8, labelcolor=text_color)
                ax.set_xticks(range(len(active_cols)))
                ax.set_xticklabels(active_cols)
                ax.set_yticks(range(len(row_labels)))
                ax.set_yticklabels(row_labels)
                for i in range(len(row_labels)):
                    for j in range(len(active_cols)):
                        val = mat_np[i, j]
                        ax.text(
                            j,
                            i,
                            f"{val:.1f}" if not val.is_integer() else f"{int(val)}",
                            ha="center",
                            va="center",
                            color="white" if val > mat_np.mean() else "black",
                            fontsize=7.5,
                        )

        elif target_type == ChartType.AREA_CHART:
            active_y_cols = y_cols[:3] if y_cols else [dataset.columns[-1]]
            x_indices = np.arange(len(x_vals))
            for idx, y_c in enumerate(active_y_cols):
                y_idx = dataset.columns.index(y_c)
                y_vals = [float(r[y_idx]) if isinstance(r[y_idx], (int, float)) else 0.0 for r in dataset.rows]
                color = colors[idx % len(colors)]
                ax.fill_between(x_indices, y_vals, alpha=0.4, color=color, label=y_c, zorder=2)
                ax.plot(x_indices, y_vals, color=color, linewidth=1.8, zorder=3)

            ax.set_xticks(x_indices)
            ax.set_xticklabels(x_vals)
            ax.set_ylabel(cfg.y_label or active_y_cols[0], color=text_color)
            if len(active_y_cols) > 1:
                ax.legend(frameon=True, facecolor=ax_bg_color, edgecolor=grid_color, fontsize=8)

        elif target_type in (ChartType.PIE_CHART, ChartType.DONUT_CHART):
            y_col = y_cols[0] if y_cols else dataset.columns[-1]
            y_idx = dataset.columns.index(y_col)
            pie_vals = [max(0.0, float(r[y_idx])) if isinstance(r[y_idx], (int, float)) else 0.0 for r in dataset.rows]
            labels = [str(r[x_idx]) for r in dataset.rows]
            total_val = sum(pie_vals)
            if total_val == 0:
                pie_vals = [1.0] * len(labels)

            is_donut = (target_type == ChartType.DONUT_CHART)
            wedgeprops = dict(width=0.4 if is_donut else None, edgecolor=bg_color, linewidth=1.5)
            wedges, texts, autotexts = ax.pie(
                pie_vals,
                labels=labels if len(labels) <= 5 else None,
                autopct="%1.1f%%" if len(labels) <= 6 else None,
                pctdistance=0.75 if is_donut else 0.6,
                startangle=140,
                colors=colors[:len(labels)],
                wedgeprops=wedgeprops,
                textprops=dict(color=text_color, fontsize=8),
            )
            for at in autotexts:
                at.set_color(text_color)
                at.set_fontsize(8)
                at.set_weight("bold")
            if is_donut:
                center_str = f"Total\n{total_val:.1f}" if total_val != 1.0 else "Total"
                ax.text(0, 0, center_str, ha="center", va="center", color=text_color, fontsize=9, fontweight="bold")
            if len(labels) > 5:
                ax.legend(wedges, labels, loc="center left", bbox_to_anchor=(1, 0, 0.5, 1), frameon=False, fontsize=7.5)

        elif target_type == ChartType.STACKED_BAR:
            active_y_cols = y_cols[:6] if len(y_cols) > 1 else [dataset.columns[-1]]
            n_rows = len(dataset.rows)
            indices = np.arange(n_rows)
            bottom = np.zeros(n_rows)

            for s_idx, col_name in enumerate(active_y_cols):
                c_idx = dataset.columns.index(col_name)
                y_vals = np.array([float(r[c_idx]) if isinstance(r[c_idx], (int, float)) else 0.0 for r in dataset.rows])
                color = colors[s_idx % len(colors)]
                ax.bar(
                    indices,
                    y_vals,
                    bottom=bottom,
                    color=color,
                    label=col_name,
                    alpha=0.9,
                    edgecolor=bg_color,
                    linewidth=0.5,
                    zorder=3,
                )
                bottom += y_vals

            ax.set_xticks(indices)
            ax.set_xticklabels(x_vals)
            ax.set_ylabel(cfg.y_label or "Total", color=text_color)
            ax.legend(frameon=True, facecolor=ax_bg_color, edgecolor=grid_color, fontsize=8)

        elif target_type == ChartType.STACKED_AREA:
            active_y_cols = y_cols[:6] if len(y_cols) > 1 else [dataset.columns[-1]]
            x_indices = np.arange(len(x_vals))
            y_matrix = []
            for col_name in active_y_cols:
                c_idx = dataset.columns.index(col_name)
                y_vals = [float(r[c_idx]) if isinstance(r[c_idx], (int, float)) else 0.0 for r in dataset.rows]
                y_matrix.append(y_vals)

            ax.stackplot(
                x_indices,
                y_matrix,
                labels=active_y_cols,
                colors=colors[:len(active_y_cols)],
                alpha=0.85,
                edgecolor=bg_color,
                linewidth=0.5,
                zorder=2,
            )
            ax.set_xticks(x_indices)
            ax.set_xticklabels(x_vals)
            ax.set_ylabel(cfg.y_label or "Cumulative Total", color=text_color)
            ax.legend(frameon=True, facecolor=ax_bg_color, edgecolor=grid_color, fontsize=8)

        elif target_type == ChartType.BUBBLE_CHART:
            x_c = num_cols[0] if len(num_cols) >= 1 else dataset.columns[0]
            y_c = num_cols[1] if len(num_cols) >= 2 else dataset.columns[1]
            s_c = num_cols[2] if len(num_cols) >= 3 else dataset.columns[-1]

            x_idx_b = dataset.columns.index(x_c)
            y_idx_b = dataset.columns.index(y_c)
            s_idx_b = dataset.columns.index(s_c)

            x_b = [float(r[x_idx_b]) if isinstance(r[x_idx_b], (int, float)) else 0.0 for r in dataset.rows]
            y_b = [float(r[y_idx_b]) if isinstance(r[y_idx_b], (int, float)) else 0.0 for r in dataset.rows]
            s_b = [max(0.1, float(r[s_idx_b])) if isinstance(r[s_idx_b], (int, float)) else 1.0 for r in dataset.rows]

            min_s, max_s = min(s_b), max(s_b)
            norm_s = [120 + (v - min_s) / max(1e-5, max_s - min_s) * 800 for v in s_b]

            ax.scatter(
                x_b, y_b, s=norm_s, color=colors[0], alpha=0.6,
                edgecolors=bg_color, linewidth=1.2, zorder=4
            )
            if cat_cols and len(dataset.rows) <= 15:
                cat_idx = dataset.columns.index(cat_cols[0])
                for i, r in enumerate(dataset.rows):
                    lbl = str(r[cat_idx])
                    if lbl:
                        ax.annotate(lbl, (x_b[i], y_b[i]), xytext=(5, 5), textcoords="offset points", fontsize=7.5, color=text_color)

            ax.set_xlabel(cfg.x_label or x_c, color=text_color)
            ax.set_ylabel(cfg.y_label or y_c, color=text_color)

        elif target_type == ChartType.RADAR_CHART:
            ax.remove()
            ax = fig.add_subplot(111, polar=True)
            ax.set_facecolor(ax_bg_color)
            ax.grid(True, linestyle="--", alpha=0.6, color=grid_color)

            radar_cols = num_cols[:8] if len(num_cols) >= 3 else dataset.columns[1:min(9, len(dataset.columns))]
            n_axes = len(radar_cols)
            angles = np.linspace(0, 2 * np.pi, n_axes, endpoint=False).tolist()
            angles += angles[:1]

            entities = dataset.rows[:5]
            cat_name = cat_cols[0] if cat_cols else dataset.columns[0]
            cat_i = dataset.columns.index(cat_name)

            for e_idx, row in enumerate(entities):
                vals = []
                for c in radar_cols:
                    c_i = dataset.columns.index(c)
                    vals.append(float(row[c_i]) if isinstance(row[c_i], (int, float)) else 0.0)
                vals += vals[:1]
                color = colors[e_idx % len(colors)]
                label = str(row[cat_i]) if cat_i < len(row) else f"Entity {e_idx+1}"
                ax.plot(angles, vals, color=color, linewidth=1.8, label=label, zorder=3)
                ax.fill(angles, vals, color=color, alpha=0.2, zorder=2)

            ax.set_thetagrids(np.degrees(angles[:-1]), radar_cols, fontsize=8, color=text_color)
            ax.tick_params(colors=text_color, labelsize=7.5)
            if len(entities) > 1:
                ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.1), frameon=True, facecolor=ax_bg_color, edgecolor=grid_color, fontsize=7.5)

        elif target_type == ChartType.GAUGE_CHART:
            ax.axis("off")
            first_num_col = num_cols[0] if num_cols else dataset.columns[-1]
            val_idx_g = dataset.columns.index(first_num_col)
            curr_val = float(dataset.rows[0][val_idx_g]) if dataset.rows and isinstance(dataset.rows[0][val_idx_g], (int, float)) else 75.0
            target_val = 100.0
            if len(num_cols) >= 2:
                tgt_col = num_cols[1]
                tgt_idx = dataset.columns.index(tgt_col)
                if dataset.rows and isinstance(dataset.rows[0][tgt_idx], (int, float)):
                    target_val = float(dataset.rows[0][tgt_idx])

            pct = min(1.0, max(0.0, curr_val / max(1e-5, target_val)))
            t_bg = np.linspace(np.pi, 0, 100)
            ax.plot(np.cos(t_bg), np.sin(t_bg), color=grid_color, linewidth=18, solid_capstyle="round")
            t_val = np.linspace(np.pi, np.pi - pct * np.pi, max(2, int(pct * 100)))
            progress_color = "#00E5FF" if pct >= 0.8 else ("#FFB300" if pct >= 0.5 else "#FF5252")
            ax.plot(np.cos(t_val), np.sin(t_val), color=progress_color, linewidth=18, solid_capstyle="round")
            needle_angle = np.pi - pct * np.pi
            ax.plot([0, 0.75 * np.cos(needle_angle)], [0, 0.75 * np.sin(needle_angle)], color="#FFFFFF", linewidth=2.5, zorder=5)
            ax.scatter([0], [0], color="#FFFFFF", s=80, zorder=6)
            ax.text(0, -0.2, f"{curr_val:.1f} / {target_val:.1f} ({pct*100:.1f}%)", ha="center", va="center", color=text_color, fontsize=12, fontweight="bold")
            ax.text(0, -0.38, first_num_col, ha="center", va="center", color="#8888AA", fontsize=9)
            ax.set_xlim(-1.2, 1.2)
            ax.set_ylim(-0.5, 1.2)

        elif target_type == ChartType.WATERFALL_CHART:
            y_col = num_cols[0] if num_cols else dataset.columns[-1]
            y_idx_w = dataset.columns.index(y_col)
            deltas = [float(r[y_idx_w]) if isinstance(r[y_idx_w], (int, float)) else 0.0 for r in dataset.rows]
            labels_w = [str(r[x_idx]) for r in dataset.rows]
            n_w = len(deltas)
            indices_w = np.arange(n_w)

            running = 0.0
            bottoms = []
            heights = []
            bar_colors = []

            for i, d in enumerate(deltas):
                lbl_lower = labels_w[i].lower()
                is_total = "net" in lbl_lower or "total" in lbl_lower or i == n_w - 1
                if is_total:
                    bottoms.append(0.0)
                    heights.append(d if abs(d - running) > 1e-3 else running)
                    bar_colors.append("#2979FF")
                    running = heights[-1]
                else:
                    if d >= 0:
                        bottoms.append(running)
                        heights.append(d)
                        bar_colors.append("#00E676")
                    else:
                        bottoms.append(running + d)
                        heights.append(abs(d))
                        bar_colors.append("#FF5252")
                    running += d

            ax.bar(indices_w, heights, bottom=bottoms, color=bar_colors, edgecolor=bg_color, width=0.6, zorder=3)
            for i in range(n_w - 1):
                y_conn = bottoms[i] + heights[i] if deltas[i] >= 0 else bottoms[i]
                ax.plot([indices_w[i] + 0.3, indices_w[i+1] - 0.3], [y_conn, y_conn], color=spine_color, linestyle=":", linewidth=1)

            ax.set_xticks(indices_w)
            ax.set_xticklabels(labels_w)
            ax.set_ylabel(cfg.y_label or y_col, color=text_color)

        elif target_type == ChartType.GANTT_CHART:
            from data_to_graph.chart_selector import _find_col_by_keywords, GANTT_START_KEYWORDS, GANTT_END_KEYWORDS
            task_col = cat_cols[0] if cat_cols else dataset.columns[0]
            t_idx = dataset.columns.index(task_col)
            tasks = [str(r[t_idx]) for r in dataset.rows]
            n_tasks = len(tasks)
            y_pos_g = np.arange(n_tasks)

            start_vals = []
            dur_vals = []
            s_c = _find_col_by_keywords(dataset.columns, GANTT_START_KEYWORDS)
            e_c = _find_col_by_keywords(dataset.columns, GANTT_END_KEYWORDS)
            s_i = dataset.columns.index(s_c) if s_c else (dataset.columns.index(num_cols[0]) if num_cols else 1)
            e_i = dataset.columns.index(e_c) if e_c else (dataset.columns.index(num_cols[1]) if len(num_cols) > 1 else s_i)

            for i, r in enumerate(dataset.rows):
                sv = float(r[s_i]) if isinstance(r[s_i], (int, float)) else float(i * 2)
                ev = float(r[e_i]) if isinstance(r[e_i], (int, float)) else sv + 3.0
                dur = ev - sv if ev >= sv else ev
                start_vals.append(sv)
                dur_vals.append(max(1.0, dur))

            ax.barh(y_pos_g, dur_vals, left=start_vals, height=0.5, color=colors[0], alpha=0.85, edgecolor=bg_color, linewidth=1, zorder=3)
            ax.set_yticks(y_pos_g)
            ax.set_yticklabels(tasks, color=text_color)
            ax.invert_yaxis()
            ax.set_xlabel(cfg.x_label or "Timeline / Duration", color=text_color)

        elif target_type == ChartType.FUNNEL_CHART:
            stage_col = cat_cols[0] if cat_cols else dataset.columns[0]
            val_col = num_cols[0] if num_cols else dataset.columns[-1]
            s_i = dataset.columns.index(stage_col)
            v_i = dataset.columns.index(val_col)

            stages = [str(r[s_i]) for r in dataset.rows]
            f_vals = [float(r[v_i]) if isinstance(r[v_i], (int, float)) else 0.0 for r in dataset.rows]
            n_f = len(stages)
            y_pos_f = np.arange(n_f)
            max_val = max(f_vals) if f_vals and max(f_vals) > 0 else 1.0

            widths = np.array(f_vals)
            lefts = -widths / 2.0
            ax.barh(y_pos_f, widths, left=lefts, height=0.55, color=colors[:n_f], edgecolor=bg_color, linewidth=1, zorder=3)

            for i in range(n_f):
                pct_top = (f_vals[i] / max_val) * 100
                lbl = f"{stages[i]}: {f_vals[i]:,.0f} ({pct_top:.1f}%)"
                ax.text(0, y_pos_f[i], lbl, ha="center", va="center", color=text_color, fontsize=8, fontweight="bold", zorder=4)

            ax.set_yticks([])
            ax.invert_yaxis()
            ax.set_xlim(-max_val * 0.7, max_val * 0.7)
            ax.set_xlabel("Funnel Conversion Volume", color=text_color)

        elif target_type == ChartType.CANDLESTICK_CHART:
            from data_to_graph.chart_selector import _find_col_by_keywords
            op_c = _find_col_by_keywords(dataset.columns, {"open"}) or (num_cols[0] if num_cols else dataset.columns[0])
            hi_c = _find_col_by_keywords(dataset.columns, {"high"}) or (num_cols[1] if len(num_cols) > 1 else op_c)
            lo_c = _find_col_by_keywords(dataset.columns, {"low"}) or (num_cols[2] if len(num_cols) > 2 else op_c)
            cl_c = _find_col_by_keywords(dataset.columns, {"close"}) or (num_cols[3] if len(num_cols) > 3 else op_c)

            op_i, hi_i, lo_i, cl_i = [dataset.columns.index(c) for c in (op_c, hi_c, lo_c, cl_c)]
            x_idx_c = np.arange(len(dataset.rows))

            for i, r in enumerate(dataset.rows):
                o = float(r[op_i]) if isinstance(r[op_i], (int, float)) else 0.0
                h = float(r[hi_i]) if isinstance(r[hi_i], (int, float)) else o
                l = float(r[lo_i]) if isinstance(r[lo_i], (int, float)) else o
                c = float(r[cl_i]) if isinstance(r[cl_i], (int, float)) else o

                candle_color = "#00E676" if c >= o else "#FF5252"
                ax.plot([i, i], [l, h], color=candle_color, linewidth=1.2, zorder=2)
                body_bottom = min(o, c)
                body_height = max(abs(c - o), (h - l) * 0.02 if h > l else 0.1)
                ax.bar(i, body_height, bottom=body_bottom, width=0.6, color=candle_color, edgecolor=bg_color, linewidth=0.5, zorder=3)

            ax.set_xticks(x_idx_c)
            ax.set_xticklabels(x_vals)
            ax.set_ylabel("Price / OHLC", color=text_color)

        elif target_type == ChartType.TREEMAP:
            ax.axis("off")
            cat_col = cat_cols[0] if cat_cols else dataset.columns[0]
            num_c = num_cols[0] if num_cols else dataset.columns[-1]
            c_i = dataset.columns.index(cat_col)
            n_i = dataset.columns.index(num_c)

            items = []
            for r in dataset.rows:
                val = max(0.1, float(r[n_i])) if isinstance(r[n_i], (int, float)) else 1.0
                items.append((str(r[c_i]), val))
            items.sort(key=lambda x: x[1], reverse=True)

            total_val = sum(v for _, v in items)
            x_curr, y_curr, w_rem, h_rem = 0.0, 0.0, 1.0, 1.0
            horizontal = True
            for idx, (lbl, val) in enumerate(items):
                share = val / max(1e-5, total_val)
                color = colors[idx % len(colors)]
                if horizontal:
                    w_box = max(0.02, share / max(1e-5, h_rem))
                    w_box = min(w_box, w_rem)
                    rect = plt.Rectangle((x_curr, y_curr), w_box, h_rem, facecolor=color, alpha=0.85, edgecolor=bg_color, linewidth=1.5)
                    ax.add_patch(rect)
                    if w_box > 0.08 and h_rem > 0.08:
                        ax.text(x_curr + w_box/2, y_curr + h_rem/2, f"{lbl}\n{share*100:.1f}%", ha="center", va="center", color=text_color, fontsize=7.5, fontweight="bold")
                    x_curr += w_box
                    w_rem -= w_box
                else:
                    h_box = max(0.02, share / max(1e-5, w_rem))
                    h_box = min(h_box, h_rem)
                    rect = plt.Rectangle((x_curr, y_curr), w_rem, h_box, facecolor=color, alpha=0.85, edgecolor=bg_color, linewidth=1.5)
                    ax.add_patch(rect)
                    if w_rem > 0.08 and h_box > 0.08:
                        ax.text(x_curr + w_rem/2, y_curr + h_box/2, f"{lbl}\n{share*100:.1f}%", ha="center", va="center", color=text_color, fontsize=7.5, fontweight="bold")
                    y_curr += h_box
                    h_rem -= h_box
                horizontal = not horizontal
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)

        elif target_type == ChartType.PAIR_PLOT:
            active_vars = num_cols[:4] if len(num_cols) >= 3 else dataset.columns[:min(4, len(dataset.columns))]
            k = max(2, len(active_vars))
            fig.clf()
            sub_axes = fig.subplots(k, k, sharex="col", sharey="row")
            fig.subplots_adjust(wspace=0.2, hspace=0.2, top=0.88, bottom=0.12, left=0.12, right=0.92)

            data_arrays = {}
            for col in active_vars:
                c_idx_p = dataset.columns.index(col)
                data_arrays[col] = [float(r[c_idx_p]) if isinstance(r[c_idx_p], (int, float)) else 0.0 for r in dataset.rows]

            for r_i in range(k):
                for c_i in range(k):
                    sub_ax = sub_axes[r_i, c_i]
                    sub_ax.set_facecolor(ax_bg_color)
                    sub_ax.tick_params(colors=text_color, labelsize=6)
                    for sp in sub_ax.spines.values():
                        sp.set_color(spine_color)
                        sp.set_linewidth(0.5)

                    if r_i == c_i:
                        sub_ax.hist(data_arrays[active_vars[r_i]], bins=5, color=colors[0], alpha=0.7, edgecolor=bg_color)
                    else:
                        sub_ax.scatter(data_arrays[active_vars[c_i]], data_arrays[active_vars[r_i]], color=colors[1 % len(colors)], s=16, alpha=0.7)

                    if r_i == k - 1:
                        sub_ax.set_xlabel(active_vars[c_i][:8], fontsize=7, color=text_color)
                    if c_i == 0:
                        sub_ax.set_ylabel(active_vars[r_i][:8], fontsize=7, color=text_color)

        elif target_type == ChartType.TABLE_VIEW:
            ax.axis("off")
            table_data = []
            for r in dataset.rows[:12]:
                table_data.append([str(c)[:30] + ("…" if len(str(c)) > 30 else "") for c in r])
            if table_data and dataset.columns:
                tbl = ax.table(
                    cellText=table_data,
                    colLabels=dataset.columns,
                    loc="center",
                    cellLoc="left",
                )
                tbl.auto_set_font_size(False)
                tbl.set_fontsize(8.5)
                tbl.scale(1.0, 1.4)
                for (r_idx, c_idx), cell in tbl.get_celld().items():
                    cell.set_edgecolor(spine_color)
                    cell.set_linewidth(0.6)
                    if r_idx == 0:
                        cell.set_facecolor("#1E222A" if is_dark else "#EAECEF")
                        cell.set_text_props(weight="bold", color=text_color)
                    else:
                        bg = ("#16181D" if r_idx % 2 == 0 else "#101216") if is_dark else ("#FFFFFF" if r_idx % 2 == 0 else "#F7F8FA")
                        cell.set_facecolor(bg)
                        cell.set_text_props(color=text_color)

        # Strictly use table heading without stating chart type
        heading = getattr(dataset, "group_name", None)
        if heading:
            clean_title = re.sub(r"^(?:Group:\s*|Table Block \d+:\s*)", "", str(heading)).strip()
            chart_title = cfg.title or clean_title
        elif cfg.title:
            chart_title = cfg.title
        else:
            if active_y_cols:
                y_desc = ", ".join(active_y_cols[:2]) + ("..." if len(active_y_cols) > 2 else "")
                chart_title = f"{y_desc} by {x_col}" if x_col and x_col != y_desc else y_desc
            else:
                chart_title = dataset.columns[0] if dataset.columns else "Table Data"

        if target_type == ChartType.PAIR_PLOT:
            fig.suptitle(chart_title, fontsize=11, fontweight="bold", color=text_color)
        else:
            ax.set_title(chart_title, fontsize=11, fontweight="bold", pad=12, color=text_color)

        # Set default x_label ONLY for Cartesian charts that haven't set their own specific x_label
        if target_type in (
            ChartType.BAR_CHART, ChartType.LINE_CHART, ChartType.AREA_CHART,
            ChartType.STACKED_BAR, ChartType.STACKED_AREA
        ):
            if not ax.get_xlabel():
                ax.set_xlabel(x_label_text, color=text_color)

        if target_type not in (
            ChartType.PIE_CHART, ChartType.DONUT_CHART, ChartType.RADAR_CHART,
            ChartType.GAUGE_CHART, ChartType.TREEMAP, ChartType.PAIR_PLOT, ChartType.TABLE_VIEW,
        ):
            for spine in ("top", "right"):
                ax.spines[spine].set_visible(False)
            for spine in ("bottom", "left"):
                ax.spines[spine].set_color(spine_color)
                ax.spines[spine].set_linewidth(0.8)
            ax.tick_params(colors=text_color, labelsize=8.5)

        if target_type in (
            ChartType.BAR_CHART, ChartType.LINE_CHART, ChartType.AREA_CHART,
            ChartType.STACKED_BAR, ChartType.STACKED_AREA, ChartType.WATERFALL_CHART,
            ChartType.CANDLESTICK_CHART
        ):
            rot = 25 if len(x_vals) > 5 or any(len(str(v)) > 7 for v in x_vals) else 0
            plt.xticks(rotation=rot, ha="right" if rot > 0 else "center")

        png_buf = io.BytesIO()
        svg_buf = io.StringIO()
        fig.savefig(png_buf, format="png", dpi=cfg.dpi, bbox_inches="tight")
        fig.savefig(svg_buf, format="svg", bbox_inches="tight")
        plt.close(fig)

        from data_to_graph.chart_selector import get_compatible_chart_types
        compatible_types = get_compatible_chart_types(dataset)
        alternatives = [t for t in compatible_types if t != target_type]

        return RenderedChart(
            png_bytes=png_buf.getvalue(),
            svg_text=svg_buf.getvalue(),
            chart_type=target_type,
            dataset=dataset,
            available_alternatives=alternatives,
            group_name=getattr(dataset, "group_name", None),
            source_range=getattr(dataset, "source_range", None),
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


def generate_charts_for_table(
    raw_table_text_or_dataset: Union[str, ParsedTableDataset],
    style: Optional[ChartStyleConfig] = None,
) -> List[RenderedChart]:
    """Generates a collection of charts (one per detected data group) for multi-heading tables."""
    from data_to_graph.segmenter import TableSegmenter
    segmenter = TableSegmenter(_global_table_graph_engine)
    return segmenter.generate_charts(raw_table_text_or_dataset, style)


def parse_multi_group_tables(raw_table_text: str) -> List[ParsedTableDataset]:
    """Parses and segments raw tabular text into individual group datasets."""
    from data_to_graph.segmenter import TableSegmenter
    segmenter = TableSegmenter(_global_table_graph_engine)
    return segmenter.segment_table(raw_table_text)

