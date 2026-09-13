"""Integration and unit tests for Master Application Orchestrator."""

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch
import pytest

_src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from app.models import (
    ActionResult,
    ActionTrigger,
    AppExitReport,
    AppRuntimeContext,
    ShutdownReason,
)
from app.orchestrator import (
    AppOrchestrator,
    dispatch_action_pipeline,
    init_application,
    shutdown_application,
)
from selection_reader.models import AppInfo, SelectionPayload


def make_payload(text: str) -> SelectionPayload:
    return SelectionPayload(
        selected_text=text,
        app=AppInfo(name="WINWORD.EXE", title="Draft Paper - Word", category="word_processor", pid=1234),
    )


def test_app_lifecycle():
    with patch("hotkey_manager.manager.keyboard.GlobalHotKeys"):
        orchestrator = AppOrchestrator()
        context = orchestrator.init_application()

        assert isinstance(context, AppRuntimeContext)
        assert context.is_healthy is True
        assert context.session_id.startswith("session_")
        assert context.daemon_pid == os.getpid()
        assert context.active_subsystems["hotkey_manager"] is True
        assert context.active_subsystems["overlay_ui"] is True
        assert context.active_subsystems["api_gateway"] is True

        # Clean shutdown
        report = orchestrator.shutdown_application(reason=ShutdownReason.USER_QUIT)
        assert isinstance(report, AppExitReport)
        assert report.success is True
        assert "hotkey_manager" in report.subsystems_stopped
        assert "daemon_service" in report.subsystems_stopped
        assert orchestrator.is_running is False


def test_empty_selection_handling():
    orchestrator = AppOrchestrator()
    payload = make_payload("")
    res = orchestrator.dispatch_action_pipeline(ActionTrigger.FIND_SYNONYMS, payload)

    assert res.success is False
    assert res.tokens_used == 0
    assert "No text was selected" in res.output_summary


def test_tier1_find_synonyms_pipeline():
    orchestrator = AppOrchestrator()
    payload = make_payload("empirical")
    res = orchestrator.dispatch_action_pipeline(ActionTrigger.FIND_SYNONYMS, payload)

    assert res.success is True
    assert res.tier == "TIER_1_LOCAL"
    assert res.tokens_used == 0
    assert res.ui_handle_id is not None
    assert "contextual synonyms" in res.output_summary


def test_tier1_find_definitions_pipeline():
    orchestrator = AppOrchestrator()
    payload = make_payload("demonstrate")
    res = orchestrator.dispatch_action_pipeline(ActionTrigger.FIND_DEFINITIONS, payload)

    assert res.success is True
    assert res.tier == "TIER_1_LOCAL"
    assert res.tokens_used == 0
    assert res.ui_handle_id is not None
    assert "definitions" in res.output_summary


def test_tier1_generate_graph_pipeline():
    orchestrator = AppOrchestrator()
    tabular_data = "Model, Accuracy\nBERT, 85.2\nRoBERTa, 89.1\nDeBERTa, 91.4"
    payload = make_payload(tabular_data)
    res = orchestrator.dispatch_action_pipeline(ActionTrigger.GENERATE_GRAPH, payload)

    assert res.success is True
    assert res.tier == "TIER_1_LOCAL"
    assert res.tokens_used == 0
    assert res.ui_handle_id is not None


def test_tier2_reword_text_pipeline():
    orchestrator = AppOrchestrator()
    text = "This proposed strategy produces very good experimental outcomes."
    payload = make_payload(text)

    with patch("text_injector.injector.pyperclip.copy"), patch("text_injector.injector.pyperclip.paste", return_value=text):
        res = orchestrator.dispatch_action_pipeline(ActionTrigger.REWORD_TEXT, payload)

        assert res.success is True
        assert res.tier == "TIER_2_HYBRID"
        assert res.tokens_used >= 0
        assert res.injected is True


def test_tier2_discover_papers_pipeline():
    orchestrator = AppOrchestrator()
    claim = "Deep neural language models achieve state-of-the-art results on NLP tasks."
    payload = make_payload(claim)
    res = orchestrator.dispatch_action_pipeline(ActionTrigger.DISCOVER_PAPERS, payload)

    assert res.success is True
    assert res.tier == "TIER_2_HYBRID"
    assert res.ui_handle_id is not None
    assert "academic papers" in res.output_summary


def test_tier2_retrieve_evidence_pipeline():
    orchestrator = AppOrchestrator()
    claim = "BERT improves contextual sentence understanding across language tasks."
    payload = make_payload(claim)
    res = orchestrator.dispatch_action_pipeline(ActionTrigger.RETRIEVE_EVIDENCE, payload)

    assert res.success is True
    assert res.tier == "TIER_2_HYBRID"
    assert res.ui_handle_id is not None
    assert "ratio" in res.output_summary.lower()


def test_tier2_summarize_source_pipeline():
    orchestrator = AppOrchestrator()
    code = "import numpy as np\ndef calc(arr):\n    return np.mean(arr)\n"
    payload = make_payload(code)
    res = orchestrator.dispatch_action_pipeline(ActionTrigger.SUMMARIZE_SOURCE, payload)

    assert res.success is True
    assert res.tier == "TIER_2_HYBRID"
    assert res.ui_handle_id is not None
    assert "structure" in res.output_summary.lower()


def test_global_helpers():
    with patch("hotkey_manager.manager.keyboard.GlobalHotKeys"):
        ctx = init_application()
        assert ctx.is_healthy is True

        payload = make_payload("methodology")
        result = dispatch_action_pipeline(ActionTrigger.FIND_SYNONYMS, payload)
        assert result.success is True

        exit_rep = shutdown_application()
        assert exit_rep.success is True


def test_apply_chosen_synonym_preserves_trailing_space():
    orchestrator = AppOrchestrator()
    with patch("app.orchestrator.replace_hovered_word_with_text") as mock_replace:
        res = orchestrator.apply_chosen_synonym(
            chosen_word="discovered",
            target_word="Learned",
            original_text="Learned Inverse-Kinematics Benchmark",
            cursor_pos=(500, 500),
            target_hwnd=1234,
            is_hovered=True,
        )
        assert res == "Discovered "
        assert res.endswith(" ")
        mock_replace.assert_called_once_with("Discovered ", cursor_pos=(500, 500), target_hwnd=1234)


def test_apply_chosen_synonym_no_trailing_space_at_end():
    orchestrator = AppOrchestrator()
    with patch("app.orchestrator.replace_hovered_word_with_text") as mock_replace:
        res = orchestrator.apply_chosen_synonym(
            chosen_word="acquired",
            target_word="learned",
            original_text="The concept was learned.",
            cursor_pos=(500, 500),
            target_hwnd=1234,
            is_hovered=True,
        )
        assert res == "acquired"
        assert not res.endswith(" ")
        mock_replace.assert_called_once_with("acquired", cursor_pos=(500, 500), target_hwnd=1234)


def test_apply_chosen_synonym_casing():
    orchestrator = AppOrchestrator()
    with patch("app.orchestrator.replace_hovered_word_with_text"):
        # Uppercase
        res_upper = orchestrator.apply_chosen_synonym(
            chosen_word="goal",
            target_word="OBJECTIVE",
            original_text="PRIMARY OBJECTIVE HERE",
            cursor_pos=(100, 100),
            is_hovered=True,
        )
        assert res_upper.startswith("GOAL")

        # Capitalized
        res_cap = orchestrator.apply_chosen_synonym(
            chosen_word="demonstrate",
            target_word="Illustrate",
            original_text="Illustrate the chart",
            cursor_pos=(100, 100),
            is_hovered=True,
        )
        assert res_cap.startswith("Demonstrate")

        # Lowercase
        res_lower = orchestrator.apply_chosen_synonym(
            chosen_word="empirical",
            target_word="experimental",
            original_text="experimental proof",
            cursor_pos=(100, 100),
            is_hovered=True,
        )
        assert res_lower.startswith("empirical")


def test_pyqt_overlay_trigger_with_bridge():
    orchestrator = AppOrchestrator()
    payload = SelectionPayload(
        selected_text="The concept was learned.",
        app=AppInfo(name="chrome.exe", title="Google Docs", category="browser", pid=1234),
        hovered_word="learned",
        overlap_pixels=100,
        cursor_position=(500, 500),
    )

    mock_bridge = MagicMock()
    with patch("app.orchestrator.get_synonym_overlay_bridge", return_value=mock_bridge):
        res = orchestrator.dispatch_action_pipeline(ActionTrigger.FIND_SYNONYMS, payload)
        assert res.success is True
        assert res.ui_handle_id == "synonym_overlay"
        mock_bridge.sig_show_loading.emit.assert_called_once_with("learned")
        mock_bridge.sig_show_synonyms.emit.assert_called_once()


def test_pyqt_overlay_ui_navigation_and_cancel():
    from PyQt6 import QtCore, QtGui, QtWidgets
    from overlay_ui.pyqt_synonym_overlay import PyQtSynonymOverlay

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    overlay = PyQtSynonymOverlay()
    chosen_results = []

    # 1. Loading state
    overlay.show_loading("test_word")
    assert overlay.isVisible()
    assert overlay._stack.currentIndex() == 0

    # 2. Populated list state
    overlay.show_synonyms("test_word", ["option1", "option2", "option3"], on_apply=lambda w: chosen_results.append(w))
    assert overlay.isVisible()
    assert overlay._stack.currentIndex() == 1
    assert overlay._list_widget.count() == 3
    assert overlay._list_widget.currentRow() == 0

    # 3. Down arrow navigation
    event_down = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Down, QtCore.Qt.KeyboardModifier.NoModifier)
    app.sendEvent(overlay._list_widget, event_down)
    assert overlay._list_widget.currentRow() == 1

    # 4. Enter applies chosen synonym
    event_enter = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Return, QtCore.Qt.KeyboardModifier.NoModifier)
    app.sendEvent(overlay._list_widget, event_enter)
    assert chosen_results == ["option2"]
    assert not overlay.isVisible()

    # 5. Esc closes popup
    overlay.show_synonyms("test_word", ["option1", "option2"])
    assert overlay.isVisible()
    event_esc = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Escape, QtCore.Qt.KeyboardModifier.NoModifier)
    app.sendEvent(overlay._list_widget, event_esc)
    assert not overlay.isVisible()


