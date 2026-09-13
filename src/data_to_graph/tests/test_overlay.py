"""Unit and integration tests for TableGraphOverlay inside data_to_graph."""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch

from PyQt6 import QtCore, QtGui, QtWidgets

from data_to_graph.models import ChartType, ParsedTableDataset, RenderedChart
from data_to_graph.overlay import (
    TableGraphOverlay,
    TableGraphOverlayBridge,
    get_table_graph_overlay_bridge,
    show_table_graph_overlay,
)


@pytest.fixture(scope="session")
def qapp():
    """Ensures QApplication singleton exists for PyQt tests."""
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    return app


def test_overlay_build_and_init(qapp):
    overlay = TableGraphOverlay()
    assert overlay._header.text() == "// TABLE // GRAPH"
    assert overlay.windowFlags() & QtCore.Qt.WindowType.FramelessWindowHint
    assert overlay.testAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
    assert overlay._stack.count() >= 3


def test_overlay_show_table_and_render(qapp):
    overlay = TableGraphOverlay()
    md_table = """### Quarterly Revenue
| Quarter | Revenue |
| :--- | :--- |
| Q1 | 120 |
| Q2 | 150 |
| Q3 | 190 |
| Q4 | 220 |
"""
    overlay.show_table(md_table)
    assert overlay._target.text() == "Quarterly Revenue"
    assert overlay._current_chart is not None
    assert overlay._current_chart.chart_type in (ChartType.BAR_CHART, ChartType.LINE_CHART)
    assert len(overlay._compatible_types) >= 2
    assert len(overlay._type_buttons) == len(overlay._compatible_types[:9])


def test_overlay_switch_chart_type(qapp):
    overlay = TableGraphOverlay()
    md_table = """| Quarter | Revenue |
| Q1 | 120 |
| Q2 | 150 |
| Q3 | 190 |
| Q4 | 220 |
"""
    overlay.show_table(md_table)
    initial_type = overlay._current_chart.chart_type

    # Find an alternative compatible type
    alt_types = [t for t in overlay._compatible_types if t != initial_type]
    assert len(alt_types) > 0
    next_t = alt_types[0]

    signals_emitted = []
    overlay.chart_selected.connect(lambda t: signals_emitted.append(t))

    overlay.switch_chart_type(next_t)
    assert overlay._current_chart.chart_type == next_t
    assert next_t.value in signals_emitted


def test_overlay_cycle_chart_types_via_keyboard(qapp):
    overlay = TableGraphOverlay()
    md_table = """| Month | Temp |
| Jan | 32 |
| Feb | 35 |
| Mar | 45 |
"""
    overlay.show_table(md_table)
    first_type = overlay._current_chart.chart_type

    # Simulate Tab key press
    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Tab,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    overlay.keyPressEvent(event)

    second_type = overlay._current_chart.chart_type
    assert second_type != first_type or len(overlay._compatible_types) == 1


def test_overlay_numeric_shortcut_key(qapp):
    overlay = TableGraphOverlay()
    md_table = """| Month | Temp |
| Jan | 32 |
| Feb | 35 |
| Mar | 45 |
"""
    overlay.show_table(md_table)
    if len(overlay._compatible_types) >= 2:
        target_second = overlay._compatible_types[1]
        # Press '2'
        event = QtGui.QKeyEvent(
            QtCore.QEvent.Type.KeyPress,
            QtCore.Qt.Key.Key_2,
            QtCore.Qt.KeyboardModifier.NoModifier,
            "2",
        )
        overlay.keyPressEvent(event)
        assert overlay._current_chart.chart_type == target_second


def test_overlay_multi_dataset_navigation(qapp):
    overlay = TableGraphOverlay()
    multi_table = """### Sales Group A
| Item | Amount |
| Alpha | 10 |
| Beta | 20 |

### Sales Group B
| Region | Units |
| North | 100 |
| South | 200 |
"""
    overlay.show_table(multi_table)
    assert len(overlay._datasets) == 2
    assert overlay._dataset_bar.isVisible()

    # Navigate right
    event_right = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Right,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    overlay.keyPressEvent(event_right)
    assert overlay._current_dataset_idx == 1
    assert "Group B" in overlay._target.text()


def test_overlay_clipboard_copy(qapp):
    overlay = TableGraphOverlay()
    table = """| A | B |
| X | 1 |
| Y | 2 |
"""
    overlay.show_table(table)
    copied = []
    overlay.copy_requested.connect(lambda: copied.append(True))

    event_enter = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Return,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    overlay.keyPressEvent(event_enter)
    assert len(copied) == 1


def test_overlay_paste_below_table(qapp):
    overlay = TableGraphOverlay()
    table = """| ColA | ColB |
| 1 | 10 |
| 2 | 20 |
"""
    overlay.show_table(table, target_hwnd=99999)
    applied = []
    overlay.apply_requested.connect(lambda: applied.append(True))

    with patch.object(overlay, "_perform_paste_below_table") as mock_paste:
        event_enter = QtGui.QKeyEvent(
            QtCore.QEvent.Type.KeyPress,
            QtCore.Qt.Key.Key_Return,
            QtCore.Qt.KeyboardModifier.NoModifier,
        )
        overlay.keyPressEvent(event_enter)
        assert len(applied) == 1
        assert overlay.isHidden()
        mock_paste.assert_called_once_with(99999)


def test_overlay_escape_hides(qapp):
    overlay = TableGraphOverlay()
    overlay.show()
    dismissed = []
    overlay.dismissed.connect(lambda: dismissed.append(True))

    event_esc = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_Escape,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    overlay.keyPressEvent(event_esc)
    assert overlay.isHidden()
    assert len(dismissed) == 1


def test_table_graph_overlay_bridge(qapp):
    overlay = TableGraphOverlay()
    bridge = TableGraphOverlayBridge(overlay)

    # Test queued signal invocation
    bridge.sig_show_loading.emit("Test Title")
    qapp.processEvents()
    assert "Test Title" in overlay._target.text()

    bridge.sig_close.emit()
    qapp.processEvents()
    assert overlay.isHidden()


def test_overlay_paste_table_and_chart_shift_enter(qapp):
    overlay = TableGraphOverlay()
    table = """| Metric | Score |
| Accuracy | 95 |
| Precision | 92 |
"""
    overlay.show_table(table, target_hwnd=88888)
    applied = []
    overlay.apply_requested.connect(lambda: applied.append(True))

    with patch.object(overlay, "_perform_direct_paste") as mock_direct:
        event_shift_enter = QtGui.QKeyEvent(
            QtCore.QEvent.Type.KeyPress,
            QtCore.Qt.Key.Key_Return,
            QtCore.Qt.KeyboardModifier.ShiftModifier,
        )
        overlay.keyPressEvent(event_shift_enter)
        assert len(applied) == 1
        assert overlay.isHidden()
        mock_direct.assert_called_once_with(88888)


def test_overlay_toast_display(qapp):
    from data_to_graph.overlay import TableGraphToast
    toast = TableGraphToast()
    toast.show_toast("Test Title", "Test Hint", duration_ms=500)
    assert toast._msg.text() == "Test Title"
    assert toast._hint.text() == "Test Hint"
    toast.hide()

