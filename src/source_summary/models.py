"""Data models for Source Summary Subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SourceType(str, Enum):
    LOCAL_CODEBASE = "LOCAL_CODEBASE"
    GITHUB_REPO = "GITHUB_REPO"
    TABULAR_DATASET = "TABULAR_DATASET"


class ScreenCorner(str, Enum):
    TOP_RIGHT = "TOP_RIGHT"
    BOTTOM_RIGHT = "BOTTOM_RIGHT"
    TOP_LEFT = "TOP_LEFT"
    BOTTOM_LEFT = "BOTTOM_LEFT"


@dataclass
class SourceSummaryReport:
    """Architectural or tabular profile report."""
    source_id: str
    title: str
    source_type: SourceType
    executive_summary: str
    methodology_bullet_points: List[str] = field(default_factory=list)
    statistics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceAnswer:
    """Answer to user query over the source context."""
    markdown_answer: str
    cited_files_or_columns: List[str] = field(default_factory=list)
    confidence: float = 0.9


@dataclass
class InspectorHandle:
    """Handle for the floating methodology sidebar overlay."""
    window_id: str
    corner: ScreenCorner = ScreenCorner.TOP_RIGHT
    is_pinned: bool = True
