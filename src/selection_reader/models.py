"""Data models for Selection Reader Subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Tuple


@dataclass
class AppInfo:
    """Active application details."""
    name: str
    title: str
    category: str
    pid: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "category": self.category,
            "pid": self.pid,
        }


@dataclass
class HoveredWordMatch:
    """Represents a candidate word hovered over by the mouse cursor."""
    word: str
    bounding_box: Tuple[float, float, float, float]  # (x, y, width, height)
    overlap_pixels: int
    is_part_of_selection: bool


@dataclass
class SelectionPayload:
    """Payload representing extracted desktop selection and hovered word."""
    selected_text: str
    app: AppInfo
    hovered_word: Optional[str] = None
    cursor_position: Optional[Tuple[int, int]] = None
    overlap_pixels: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_text": self.selected_text,
            "hovered_word": self.hovered_word,
            "cursor_position": self.cursor_position,
            "overlap_pixels": self.overlap_pixels,
            "app": self.app.to_dict(),
            "timestamp": self.timestamp,
        }
