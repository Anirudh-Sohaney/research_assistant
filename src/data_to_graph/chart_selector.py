"""Chart Selection Engine supporting the Top 20 Most-Used Graph Types.

Implements rule-based routing based on data shape + intent signals,
with strict confidence gates and graceful fallbacks.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from data_to_graph.models import ChartType, ParsedTableDataset


@dataclass
class ChartSelectionResult:
    """Result of chart type selection including confidence score and alternatives."""
    suggested_chart_type: ChartType
    confidence_score: float = 1.0
    fallback_reason: Optional[str] = None
    available_alternatives: List[ChartType] = field(default_factory=list)
    intent_detected: Optional[str] = None


DATETIME_KEYWORDS: Set[str] = {
    "date", "time", "year", "month", "day", "epoch", "step", "iter",
    "iteration", "round", "quarter", "qtr", "period", "timestamp",
    "joint", "joints", "layer", "layers", "week", "hour", "minute",
}

GANTT_TASK_KEYWORDS: Set[str] = {"task", "activity", "item", "event", "job", "phase", "milestone"}
GANTT_START_KEYWORDS: Set[str] = {"start", "begin", "start_date", "start_time", "from"}
GANTT_END_KEYWORDS: Set[str] = {"end", "finish", "end_date", "end_time", "to", "duration", "days", "hours"}

FUNNEL_KEYWORDS: Set[str] = {"stage", "step", "funnel", "pipeline", "dropoff", "conversion", "leads", "visitors"}
WATERFALL_KEYWORDS: Set[str] = {"waterfall", "variance", "delta", "contribution", "ebitda", "cashflow", "bridge", "net"}
GAUGE_KEYWORDS: Set[str] = {"target", "goal", "kpi", "progress", "completion", "gauge", "quota", "achievement", "score"}
RADAR_KEYWORDS: Set[str] = {"radar", "spider", "skills", "skill", "benchmark", "rubric", "competencies", "attributes", "dimensions"}
PIE_DONUT_KEYWORDS: Set[str] = {"share", "percent", "pct", "proportion", "breakdown", "pie", "donut", "ratio", "split", "allocation"}
STACKED_KEYWORDS: Set[str] = {"stacked", "composition", "breakdown", "components", "parts"}
CUMULATIVE_KEYWORDS: Set[str] = {"cumulative", "volume", "area", "growth", "total"}


def is_datetime_or_sequential(col_name: str, values: List[Any]) -> bool:
    """Detects if a column represents time or ordered sequential steps."""
    name_lower = col_name.lower().strip()
    if any(kw in name_lower for kw in DATETIME_KEYWORDS):
        return True

    # Sample value checks
    str_vals = [str(v).strip() for v in values[:10] if str(v).strip()]
    if not str_vals:
        return False

    date_patterns = [
        r"^\d{4}-\d{2}-\d{2}",       # 2026-09-13
        r"^\d{2}/\d{2}/\d{2,4}",     # 09/13/2026
        r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)",
        r"^Q[1-4](?:[\s_-]?\d{2,4})?$",  # Q1, Q1 2026
    ]
    matches = sum(1 for v in str_vals if any(re.search(p, v, re.IGNORECASE) for p in date_patterns))
    return matches / len(str_vals) >= 0.6


def _find_col_by_keywords(columns: List[str], keywords: Set[str]) -> Optional[str]:
    """Finds first column matching any of the specified keywords."""
    for c in columns:
        c_lower = c.lower().strip()
        for kw in keywords:
            if kw in c_lower or re.search(rf"\b{kw}\b", c_lower):
                return c
    return None


def select_chart_type(dataset: ParsedTableDataset) -> ChartSelectionResult:
    """Decision tree routing on data shape + intent signals with strict confidence gates."""
    columns = dataset.columns
    parsed_rows = dataset.rows
    col_types = dataset.column_types
    units = dataset.column_units

    cat_cols = [c for c, t in col_types.items() if t == "CATEGORICAL"]
    num_cols = [c for c, t in col_types.items() if t == "NUMERICAL"]
    n_rows = len(parsed_rows)
    all_headers_lower = " ".join(c.lower() for c in columns)
    is_x_time = is_datetime_or_sequential(columns[0], [r[0] for r in parsed_rows if r]) if columns else False

    # -----------------------------------------------------------------
    # Gate 0: Non-numeric Fallback
    # -----------------------------------------------------------------
    if not num_cols:
        return ChartSelectionResult(
            suggested_chart_type=ChartType.TABLE_VIEW,
            confidence_score=0.0,
            fallback_reason="No quantitative numerical measures found in table; formatted table view provided.",
            available_alternatives=[],
        )

    # -----------------------------------------------------------------
    # 1. Candlestick Chart (Open, High, Low, Close)
    # -----------------------------------------------------------------
    open_c = _find_col_by_keywords(columns, {"open"})
    high_c = _find_col_by_keywords(columns, {"high"})
    low_c = _find_col_by_keywords(columns, {"low"})
    close_c = _find_col_by_keywords(columns, {"close"})
    if open_c and high_c and low_c and close_c and len(num_cols) >= 4:
        return ChartSelectionResult(
            suggested_chart_type=ChartType.CANDLESTICK_CHART,
            confidence_score=1.0,
            intent_detected="Financial OHLC time series",
            available_alternatives=[ChartType.LINE_CHART, ChartType.AREA_CHART],
        )

    # -----------------------------------------------------------------
    # 2. Gantt Chart (Task + Start + End/Duration)
    # -----------------------------------------------------------------
    task_c = _find_col_by_keywords(columns, GANTT_TASK_KEYWORDS) or (cat_cols[0] if cat_cols else None)
    start_c = _find_col_by_keywords(columns, GANTT_START_KEYWORDS)
    end_c = _find_col_by_keywords(columns, GANTT_END_KEYWORDS)
    if task_c and start_c and end_c and any(kw in all_headers_lower for kw in ("start", "duration", "timeline", "schedule")):
        return ChartSelectionResult(
            suggested_chart_type=ChartType.GANTT_CHART,
            confidence_score=1.0,
            intent_detected="Project schedule / timeline",
            available_alternatives=[ChartType.HORIZONTAL_BAR, ChartType.TABLE_VIEW],
        )

    # -----------------------------------------------------------------
    # 3. Gauge Chart (Single value vs target / KPI / goal)
    # -----------------------------------------------------------------
    has_gauge_intent = any(kw in all_headers_lower for kw in GAUGE_KEYWORDS)
    if (n_rows == 1 or n_rows == 2) and len(num_cols) in (1, 2) and has_gauge_intent:
        return ChartSelectionResult(
            suggested_chart_type=ChartType.GAUGE_CHART,
            confidence_score=1.0,
            intent_detected="Single KPI metric against target/threshold",
            available_alternatives=[ChartType.BAR_CHART, ChartType.TABLE_VIEW],
        )

    # -----------------------------------------------------------------
    # 4. Waterfall Chart (Sequential positive/negative deltas to total)
    # -----------------------------------------------------------------
    has_waterfall_intent = any(kw in all_headers_lower for kw in WATERFALL_KEYWORDS)
    if len(num_cols) == 1 and cat_cols and (3 <= n_rows <= 12):
        val_idx = columns.index(num_cols[0])
        nums = [float(r[val_idx]) for r in parsed_rows if isinstance(r[val_idx], (int, float))]
        has_pos_and_neg = any(v > 0 for v in nums) and any(v < 0 for v in nums)
        cat_vals_lower = [str(r[columns.index(cat_cols[0])]).lower() for r in parsed_rows]
        has_net_step = any(kw in " ".join(cat_vals_lower) for kw in ("net", "total", "ebitda", "ending", "bridge", "starting"))
        if has_waterfall_intent or (has_pos_and_neg and has_net_step):
            return ChartSelectionResult(
                suggested_chart_type=ChartType.WATERFALL_CHART,
                confidence_score=1.0,
                intent_detected="Sequential variance / waterfall bridge",
                available_alternatives=[ChartType.BAR_CHART, ChartType.LINE_CHART],
            )

    # -----------------------------------------------------------------
    # 5. Treemap (Hierarchical categories or part-to-whole with multiple categories)
    # -----------------------------------------------------------------
    has_treemap_intent = any(kw in all_headers_lower for kw in ("treemap", "parent", "sub-category", "hierarchy"))
    if (len(cat_cols) >= 2 and len(num_cols) >= 1) or (has_treemap_intent and cat_cols and len(num_cols) >= 1):
        return ChartSelectionResult(
            suggested_chart_type=ChartType.TREEMAP,
            confidence_score=1.0,
            intent_detected="Hierarchical part-to-whole tree structure",
            available_alternatives=[ChartType.BAR_CHART, ChartType.HEATMAP],
        )

    # -----------------------------------------------------------------
    # 6. Pie Chart & Donut Chart (Proportions of whole, Cardinality <= 6, 1 category dimension)
    # -----------------------------------------------------------------
    if len(cat_cols) == 1 and len(num_cols) == 1 and (2 <= n_rows <= 6):
        num_c = num_cols[0]
        c_unit = units.get(num_c, "")
        val_idx = columns.index(num_c)
        nums = [float(r[val_idx]) for r in parsed_rows if isinstance(r[val_idx], (int, float))]
        all_positive = all(v >= 0 for v in nums)
        val_sum = sum(nums)
        is_pct_scale = c_unit in ("%", "pct") or (85.0 <= val_sum <= 115.0) or ("%" in num_c) or ("share" in num_c.lower())
        has_pie_intent = any(kw in all_headers_lower for kw in PIE_DONUT_KEYWORDS)

        if all_positive and (is_pct_scale or has_pie_intent):
            is_donut = "donut" in all_headers_lower or "ratio" in all_headers_lower
            target = ChartType.DONUT_CHART if is_donut else ChartType.PIE_CHART
            alt = ChartType.PIE_CHART if is_donut else ChartType.DONUT_CHART
            return ChartSelectionResult(
                suggested_chart_type=target,
                confidence_score=1.0,
                intent_detected="Part-to-whole composition with low cardinality (<= 6)",
                available_alternatives=[alt, ChartType.BAR_CHART, ChartType.HORIZONTAL_BAR],
            )

    # -----------------------------------------------------------------
    # 7. Funnel Chart (Stages with sequential dropoff / conversion)
    # -----------------------------------------------------------------
    has_funnel_intent = any(kw in all_headers_lower for kw in FUNNEL_KEYWORDS)
    if len(num_cols) == 1 and cat_cols and (3 <= n_rows <= 10):
        val_idx = columns.index(num_cols[0])
        nums = [float(r[val_idx]) for r in parsed_rows if isinstance(r[val_idx], (int, float))]
        is_decreasing = len(nums) >= 3 and all(nums[i] >= nums[i+1] for i in range(len(nums)-1))
        cat_vals_lower = [str(r[columns.index(cat_cols[0])]).lower() for r in parsed_rows]
        stages_have_funnel = any(any(kw in cv for kw in FUNNEL_KEYWORDS) for cv in cat_vals_lower)
        if has_funnel_intent or (is_decreasing and stages_have_funnel):
            return ChartSelectionResult(
                suggested_chart_type=ChartType.FUNNEL_CHART,
                confidence_score=1.0,
                intent_detected="Sequential funnel conversion stages",
                available_alternatives=[ChartType.HORIZONTAL_BAR, ChartType.BAR_CHART],
            )

    # -----------------------------------------------------------------
    # 8. Stacked Bar & Stacked Area (Category/Time components)
    # -----------------------------------------------------------------
    has_stacked_intent = any(kw in all_headers_lower for kw in STACKED_KEYWORDS)
    if len(num_cols) >= 2 and has_stacked_intent:
        if is_x_time:
            return ChartSelectionResult(
                suggested_chart_type=ChartType.STACKED_AREA,
                confidence_score=1.0,
                intent_detected="Part-to-whole trend over time",
                available_alternatives=[ChartType.LINE_CHART, ChartType.STACKED_BAR],
            )
        else:
            return ChartSelectionResult(
                suggested_chart_type=ChartType.STACKED_BAR,
                confidence_score=1.0,
                intent_detected="Category totals segmented into sub-parts",
                available_alternatives=[ChartType.BAR_CHART, ChartType.HEATMAP],
            )

    # -----------------------------------------------------------------
    # 9. Bubble Chart (3 numeric dimensions: X, Y, Size)
    # -----------------------------------------------------------------
    if len(num_cols) >= 3:
        size_keywords = {"size", "volume", "pop", "population", "market_cap", "weight", "bubble", "radius"}
        has_bubble_signal = any(any(kw in c.lower() for kw in size_keywords) for c in num_cols[2:]) or any(kw in all_headers_lower for kw in ("bubble", "3d", "correlation_size"))
        if has_bubble_signal or (len(num_cols) == 3 and not cat_cols and not is_x_time):
            return ChartSelectionResult(
                suggested_chart_type=ChartType.BUBBLE_CHART,
                confidence_score=1.0,
                intent_detected="Three numeric dimensions (X, Y, Size)",
                available_alternatives=[ChartType.SCATTER_DOT, ChartType.BAR_CHART],
            )

    # -----------------------------------------------------------------
    # 10. Radar Chart (3 to 8 numeric axes across 1 to 6 entities)
    # -----------------------------------------------------------------
    has_radar_intent = any(kw in all_headers_lower for kw in RADAR_KEYWORDS)
    if (3 <= len(num_cols) <= 8) and (1 <= n_rows <= 6):
        if has_radar_intent or (cat_cols and len(num_cols) >= 3 and not is_x_time):
            return ChartSelectionResult(
                suggested_chart_type=ChartType.RADAR_CHART,
                confidence_score=1.0,
                intent_detected="Multivariate entity comparison across 3-8 axes",
                available_alternatives=[ChartType.BAR_CHART, ChartType.HEATMAP],
            )

    # -----------------------------------------------------------------
    # 11. Pair Plot (Multivariate scatter matrix for 3+ numeric columns)
    # -----------------------------------------------------------------
    has_pair_intent = any(kw in all_headers_lower for kw in ("pair", "pairs", "scatter_matrix", "multivariate", "pairwise"))
    if len(num_cols) >= 3 and has_pair_intent:
        return ChartSelectionResult(
            suggested_chart_type=ChartType.PAIR_PLOT,
            confidence_score=1.0,
            intent_detected="Pairwise scatter plot matrix across numeric variables",
            available_alternatives=[ChartType.HEATMAP, ChartType.SCATTER_DOT],
        )

    # -----------------------------------------------------------------
    # 12. Heatmap (2D matrix or correlation matrix)
    # -----------------------------------------------------------------
    has_heatmap_intent = any(kw in all_headers_lower for kw in ("heatmap", "matrix", "correlation", "confusion", "density"))
    if (len(num_cols) >= 4 and n_rows >= 3) and (has_heatmap_intent or not cat_cols):
        return ChartSelectionResult(
            suggested_chart_type=ChartType.HEATMAP,
            confidence_score=1.0,
            intent_detected="2D intensity matrix / correlation grid",
            available_alternatives=[ChartType.PAIR_PLOT, ChartType.BAR_CHART],
        )

    # -----------------------------------------------------------------
    # 13. Box Plot (Distribution spread / quartiles)
    # -----------------------------------------------------------------
    has_box_intent = any(kw in all_headers_lower for kw in ("box", "distribution", "spread", "quartile", "iqr", "variance"))
    if has_box_intent and len(num_cols) >= 1:
        return ChartSelectionResult(
            suggested_chart_type=ChartType.BOX_PLOT,
            confidence_score=1.0,
            intent_detected="Distribution spread and quartile analysis",
            available_alternatives=[ChartType.HISTOGRAM, ChartType.BAR_CHART],
        )

    # -----------------------------------------------------------------
    # 14. Temporal / Sequential Trends (Area & Line)
    # -----------------------------------------------------------------
    if is_x_time and len(num_cols) >= 1:
        if any(kw in all_headers_lower for kw in CUMULATIVE_KEYWORDS):
            return ChartSelectionResult(
                suggested_chart_type=ChartType.AREA_CHART,
                confidence_score=1.0,
                intent_detected="Cumulative volume or trend over continuous sequence",
                available_alternatives=[ChartType.LINE_CHART, ChartType.BAR_CHART],
            )
        return ChartSelectionResult(
            suggested_chart_type=ChartType.LINE_CHART,
            confidence_score=1.0,
            intent_detected="Temporal trend over sequential axis",
            available_alternatives=[ChartType.AREA_CHART, ChartType.BAR_CHART],
        )

    # -----------------------------------------------------------------
    # 15. Scatter Plot (Correlation between 2 numeric variables)
    # -----------------------------------------------------------------
    if len(num_cols) == 2 and not cat_cols:
        return ChartSelectionResult(
            suggested_chart_type=ChartType.SCATTER_DOT,
            confidence_score=1.0,
            intent_detected="Bivariate relationship / correlation",
            available_alternatives=[ChartType.LINE_CHART, ChartType.BAR_CHART],
        )

    # -----------------------------------------------------------------
    # 16. Histogram (Distribution of single numeric variable)
    # -----------------------------------------------------------------
    if len(num_cols) == 1 and not cat_cols:
        return ChartSelectionResult(
            suggested_chart_type=ChartType.HISTOGRAM,
            confidence_score=1.0,
            intent_detected="Univariate frequency distribution",
            available_alternatives=[ChartType.BOX_PLOT, ChartType.BAR_CHART],
        )

    # -----------------------------------------------------------------
    # 17. Horizontal Bar Chart (Long labels or > 8 categories)
    # -----------------------------------------------------------------
    if cat_cols and len(num_cols) >= 1:
        first_col_vals = [str(r[columns.index(cat_cols[0])]) for r in parsed_rows if r]
        has_long_labels = any(len(v) > 14 for v in first_col_vals)
        if n_rows > 8 or has_long_labels:
            return ChartSelectionResult(
                suggested_chart_type=ChartType.HORIZONTAL_BAR,
                confidence_score=1.0,
                intent_detected="Categorical comparison with many or long labels",
                available_alternatives=[ChartType.BAR_CHART, ChartType.LINE_CHART],
            )

    # -----------------------------------------------------------------
    # 18. Default: Bar Chart
    # -----------------------------------------------------------------
    res = ChartSelectionResult(
        suggested_chart_type=ChartType.BAR_CHART,
        confidence_score=1.0,
        intent_detected="Standard discrete categorical comparison",
        available_alternatives=[ChartType.HORIZONTAL_BAR, ChartType.LINE_CHART],
    )
    # Refine available_alternatives strictly to compatible charts
    compatible = get_compatible_chart_types(dataset)
    res.available_alternatives = [t for t in compatible if t != res.suggested_chart_type]
    return res


def get_compatible_chart_types(dataset: ParsedTableDataset) -> List[ChartType]:
    """Returns strictly the chart types that are structurally valid and compatible with the dataset."""
    columns = dataset.columns
    parsed_rows = dataset.rows
    col_types = dataset.column_types

    cat_cols = [c for c, t in col_types.items() if t == "CATEGORICAL"]
    num_cols = [c for c, t in col_types.items() if t == "NUMERICAL"]
    n_rows = len(parsed_rows)
    is_x_time = is_datetime_or_sequential(columns[0], [r[0] for r in parsed_rows if r]) if columns and parsed_rows else False

    if not num_cols or not parsed_rows:
        return [ChartType.TABLE_VIEW]

    compatible: List[ChartType] = []

    # Bar and Horizontal Bar (compatible with any quantitative data)
    if len(num_cols) >= 1:
        compatible.append(ChartType.BAR_CHART)
        compatible.append(ChartType.HORIZONTAL_BAR)

    # Line Chart & Area Chart
    if len(num_cols) >= 1 and n_rows >= 2:
        compatible.append(ChartType.LINE_CHART)
        compatible.append(ChartType.AREA_CHART)

    # Pie & Donut: strictly when 1 num col, non-negative values, cardinality <= 6
    if len(num_cols) == 1 and (2 <= n_rows <= 6):
        val_idx = columns.index(num_cols[0])
        nums = [float(r[val_idx]) for r in parsed_rows if isinstance(r[val_idx], (int, float))]
        if all(v >= 0 for v in nums):
            compatible.append(ChartType.PIE_CHART)
            compatible.append(ChartType.DONUT_CHART)

    # Stacked Bar: requires at least 2 numeric columns
    if len(num_cols) >= 2:
        compatible.append(ChartType.STACKED_BAR)

    # Stacked Area: requires at least 2 numeric columns and sequential rows
    if len(num_cols) >= 2 and n_rows >= 2:
        compatible.append(ChartType.STACKED_AREA)

    # Scatter Plot: requires at least 2 numeric variables
    if len(num_cols) >= 2:
        compatible.append(ChartType.SCATTER_DOT)

    # Bubble Chart: requires at least 3 numeric variables
    if len(num_cols) >= 3:
        compatible.append(ChartType.BUBBLE_CHART)

    # Histogram: distribution of numeric values
    if len(num_cols) >= 1 and n_rows >= 3:
        compatible.append(ChartType.HISTOGRAM)

    # Box Plot: requires distribution spread
    if len(num_cols) >= 1 and n_rows >= 4:
        compatible.append(ChartType.BOX_PLOT)

    # Heatmap: 2D intensity matrix
    if len(num_cols) >= 3 and n_rows >= 2:
        compatible.append(ChartType.HEATMAP)

    # Radar: strictly 3 to 8 numeric metrics across 1 to 6 entities
    if (3 <= len(num_cols) <= 8) and (1 <= n_rows <= 6):
        compatible.append(ChartType.RADAR_CHART)

    # Gauge: 1 to 2 rows with 1 to 2 metrics
    if (1 <= n_rows <= 2) and (1 <= len(num_cols) <= 2):
        compatible.append(ChartType.GAUGE_CHART)

    # Waterfall: delta column across sequential steps
    if len(num_cols) >= 1 and (3 <= n_rows <= 15):
        compatible.append(ChartType.WATERFALL_CHART)

    # Gantt: task + start + duration/end
    start_c = _find_col_by_keywords(columns, GANTT_START_KEYWORDS)
    end_c = _find_col_by_keywords(columns, GANTT_END_KEYWORDS)
    if start_c and end_c:
        compatible.append(ChartType.GANTT_CHART)

    # Funnel: 1 numeric column across 3 to 10 stages
    if len(num_cols) >= 1 and (3 <= n_rows <= 10):
        compatible.append(ChartType.FUNNEL_CHART)

    # Candlestick: requires OHLC columns
    open_c = _find_col_by_keywords(columns, {"open"})
    high_c = _find_col_by_keywords(columns, {"high"})
    low_c = _find_col_by_keywords(columns, {"low"})
    close_c = _find_col_by_keywords(columns, {"close"})
    if open_c and high_c and low_c and close_c and len(num_cols) >= 4:
        compatible.append(ChartType.CANDLESTICK_CHART)

    # Treemap: hierarchical categories
    if len(cat_cols) >= 2 and len(num_cols) >= 1:
        compatible.append(ChartType.TREEMAP)

    # Pair Plot: at least 3 continuous numeric variables
    if len(num_cols) >= 3 and n_rows >= 4:
        compatible.append(ChartType.PAIR_PLOT)

    # Table view is always available as fallback
    compatible.append(ChartType.TABLE_VIEW)

    return compatible

