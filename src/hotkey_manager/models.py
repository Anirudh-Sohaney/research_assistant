"""Data models for Hotkey Manager Subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class InterceptionMode(str, Enum):
    PASS_THROUGH = "PASS_THROUGH"
    EXCLUSIVE_CONSUME = "EXCLUSIVE_CONSUME"


@dataclass
class HotkeyPressedEvent:
    """Event emitted upon physical key chord match."""
    action: str
    chord: str
    timestamp: float


@dataclass
class RegistrationResult:
    """Outcome of shortcut registration."""
    success: bool
    bound_chords: Dict[str, str] = field(default_factory=dict)
    conflicts: List[str] = field(default_factory=list)


@dataclass
class UnregistrationResult:
    """Outcome of shortcut unregistration."""
    released_count: int
    remaining_count: int


@dataclass
class ListenerHandle:
    """Control token for background shortcut listener."""
    is_listening: bool
    backend: str = "pynput"
