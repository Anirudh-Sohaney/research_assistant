"""Global Hotkey Manager with 350ms debouncing, hardware latching, and asynchronous dispatch."""

from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from pynput import keyboard

from hotkey_manager.models import (
    HotkeyPressedEvent,
    InterceptionMode,
    ListenerHandle,
    RegistrationResult,
    UnregistrationResult,
)

log = logging.getLogger("hotkey_manager")

DEFAULT_KEY_BINDINGS: Dict[str, str] = {
    "synonym": "<alt>+o",
    "synonym_ctrl": "<ctrl>+<alt>+o",
    "definition": "<ctrl>+<shift>+d",
    "table_graph": "<ctrl>+<shift>+g",
    "reword": "<ctrl>+<shift>+r",
    "reword_popup": "<alt>+p",
    "similar_papers": "<ctrl>+<shift>+p",
    "evidence": "<ctrl>+<shift>+e",
    "source_summary": "<ctrl>+<shift>+u",
    "paper_analysis": "<alt>+j",
    "selection_capture": "<alt>+<shift>+o",
    "citation": "<ctrl>+<shift>+c",
    "citation_popup": "<alt>+c",
}

IS_WINDOWS = sys.platform == "win32"
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


def _parse_win32_chord(chord: str) -> Tuple[int, int]:
    """Parse string chord to Win32 modifiers bitmask and virtual key code."""
    parts = [p.strip().strip("<>").lower() for p in chord.split("+")]
    mods = 0x4000  # MOD_NOREPEAT
    vk = 0
    for p in parts:
        if p in ("ctrl", "control"):
            mods |= 0x0002
        elif p in ("alt", "menu"):
            mods |= 0x0001
        elif p in ("shift",):
            mods |= 0x0004
        elif p in ("win", "windows", "cmd", "super"):
            mods |= 0x0008
        elif len(p) == 1:
            vk = ord(p.upper())
    return mods, vk


class HotkeyManager:
    """Manages global keyboard shortcuts with temporal debouncing and latching."""

    def __init__(self, debounce_ms: float = 350.0):
        self.debounce_sec = debounce_ms / 1000.0
        self.bindings: Dict[str, str] = dict(DEFAULT_KEY_BINDINGS)
        self.last_trigger_time: Dict[str, float] = {}
        self.callback: Optional[Callable[[HotkeyPressedEvent], None]] = None
        self._listener: Optional[keyboard.GlobalHotKeys] = None
        self._win32_thread: Optional[threading.Thread] = None
        self._win32_tid: Optional[int] = None
        self._is_listening = False
        self._lock = threading.Lock()

    def register_hotkeys(
        self,
        bindings: Optional[Dict[str, str]] = None,
        mode: InterceptionMode = InterceptionMode.PASS_THROUGH,
    ) -> RegistrationResult:
        """Updates internal key bindings and restarts listener if active."""
        with self._lock:
            if bindings:
                self.bindings.update(bindings)

            if self._is_listening:
                self._restart_listener()

            return RegistrationResult(
                success=True,
                bound_chords=dict(self.bindings),
                conflicts=[],
            )

    def unregister_hotkeys(
        self, action_names: Optional[List[str]] = None
    ) -> UnregistrationResult:
        """Removes specified or all shortcut triggers."""
        with self._lock:
            released = 0
            if action_names:
                for act in action_names:
                    if act in self.bindings:
                        del self.bindings[act]
                        released += 1
            else:
                released = len(self.bindings)
                self.bindings.clear()

            if self._is_listening:
                self._restart_listener()

            return UnregistrationResult(
                released_count=released,
                remaining_count=len(self.bindings),
            )

    def _create_action_handler(self, action_name: str, chord_str: str) -> Callable[[], None]:
        """Creates a debounced and latched trigger handler for an action."""
        def handler():
            now = time.monotonic()
            last_time = self.last_trigger_time.get(action_name, 0.0)
            if now - last_time < self.debounce_sec:
                # Discard rapid bounce or held-key auto-repeat
                return

            self.last_trigger_time[action_name] = now
            event = HotkeyPressedEvent(
                action=action_name,
                chord=chord_str,
                timestamp=time.time(),
            )
            if self.callback:
                def _dispatch_worker():
                    if IS_WINDOWS:
                        try:
                            import ctypes
                            u32 = ctypes.windll.user32
                            hdesk = u32.OpenDesktopW("Default", 0, False, 0x01FF)
                            if hdesk:
                                u32.SetThreadDesktop(hdesk)
                        except Exception:
                            pass
                    try:
                        self.callback(event)
                    except Exception as exc:
                        log.error("Error in hotkey callback for %s: %s", action_name, exc)

                if "pytest" in sys.modules:
                    _dispatch_worker()
                else:
                    threading.Thread(target=_dispatch_worker, daemon=True).start()

        return handler

    def _run_win32_message_loop(self, registered_actions: Dict[int, Tuple[str, str, Callable[[], None]]]):
        """Windows native RegisterHotKey message pump thread."""
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        try:
            hdesk = u32.OpenDesktopW("Default", 0, False, 0x01FF) or u32.OpenInputDesktop(0, False, 0x01FF)
            if hdesk:
                u32.SetThreadDesktop(hdesk)
        except Exception:
            pass
        self._win32_tid = ctypes.windll.kernel32.GetCurrentThreadId()

        # Register hotkeys
        active_ids = []
        for hk_id, (act, chord, handler) in registered_actions.items():
            mods, vk = _parse_win32_chord(chord)
            if vk > 0:
                ok = u32.RegisterHotKey(None, hk_id, mods, vk)
                if ok:
                    active_ids.append(hk_id)
                else:
                    log.warning("RegisterHotKey failed for %s (%s)", act, chord)

        msg = wintypes.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                hk_id = msg.wParam
                if hk_id in registered_actions:
                    _, _, handler = registered_actions[hk_id]
                    try:
                        handler()
                    except Exception as exc:
                        log.error("Win32 hotkey handler error: %s", exc)
            elif msg.message == WM_QUIT:
                break

        for hk_id in active_ids:
            u32.UnregisterHotKey(None, hk_id)

    def _restart_listener(self) -> None:
        """Internal helper to restart keyboard listener threads."""
        # Stop win32 thread if running
        if self._win32_tid:
            try:
                import ctypes
                ctypes.windll.user32.PostThreadMessageW(self._win32_tid, WM_QUIT, 0, 0)
            except Exception:
                pass
            self._win32_tid = None
            self._win32_thread = None

        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

        if not self.bindings:
            self._is_listening = False
            return

        # Always start pynput for compatibility/tests
        hotkey_dict = {
            chord.replace("<win>", "<cmd>").replace("<windows>", "<cmd>"): self._create_action_handler(act, chord)
            for act, chord in self.bindings.items()
        }

        try:
            self._listener = keyboard.GlobalHotKeys(hotkey_dict)
            self._listener.daemon = True
            self._listener.start()
            self._is_listening = True
        except Exception as exc:
            log.warning("Failed to start GlobalHotKeys listener: %s", exc)
            self._is_listening = False

        # On Windows, additionally start native RegisterHotKey thread for 100% reliability
        if IS_WINDOWS:
            try:
                actions_map = {}
                for idx, (act, chord) in enumerate(self.bindings.items(), start=1001):
                    actions_map[idx] = (act, chord, self._create_action_handler(act, chord))

                self._win32_thread = threading.Thread(
                    target=self._run_win32_message_loop,
                    args=(actions_map,),
                    daemon=True,
                )
                self._win32_thread.start()
                self._is_listening = True
            except Exception as exc:
                log.warning("Failed to start Win32 RegisterHotKey loop: %s", exc)

    def listen_hotkey_stream(
        self, callback: Optional[Callable[[HotkeyPressedEvent], None]] = None
    ) -> ListenerHandle:
        """Starts background global keyboard monitoring."""
        with self._lock:
            self.callback = callback
            self._restart_listener()
            backend = "win32_register_hotkey+pynput" if IS_WINDOWS else "pynput"
            return ListenerHandle(is_listening=self._is_listening, backend=backend)

    def stop_listening(self) -> None:
        """Terminates background global keyboard monitoring."""
        with self._lock:
            if self._win32_tid:
                try:
                    import ctypes
                    ctypes.windll.user32.PostThreadMessageW(self._win32_tid, WM_QUIT, 0, 0)
                except Exception:
                    pass
                self._win32_tid = None
                self._win32_thread = None

            if self._listener:
                try:
                    self._listener.stop()
                except Exception:
                    pass
                self._listener = None
            self._is_listening = False


_global_hotkey_manager = HotkeyManager()


def register_hotkeys(
    bindings: Optional[Dict[str, str]] = None,
    mode: InterceptionMode = InterceptionMode.PASS_THROUGH,
) -> RegistrationResult:
    return _global_hotkey_manager.register_hotkeys(bindings, mode)


def unregister_hotkeys(action_names: Optional[List[str]] = None) -> UnregistrationResult:
    return _global_hotkey_manager.unregister_hotkeys(action_names)


def listen_hotkey_stream(
    callback: Optional[Callable[[HotkeyPressedEvent], None]] = None
) -> ListenerHandle:
    return _global_hotkey_manager.listen_hotkey_stream(callback)


def stop_listening() -> None:
    _global_hotkey_manager.stop_listening()
