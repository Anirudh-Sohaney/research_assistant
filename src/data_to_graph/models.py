"""Data models for Data to Graph Subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ChartType(str, Enum):
    BAR_CHART = "BAR_CHART"
    LINE_CHART = "LINE_CHART"
    SCATTER_DOT = "SCATTER_DOT"
    BOX_PLOT = "BOX_PLOT"
    HISTOGRAM = "HISTOGRAM"


@dataclass
class ChartStyleConfig:
    """Styling configuration for rendered graphics."""
    dpi: int = 300
    palette: str = "seaborn-v0_8-paper"
    title: Optional[str] = None
    x_label: Optional[str] = None
    y_label: Optional[str] = None


@dataclass
class ParsedTableDataset:
    """Structured tabular dataset extracted from text."""
    columns: List[str]
    rows: List[List[Any]]
    column_types: Dict[str, str] = field(default_factory=dict)
    format_detected: str = "CSV"
    suggested_chart_type: ChartType = ChartType.BAR_CHART


@dataclass
class RenderedChart:
    """Output artifact containing rendered vector and raster image data."""
    png_bytes: bytes
    svg_text: str
    chart_type: ChartType
    dataset: ParsedTableDataset
    available_alternatives: List[ChartType] = field(default_factory=list)
