"""Hotkey Manager Subsystem for Research Aid."""

from hotkey_manager.models import (
    InterceptionMode,
    HotkeyPressedEvent,
    RegistrationResult,
    UnregistrationResult,
    ListenerHandle,
)
from hotkey_manager.manager import (
    HotkeyManager,
    register_hotkeys,
    unregister_hotkeys,
    listen_hotkey_stream,
    stop_listening,
)

__all__ = [
    "InterceptionMode",
    "HotkeyPressedEvent",
    "RegistrationResult",
    "UnregistrationResult",
    "ListenerHandle",
    "HotkeyManager",
    "register_hotkeys",
    "unregister_hotkeys",
    "listen_hotkey_stream",
    "stop_listening",
]
