"""Data models for Text Injector Subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class InjectionTier(str, Enum):
    ACCESSIBILITY_DIRECT = "ACCESSIBILITY_DIRECT"
    CLIPBOARD_PASTE = "CLIPBOARD_PASTE"
    SYNTHETIC_KEYSTROKES = "SYNTHETIC_KEYSTROKES"


@dataclass
class WindowMetadata:
    """Metadata describing the target application window."""
    name: str = "unknown"
    title: str = "unknown"
    category: str = "general"
    pid: int = 0


@dataclass
class InjectionResult:
    """Outcome report for a text/media injection operation."""
    success: bool
    strategy: InjectionTier
    latency_ms: float
    clipboard_restored: bool = True
    error: Optional[str] = None
