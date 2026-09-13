"""Tests for hotkey_manager subsystem."""

import time
from unittest.mock import MagicMock, patch
import pytest

from hotkey_manager.models import (
    HotkeyPressedEvent,
    InterceptionMode,
    ListenerHandle,
    RegistrationResult,
    UnregistrationResult,
)
from hotkey_manager.manager import (
    HotkeyManager,
    DEFAULT_KEY_BINDINGS,
    register_hotkeys,
    unregister_hotkeys,
    listen_hotkey_stream,
    stop_listening,
)


def test_default_registration():
    manager = HotkeyManager()
    res = manager.register_hotkeys()
    assert res.success is True
    assert "synonym" in res.bound_chords
    assert res.bound_chords["synonym"] == "<alt>+o"
    assert len(res.bound_chords) == len(DEFAULT_KEY_BINDINGS)


def test_custom_registration_and_override():
    manager = HotkeyManager()
    res = manager.register_hotkeys({"custom_action": "<ctrl>+<alt>+z", "synonym": "<ctrl>+s"})
    assert res.success is True
    assert res.bound_chords["custom_action"] == "<ctrl>+<alt>+z"
    assert res.bound_chords["synonym"] == "<ctrl>+s"


def test_unregistration():
    manager = HotkeyManager()
    # Unregister specific
    res1 = manager.unregister_hotkeys(["synonym", "definition"])
    assert res1.released_count == 2
    assert "synonym" not in manager.bindings
    assert "definition" not in manager.bindings

    # Unregister all
    res2 = manager.unregister_hotkeys()
    assert res2.released_count == len(DEFAULT_KEY_BINDINGS) - 2
    assert res2.remaining_count == 0
    assert len(manager.bindings) == 0


def test_debounce_mechanism():
    manager = HotkeyManager(debounce_ms=100.0)
    received_events = []

    def on_event(ev: HotkeyPressedEvent):
        received_events.append(ev)

    manager.callback = on_event
    handler = manager._create_action_handler("test_act", "<ctrl>+t")

    # Fire once
    handler()
    assert len(received_events) == 1
    assert received_events[0].action == "test_act"
    assert received_events[0].chord == "<ctrl>+t"

    # Fire immediately again within debounce window (should be discarded)
    handler()
    handler()
    assert len(received_events) == 1

    # Sleep past debounce window (100ms + margin)
    time.sleep(0.12)
    handler()
    assert len(received_events) == 2


def test_listener_lifecycle():
    with patch("hotkey_manager.manager.keyboard.GlobalHotKeys") as mock_ghk:
        mock_instance = MagicMock()
        mock_ghk.return_value = mock_instance

        manager = HotkeyManager()
        handle = manager.listen_hotkey_stream(callback=lambda ev: None)
        assert handle.is_listening is True
        mock_instance.start.assert_called_once()

        manager.stop_listening()
        assert manager._is_listening is False
        mock_instance.stop.assert_called_once()


def test_module_level_helpers():
    with patch("hotkey_manager.manager.keyboard.GlobalHotKeys") as mock_ghk:
        mock_instance = MagicMock()
        mock_ghk.return_value = mock_instance

        reg_res = register_hotkeys({"test_mod": "<alt>+m"})
        assert reg_res.success is True
        assert "test_mod" in reg_res.bound_chords

        handle = listen_hotkey_stream(lambda ev: None)
        assert isinstance(handle, ListenerHandle)

        stop_listening()
        unreg_res = unregister_hotkeys(["test_mod"])
        assert unreg_res.released_count == 1
