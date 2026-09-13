import os
import sys

_src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import pytest
from overlay_ui.models import (
    CardType,
    PopupActionEvent,
    PopupCardPayload,
    PopupHandle,
    PopupItem,
    ScreenRect,
)
from overlay_ui.overlay import (
    OverlayUIManager,
    calculate_clamped_bounds,
    dismiss_popup,
    display_popup_card,
    update_popup_content,
)


def test_calculate_clamped_bounds_normal_placement():
    # Ample screen space: should place 8px below selection
    anchor = ScreenRect(x=300, y=200, width=150, height=20)
    bounds = calculate_clamped_bounds(
        anchor, popup_width=400, popup_height=300, screen_width=1920, screen_height=1080
    )
    assert bounds.x == 300
    assert bounds.y == 200 + 20 + 8
    assert bounds.width == 400
    assert bounds.height == 300


def test_calculate_clamped_bounds_flip_above():
    # Near bottom of screen (y = 950): should flip above selection
    anchor = ScreenRect(x=300, y=950, width=150, height=20)
    bounds = calculate_clamped_bounds(
        anchor, popup_width=400, popup_height=300, screen_width=1920, screen_height=1080
    )
    assert bounds.x == 300
    # anchor.y - popup_height - 8 = 950 - 300 - 8 = 642
    assert bounds.y == 642


def test_calculate_clamped_bounds_right_edge_clamping():
    # Near right edge (x = 1800 on 1920 screen)
    anchor = ScreenRect(x=1800, y=200, width=100, height=20)
    bounds = calculate_clamped_bounds(
        anchor, popup_width=400, popup_height=300, screen_width=1920, screen_height=1080
    )
    # screen_width - popup_width - 16 = 1920 - 400 - 16 = 1504
    assert bounds.x == 1504
    assert bounds.y == 228


def test_display_and_update_popup():
    manager = OverlayUIManager()
    payload = PopupCardPayload(
        card_type=CardType.SYNONYMS,
        title="Synonyms for 'robust'",
        items=[
            PopupItem(id="1", title="resilient", badge="[1]"),
            PopupItem(id="2", title="sturdy", badge="[2]"),
        ],
    )
    anchor = ScreenRect(x=100, y=100, width=80, height=20)
    handle = manager.display_popup_card(payload, anchor)

    assert handle.is_visible is True
    assert handle.window_id in manager.active_popups
    assert handle.active_payload.title == "Synonyms for 'robust'"

    # Update content
    new_payload = PopupCardPayload(
        card_type=CardType.SYNONYMS,
        title="Updated Synonyms",
        items=[PopupItem(id="3", title="durable", badge="[1]")],
    )
    updated = manager.update_popup_content(handle.window_id, new_payload)
    assert updated is True
    assert handle.active_payload.title == "Updated Synonyms"


def test_dismiss_popup():
    manager = OverlayUIManager()
    payload = PopupCardPayload(card_type=CardType.DEFINITION, title="Definition")
    anchor = ScreenRect(x=50, y=50, width=50, height=20)
    handle = manager.display_popup_card(payload, anchor)

    assert handle.is_visible is True
    dismissed = manager.dismiss_popup(handle.window_id)
    assert dismissed is True
    assert handle.window_id not in manager.active_popups

    # Second dismiss should return False
    assert manager.dismiss_popup(handle.window_id) is False


def test_handle_user_input_keystrokes():
    manager = OverlayUIManager()
    actions = []

    def on_action(event: PopupActionEvent):
        actions.append(event)

    payload = PopupCardPayload(
        card_type=CardType.SYNONYMS,
        title="Synonyms",
        items=[
            PopupItem(id="syn_1", title="comprehensive", badge="[1]"),
            PopupItem(id="syn_2", title="thorough", badge="[2]"),
        ],
    )
    anchor = ScreenRect(x=100, y=100, width=50, height=20)
    handle = manager.display_popup_card(payload, anchor, on_action=on_action)

    # Press '1' to select first item
    ev1 = manager.handle_user_input(handle.window_id, "1")
    assert ev1 is not None
    assert ev1.action == "select_item"
    assert ev1.item_id == "syn_1"
    assert ev1.text_input == "comprehensive"
    assert len(actions) == 1

    # Press 'esc' to dismiss
    ev2 = manager.handle_user_input(handle.window_id, "esc")
    assert ev2 is not None
    assert ev2.action == "dismiss"
    assert handle.window_id not in manager.active_popups


def test_global_helpers():
    payload = PopupCardPayload(card_type=CardType.SIMILAR_PAPERS, title="Papers")
    anchor = ScreenRect(x=200, y=200, width=100, height=25)
    handle = display_popup_card(payload, anchor)

    assert handle.is_visible is True
    assert update_popup_content(handle.window_id, payload) is True
    assert dismiss_popup(handle.window_id) is True


def test_pyqt_synonym_overlay_full_flow():
    from PyQt6 import QtCore, QtGui, QtWidgets
    from overlay_ui.pyqt_synonym_overlay import PyQtSynonymOverlay, SynonymOverlayBridge

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    overlay = PyQtSynonymOverlay()
    bridge = SynonymOverlayBridge(overlay)

    # 1. Loading signal
    bridge.sig_show_loading.emit("analyze")
    assert overlay.isVisible()
    assert overlay._stack.currentIndex() == 0

    applied_words = []
    # 2. Show synonyms signal
    bridge.sig_show_synonyms.emit("analyze", ["examine", "investigate", "evaluate"], lambda w: applied_words.append(w))
    assert overlay._stack.currentIndex() == 1
    assert overlay._list_widget.count() == 3

    # 3. Arrow down and apply
    event_down = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Down, QtCore.Qt.KeyboardModifier.NoModifier)
    app.sendEvent(overlay._list_widget, event_down)
    assert overlay._list_widget.currentRow() == 1

    event_enter = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Return, QtCore.Qt.KeyboardModifier.NoModifier)
    app.sendEvent(overlay._list_widget, event_enter)
    assert applied_words == ["investigate"]
    assert not overlay.isVisible()

    # 4. Close signal
    overlay.show()
    assert overlay.isVisible()
    bridge.sig_close.emit()
    assert not overlay.isVisible()
