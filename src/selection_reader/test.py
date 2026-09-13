#!/usr/bin/env python3
"""Selection Reader — Interactive One-Shot Test.

Waits for the user to highlight text and press Alt+O, extracts the highlighted
text and foreground application info, prints the JSON results, and closes.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import platform
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
SRC_DIR = CURRENT_DIR.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

IS_WINDOWS = platform.system() == "Windows"
_HDESK = None

if IS_WINDOWS:
    try:
        u32 = ctypes.windll.user32
        _HDESK = u32.OpenDesktopW("Default", 0, False, 0x01FF)
        if _HDESK:
            u32.SetThreadDesktop(_HDESK)
    except Exception:
        pass

from selection_reader.extractor import (
    ensure_desktop_attachment,
    extract_selection,
    inspect_active_window,
    set_screen_reader_flag,
)

HOTKEY_ID_ALTO = 101
HOTKEY_ID_CTRLALTO = 102

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_O = ord("O")


def register_hotkeys() -> bool:
    if not IS_WINDOWS:
        return False
    ensure_desktop_attachment()
    u32 = ctypes.windll.user32
    ok1 = u32.RegisterHotKey(None, HOTKEY_ID_ALTO, MOD_ALT | MOD_NOREPEAT, VK_O)
    ok2 = u32.RegisterHotKey(None, HOTKEY_ID_CTRLALTO, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_O)
    return bool(ok1 or ok2)


def unregister_hotkeys() -> None:
    if not IS_WINDOWS:
        return
    u32 = ctypes.windll.user32
    try:
        u32.UnregisterHotKey(None, HOTKEY_ID_ALTO)
        u32.UnregisterHotKey(None, HOTKEY_ID_CTRLALTO)
    except Exception:
        pass


def main():
    print("=" * 65)
    print("  SELECTION READER — Interactive One-Shot Test")
    print("=" * 65)
    print("  1. Highlight text anywhere (Chrome, VS Code, Notepad, Word, etc.)")
    print("  2. Press [Alt+O] (or [Ctrl+Alt+O])")
    print("=" * 65)
    sys.stdout.flush()

    set_screen_reader_flag(True)
    if not register_hotkeys():
        print("[ERROR] Could not register global hotkey Alt+O. Check permissions.")
        sys.exit(1)

    print("  [*] Waiting for [Alt+O] press...")
    sys.stdout.flush()

    u32 = ctypes.windll.user32 if IS_WINDOWS else None
    msg = wintypes.MSG() if IS_WINDOWS else None

    try:
        while True:
            if IS_WINDOWS and u32 is not None and msg is not None:
                if u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    if msg.message == 0x0312:  # WM_HOTKEY
                        payload = extract_selection()
                        if payload and payload.selected_text:
                            print()
                            print("=" * 65)
                            print("  SUCCESS: HIGHLIGHTED TEXT EXTRACTED")
                            print("=" * 65)
                            print(f"  Selected Text:    {payload.selected_text!r}")
                            print(f"  App Name:         {payload.app.name}")
                            print(f"  Window Title:     {payload.app.title}")
                            print(f"  Category:         {payload.app.category.upper()}")
                            print(f"  PID:              {payload.app.pid}")
                            print(f"  Timestamp:        {payload.timestamp}")
                            print("=" * 65)
                            print()
                            print("JSON Output:")
                            print(json.dumps(payload.to_dict(), indent=2))
                            print("=" * 65)
                            sys.stdout.flush()
                            break
                        else:
                            active = inspect_active_window()
                            print(
                                f"  [!] Alt+O pressed in [{active.name}], but no text was highlighted."
                            )
                            print("      Please highlight some text and press [Alt+O] again...")
                            sys.stdout.flush()

                    u32.TranslateMessage(ctypes.byref(msg))
                    u32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nTest cancelled by user.")
    finally:
        unregister_hotkeys()
        set_screen_reader_flag(False)
        print("\nTest finished. Exiting.")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
