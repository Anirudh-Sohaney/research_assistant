"""OCR-based cursor hover word extraction and spatial overlap resolution."""

from __future__ import annotations

import asyncio
import io
import logging
import math
import os
import re
import sys
from typing import List, Optional, Tuple

from selection_reader.models import HoveredWordMatch

log = logging.getLogger("selection_reader.ocr_hover")

IS_WINDOWS = sys.platform == "win32"


def get_cursor_bounds(pointer_width: int = 16, pointer_height: int = 16) -> Tuple[int, int, int, int]:
    """Returns the current mouse cursor screen bounding box (x, y, width, height)."""
    if IS_WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes
            pt = wintypes.POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                return pt.x, pt.y, pointer_width, pointer_height
        except Exception as exc:
            log.debug("GetCursorPos error: %s", exc)
    return 0, 0, pointer_width, pointer_height


def compute_pixel_overlap(
    box1: Tuple[float, float, float, float],
    box2: Tuple[float, float, float, float],
) -> int:
    """Computes exact intersection area in pixels between two bounding boxes (x, y, w, h)."""
    x1, y1, w1, h1 = box1
    x2, y2, w2, h2 = box2

    x_left = max(x1, x2)
    y_top = max(y1, y2)
    x_right = min(x1 + w1, x2 + w2)
    y_bottom = min(y1 + h1, y2 + h2)

    if x_right > x_left and y_bottom > y_top:
        return int(math.ceil((x_right - x_left) * (y_bottom - y_top)))
    return 0


def clean_word_token(text: str) -> str:
    """Strips punctuation and whitespace to isolate root word token."""
    return re.sub(r"^[^\w]+|[^\w]+$", "", text.strip().lower())


def _is_one_edit_away(s1: str, s2: str) -> bool:
    """Checks if two strings have a Levenshtein distance of at most 1."""
    if abs(len(s1) - len(s2)) > 1:
        return False
    if s1 == s2:
        return True
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    diff = 0
    i, j = 0, 0
    while i < len(s1) and j < len(s2):
        if s1[i] != s2[j]:
            diff += 1
            if diff > 1:
                return False
            if len(s1) == len(s2):
                i += 1
                j += 1
            else:
                j += 1
        else:
            i += 1
            j += 1
    return True


def find_matching_selection_token(word: str, selected_text: str) -> Optional[str]:
    """Matches an OCR word token against true tokens in selected_text.

    Returns the clean canonical token from selected_text if matched, else None.
    Handles:
    - Exact match (case-insensitive)
    - Clipped boundary glyphs (e.g. 'earned' matching 'learned', len difference <= 2)
    - Minor single-character OCR misrecognition (Levenshtein distance <= 1 for tokens len >= 4)
    """
    if not word or not selected_text:
        return None

    clean_w = clean_word_token(word)
    if not clean_w:
        return None

    raw_tokens = [clean_word_token(t) for t in re.findall(r"\b[\w'-]+\b", selected_text)]
    tokens = [t for t in raw_tokens if t]

    # 1. Exact match
    if clean_w in tokens:
        return clean_w

    # 2. Substring / clipped boundary match (e.g. 'earned' matching 'learned')
    for tok in tokens:
        if len(tok) >= 4 and len(clean_w) >= 3:
            if clean_w in tok and (len(tok) - len(clean_w)) <= 2:
                return tok
            if tok in clean_w and (len(clean_w) - len(tok)) <= 2:
                return tok

    # 3. Single-edit distance for tokens of length >= 4
    if len(clean_w) >= 4:
        for tok in tokens:
            if len(tok) >= 4 and abs(len(tok) - len(clean_w)) <= 1:
                if _is_one_edit_away(clean_w, tok):
                    return tok

    return None


def is_word_in_selection(word: str, selected_text: str) -> bool:
    """Strict check verifying whether a word belongs to the highlighted selection."""
    return find_matching_selection_token(word, selected_text) is not None


async def _run_winrt_ocr_on_bytes(png_data: bytes) -> List[Tuple[str, Tuple[float, float, float, float]]]:
    """Runs Windows Native OCR on image bytes and returns words with bounding boxes."""
    try:
        import winrt.windows.graphics.imaging as imaging
        import winrt.windows.media.ocr as ocr
        import winrt.windows.storage.streams as streams

        stream = streams.InMemoryRandomAccessStream()
        writer = streams.DataWriter(stream)
        writer.write_bytes(png_data)
        await writer.store_async()
        await writer.flush_async()
        writer.detach_stream()

        stream.seek(0)
        decoder = await imaging.BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()

        engine = ocr.OcrEngine.try_create_from_user_profile_languages()
        if not engine:
            return []

        ocr_res = await engine.recognize_async(bitmap)
        words: List[Tuple[str, Tuple[float, float, float, float]]] = []
        for line in ocr_res.lines:
            for w in line.words:
                rc = w.bounding_rect
                words.append((w.text, (rc.x, rc.y, rc.width, rc.height)))
        return words
    except Exception as exc:
        log.debug("WinRT OCR execution error: %s", exc)
        return []


def capture_and_recognize_ocr_words(
    roi_box: Tuple[int, int, int, int],
    source_img: Optional[Any] = None,
) -> List[Tuple[str, Tuple[float, float, float, float]]]:
    """Captures screen ROI (or uses provided preprocessed image) and executes native OCR."""
    try:
        x1, y1, w, h = roi_box
        x2, y2 = x1 + w, y1 + h

        if source_img is not None:
            img = source_img
        else:
            from PIL import ImageGrab
            raw_img = ImageGrab.grab(bbox=(x1, y1, x2, y2))
            try:
                import numpy as np
                from PIL import Image
                arr = np.array(raw_img)
                r = arr[:, :, 0].astype(int)
                g = arr[:, :, 1].astype(int)
                b = arr[:, :, 2].astype(int)
                blue_sel = ((b > r + 8) & (b > g - 15) & (b > 100)) | ((b > 150) & (b > r + 5))
                yellow_sel = (r > 180) & (g > 180) & (b < 150)
                sel_mask = blue_sel | yellow_sel
                if np.sum(sel_mask) > 30:
                    arr_clean = arr.copy()
                    highlight_bg = sel_mask & (r > 80) & (g > 80)
                    arr_clean[highlight_bg] = [255, 255, 255]
                    img = Image.fromarray(arr_clean)
                else:
                    img = raw_img
            except Exception:
                img = raw_img

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        # Run async WinRT OCR safely
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(1) as pool:
                local_words = pool.submit(asyncio.run, _run_winrt_ocr_on_bytes(png_bytes)).result()
        else:
            local_words = asyncio.run(_run_winrt_ocr_on_bytes(png_bytes))

        # Convert local image coordinates to absolute screen coordinates
        screen_words: List[Tuple[str, Tuple[float, float, float, float]]] = []
        for word_text, (lx, ly, lw, lh) in local_words:
            screen_words.append((word_text, (x1 + lx, y1 + ly, lw, lh)))
        return screen_words

    except Exception as exc:
        log.debug("Screen OCR capture error: %s", exc)
        return []


def resolve_hovered_word(
    highlighted_text: str,
    cursor_bounds: Optional[Tuple[int, int, int, int]] = None,
    ocr_words: Optional[List[Tuple[str, Tuple[float, float, float, float]]]] = None,
) -> Optional[HoveredWordMatch]:
    """Identifies the word hovered over by the cursor with >= 1px overlap, gated by selection."""
    if not highlighted_text or not highlighted_text.strip():
        return None

    cur_box = cursor_bounds or get_cursor_bounds(pointer_width=16, pointer_height=16)

    # If OCR words are not supplied, capture a screen patch around cursor
    if ocr_words is None:
        cx, cy, cw, ch = cur_box
        # ROI: 300px horizontal, 160px vertical centered around cursor
        roi_x = max(0, cx - 150)
        roi_y = max(0, cy - 80)
        roi_w = 300
        roi_h = 160
        ocr_words = capture_and_recognize_ocr_words((roi_x, roi_y, roi_w, roi_h))

    if not ocr_words:
        return None

    cx, cy, cw, ch = cur_box
    cur_center_x = cx + (cw / 2.0)
    cur_center_y = cy + (ch / 2.0)

    candidate_matches: List[HoveredWordMatch] = []

    for word_text, word_box in ocr_words:
        overlap = compute_pixel_overlap(cur_box, word_box)
        if overlap >= 1:
            matched_tok = find_matching_selection_token(word_text, highlighted_text)
            # CRITICAL RULE: Only candidate words that belong to the highlighted text are eligible!
            if matched_tok:
                candidate_matches.append(
                    HoveredWordMatch(
                        word=matched_tok,
                        bounding_box=word_box,
                        overlap_pixels=overlap,
                        is_part_of_selection=True,
                    )
                )

    if not candidate_matches:
        # If cursor is not hovering over the highlighted text, return None!
        return None

    # Sort candidates by:
    # 1. Overlap pixels descending (highest overlap wins; even 1 pixel makes the difference)
    # 2. Minimum distance from cursor center to word box center (tie-breaker)
    def sort_key(cand: HoveredWordMatch) -> Tuple[int, float]:
        wx, wy, ww, wh = cand.bounding_box
        word_center_x = wx + (ww / 2.0)
        word_center_y = wy + (wh / 2.0)
        dist_sq = (word_center_x - cur_center_x) ** 2 + (word_center_y - cur_center_y) ** 2
        return (cand.overlap_pixels, -dist_sq)

    candidate_matches.sort(key=sort_key, reverse=True)
    return candidate_matches[0]
