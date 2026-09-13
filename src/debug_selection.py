"""Diagnostic script to inspect what selection_reader sees on hotkey trigger."""

import ctypes
import sys
import time
import uiautomation as auto

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from hotkey_manager.manager import HotkeyManager
from selection_reader.extractor import inspect_active_window, set_screen_reader_flag, ensure_desktop_attachment


def diagnose():
    print("=" * 60, flush=True)
    print("SELECTION DIAGNOSTIC TOOL", flush=True)
    print("=" * 60, flush=True)

    ensure_desktop_attachment()
    set_screen_reader_flag(True)

    manager = HotkeyManager()

    def on_hotkey(ev):
        print("\n" + "=" * 60, flush=True)
        print(f"[EVENT] Hotkey fired: {ev.action} ({ev.chord})", flush=True)
        print("=" * 60, flush=True)

        app = inspect_active_window()
        print(f"Foreground App : {app.name} (PID: {app.pid})", flush=True)
        print(f"Window Title   : {app.title}", flush=True)
        print(f"Category       : {app.category}", flush=True)

        u32 = ctypes.windll.user32
        fg_hwnd = u32.GetForegroundWindow()
        print(f"Foreground HWND: {hex(fg_hwnd)}", flush=True)

        # Set search timeout to 0.5s for stability
        auto.SetGlobalSearchTimeout(0.5)

        try:
            focused = auto.GetFocusedControl()
            print(f"Focused Control: {focused}", flush=True)
            if focused:
                print(f"  Type : {focused.ControlTypeName}", flush=True)
                print(f"  Class: {focused.ClassName}", flush=True)
                print(f"  Name : {focused.Name}", flush=True)
                print(f"  Rect : {focused.BoundingRectangle}", flush=True)

                for pid_name in ("TextPattern", "TextPattern2", "ValuePattern", "TextEditPattern"):
                    pid_val = getattr(auto.PatternId, pid_name, None)
                    if pid_val is not None:
                        try:
                            pat = focused.GetPattern(pid_val)
                            print(f"  Pattern {pid_name}: {pat is not None}", flush=True)
                            if pat and hasattr(pat, "GetSelection"):
                                sel = pat.GetSelection()
                                print(f"    Selection length: {len(sel) if sel else 0}", flush=True)
                                if sel:
                                    print(f"    Selected Text: '{sel[0].GetText(-1)}'", flush=True)
                        except Exception as e:
                            print(f"    Error checking {pid_name}: {e}", flush=True)

                # Check parents of focused
                p = focused.GetParentControl()
                depth = 1
                while p and depth <= 4:
                    print(f"  Parent [{depth}]: {p.ControlTypeName} ({p.ClassName}) '{p.Name}'", flush=True)
                    try:
                        pat = p.GetPattern(auto.PatternId.TextPattern)
                        if pat:
                            sel = pat.GetSelection()
                            if sel:
                                print(f"    Parent Selected Text: '{sel[0].GetText(-1)}'", flush=True)
                    except Exception:
                        pass
                    p = p.GetParentControl()
                    depth += 1
        except Exception as exc:
            print(f"Error getting focused control: {exc}", flush=True)

        # Check win_ctrl
        try:
            win_ctrl = auto.ControlFromHandle(fg_hwnd)
            print(f"\nWindow Control: {win_ctrl}", flush=True)
            if win_ctrl:
                print("Scanning window control children for text...", flush=True)
                for c, _ in auto.WalkTree(
                    win_ctrl,
                    getFirstChild=lambda x: x.GetFirstChildControl(),
                    getNextSibling=lambda x: x.GetNextSiblingControl(),
                    includeTop=False,
                    maxDepth=6,
                ):
                    try:
                        pat = c.GetPattern(auto.PatternId.TextPattern)
                        if pat:
                            sel = pat.GetSelection()
                            if sel:
                                text = sel[0].GetText(-1)
                                if text and text.strip():
                                    print(f"  FOUND in {c.ControlTypeName} ({c.ClassName}): '{text.strip()}'", flush=True)
                    except Exception:
                        pass
        except Exception as exc:
            print(f"Error scanning window control: {exc}", flush=True)

        print("-" * 60, flush=True)

    manager.listen_hotkey_stream(callback=on_hotkey)
    print("Diagnostic listener active on Alt+O. Please highlight text and press Alt+O.", flush=True)
    try:
        time.sleep(60.0)
    except KeyboardInterrupt:
        pass
    manager.stop_listening()
    print("Diagnostic finished.", flush=True)


if __name__ == "__main__":
    diagnose()
