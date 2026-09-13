"""Data models for Overlay UI Subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class CardType(str, Enum):
    DEFINITION = "DEFINITION"
    SYNONYMS = "SYNONYMS"
    EVIDENCE_STANCE = "EVIDENCE_STANCE"
    SIMILAR_PAPERS = "SIMILAR_PAPERS"
    SOURCE_SUMMARY = "SOURCE_SUMMARY"
    GRAPH_PREVIEW = "GRAPH_PREVIEW"
    CITATION = "CITATION"


@dataclass
class ScreenRect:
    x: int
    y: int
    width: int
    height: int


@dataclass
class PopupItem:
    id: str
    title: str
    subtitle: Optional[str] = None
    badge: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PopupCardPayload:
    card_type: CardType
    title: str
    items: List[PopupItem] = field(default_factory=list)
    interactive_actions: List[str] = field(default_factory=list)
    allow_user_prompts: bool = False
    custom_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PopupActionEvent:
    window_id: str
    action: str
    item_id: Optional[str] = None
    text_input: Optional[str] = None


@dataclass
class PopupHandle:
    window_id: str
    is_visible: bool
    bounds: ScreenRect
    active_payload: Optional[PopupCardPayload] = None
    on_action: Optional[Callable[[PopupActionEvent], None]] = None
