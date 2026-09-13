"""Data models for Data to Graph Subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union


class ChartType(str, Enum):
    BAR_CHART = "BAR_CHART"
    LINE_CHART = "LINE_CHART"
    PIE_CHART = "PIE_CHART"
    DONUT_CHART = "DONUT_CHART"
    SCATTER_DOT = "SCATTER_DOT"
    HISTOGRAM = "HISTOGRAM"
    AREA_CHART = "AREA_CHART"
    STACKED_BAR = "STACKED_BAR"
    STACKED_AREA = "STACKED_AREA"
    BUBBLE_CHART = "BUBBLE_CHART"
    BOX_PLOT = "BOX_PLOT"
    HEATMAP = "HEATMAP"
    RADAR_CHART = "RADAR_CHART"
    GAUGE_CHART = "GAUGE_CHART"
    WATERFALL_CHART = "WATERFALL_CHART"
    TREEMAP = "TREEMAP"
    GANTT_CHART = "GANTT_CHART"
    FUNNEL_CHART = "FUNNEL_CHART"
    CANDLESTICK_CHART = "CANDLESTICK_CHART"
    PAIR_PLOT = "PAIR_PLOT"
    HORIZONTAL_BAR = "HORIZONTAL_BAR"
    TABLE_VIEW = "TABLE_VIEW"


@dataclass
class ChartStyleConfig:
    """Styling configuration for rendered graphics."""
    dpi: int = 300
    palette: str = "academic"  # "academic", "colorblind", "scifi", "grayscale", "seaborn"
    title: Optional[str] = None
    x_label: Optional[str] = None
    y_label: Optional[str] = None
    dark_mode: bool = False
    show_grid: bool = True
    show_values: bool = False
    figure_size: Tuple[float, float] = (6.5, 4.0)


@dataclass
class ParsedTableDataset:
    """Structured tabular dataset extracted from text."""
    columns: List[str]
    rows: List[List[Any]]
    column_types: Dict[str, str] = field(default_factory=dict)
    format_detected: str = "CSV"
    suggested_chart_type: ChartType = ChartType.BAR_CHART
    column_units: Dict[str, str] = field(default_factory=dict)
    uncertainties: Dict[int, List[Optional[float]]] = field(default_factory=dict)
    confidence_score: float = 1.0
    fallback_reason: Optional[str] = None
    group_name: Optional[str] = None
    source_range: Optional[Dict[str, Any]] = None
    is_subgroup: bool = False


@dataclass
class RenderedChart:
    """Output artifact containing rendered vector and raster image data."""
    png_bytes: bytes
    svg_text: str
    chart_type: ChartType
    dataset: ParsedTableDataset
    available_alternatives: List[ChartType] = field(default_factory=list)
    group_name: Optional[str] = None
    source_range: Optional[Dict[str, Any]] = None
    sub_charts: List[RenderedChart] = field(default_factory=list)


@dataclass
class ChartCollection:
    """Collection of rendered charts from a multi-heading or segmented dataset."""
    charts: List[RenderedChart]
    primary_chart: Optional[RenderedChart] = None
    is_multi_group: bool = False
    source_table_title: Optional[str] = None

    def __post_init__(self):
        if self.charts and self.primary_chart is None:
            self.primary_chart = self.charts[0]
