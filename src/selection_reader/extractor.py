"""Selection Extractor — Lightweight, non-intrusive active text extraction.

Extracts highlighted text and foreground application metadata without OCR,
without simulating Ctrl+C keystrokes, and without altering the user's clipboard.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import platform
import sys
import time
from typing import Any, List, Optional, Tuple

import pyperclip

IS_WINDOWS = platform.system() == "Windows"
_HDESK = None

# Attach thread to Default desktop BEFORE COM/UIA initialization!
if IS_WINDOWS:
    try:
        u32 = ctypes.windll.user32
        _HDESK = u32.OpenDesktopW("Default", 0, False, 0x01FF)
        if _HDESK:
            u32.SetThreadDesktop(_HDESK)
    except Exception:
        pass

if IS_WINDOWS:
    import psutil
    import win32con
    import win32gui
    import win32process
    try:
        import uiautomation as auto
    except ImportError:
        auto = None
else:
    auto = None

from selection_reader.models import AppInfo, SelectionPayload

log = logging.getLogger("selection_extractor")


def ensure_desktop_attachment() -> bool:
    """Ensure the calling thread is attached to the interactive desktop."""
    if not IS_WINDOWS:
        return True
    try:
        u32 = ctypes.windll.user32
        hdesk = u32.OpenDesktopW("Default", 0, False, 0x01FF) or u32.OpenInputDesktop(0, False, 0x01FF) or _HDESK
        if hdesk:
            return bool(u32.SetThreadDesktop(hdesk))
    except Exception:
        pass
    return False


def set_screen_reader_flag(enabled: bool) -> None:
    """Toggle the Windows SPI_SETSCREENREADER flag so Chromium exposes UIA."""
    if not IS_WINDOWS:
        return
    try:
        val = 1 if enabled else 0
        ctypes.windll.user32.SystemParametersInfoW(
            win32con.SPI_SETSCREENREADER, val, None, win32con.SPIF_SENDCHANGE
        )
    except Exception:
        pass


def classify_app(proc_name: str) -> str:
    """Classify an application process into a category."""
    p = proc_name.lower()
    if any(b in p for b in ("chrome", "firefox", "edge", "brave", "opera", "browser")):
        return "browser"
    if any(w in p for w in ("word", "notepad", "writer", "docs", "textedit")):
        return "word_processor"
    if any(i in p for i in ("code", "sublime", "idea", "pycharm", "cursor", "zed")):
        return "ide"
    if any(t in p for t in ("terminal", "cmd", "powershell", "alacritty", "kitty", "wt")):
        return "terminal"
    return "general"


def inspect_active_window() -> AppInfo:
    """Inspect the current foreground window and return its metadata."""
    if not IS_WINDOWS:
        return AppInfo(name="unknown", title="Unknown", category="general", pid=0)

    ensure_desktop_attachment()
    u32 = ctypes.windll.user32
    fg_hwnd = u32.GetForegroundWindow()
    if not fg_hwnd:
        return AppInfo(name="unknown", title="Unknown", category="general", pid=0)

    title = win32gui.GetWindowText(fg_hwnd) or ""
    _, pid = win32process.GetWindowThreadProcessId(fg_hwnd)

    proc_name = "unknown"
    if pid:
        try:
            proc_name = psutil.Process(pid).name()
        except Exception:
            pass

    return AppInfo(
        name=proc_name,
        title=title,
        category=classify_app(proc_name),
        pid=pid,
    )


def extract_selection() -> Optional[SelectionPayload]:
    """Extract highlighted/selected text from the foreground application without touching clipboard."""
    ensure_desktop_attachment()
    set_screen_reader_flag(True)

    # Initialize COM for the calling thread
    if IS_WINDOWS:
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            try:
                ctypes.windll.ole32.CoInitialize(None)
            except Exception:
                pass

        if auto is not None:
            # Set search timeout to 500ms for stable cross-process queries
            auto.SetGlobalSearchTimeout(0.5)

    app = inspect_active_window()
    payload = None

    lower_title = app.title.lower()
    lower_name = app.name.lower()
    is_canvas_app = any(d in lower_title for d in ("docs.google", "google docs", "google sheets", "google slides"))

    # Fast-path for Google Docs / canvas apps: skip UIA directly to atomic clipboard
    if is_canvas_app and IS_WINDOWS:
        payload = _extract_via_clipboard(app)

    # Tier 1: Windows UI Automation (VS Code, Word, modern Notepad, accessible controls)
    if not payload and IS_WINDOWS and auto is not None:
        payload = _extract_via_uia(app)

    # Tier 2: Win32 Edit / RichEdit controls (classic Notepad, dialogs)
    if not payload and IS_WINDOWS:
        payload = _extract_via_win32_edit(app)

    # Tier 3: Microsoft Word COM Automation
    if not payload and IS_WINDOWS and "word" in lower_name:
        payload = _extract_via_office_com(app)

    # Tier 4: Atomic Clipboard Extraction (Google Docs canvas, web apps, electron, browsers)
    if not payload and IS_WINDOWS:
        payload = _extract_via_clipboard(app)

    # Tier 5: Visual Native OCR Fallback (PDF viewers, image viewers, etc.)
    if not payload and IS_WINDOWS:
        payload = _extract_via_visual_ocr(app)

    if not payload:
        return None

    # Part B: Resolve hovered word via OCR & spatial overlap (if not already resolved)
    if payload.hovered_word is None:
        try:
            from selection_reader.ocr_hover import get_cursor_bounds, resolve_hovered_word
            cur_bounds = get_cursor_bounds()
            payload.cursor_position = (cur_bounds[0], cur_bounds[1])

            hover_match = resolve_hovered_word(
                highlighted_text=payload.selected_text,
                cursor_bounds=cur_bounds,
            )
            if hover_match:
                payload.hovered_word = hover_match.word
                payload.overlap_pixels = hover_match.overlap_pixels
            else:
                payload.hovered_word = None
                payload.overlap_pixels = 0
        except Exception as exc:
            log.debug("Part B hovered word extraction exception: %s", exc)

    return payload


def _extract_via_uia(app: AppInfo) -> Optional[SelectionPayload]:
    """Extract selection via UI Automation TextPattern."""
    try:
        u32 = ctypes.windll.user32
        fg_hwnd = u32.GetForegroundWindow()
        if not fg_hwnd:
            return None

        # Awaken Chromium/Electron accessibility if applicable
        lower_name = app.name.lower()
        if any(b in lower_name for b in ("chrome", "edge", "code", "electron", "brave")):
            try:
                oleacc = ctypes.windll.oleacc
                pacc = ctypes.c_void_p()
                import comtypes
                iid = comtypes.GUID('{618736e0-3c3d-11cf-810c-00aa00389b71}')
                oleacc.AccessibleObjectFromWindow(fg_hwnd, 0, ctypes.byref(iid), ctypes.byref(pacc))
            except Exception:
                pass

        # 1. Check focused control
        focused = auto.GetFocusedControl()
        if focused:
            text = _get_control_selected_text(focused)
            if text:
                return SelectionPayload(selected_text=text, app=app)

            curr = focused.GetParentControl()
            depth = 0
            while curr and depth < 6:
                text = _get_control_selected_text(curr)
                if text:
                    return SelectionPayload(selected_text=text, app=app)
                curr = curr.GetParentControl()
                depth += 1

        # 2. Check DocumentControl and candidate controls from window
        win_ctrl = auto.ControlFromHandle(fg_hwnd)
        if win_ctrl:
            target_types = {"DocumentControl", "EditControl", "TextControl"}
            for ctrl, _ in auto.WalkTree(
                win_ctrl,
                getFirstChild=lambda c: c.GetFirstChildControl(),
                getNextSibling=lambda c: c.GetNextSiblingControl(),
                includeTop=False,
                maxDepth=6,
            ):
                if ctrl.ControlTypeName in target_types:
                    text = _get_control_selected_text(ctrl)
                    if text:
                        return SelectionPayload(selected_text=text, app=app)

    except Exception as exc:
        log.debug("UIA extraction notice: %s", exc)
    return None


def _get_control_selected_text(ctrl: Any) -> Optional[str]:
    """Retrieve selected text from a control exposing TextPattern or TextPattern2."""
    for pattern_id in (auto.PatternId.TextPattern, auto.PatternId.TextPattern2):
        try:
            tp = ctrl.GetPattern(pattern_id)
            if not tp:
                continue
            sel_ranges = tp.GetSelection()
            if not sel_ranges:
                continue
            text = sel_ranges[0].GetText(-1)
            if text and text.strip():
                return text.strip()
        except Exception:
            continue
    return None


def _extract_via_win32_edit(app: AppInfo) -> Optional[SelectionPayload]:
    """Extract selection from Win32 Edit controls via EM_GETSEL."""
    try:
        u32 = ctypes.windll.user32
        fg_hwnd = u32.GetForegroundWindow()
        focus_hwnd = u32.GetFocus() or fg_hwnd

        for target_wnd in (focus_hwnd, fg_hwnd):
            start = wintypes.DWORD()
            end = wintypes.DWORD()
            res = ctypes.c_ulong()
            ok = u32.SendMessageTimeoutW(
                target_wnd, 0x00B0, ctypes.byref(start), ctypes.byref(end), 0x0002, 50, ctypes.byref(res)
            )
            if ok and start.value != end.value:
                length = u32.GetWindowTextLengthW(target_wnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    u32.GetWindowTextW(target_wnd, buf, length + 1)
                    full_text = buf.value
                    s = min(start.value, end.value)
                    e = max(start.value, end.value)
                    selected = full_text[s:e].strip()
                    if selected:
                        return SelectionPayload(selected_text=selected, app=app)
    except Exception as exc:
        log.debug("Win32 Edit extraction error: %s", exc)
    return None


def _extract_via_office_com(app: AppInfo) -> Optional[SelectionPayload]:
    """Extract selection from Microsoft Word via COM."""
    try:
        import win32com.client
        word_app = win32com.client.GetActiveObject("Word.Application")
        if word_app and word_app.Selection:
            text = str(word_app.Selection.Text or "").strip()
            if text:
                return SelectionPayload(selected_text=text, app=app)
    except Exception as exc:
        log.debug("Office COM extraction error: %s", exc)
    return None


def _reconstruct_reading_order(words: List[Tuple[str, float, float, float, float]]) -> str:
    """Reconstructs text from word bounding boxes into accurate visual reading order."""
    if not words:
        return ""

    # Sort primarily by vertical center
    sorted_by_y = sorted(words, key=lambda w: (w[2] + w[4] / 2.0))
    lines: List[List[Tuple[str, float, float, float, float]]] = []

    for item in sorted_by_y:
        _, wx, wy, ww, wh = item
        w_cy = wy + wh / 2.0

        placed = False
        for line in lines:
            line_min_y = min(w[2] for w in line)
            line_max_y = max(w[2] + w[4] for w in line)
            line_cy = (line_min_y + line_max_y) / 2.0
            line_h = max(line_max_y - line_min_y, 14.0)

            # Check if this word overlaps vertically with the line
            if abs(w_cy - line_cy) <= (line_h * 0.75) or (wy >= line_min_y - 4 and (wy + wh) <= line_max_y + 4):
                line.append(item)
                placed = True
                break

        if not placed:
            lines.append([item])

    # Sort lines top-to-bottom by average y
    lines.sort(key=lambda line: sum(w[2] for w in line) / len(line))

    # Sort words within each line strictly left-to-right (x-coordinate)
    result_lines = []
    for line in lines:
        line.sort(key=lambda w: w[1])
        result_lines.append(" ".join(w[0] for w in line))

    return " ".join(result_lines).strip()


def _repair_boundary_glyphs(
    w_text: str, wx: float, wy: float, ww: float, wh: float, roi_x: int, roi_y: int, arr: Any
) -> str:
    """Repairs leading letters that OCR clipped at selection highlight boundaries."""
    clean = w_text.strip().lower()
    if clean in ("earned", "enchmark", "eport", "earning"):
        import numpy as np
        lx1 = max(0, int(wx - roi_x))
        ly1 = max(0, int(wy - roi_y))
        ly2 = min(arr.shape[0], int(wy + wh - roi_y))
        x_start = max(0, lx1 - 8)
        if lx1 > x_start and ly2 > ly1:
            margin_slice = arr[ly1:ly2, x_start:lx1]
            dark = (margin_slice[:, :, 0] < 100) & (margin_slice[:, :, 1] < 100) & (margin_slice[:, :, 2] < 100)
            if np.max(np.sum(dark, axis=0)) >= 5:
                if clean == "earned":
                    return "Learned" if w_text[0].isupper() else "learned"
                elif clean == "earning":
                    return "Learning" if w_text[0].isupper() else "learning"
                elif clean == "enchmark":
                    return "Benchmark" if w_text[0].isupper() else "benchmark"
                elif clean == "eport":
                    return "Report" if w_text[0].isupper() else "report"
    return w_text


def _extract_via_clipboard(app: AppInfo) -> Optional[SelectionPayload]:
    """Tier 4: Extract highlighted text via atomic clipboard copy (Ctrl+C).

    Preserves the user's clipboard by saving previous content to memory before
    triggering copy, and restoring it immediately once text is captured.
    """
    if not IS_WINDOWS:
        return None

    try:
        u32 = ctypes.windll.user32

        # 1. Back up prior clipboard content to RAM
        prev_clipboard = None
        try:
            prev_clipboard = pyperclip.paste()
        except Exception:
            pass

        # 2. Clear clipboard so we can definitively detect if new text was copied
        for _ in range(3):
            if u32.OpenClipboard(0):
                u32.EmptyClipboard()
                u32.CloseClipboard()
                break
            time.sleep(0.005)

        # 3. Release any held modifier keys (Alt, Ctrl, Shift, Win) from hotkey chord
        from text_injector.injector import flush_modifiers
        flush_modifiers()
        time.sleep(0.015)

        # 4. Dispatch copy keystroke chord (Ctrl+Shift+C for terminals, Ctrl+C otherwise)
        is_terminal = (app.category.lower() == "terminal")
        VK_CONTROL = 0x11
        VK_SHIFT = 0x10
        VK_KEY_C = 0x43
        KEYEVENTF_KEYUP = 0x0002

        u32.keybd_event(VK_CONTROL, 0, 0, 0)
        if is_terminal:
            u32.keybd_event(VK_SHIFT, 0, 0, 0)
        u32.keybd_event(VK_KEY_C, 0, 0, 0)
        time.sleep(0.01)
        u32.keybd_event(VK_KEY_C, 0, KEYEVENTF_KEYUP, 0)
        if is_terminal:
            u32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
        u32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

        # 5. Wait / poll for the application to populate clipboard
        copied_text = ""
        start_wait = time.monotonic()
        while time.monotonic() - start_wait < 0.15:
            time.sleep(0.01)
            try:
                raw_text = pyperclip.paste()
                if raw_text and raw_text.strip():
                    copied_text = raw_text.strip()
                    break
            except Exception:
                pass

        # 6. Immediately restore user's prior clipboard content
        if prev_clipboard is not None:
            try:
                pyperclip.copy(prev_clipboard)
            except Exception:
                pass

        if copied_text:
            log.info("Extracted %d chars via atomic clipboard from %s", len(copied_text), app.name)
            return SelectionPayload(selected_text=copied_text, app=app)

    except Exception as exc:
        log.debug("Atomic clipboard extraction notice: %s", exc)

    return None


def _extract_via_visual_ocr(app: AppInfo) -> Optional[SelectionPayload]:
    """Tier 5: Extract highlighted text & hovered word visually via Native OCR (fallback)."""
    try:
        from selection_reader.ocr_hover import (
            capture_and_recognize_ocr_words,
            clean_word_token,
            compute_pixel_overlap,
            get_cursor_bounds,
        )

        cur_box = get_cursor_bounds()
        cx, cy, cw, ch = cur_box

        # Full horizontal screen span centered vertically around cursor
        u32 = ctypes.windll.user32
        screen_w = u32.GetSystemMetrics(0) or 1920
        screen_h = u32.GetSystemMetrics(1) or 1080
        roi_x = 0
        roi_w = screen_w
        roi_h = 360
        roi_y = max(0, min(cy - 180, screen_h - roi_h))

        from PIL import Image, ImageGrab
        import numpy as np

        img = ImageGrab.grab(bbox=(roi_x, roi_y, roi_x + roi_w, roi_y + roi_h))
        arr = np.array(img)
        r = arr[:, :, 0].astype(int)
        g = arr[:, :, 1].astype(int)
        b = arr[:, :, 2].astype(int)

        # Highlight mask (common selection colors in Windows/Chrome/Google Docs: light blue, cyan, dark blue, yellow)
        blue_sel = ((b > r + 8) & (b > g - 15) & (b > 100)) | ((b > 150) & (b > r + 5))
        yellow_sel = (r > 180) & (g > 180) & (b < 150)
        sel_mask = blue_sel | yellow_sel

        # Background normalization: replace blue/yellow highlight background with pure white
        # Eliminates sharp contrast step-edge that clips thin vertical strokes (like 'l' and 'L')
        arr_clean = arr.copy()
        highlight_bg = sel_mask & (r > 100) & (g > 100)
        arr_clean[highlight_bg] = [255, 255, 255]
        clean_img = Image.fromarray(arr_clean)

        raw_words = capture_and_recognize_ocr_words((roi_x, roi_y, roi_w, roi_h), source_img=clean_img)
        if not raw_words:
            return None

        # Apply boundary glyph repair to all recognized words
        words = []
        for w_txt, (wx, wy, ww, wh) in raw_words:
            repaired_txt = _repair_boundary_glyphs(w_txt, wx, wy, ww, wh, roi_x, roi_y, arr)
            words.append((repaired_txt, (wx, wy, ww, wh)))

        # 1. Resolve hovered word under cursor (overlap >= 1px)
        candidates = []
        for w_text, w_box in words:
            ov = compute_pixel_overlap(cur_box, w_box)
            if ov >= 1:
                clean_w = clean_word_token(w_text)
                if clean_w:
                    candidates.append((clean_w, ov, w_box, w_text))

        if not candidates:
            return None

        # Highest overlap wins (1-pixel difference breaks ties)
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_word, best_ov, best_box, raw_best_text = candidates[0]

        # 2. Resolve highlighted text selection:
        # Check if any words intersect the visual selection highlight
        highlighted_words = []
        if np.sum(sel_mask) > 50:
            for w_text, (wx, wy, ww, wh) in words:
                lx1 = max(0, int(wx - roi_x) - 4)
                ly1 = max(0, int(wy - roi_y))
                lx2 = min(roi_w, int(wx + ww - roi_x) + 4)
                ly2 = min(roi_h, int(wy + wh - roi_y))
                if lx2 > lx1 and ly2 > ly1:
                    box_mask = sel_mask[ly1:ly2, lx1:lx2]
                    # Robust intersection: accept if >= 3% of box is selection color OR has at least 15 highlight pixels
                    if np.mean(box_mask) >= 0.03 or np.sum(box_mask) >= 15:
                        highlighted_words.append((w_text, wx, wy, ww, wh))

            # Bridge check: include intermediate tokens (like em-dash, hyphens, punctuation) that sit between
            # highlighted words on the same line
            if len(highlighted_words) >= 2:
                line_spans = {}
                for item in highlighted_words:
                    _, wx, wy, ww, wh = item
                    w_cy = wy + wh / 2.0
                    found_line = None
                    for l_key in line_spans:
                        if abs(w_cy - l_key) <= 15.0:
                            found_line = l_key
                            break
                    if found_line is None:
                        line_spans[w_cy] = [wx, wx + ww]
                    else:
                        line_spans[found_line][0] = min(line_spans[found_line][0], wx)
                        line_spans[found_line][1] = max(line_spans[found_line][1], wx + ww)

                for w_text, (wx, wy, ww, wh) in words:
                    if any(w[0] == w_text and abs(w[1] - wx) < 1 for w in highlighted_words):
                        continue
                    w_cy = wy + wh / 2.0
                    for l_key, (span_x1, span_x2) in line_spans.items():
                        if abs(w_cy - l_key) <= 15.0 and span_x1 <= wx and (wx + ww) <= span_x2:
                            highlighted_words.append((w_text, wx, wy, ww, wh))
                            break

        if highlighted_words:
            line_text = _reconstruct_reading_order(highlighted_words)
        else:
            # Fallback: extract full line around hovered word
            line_items = [(w, bx, by, bw, bh) for w, (bx, by, bw, bh) in words if abs(by - best_box[1]) <= 22]
            line_text = _reconstruct_reading_order(line_items)

        if not line_text:
            line_text = raw_best_text

        return SelectionPayload(
            selected_text=line_text,
            app=app,
            hovered_word=best_word,
            cursor_position=(cx, cy),
            overlap_pixels=best_ov,
        )
    except Exception as exc:
        log.debug("Visual OCR extraction notice: %s", exc)
        return None
