"""Unit and integration tests for selection_reader subsystem.

Tests:
1. Data models: AppInfo, HoveredWordMatch, and SelectionPayload serialization and defaults.
2. Application classification heuristics.
3. Window inspection (mocked and live Windows API fallback).
4. Selection extraction logic and tier fallback (zero-clipboard).
5. Part B: Spatial pixel overlap calculation (including 1-pixel overlap).
6. Part B: Strict selection membership gating (only words inside selection are eligible).
7. Part B: Multi-word collision resolution (highest overlap pixel wins).
8. Part B: Fallback when cursor is not hovering over highlighted text.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from selection_reader.extractor import (
    classify_app,
    ensure_desktop_attachment,
    extract_selection,
    inspect_active_window,
    set_screen_reader_flag,
)
from selection_reader.models import AppInfo, HoveredWordMatch, SelectionPayload
from selection_reader.ocr_hover import (
    clean_word_token,
    compute_pixel_overlap,
    is_word_in_selection,
    resolve_hovered_word,
)


class TestModels:
    def test_app_info_to_dict(self):
        info = AppInfo(name="chrome.exe", title="Test Page", category="browser", pid=1234)
        d = info.to_dict()
        assert d == {
            "name": "chrome.exe",
            "title": "Test Page",
            "category": "browser",
            "pid": 1234,
        }

    def test_selection_payload_to_dict(self):
        info = AppInfo(name="Code.exe", title="models.py", category="ide", pid=5678)
        payload = SelectionPayload(
            selected_text="empirical analysis",
            app=info,
            hovered_word="empirical",
            cursor_position=(100, 200),
            overlap_pixels=24,
        )
        d = payload.to_dict()
        assert d["selected_text"] == "empirical analysis"
        assert d["hovered_word"] == "empirical"
        assert d["cursor_position"] == (100, 200)
        assert d["overlap_pixels"] == 24
        assert d["app"]["name"] == "Code.exe"
        assert d["app"]["category"] == "ide"
        assert "timestamp" in d


class TestAppClassification:
    def test_browsers(self):
        assert classify_app("chrome.exe") == "browser"
        assert classify_app("firefox.exe") == "browser"
        assert classify_app("msedge.exe") == "browser"
        assert classify_app("brave.exe") == "browser"

    def test_word_processors(self):
        assert classify_app("WINWORD.EXE") == "word_processor"
        assert classify_app("notepad.exe") == "word_processor"
        assert classify_app("writer.exe") == "word_processor"

    def test_ides(self):
        assert classify_app("Code.exe") == "ide"
        assert classify_app("pycharm64.exe") == "ide"
        assert classify_app("sublime_text.exe") == "ide"

    def test_terminals(self):
        assert classify_app("WindowsTerminal.exe") == "terminal"
        assert classify_app("cmd.exe") == "terminal"
        assert classify_app("powershell.exe") == "terminal"
        assert classify_app("alacritty.exe") == "terminal"

    def test_general(self):
        assert classify_app("calc.exe") == "general"
        assert classify_app("explorer.exe") == "general"


class TestWindowInspection:
    def test_inspect_active_window_structure(self):
        info = inspect_active_window()
        assert isinstance(info, AppInfo)
        assert hasattr(info, "name")
        assert hasattr(info, "title")
        assert hasattr(info, "category")
        assert hasattr(info, "pid")

    def test_ensure_desktop_attachment(self):
        assert isinstance(ensure_desktop_attachment(), bool)

    def test_set_screen_reader_flag(self):
        set_screen_reader_flag(True)
        set_screen_reader_flag(False)


class TestSpatialPixelOverlap:
    def test_disjoint_boxes_have_zero_overlap(self):
        box1 = (0, 0, 10, 10)
        box2 = (20, 20, 10, 10)
        assert compute_pixel_overlap(box1, box2) == 0

    def test_exact_one_pixel_overlap(self):
        # 1-pixel overlap at corner: x=9..10, y=9..10
        box1 = (0, 0, 10, 10)
        box2 = (9, 9, 10, 10)
        assert compute_pixel_overlap(box1, box2) == 1

    def test_multi_pixel_overlap(self):
        # Overlap: [5..15] in x (10px) and [5..10] in y (5px) = 50px
        box1 = (0, 0, 15, 10)
        box2 = (5, 5, 20, 20)
        assert compute_pixel_overlap(box1, box2) == 50


class TestSelectionGating:
    def test_clean_word_token(self):
        assert clean_word_token("  (empirical), ") == "empirical"
        assert clean_word_token("'demonstrate'?") == "demonstrate"
        assert clean_word_token("state-of-the-art.") == "state-of-the-art"

    def test_word_in_selection_matching(self):
        selection = "The empirical results demonstrate high accuracy."
        assert is_word_in_selection("empirical", selection) is True
        assert is_word_in_selection("results,", selection) is True
        assert is_word_in_selection("demonstrate", selection) is True
        assert is_word_in_selection("hypothetical", selection) is False
        assert is_word_in_selection("", selection) is False


class TestHoverWordResolution:
    def test_hover_on_word_inside_selection(self):
        highlighted = "The empirical results demonstrate coherence."
        cursor = (50, 20, 16, 16)
        ocr_words = [
            ("The", (10, 20, 25, 15)),
            ("empirical", (45, 20, 60, 15)),
            ("results", (115, 20, 50, 15)),
        ]
        match = resolve_hovered_word(highlighted, cursor_bounds=cursor, ocr_words=ocr_words)
        assert match is not None
        assert match.word == "empirical"
        assert match.is_part_of_selection is True
        assert match.overlap_pixels > 0

    def test_cursor_not_on_highlighted_text_returns_none(self):
        # Highlighted text is "empirical results", but cursor is hovering on "unrelated"
        highlighted = "empirical results"
        cursor = (300, 20, 16, 16)
        ocr_words = [
            ("empirical", (10, 20, 60, 15)),
            ("results", (80, 20, 50, 15)),
            ("unrelated", (295, 20, 70, 15)),  # Cursor overlaps here!
        ]
        match = resolve_hovered_word(highlighted, cursor_bounds=cursor, ocr_words=ocr_words)
        # CRITICAL: Since 'unrelated' is NOT in highlighted text, MUST return None!
        assert match is None

    def test_two_conflicting_words_choose_word_with_more_overlap(self):
        # Cursor spans between 'wordA' and 'wordB'
        # Cursor: [100, 100, 20, 20] (x from 100 to 120, y from 100 to 120)
        # WordA: [90, 100, 22, 20] -> overlap with cursor in x is [100..112] = 12px; y is [100..120] = 20px -> 240px
        # WordB: [109, 100, 30, 20] -> overlap with cursor in x is [109..120] = 11px; y is [100..120] = 20px -> 220px
        # 1 pixel difference in x (12px vs 11px) -> WordA wins!
        highlighted = "wordA wordB"
        cursor = (100, 100, 20, 20)
        ocr_words = [
            ("wordA", (90, 100, 22, 20)),
            ("wordB", (109, 100, 30, 20)),
        ]
        match = resolve_hovered_word(highlighted, cursor_bounds=cursor, ocr_words=ocr_words)
        assert match is not None
        assert match.word == "worda"
        assert match.overlap_pixels == 240

    def test_single_pixel_overlap_qualifies(self):
        highlighted = "target"
        # Cursor: (10, 10, 5, 5) -> [10..15, 10..15]
        # Word: (14, 14, 20, 20) -> [14..34, 14..34]
        # Overlap in x: [14..15] = 1px; Overlap in y: [14..15] = 1px -> 1px total
        cursor = (10, 10, 5, 5)
        ocr_words = [("target", (14, 14, 20, 20))]
        match = resolve_hovered_word(highlighted, cursor_bounds=cursor, ocr_words=ocr_words)
        assert match is not None
        assert match.word == "target"
        assert match.overlap_pixels == 1

    def test_no_overlap_returns_none(self):
        highlighted = "isolated"
        cursor = (500, 500, 16, 16)
        ocr_words = [("isolated", (10, 10, 50, 15))]
        match = resolve_hovered_word(highlighted, cursor_bounds=cursor, ocr_words=ocr_words)
        assert match is None

    def test_hover_on_clipped_word_resolves_to_full_word(self):
        # Even if OCR clipped 'l' from 'learned' producing 'earned', it resolves to 'learned'
        highlighted = "The model learned new representations."
        cursor = (50, 20, 16, 16)
        ocr_words = [
            ("The", (10, 20, 25, 15)),
            ("earned", (45, 20, 55, 15)),
        ]
        match = resolve_hovered_word(highlighted, cursor_bounds=cursor, ocr_words=ocr_words)
        assert match is not None
        assert match.word == "learned"
        assert match.is_part_of_selection is True
        assert match.overlap_pixels > 0


class TestSelectionExtractionTiers:
    @patch("selection_reader.extractor._extract_via_uia")
    @patch("selection_reader.ocr_hover.resolve_hovered_word")
    def test_extract_selection_with_hovered_word(self, mock_resolve, mock_uia):
        info = AppInfo(name="WINWORD.EXE", title="Draft.docx", category="word_processor", pid=100)
        mock_uia.return_value = SelectionPayload(selected_text="empirical findings", app=info)
        mock_resolve.return_value = HoveredWordMatch(
            word="empirical", bounding_box=(10, 10, 40, 15), overlap_pixels=32, is_part_of_selection=True
        )

        payload = extract_selection()
        assert payload is not None
        assert payload.selected_text == "empirical findings"
        assert payload.hovered_word == "empirical"
        assert payload.overlap_pixels == 32

    @patch("selection_reader.extractor._extract_via_uia")
    @patch("selection_reader.ocr_hover.resolve_hovered_word")
    def test_extract_selection_when_cursor_not_on_text(self, mock_resolve, mock_uia):
        info = AppInfo(name="WINWORD.EXE", title="Draft.docx", category="word_processor", pid=100)
        mock_uia.return_value = SelectionPayload(selected_text="empirical findings", app=info)
        # Cursor is in margin, so resolve_hovered_word returns None
        mock_resolve.return_value = None

        payload = extract_selection()
        assert payload is not None
        assert payload.selected_text == "empirical findings"
        assert payload.hovered_word is None
        assert payload.overlap_pixels == 0

    @patch("selection_reader.extractor._extract_via_uia", return_value=None)
    @patch("selection_reader.extractor._extract_via_win32_edit")
    def test_extract_selection_fallback_to_win32(self, mock_win32, mock_uia):
        info = AppInfo(name="notepad.exe", title="Untitled", category="word_processor", pid=101)
        mock_win32.return_value = SelectionPayload(selected_text="win32 text", app=info)

        payload = extract_selection()
        assert payload is not None
        assert payload.selected_text == "win32 text"

    @patch("selection_reader.extractor._extract_via_uia", return_value=None)
    @patch("selection_reader.extractor._extract_via_win32_edit", return_value=None)
    @patch("selection_reader.extractor._extract_via_office_com")
    def test_extract_selection_fallback_to_word_com(self, mock_com, mock_win32, mock_uia):
        info = AppInfo(name="WINWORD.EXE", title="Word", category="word_processor", pid=102)
        mock_com.return_value = SelectionPayload(selected_text="office text", app=info)

        with patch("selection_reader.extractor.inspect_active_window", return_value=info):
            payload = extract_selection()
            assert payload is not None
            assert payload.selected_text == "office text"

    @patch("selection_reader.extractor._extract_via_uia", return_value=None)
    @patch("selection_reader.extractor._extract_via_win32_edit", return_value=None)
    @patch("selection_reader.extractor._extract_via_office_com", return_value=None)
    @patch("selection_reader.extractor._extract_via_clipboard")
    def test_extract_selection_atomic_clipboard(self, mock_clip, mock_com, mock_win32, mock_uia):
        info = AppInfo(name="chrome.exe", title="Google Docs", category="browser", pid=103)
        mock_clip.return_value = SelectionPayload(
            selected_text="The model learned new representations.",
            app=info,
        )

        with patch("selection_reader.extractor.inspect_active_window", return_value=info):
            payload = extract_selection()
            assert payload is not None
            assert payload.selected_text == "The model learned new representations."

    @patch("selection_reader.extractor._extract_via_uia", return_value=None)
    @patch("selection_reader.extractor._extract_via_win32_edit", return_value=None)
    @patch("selection_reader.extractor._extract_via_office_com", return_value=None)
    @patch("selection_reader.extractor._extract_via_clipboard", return_value=None)
    @patch("selection_reader.extractor._extract_via_visual_ocr")
    def test_extract_selection_fallback_to_visual_ocr(self, mock_ocr, mock_clip, mock_com, mock_win32, mock_uia):
        info = AppInfo(name="chrome.exe", title="Google Docs", category="browser", pid=103)
        mock_ocr.return_value = SelectionPayload(
            selected_text="canvas sentence with keywords",
            app=info,
            hovered_word="keywords",
            cursor_position=(400, 300),
            overlap_pixels=25,
        )

        with patch("selection_reader.extractor.inspect_active_window", return_value=info):
            payload = extract_selection()
            assert payload is not None
            assert payload.selected_text == "canvas sentence with keywords"
            assert payload.hovered_word == "keywords"
            assert payload.overlap_pixels == 25
