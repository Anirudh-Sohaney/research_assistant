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


def test_auto_replace_synonym_preserves_trailing_space():
    orchestrator = AppOrchestrator()
    payload = SelectionPayload(
        selected_text="Learned Inverse-Kinematics Benchmark",
        app=AppInfo(name="chrome.exe", title="Google Docs", category="browser", pid=1234),
        hovered_word="Learned",
        overlap_pixels=256,
        cursor_position=(500, 500),
    )

    with patch("app.orchestrator.replace_hovered_word_with_text") as mock_replace:
        res = orchestrator.dispatch_action_pipeline(ActionTrigger.FIND_SYNONYMS, payload)
        assert res.success is True
        assert res.ui_handle_id == "auto_replaced"
        assert mock_replace.called
        typed_text = mock_replace.call_args[0][0]
        assert typed_text.endswith(" ")


def test_auto_replace_synonym_no_trailing_space_at_end():
    orchestrator = AppOrchestrator()
    payload = SelectionPayload(
        selected_text="The concept was learned.",
        app=AppInfo(name="chrome.exe", title="Google Docs", category="browser", pid=1234),
        hovered_word="learned",
        overlap_pixels=100,
        cursor_position=(500, 500),
    )

    with patch("app.orchestrator.replace_hovered_word_with_text") as mock_replace:
        res = orchestrator.dispatch_action_pipeline(ActionTrigger.FIND_SYNONYMS, payload)
        assert res.success is True
        assert res.ui_handle_id == "auto_replaced"
        assert mock_replace.called
        typed_text = mock_replace.call_args[0][0]
        assert not typed_text.endswith(" ")


def test_synonym_cycling_on_stationary_cursor():
    import time
    orchestrator = AppOrchestrator()
    payload = SelectionPayload(
        selected_text="We observed substantial progress.",
        app=AppInfo(name="chrome.exe", title="Google Docs", category="browser", pid=1234),
        hovered_word="observed",
        overlap_pixels=200,
        cursor_position=(600, 400),
    )

    with patch("app.orchestrator.replace_hovered_word_with_text") as mock_replace, \
         patch("app.orchestrator.backspace_and_type") as mock_backspace:

        # 1. Initial Alt+O: auto-replaces hovered word and initializes cycle state
        res1 = orchestrator.dispatch_action_pipeline(ActionTrigger.FIND_SYNONYMS, payload)
        assert res1.success is True
        assert res1.ui_handle_id == "auto_replaced"
        assert mock_replace.called
        assert orchestrator._synonym_cycle_state is not None
        assert len(orchestrator._synonym_cycle_state.candidates) >= 8
        first_word = orchestrator._synonym_cycle_state.candidates[0]
        assert orchestrator._synonym_cycle_state.current_index == 0

        # 2. Subsequent Alt+O at same cursor (within 5px jitter tolerance)
        same_cursor_payload = SelectionPayload(
            selected_text="We observed substantial progress.",
            app=AppInfo(name="chrome.exe", title="Google Docs", category="browser", pid=1234),
            hovered_word="observed",
            overlap_pixels=200,
            cursor_position=(602, 401),
        )
        res2 = orchestrator.dispatch_action_pipeline(ActionTrigger.FIND_SYNONYMS, same_cursor_payload)
        assert res2.success is True
        assert res2.ui_handle_id == "synonym_cycled"
        assert orchestrator._synonym_cycle_state.current_index == 1
        assert mock_backspace.called

        # Verify backspace count matches length of first replacement
        last_typed_len = len(orchestrator._synonym_cycle_state.candidates[0]) + 1  # trailing space
        mock_backspace.assert_called_with(
            last_typed_len,
            orchestrator._synonym_cycle_state.candidates[1] + " "
        )

        # 3. Third Alt+O: cycles to index 2
        res3 = orchestrator.dispatch_action_pipeline(ActionTrigger.FIND_SYNONYMS, same_cursor_payload)
        assert res3.success is True
        assert res3.ui_handle_id == "synonym_cycled"
        assert orchestrator._synonym_cycle_state.current_index == 2


def test_synonym_cycling_aborts_when_cursor_moves():
    orchestrator = AppOrchestrator()
    payload = SelectionPayload(
        selected_text="We observed substantial progress.",
        app=AppInfo(name="chrome.exe", title="Google Docs", category="browser", pid=1234),
        hovered_word="observed",
        overlap_pixels=200,
        cursor_position=(600, 400),
    )

    with patch("app.orchestrator.replace_hovered_word_with_text") as mock_replace, \
         patch("app.orchestrator.backspace_and_type") as mock_backspace:

        # 1. Initial Alt+O
        res1 = orchestrator.dispatch_action_pipeline(ActionTrigger.FIND_SYNONYMS, payload)
        assert res1.success is True
        assert res1.ui_handle_id == "auto_replaced"

        # 2. Cursor moves significantly (e.g. 150 pixels away)
        moved_payload = SelectionPayload(
            selected_text="We observed substantial progress.",
            app=AppInfo(name="chrome.exe", title="Google Docs", category="browser", pid=1234),
            hovered_word="observed",
            overlap_pixels=200,
            cursor_position=(750, 400),
        )
        assert orchestrator.can_cycle_synonym(moved_payload.cursor_position) is False

        # Dispatch should NOT cycle; it should re-run initial auto-replace pipeline
        res2 = orchestrator.dispatch_action_pipeline(ActionTrigger.FIND_SYNONYMS, moved_payload)
        assert res2.success is True
        assert res2.ui_handle_id == "auto_replaced"
        # mock_backspace should not have been called because it did not cycle
        assert not mock_backspace.called


def test_synonym_cycle_wraparound():
    import time
    from app.orchestrator import SynonymCycleState
    orchestrator = AppOrchestrator()
    candidates = ["examined", "investigated", "evaluated"]
    orchestrator._synonym_cycle_state = SynonymCycleState(
        cursor_pos=(100, 100),
        target_word="observed",
        candidates=candidates,
        current_index=2,  # At the end of the candidate list
        last_typed_text="evaluated ",
        has_trailing_space=True,
        casing="lower",
        timestamp=time.monotonic(),
    )

    with patch("app.orchestrator.backspace_and_type") as mock_backspace:
        res = orchestrator.cycle_next_synonym()
        assert res.success is True
        # Should wrap back around to index 0
        assert orchestrator._synonym_cycle_state.current_index == 0
        assert orchestrator._synonym_cycle_state.last_typed_text == "examined "
        mock_backspace.assert_called_once_with(len("evaluated "), "examined ")


