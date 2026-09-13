"""Data to Graph Subsystem for Research Aid."""

from data_to_graph.models import (
    ChartType,
    ChartStyleConfig,
    ParsedTableDataset,
    RenderedChart,
    ChartCollection,
)
from data_to_graph.grapher import (
    TableGraphEngine,
    parse_tabular_data,
    generate_chart,
    toggle_chart_type,
    generate_charts_for_table,
    parse_multi_group_tables,
)
from data_to_graph.segmenter import TableSegmenter
from data_to_graph.overlay import (
    TableGraphOverlay,
    TableGraphOverlayBridge,
    get_table_graph_overlay_bridge,
    show_table_graph_overlay,
)

__all__ = [
    "ChartType",
    "ChartStyleConfig",
    "ParsedTableDataset",
    "RenderedChart",
    "ChartCollection",
    "TableGraphEngine",
    "TableSegmenter",
    "TableGraphOverlay",
    "TableGraphOverlayBridge",
    "get_table_graph_overlay_bridge",
    "show_table_graph_overlay",
    "parse_tabular_data",
    "generate_chart",
    "toggle_chart_type",
    "generate_charts_for_table",
    "parse_multi_group_tables",
]
