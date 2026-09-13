"""Table Segmentation Engine for Multi-Heading and Multi-Dataset Tables.

Implements the 4-stage pipeline for handling tables with multiple distinct types
of information under multiple headings:
1. Detect Group Boundaries (blank rows/columns, repeated headers, super-categories, distinct units/scales)
2. Cluster Columns Into Groups (shared namespaces, prefixes, units, shared category axis)
3. Generate One Chart Per Group (independent type inference, confidence gate, TABLE_VIEW fallback)
4. Assemble Output (ChartCollection tagged by group name and source range)
"""

from __future__ import annotations

import copy
import math
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from data_to_graph.models import (
    ChartCollection,
    ChartStyleConfig,
    ChartType,
    ParsedTableDataset,
    RenderedChart,
)


def _split_markdown_sections(text: str) -> List[Tuple[Optional[str], str, Dict[str, int]]]:
    """Splits markdown or plain text with headings into titled blocks."""
    lines = text.splitlines()
    blocks: List[Tuple[Optional[str], List[str], int]] = []
    current_title: Optional[str] = None
    current_lines: List[str] = []
    block_start_line = 0

    heading_re = re.compile(r"^\s*(?:#{1,6}\s+(.+)|\[(?:Table\s*\d*[:\s]*)?([^\]]+)\])\s*$", re.IGNORECASE)

    for idx, line in enumerate(lines):
        m = heading_re.match(line)
        if m:
            if current_lines and any("|" in l or "," in l for l in current_lines):
                blocks.append((current_title, current_lines, block_start_line))
            current_title = (m.group(1) or m.group(2) or "").strip()
            current_lines = []
            block_start_line = idx + 1
        else:
            current_lines.append(line)

    if current_lines and any("|" in l or "," in l or "\t" in l for l in current_lines):
        blocks.append((current_title, current_lines, block_start_line))

    results = []
    for title, blk_lines, start_idx in blocks:
        block_text = "\n".join(blk_lines).strip()
        if block_text:
            results.append((title, block_text, {"row_start": start_idx, "row_end": start_idx + len(blk_lines)}))
    return results


def _split_blank_line_blocks(text: str) -> List[Tuple[Optional[str], str, Dict[str, int]]]:
    """Splits text separated by two or more consecutive blank lines into distinct tables."""
    raw_blocks = re.split(r"\n\s*\n\s*\n*", text.strip())
    if len(raw_blocks) <= 1:
        return []

    valid_blocks = []
    current_line = 0
    for i, b in enumerate(raw_blocks):
        b_clean = b.strip()
        n_lines = len(b_clean.splitlines())
        if n_lines >= 2 and any(sep in b_clean for sep in ("|", ",", "\t", ";")):
            # Check if first line might be a title / description
            lines = b_clean.splitlines()
            title = None
            if len(lines) >= 3 and not any(sep in lines[0] for sep in ("|", ",", "\t", ";")):
                title = lines[0].strip(":# ")
                b_clean = "\n".join(lines[1:]).strip()
            valid_blocks.append((title or f"Table Block {i+1}", b_clean, {"row_start": current_line, "row_end": current_line + n_lines}))
        current_line += n_lines + 2
    return valid_blocks if len(valid_blocks) > 1 else []


def _normalize_multi_level_headers(text: str) -> str:
    """Detects multi-level/hierarchical header rows (e.g. super-headers in row 0, sub-headers in row 1)
    and combines them into namespaced single-row headers (e.g. 'Q1: Revenue')."""
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) < 3:
        return text

    first_line = lines[0]
    delimiter = "\t" if "\t" in first_line else "|" if "|" in first_line else ";" if ";" in first_line else "," if "," in first_line else None
    if not delimiter:
        return text

    def get_cells(line: str) -> List[str]:
        if delimiter == "|":
            parts = [p.strip() for p in line.split("|")]
            if parts and parts[0] == "": parts.pop(0)
            if parts and parts[-1] == "": parts.pop()
            return parts
        return [c.strip() for c in line.split(delimiter)]

    r0 = get_cells(lines[0])
    r1_idx = 1
    if delimiter == "|" and re.match(r"^\|?[\s\-:|]+\|?$", lines[1]):
        r1_idx = 2
    if r1_idx >= len(lines):
        return text

    r1 = get_cells(lines[r1_idx])
    data_idx = r1_idx + 1
    if delimiter == "|" and data_idx < len(lines) and re.match(r"^\|?[\s\-:|]+\|?$", lines[data_idx]):
        data_idx += 1
    if data_idx >= len(lines):
        return text

    r_data = get_cells(lines[data_idx])
    if len(r0) != len(r1) or len(r0) < 3:
        return text

    data_has_num = any(re.search(r"\d", c) for c in r_data)
    if not data_has_num:
        return text

    r0_no_num = all(not re.match(r"^-?\d+(\.\d+)?$", c.replace("$", "").replace("%", "")) for c in r0 if c)
    r1_no_num = all(not re.match(r"^-?\d+(\.\d+)?$", c.replace("$", "").replace("%", "")) for c in r1 if c)
    if not (r0_no_num and r1_no_num):
        return text

    filled_r0 = []
    last_val = ""
    for val in r0:
        if val:
            last_val = val
            filled_r0.append(last_val)
        else:
            filled_r0.append(last_val)

    from collections import Counter
    counts = Counter(filled_r0)
    has_super = any(cnt >= 2 for cnt in counts.values())
    if not has_super or len(counts) < 2:
        return text

    merged_headers = []
    for s_hdr, sub_hdr in zip(filled_r0, r1):
        if not s_hdr or s_hdr == sub_hdr:
            merged_headers.append(sub_hdr or s_hdr)
        elif not sub_hdr:
            merged_headers.append(s_hdr)
        else:
            merged_headers.append(f"{s_hdr}: {sub_hdr}")

    if delimiter == "|":
        new_header_line = "| " + " | ".join(merged_headers) + " |"
        sep_line = "| " + " | ".join(["---"] * len(merged_headers)) + " |"
        remaining_lines = lines[data_idx:]
        return "\n".join([new_header_line, sep_line] + remaining_lines)
    else:
        new_header_line = delimiter.join(merged_headers)
        remaining_lines = lines[data_idx:]
        return "\n".join([new_header_line] + remaining_lines)



def _detect_repeated_header_rows(lines: List[str]) -> List[Tuple[str, List[str], Dict[str, int]]]:
    """Detects mid-table repeated header rows that signal row-stacked sub-tables."""
    if len(lines) < 5:
        return []

    # Filter out empty or markdown separator lines
    content_indices = [i for i, l in enumerate(lines) if l.strip() and not re.match(r"^\|?[\s\-:|]+\|?$", l)]
    if len(content_indices) < 4:
        return []

    first_line = lines[content_indices[0]]
    # Check if first line looks like a header (comma, tab, or pipe)
    delimiter = "\t" if "\t" in first_line else "|" if "|" in first_line else ";" if ";" in first_line else "," if "," in first_line else None
    if not delimiter:
        return []

    def get_cells(line: str) -> List[str]:
        if delimiter == "|":
            parts = [p.strip() for p in line.split("|")]
            if parts and parts[0] == "": parts.pop(0)
            if parts and parts[-1] == "": parts.pop()
            return parts
        return [c.strip() for c in line.split(delimiter)]

    header_cells = get_cells(first_line)
    if not header_cells:
        return []

    split_points = []
    for idx in content_indices[1:]:
        row_cells = get_cells(lines[idx])
        # Check if row matches the header cells or is completely alphabetical with same length
        if len(row_cells) == len(header_cells):
            is_exact_header = [c.lower() for c in row_cells] == [c.lower() for c in header_cells]
            is_new_header = (
                not is_exact_header
                and all(not re.match(r"^-?\d+(\.\d+)?$", c.replace("$", "").replace("%", "")) for c in row_cells if c)
                and any(len(c) > 1 for c in row_cells)
            )
            # Check if subsequent line has numbers
            next_idx_candidates = [i for i in content_indices if i > idx]
            if next_idx_candidates:
                next_cells = get_cells(lines[next_idx_candidates[0]])
                next_has_numbers = any(re.search(r"\d", c) for c in next_cells)
                if (is_exact_header or is_new_header) and next_has_numbers:
                    split_points.append(idx)

    if not split_points:
        return []

    # Slice into sub-tables
    slices = []
    bounds = [0] + split_points + [len(lines)]
    for i in range(len(bounds) - 1):
        s_start, s_end = bounds[i], bounds[i+1]
        sub_lines = lines[s_start:s_end]
        sub_clean = [l for l in sub_lines if l.strip()]
        if len(sub_clean) >= 2:
            h_cells = get_cells(sub_clean[0])
            title = f"Group {i+1}: {' / '.join(h_cells[:2])}"
            slices.append((title, sub_lines, {"row_start": s_start, "row_end": s_end}))

    return slices if len(slices) > 1 else []


def _cluster_columns_by_namespace(columns: List[str]) -> Dict[str, List[str]]:
    """Clusters column names by shared prefix namespaces (e.g. 'Q1: Rev', 'Q1: Cost' or 'Q1_Rev')."""
    delimiters = [":", " - ", "/", "_", "."]
    best_clusters: Dict[str, List[str]] = {}

    for sep in delimiters:
        candidate_clusters: Dict[str, List[str]] = {}
        for col in columns:
            if sep in col:
                parts = col.split(sep, 1)
                prefix = parts[0].strip()
                if prefix:
                    candidate_clusters.setdefault(prefix, []).append(col)

        # Check if we found at least 2 distinct prefixes with at least 1-2 columns each
        valid_groups = {k: v for k, v in candidate_clusters.items() if len(v) >= 1}
        if len(valid_groups) >= 2 and sum(len(v) for v in valid_groups.values()) >= 3:
            if len(valid_groups) > len(best_clusters):
                best_clusters = valid_groups

    return best_clusters


def _cluster_columns_by_blank_separator(columns: List[str], rows: List[List[Any]]) -> List[List[str]]:
    """Detects entirely blank columns separating horizontal table blocks."""
    if len(columns) < 4:
        return []

    blank_col_indices = []
    for c_idx in range(len(columns)):
        col_name = columns[c_idx].strip()
        is_name_blank = not col_name or col_name.startswith("Col_") or col_name.startswith("Unnamed")
        all_cells_blank = all(r[c_idx] == "" or r[c_idx] is None for r in rows)
        if is_name_blank and all_cells_blank:
            blank_col_indices.append(c_idx)

    if not blank_col_indices:
        return []

    groups = []
    start = 0
    for b_idx in blank_col_indices:
        if b_idx > start:
            groups.append(columns[start:b_idx])
        start = b_idx + 1
    if start < len(columns):
        groups.append(columns[start:])

    return [g for g in groups if len(g) >= 2]


def _cluster_columns_by_units_and_scales(dataset: ParsedTableDataset) -> Dict[str, List[str]]:
    """Clusters numerical columns that have distinct units (e.g. $ vs % vs count) or disparate scales."""
    num_cols = [c for c, t in dataset.column_types.items() if t == "NUMERICAL"]
    if len(num_cols) < 3:
        return {}

    unit_clusters: Dict[str, List[str]] = {}
    for col in num_cols:
        u = dataset.column_units.get(col, "")
        if u in ("$", "€", "£", "USD", "EUR", "GBP"):
            unit_clusters.setdefault("Financials ($)", []).append(col)
        elif u in ("%", "pct", "percent"):
            unit_clusters.setdefault("Percentages (%)", []).append(col)
        elif u in ("ms", "s", "sec", "min", "hr", "fps", "hz"):
            unit_clusters.setdefault("Performance / Latency", []).append(col)
        elif u in ("b", "kb", "mb", "gb", "tb"):
            unit_clusters.setdefault("Memory / Storage", []).append(col)

    # Only split if we have at least 2 distinct unit clusters with metrics
    valid_clusters = {k: v for k, v in unit_clusters.items() if len(v) >= 1}
    remaining_num = [c for c in num_cols if not any(c in v for v in valid_clusters.values())]

    if len(valid_clusters) >= 2:
        if remaining_num:
            valid_clusters["Counts / Metrics"] = remaining_num
        return valid_clusters

    # Check for order of magnitude scale divergence (> 100x difference in means)
    col_means: Dict[str, float] = {}
    for col in num_cols:
        idx = dataset.columns.index(col)
        vals = [float(r[idx]) for r in dataset.rows if isinstance(r[idx], (int, float))]
        if vals:
            col_means[col] = sum(vals) / len(vals)

    if len(col_means) >= 3:
        sorted_cols = sorted(col_means.items(), key=lambda x: x[1])
        min_c, min_mean = sorted_cols[0]
        max_c, max_mean = sorted_cols[-1]
        if min_mean > 0 and max_mean / min_mean >= 100.0:
            scale_clusters: Dict[str, List[str]] = {"Small Scale Metrics": [], "Large Scale Metrics": []}
            cutoff = math.sqrt(min_mean * max_mean)
            for c, m in col_means.items():
                if m <= cutoff:
                    scale_clusters["Small Scale Metrics"].append(c)
                else:
                    scale_clusters["Large Scale Metrics"].append(c)
            if len(scale_clusters["Small Scale Metrics"]) >= 1 and len(scale_clusters["Large Scale Metrics"]) >= 1:
                return scale_clusters

    return {}


class TableSegmenter:
    """Detects multi-heading boundaries, clusters columns, and produces individual data groups."""

    def __init__(self, engine=None):
        if engine is None:
            from data_to_graph.grapher import _global_table_graph_engine
            self.engine = _global_table_graph_engine
        else:
            self.engine = engine

    def segment_table(self, raw_table_text: str) -> List[ParsedTableDataset]:
        """Scans tabular text and segments into one ParsedTableDataset per detected data group."""
        text = raw_table_text.strip()
        if not text:
            return []

        # -------------------------------------------------------------
        # Stage 1: Text-Level Pre-Segmentation (Markdown sections / Blank blocks / Repeated headers)
        # -------------------------------------------------------------
        # 1A. Markdown section headers (### Title, [Table: Title])
        md_sections = _split_markdown_sections(text)
        if len(md_sections) > 1:
            datasets = []
            for title, block_text, rng in md_sections:
                ds = self.engine.parse_tabular_data(block_text)
                if ds.columns:
                    ds.group_name = title or f"Dataset {len(datasets)+1}"
                    ds.source_range = rng
                    ds.is_subgroup = True
                    datasets.append(ds)
            if len(datasets) > 1:
                return datasets

        # 1B. Double blank lines separating distinct table blocks
        blank_blocks = _split_blank_line_blocks(text)
        if len(blank_blocks) > 1:
            datasets = []
            for title, block_text, rng in blank_blocks:
                ds = self.engine.parse_tabular_data(block_text)
                if ds.columns:
                    ds.group_name = title
                    ds.source_range = rng
                    ds.is_subgroup = True
                    datasets.append(ds)
            if len(datasets) > 1:
                return datasets

        # 1C. Repeated header rows mid-table
        lines = [l for l in text.splitlines() if l.strip()]
        rep_headers = _detect_repeated_header_rows(lines)
        if len(rep_headers) > 1:
            datasets = []
            for title, sub_lines, rng in rep_headers:
                ds = self.engine.parse_tabular_data("\n".join(sub_lines))
                if ds.columns:
                    ds.group_name = title
                    ds.source_range = rng
                    ds.is_subgroup = True
                    datasets.append(ds)
            if len(datasets) > 1:
                return datasets

        # -------------------------------------------------------------
        # Stage 2: Column-Level Horizontal Segmentation
        # -------------------------------------------------------------
        # Check for multi-level headers and normalize them
        norm_text = _normalize_multi_level_headers(text)
        base_dataset = self.engine.parse_tabular_data(norm_text)
        if len(md_sections) == 1 and md_sections[0][0] and not base_dataset.group_name:
            base_dataset.group_name = md_sections[0][0]
        if not base_dataset.columns or len(base_dataset.columns) < 2:
            return [base_dataset]

        # 2A. Blank column separators in wide table
        blank_col_clusters = _cluster_columns_by_blank_separator(base_dataset.columns, base_dataset.rows)
        if len(blank_col_clusters) > 1:
            sub_datasets = []
            for idx, col_subset in enumerate(blank_col_clusters):
                sub_ds = self._slice_dataset_columns(
                    base_dataset,
                    col_subset,
                    group_name=f"Table Block {idx+1}: {col_subset[0]}",
                )
                sub_datasets.append(sub_ds)
            return sub_datasets

        # 2B. Shared namespace prefixes in headers (e.g. Q1_Rev, Q1_Cost vs Q2_Rev, Q2_Cost)
        namespace_clusters = _cluster_columns_by_namespace(base_dataset.columns)
        if len(namespace_clusters) >= 2:
            sub_datasets = []
            cat_cols = [c for c, t in base_dataset.column_types.items() if t == "CATEGORICAL"]
            primary_cat = [cat_cols[0]] if cat_cols else ([base_dataset.columns[0]] if base_dataset.columns else [])

            for prefix, col_subset in namespace_clusters.items():
                # Retain primary categorical axis if not already in subset
                full_subset = [c for c in primary_cat if c not in col_subset] + col_subset
                sub_ds = self._slice_dataset_columns(
                    base_dataset,
                    full_subset,
                    group_name=f"Group: {prefix}",
                )
                sub_datasets.append(sub_ds)
            return sub_datasets

        # 2C. Distinct units or scales across column clusters ($ vs % vs counts)
        unit_clusters = _cluster_columns_by_units_and_scales(base_dataset)
        if len(unit_clusters) >= 2:
            sub_datasets = []
            cat_cols = [c for c, t in base_dataset.column_types.items() if t == "CATEGORICAL"]
            primary_cat = [cat_cols[0]] if cat_cols else ([base_dataset.columns[0]] if base_dataset.columns else [])

            for group_label, metric_subset in unit_clusters.items():
                full_subset = [c for c in primary_cat if c not in metric_subset] + metric_subset
                sub_ds = self._slice_dataset_columns(
                    base_dataset,
                    full_subset,
                    group_name=group_label,
                )
                sub_datasets.append(sub_ds)
            return sub_datasets

        # Standard single dataset
        return [base_dataset]

    def _slice_dataset_columns(
        self,
        base_ds: ParsedTableDataset,
        col_subset: List[str],
        group_name: str,
    ) -> ParsedTableDataset:
        """Extracts a slice of columns from an existing dataset with preserved types and units."""
        col_indices = [base_ds.columns.index(c) for c in col_subset if c in base_ds.columns]
        new_columns = [base_ds.columns[i] for i in col_indices]

        new_rows = []
        for r in base_ds.rows:
            new_rows.append([r[i] for i in col_indices])

        new_types = {c: base_ds.column_types.get(c, "CATEGORICAL") for c in new_columns}
        new_units = {c: base_ds.column_units[c] for c in new_columns if c in base_ds.column_units}

        # Clean column names by stripping redundant prefix if namespace group
        prefix_tag = group_name.replace("Group: ", "").strip()
        cleaned_columns = []
        for c in new_columns:
            cleaned = c
            for sep in (": ", " - ", "/", "_", "."):
                target = f"{prefix_tag}{sep}"
                if cleaned.startswith(target):
                    cleaned = cleaned[len(target):]
                    break
            cleaned_columns.append(cleaned)

        cleaned_types = {cleaned_columns[i]: new_types[new_columns[i]] for i in range(len(new_columns))}
        cleaned_units = {cleaned_columns[i]: new_units[new_columns[i]] for i in range(len(new_columns)) if new_columns[i] in new_units}

        new_uncertainties: Dict[int, List[Optional[float]]] = {}
        for new_idx, old_idx in enumerate(col_indices):
            if old_idx in base_ds.uncertainties:
                new_uncertainties[new_idx] = base_ds.uncertainties[old_idx]

        num_cols = [c for c, t in cleaned_types.items() if t == "NUMERICAL"]
        confidence = 1.0 if num_cols else 0.0
        fallback = None if num_cols else "No quantitative numerical measures found in group; table view provided."
        suggested = ChartType.BAR_CHART if num_cols else ChartType.TABLE_VIEW

        col_start = min(col_indices) if col_indices else 0
        col_end = max(col_indices) if col_indices else 0

        return ParsedTableDataset(
            columns=cleaned_columns,
            rows=new_rows,
            column_types=cleaned_types,
            format_detected=base_ds.format_detected,
            suggested_chart_type=suggested,
            column_units=cleaned_units,
            uncertainties=new_uncertainties,
            confidence_score=confidence,
            fallback_reason=fallback,
            group_name=group_name,
            source_range={"row_start": 0, "row_end": len(new_rows), "col_start": col_start, "col_end": col_end, "columns": new_columns},
            is_subgroup=True,
        )

    def generate_charts(
        self,
        raw_table_text_or_dataset: Union[str, ParsedTableDataset],
        style: Optional[ChartStyleConfig] = None,
    ) -> List[RenderedChart]:
        """Generates one chart per detected data group with confidence gating and metadata tagging."""
        if isinstance(raw_table_text_or_dataset, ParsedTableDataset):
            datasets = [raw_table_text_or_dataset]
        else:
            datasets = self.segment_table(raw_table_text_or_dataset)

        if not datasets:
            return []

        charts: List[RenderedChart] = []
        for ds in datasets:
            cfg = copy.copy(style) if style else ChartStyleConfig()
            if ds.group_name and not cfg.title:
                cfg.title = f"{ds.group_name}"

            chart = self.engine.generate_chart(ds, style=cfg)
            chart.group_name = ds.group_name
            chart.source_range = ds.source_range
            charts.append(chart)

        # Wire cross-references so any single chart can navigate its sibling sub-charts
        for c in charts:
            c.sub_charts = charts

        return charts
