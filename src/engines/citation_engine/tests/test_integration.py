"""Tests for system-wide platform integration (Google Docs, Word, hotkeys, and overlay)."""

import pytest

from app.models import ActionTrigger
from app.orchestrator import dispatch_action_pipeline
from engines.citation_engine.models import Author, CitationDate, CitationStyle, ReferenceMetadata, SourceType
from engines.citation_engine.overlay import CitationOverlayBridge, get_citation_overlay_bridge
from hotkey_manager.manager import DEFAULT_KEY_BINDINGS, HotkeyManager
from overlay_ui.models import CardType
from selection_reader.models import AppInfo, SelectionPayload


def test_hotkey_bindings_contain_citation():
    manager = HotkeyManager()
    assert "citation" in manager.bindings
    assert "citation_popup" in manager.bindings
    assert manager.bindings["citation"] == "<ctrl>+<shift>+c"
    assert manager.bindings["citation_popup"] == "<alt>+c"


def test_card_type_contains_citation():
    assert CardType.CITATION.value == "CITATION"


def test_action_trigger_contains_citation():
    assert ActionTrigger.CITE_SOURCE.value == "CITE_SOURCE"


def test_dispatch_action_pipeline_cite_source():
    # Test selecting a DOI string and triggering CITE_SOURCE
    payload = SelectionPayload(
        selected_text="10.5555/3295222.3295349",
        app=AppInfo(name="chrome.exe", title="Google Docs - Document", category="BROWSER", pid=123),
        hovered_word=None,
        cursor_position=(100, 200),
        overlap_pixels=10,
    )

    # Pre-seed cache to ensure test runs offline / deterministically
    from engines.citation_engine.service import CitationService
    service = CitationService()
    service.cache.set("10.5555/3295222.3295349", ReferenceMetadata(
        title="Attention Is All You Need",
        authors=[Author(family="Vaswani", given="Ashish")],
        date=CitationDate(year=2017, has_date=True),
        doi="10.5555/3295222.3295349",
        source_type=SourceType.ACADEMIC_PAPER,
    ))

    result = dispatch_action_pipeline(ActionTrigger.CITE_SOURCE, payload)

    assert result.success
    assert result.action == ActionTrigger.CITE_SOURCE
    assert "Attention Is All You Need" in result.output_summary
