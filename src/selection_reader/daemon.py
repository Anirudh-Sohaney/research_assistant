#!/usr/bin/env python3
"""Selection Reader — Background Text Extraction Daemon.

Monitors global key combinations (default: Alt+O, Ctrl+Alt+O) and extracts
currently highlighted/selected text and active window metadata from any
foreground desktop application.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import logging
import os
import platform
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

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
from selection_reader.models import AppInfo, SelectionPayload

log = logging.getLogger("selection_daemon")

LOCAL_CAPTURE_FILE = CURRENT_DIR / "selection_capture.json"
LOCAL_EVENTS_FILE = CURRENT_DIR / "selection_events.jsonl"
PID_FILE = Path(os.environ.get("TEMP", "/tmp")) / "selection_daemon.pid"

_LATEST_RESULT: Optional[Dict[str, Any]] = None
_HISTORY: List[Dict[str, Any]] = []


class DaemonHTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/latest"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            data = _LATEST_RESULT or {"status": "waiting_for_selection"}
            self.wfile.write(json.dumps(data, indent=2).encode())
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            status = {
                "status": "healthy",
                "pid": os.getpid(),
                "time": datetime.now().isoformat(),
                "total_captures": len(_HISTORY),
            }
            self.wfile.write(json.dumps(status).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


class GlobalHotkeyManager:
    MOD_MAP = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004, "win": 0x0008}
    MOD_NOREPEAT = 0x4000

    def __init__(self, chords: List[str]):
        self.chords = chords
        self.hotkeys: List[dict] = []
        self._parse()

    def _parse(self):
        hid = 1
        for spec in self.chords:
            parts = [p.strip().lower() for p in spec.replace("+", " ").split() if p.strip()]
            if not parts:
                continue
            mod = self.MOD_NOREPEAT
            for p in parts[:-1]:
                if p in self.MOD_MAP:
                    mod |= self.MOD_MAP[p]
            key = parts[-1].upper()
            vk = ord(key) if len(key) == 1 and "A" <= key <= "Z" else None
            if vk:
                name = "+".join(p.capitalize() for p in parts)
                self.hotkeys.append({"id": hid, "name": name, "mod": mod, "vk": vk})
                hid += 1

    def register_all(self) -> List[str]:
        if not IS_WINDOWS:
            return []
        ensure_desktop_attachment()
        u32 = ctypes.windll.user32
        registered = []
        for hk in self.hotkeys:
            if u32.RegisterHotKey(None, hk["id"], hk["mod"], hk["vk"]):
                registered.append(hk["name"])
        return registered

    def unregister_all(self):
        if not IS_WINDOWS:
            return
        u32 = ctypes.windll.user32
        for hk in self.hotkeys:
            try:
                u32.UnregisterHotKey(None, hk["id"])
            except Exception:
                pass


class SelectionDaemon:
    def __init__(self, chords: List[str], port: int = 8901):
        self.chords = chords
        self.port = port
        self.running = False
        self.last_trigger = 0.0
        self.hotkeys = GlobalHotkeyManager(chords)
        self.http_server: Optional[HTTPServer] = None

    def start(self):
        self.running = True
        try:
            PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
        except Exception:
            pass

        set_screen_reader_flag(True)
        bound = self.hotkeys.register_all()

        print("=" * 65)
        print("  SELECTION READER — Text Extraction Daemon")
        print("=" * 65)
        print("  Primary Hotkey: [Alt+O]")
        for b in bound:
            print(f"    -> Bound: [{b}]")
        print(f"  REST API:       http://127.0.0.1:{self.port}/latest")
        print(f"  Health Check:   http://127.0.0.1:{self.port}/health")
        print("=" * 65)
        print("  READY: Highlight text anywhere and press Alt+O.")
        print("=" * 65)
        sys.stdout.flush()

        self._start_http()

        try:
            self._loop()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def _loop(self):
        u32 = ctypes.windll.user32 if IS_WINDOWS else None
        msg = wintypes.MSG() if IS_WINDOWS else None

        while self.running:
            if IS_WINDOWS and u32 and msg:
                if u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0x0001):
                    if msg.message == 0x0312:  # WM_HOTKEY
                        self._handle_trigger()
                    elif msg.message == 0x0012:  # WM_QUIT
                        break
                    u32.TranslateMessage(ctypes.byref(msg))
                    u32.DispatchMessageW(ctypes.byref(msg))
                else:
                    time.sleep(0.02)
            else:
                time.sleep(0.1)

    def _handle_trigger(self):
        now = time.monotonic()
        if (now - self.last_trigger) < 0.3:
            return
        self.last_trigger = now

        payload = extract_selection()
        if not payload or not payload.selected_text:
            active = inspect_active_window()
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] Triggered in [{active.name}], but no text was highlighted.")
            sys.stdout.flush()
            return

        global _LATEST_RESULT
        res_dict = payload.to_dict()
        _LATEST_RESULT = res_dict
        _HISTORY.append(res_dict)

        try:
            LOCAL_CAPTURE_FILE.write_text(json.dumps(res_dict, indent=2), encoding="utf-8")
            with open(LOCAL_EVENTS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(res_dict) + "\n")
        except Exception:
            pass

        ts = payload.timestamp
        print()
        print("=" * 65)
        print(f"  [{ts}] HIGHLIGHTED TEXT EXTRACTED")
        print("=" * 65)
        print(f"  Selected Text:    {payload.selected_text!r}")
        print(f"  App Name:         {payload.app.name}")
        print(f"  Window Title:     {payload.app.title}")
        print(f"  Category:         {payload.app.category.upper()}")
        print(f"  PID:              {payload.app.pid}")
        print("=" * 65)
        print()
        sys.stdout.flush()

    def _start_http(self):
        try:
            self.http_server = HTTPServer(("127.0.0.1", self.port), DaemonHTTPHandler)
            threading.Thread(target=self.http_server.serve_forever, daemon=True).start()
        except Exception as exc:
            log.warning("Could not start HTTP server on %d: %s", self.port, exc)

    def stop(self):
        self.running = False
        set_screen_reader_flag(False)
        self.hotkeys.unregister_all()
        if self.http_server:
            try:
                self.http_server.shutdown()
            except Exception:
                pass
        try:
            if PID_FILE.exists():
                PID_FILE.unlink()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Selection Reader Daemon")
    parser.add_argument("--hotkey", default="alt+o,ctrl+alt+o", help="Key chords")
    parser.add_argument("--port", type=int, default=8901, help="REST API port")
    args = parser.parse_args()

    chords = [c.strip() for c in args.hotkey.split(",") if c.strip()]
    daemon = SelectionDaemon(chords, port=args.port)
    daemon.start()


if __name__ == "__main__":
    main()
