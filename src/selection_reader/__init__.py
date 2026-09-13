"""Selection Reader — Non-intrusive active desktop text extraction package."""

from selection_reader.extractor import extract_selection, inspect_active_window
from selection_reader.models import AppInfo, HoveredWordMatch, SelectionPayload
from selection_reader.ocr_hover import (
    compute_pixel_overlap,
    get_cursor_bounds,
    is_word_in_selection,
    resolve_hovered_word,
)

__all__ = [
    "extract_selection",
    "inspect_active_window",
    "AppInfo",
    "HoveredWordMatch",
    "SelectionPayload",
    "compute_pixel_overlap",
    "get_cursor_bounds",
    "is_word_in_selection",
    "resolve_hovered_word",
]
