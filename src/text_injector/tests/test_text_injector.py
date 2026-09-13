"""Unit tests for text_injector subsystem."""

import os
import sys
from unittest.mock import patch, MagicMock

import pyperclip
import pytest

_src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from text_injector.models import InjectionResult, InjectionTier, WindowMetadata
from text_injector.injector import (
    TextInjector,
    flush_modifiers,
    inject_text_replacement,
    inject_rich_content,
    revert_last_injection,
)


class TestTextInjector:
    def test_flush_modifiers_runs_safely(self):
        # Should not raise any exception
        flush_modifiers()

    @patch("text_injector.injector._send_paste_chord")
    def test_clipboard_preservation_guarantee(self, mock_paste):
        injector = TextInjector()
        initial_clipboard = "MY_ORIGINAL_SECRET_CLIPBOARD_DATA"
        pyperclip.copy(initial_clipboard)

        w_ctx = WindowMetadata(name="chrome.exe", title="Docs", category="browser", pid=100)
        res = injector.inject_text_replacement("New Replacement Text", w_ctx)

        assert res.success is True
        assert res.strategy == InjectionTier.CLIPBOARD_PASTE
        # Verify clipboard was restored to initial value
        restored = pyperclip.paste()
        assert restored == initial_clipboard

    @patch("text_injector.injector.TextInjector._tier1_win32_edit", return_value=True)
    def test_tier1_direct_priority(self, mock_tier1):
        injector = TextInjector()
        res = injector.inject_text_replacement("Direct Text")
        assert res.success is True
        assert res.strategy == InjectionTier.ACCESSIBILITY_DIRECT

    @patch("text_injector.injector.TextInjector._tier1_win32_edit", return_value=False)
    @patch("text_injector.injector.TextInjector._tier2_clipboard_paste", return_value=False)
    @patch("text_injector.injector.TextInjector._tier3_synthetic_typing", return_value=True)
    def test_tier3_synthetic_fallback(self, mock_t3, mock_t2, mock_t1):
        injector = TextInjector()
        res = injector.inject_text_replacement("Short text")
        assert res.success is True
        assert res.strategy == InjectionTier.SYNTHETIC_KEYSTROKES

    @patch("text_injector.injector.TextInjector._tier2_clipboard_paste", return_value=True)
    def test_undo_stack_reversion(self, mock_paste):
        injector = TextInjector()
        w_ctx = WindowMetadata(name="Code.exe", category="ide", pid=500)

        # Inject with original text tracked
        res = injector.inject_text_replacement("Replacement", w_ctx, original_text="Original Before Edit")
        assert res.success is True
        assert len(injector._undo_stack) == 1

        # Revert
        success = injector.revert_last_injection()
        assert success is True
        assert len(injector._undo_stack) == 0

    @patch("text_injector.injector.TextInjector.inject_text_replacement")
    def test_inject_rich_content_markdown_fallback(self, mock_inject):
        mock_inject.return_value = InjectionResult(
            success=True, strategy=InjectionTier.CLIPBOARD_PASTE, latency_ms=10.0
        )
        injector = TextInjector()
        w_ctx = WindowMetadata(name="Code.exe", category="ide", pid=500)

        res = injector.inject_rich_content(
            image_png_bytes=b"\x89PNGFakeImageBytes",
            alt_text="![Figure 1: Loss](chart.png)",
            window_context=w_ctx,
        )
        assert res.success is True
        mock_inject.assert_called_once_with("![Figure 1: Loss](chart.png)", w_ctx)

    def test_hover_double_click_and_type_helpers(self):
        from text_injector.injector import (
            double_click_at_cursor,
            type_text_high_speed,
            replace_hovered_word_with_text,
            backspace_and_type,
        )
        # In test mode, these helpers should run safely and return True
        double_click_at_cursor()
        res_type = type_text_high_speed("test_word")
        assert res_type is True
        res_replace = replace_hovered_word_with_text("replacement")
        assert res_replace is True
        res_bs = backspace_and_type(5, "synonym")
        assert res_bs is True
