"""Overlay UI Subsystem."""

from overlay_ui.models import (
    CardType,
    PopupActionEvent,
    PopupCardPayload,
    PopupHandle,
    PopupItem,
    ScreenRect,
)
from overlay_ui.overlay import (
    OverlayUIManager,
    calculate_clamped_bounds,
    dismiss_popup,
    display_popup_card,
    get_screen_dimensions,
    update_popup_content,
)

from overlay_ui.pyqt_synonym_overlay import (
    PyQtSynonymOverlay,
    SynonymOverlayBridge,
    get_synonym_overlay_bridge,
)

__all__ = [
    "CardType",
    "PopupActionEvent",
    "PopupCardPayload",
    "PopupHandle",
    "PopupItem",
    "ScreenRect",
    "OverlayUIManager",
    "calculate_clamped_bounds",
    "display_popup_card",
    "update_popup_content",
    "dismiss_popup",
    "get_screen_dimensions",
    "PyQtSynonymOverlay",
    "SynonymOverlayBridge",
    "get_synonym_overlay_bridge",
]
