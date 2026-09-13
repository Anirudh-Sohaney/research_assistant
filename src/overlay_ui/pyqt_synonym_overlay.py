"""PyQt6 Sci-Fi Black & White Synonym Overlay Window.

Displays a minimalist, modern, black-and-white sci-fi overlay on the right edge
of the screen (centered vertically) when Alt+O is pressed. Includes a loading
scanner while synonyms are generated, and a keyboard-navigable list (Up/Down/Enter/Esc)
to select and apply the replacement word.
"""

from __future__ import annotations

import logging
import math
import sys
import time
from typing import Callable, List, Optional, Tuple

from PyQt6 import QtCore, QtGui, QtWidgets

log = logging.getLogger("overlay_ui.pyqt")

OVERLAY_WIDTH = 280
OVERLAY_HEIGHT = 440
RIGHT_MARGIN = 16


class SciFiScanLine(QtWidgets.QWidget):
    """Minimalist, black-and-white sci-fi scanner bar."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setFixedHeight(12)
        self._pos = 0.0
        self._direction = 1.0

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(25)

    def _step(self):
        self._pos += 0.035 * self._direction
        if self._pos >= 1.0:
            self._pos = 1.0
            self._direction = -1.0
        elif self._pos <= 0.0:
            self._pos = 0.0
            self._direction = 1.0
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()

        # Background track
        painter.fillRect(0, 4, w, 4, QtGui.QColor(25, 25, 25))

        # Scanning beam
        beam_w = max(40, int(w * 0.35))
        center_x = int(self._pos * (w - beam_w))
        grad = QtGui.QLinearGradient(center_x, 0, center_x + beam_w, 0)
        grad.setColorAt(0.0, QtGui.QColor(0, 0, 0, 0))
        grad.setColorAt(0.5, QtGui.QColor(255, 255, 255, 255))
        grad.setColorAt(1.0, QtGui.QColor(0, 0, 0, 0))

        painter.fillRect(center_x, 4, beam_w, 4, grad)
        painter.end()


class SciFiDictionaryRouteWidget(QtWidgets.QWidget):
    """Animated route showing the external dictionary candidate lookup."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setMinimumHeight(92)
        self._frame = 0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._timer.start(55)

    def _advance(self):
        self._frame = (self._frame + 1) % 48
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        width = self.width()
        y = 38
        nodes = [(22, "REQ"), (width // 2, "DICT"), (width - 22, "POOL")]
        painter.setPen(QtGui.QPen(QtGui.QColor("#444444"), 1))
        painter.drawLine(nodes[0][0], y, nodes[1][0], y)
        painter.drawLine(nodes[1][0], y, nodes[2][0], y)
        segment = (self._frame // 24) % 2
        progress = (self._frame % 24) / 23.0
        x1, x2 = ((nodes[0][0], nodes[1][0]), (nodes[1][0], nodes[2][0]))[segment]
        packet_x = x1 + (x2 - x1) * progress
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor("#FFFFFF"))
        painter.drawEllipse(QtCore.QPointF(packet_x, y), 4.0, 4.0)
        for x, label in nodes:
            painter.setBrush(QtGui.QColor("#0A0A0A"))
            painter.setPen(QtGui.QPen(QtGui.QColor("#BBBBBB"), 1))
            painter.drawEllipse(QtCore.QPointF(x, y), 9.0, 9.0)
            painter.setPen(QtGui.QColor("#DDDDDD"))
            painter.drawText(QtCore.QRectF(x - 22, y + 18, 44, 16), QtCore.Qt.AlignmentFlag.AlignCenter, label)
        painter.setPen(QtGui.QColor("#666666"))
        painter.drawText(0, 12, width, 16, QtCore.Qt.AlignmentFlag.AlignCenter, "EXTERNAL DICTIONARY ROUTE")
        painter.end()


class SciFiFilteringWidget(QtWidgets.QWidget):
    """Animated semantic-fit filter shown while Ling evaluates candidates."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setMinimumHeight(92)
        self._frame = 0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._timer.start(70)

    def _advance(self):
        self._frame = (self._frame + 1) % 36
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        width = self.width()
        painter.setPen(QtGui.QColor("#666666"))
        painter.drawText(0, 12, width, 16, QtCore.Qt.AlignmentFlag.AlignCenter, "SEMANTIC FILTER")
        lane_y = [42, 57, 72]
        lane_width = max(80, width - 42)
        sweep_x = 18 + (self._frame / 35.0) * lane_width
        for index, y in enumerate(lane_y):
            painter.setPen(QtGui.QPen(QtGui.QColor("#3A3A3A"), 2))
            painter.drawLine(18, y, 18 + lane_width, y)
            dot_x = 18 + ((self._frame * (index + 2) * 3) % int(lane_width))
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor("#AAAAAA" if index != 1 else "#FFFFFF"))
            painter.drawEllipse(QtCore.QPointF(dot_x, y), 3.0, 3.0)
        painter.setPen(QtGui.QPen(QtGui.QColor("#FFFFFF"), 1))
        painter.drawLine(QtCore.QPointF(sweep_x, 30), QtCore.QPointF(sweep_x, 82))
        painter.setPen(QtGui.QColor("#555555"))
        painter.drawText(0, 84, width, 14, QtCore.Qt.AlignmentFlag.AlignCenter, "CONTEXT FIT / TENSE / REGISTER")
        painter.end()


class SciFiLoadingWidget(QtWidgets.QWidget):
    """Pulsing, high-contrast black & white sci-fi loading view."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 28, 16, 28)
        layout.setSpacing(14)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        # Pulse dots
        self._dots_label = QtWidgets.QLabel("●  ○  ○")
        self._dots_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._dots_label.setStyleSheet("color: #FFFFFF; font-size: 14px; font-weight: bold; background: transparent;")
        layout.addWidget(self._dots_label)

        # Stage animation: external dictionary route, then semantic filtering.
        self._stage_stack = QtWidgets.QStackedWidget()
        self._dictionary_route = SciFiDictionaryRouteWidget()
        self._filtering_view = SciFiFilteringWidget()
        self._stage_stack.addWidget(self._dictionary_route)
        self._stage_stack.addWidget(self._filtering_view)
        layout.addWidget(self._stage_stack)

        # Retain the crisp scanner below the route/filter visualization.
        self._scanner = SciFiScanLine()
        layout.addWidget(self._scanner)

        # Status text
        self._status_label = QtWidgets.QLabel("ANALYZING CONTEXT")
        self._status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet(
            "color: #EEEEEE; font-size: 11px; font-family: 'Consolas', monospace; "
            "font-weight: bold; letter-spacing: 2px; background: transparent;"
        )
        layout.addWidget(self._status_label)

        # Subtext
        self._sub_label = QtWidgets.QLabel("QUERYING EXTERNAL DICTIONARY")
        self._sub_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._sub_label.setStyleSheet("color: #666666; font-size: 9px; font-family: 'Consolas', monospace; background: transparent;")
        layout.addWidget(self._sub_label)

        self._frame = 0
        self._pulse_timer = QtCore.QTimer(self)
        self._pulse_timer.timeout.connect(self._animate_pulse)
        self._pulse_timer.start(350)

    def _animate_pulse(self):
        self._frame = (self._frame + 1) % 3
        dots = ["○  ○  ○", "○  ○  ○", "○  ○  ○"]
        if self._frame == 0:
            self._dots_label.setText("●  ○  ○")
        elif self._frame == 1:
            self._dots_label.setText("○  ●  ○")
        else:
            self._dots_label.setText("○  ○  ●")


    def show_dictionary_stage(self):
        self._stage_stack.setCurrentWidget(self._dictionary_route)
        self._status_label.setText("HARVESTING CANDIDATES")
        self._sub_label.setText("QUERYING EXTERNAL DICTIONARY")

    def show_filtering_stage(self):
        self._stage_stack.setCurrentWidget(self._filtering_view)
        self._status_label.setText("FILTERING FOR FIT")
        self._sub_label.setText("CONTEXT + TENSE + REGISTER")


class SciFiSynonymListWidget(QtWidgets.QListWidget):
    """Custom sci-fi keyboard-navigable list widget in black and white."""

    item_selected = QtCore.pyqtSignal(str)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.setStyleSheet(
            """
            QListWidget {
                background-color: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item {
                background-color: transparent;
                color: #CCCCCC;
                padding: 6px 10px;
                border-radius: 6px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                margin-bottom: 2px;
            }
            QListWidget::item:hover {
                background-color: #1A1A1A;
                color: #FFFFFF;
            }
            QListWidget::item:selected {
                background-color: #FFFFFF;
                color: #000000;
                font-weight: bold;
            }
            """
        )
        self.itemClicked.connect(self._on_item_clicked)

    def _on_item_clicked(self, item: QtWidgets.QListWidgetItem):
        word = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if word:
            self.item_selected.emit(word)

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        key = event.key()
        if key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            chosen = self.get_current_synonym()
            if chosen:
                self.item_selected.emit(chosen)
            event.accept()
            return
        elif key == QtCore.Qt.Key.Key_Escape:
            self.window().hide()
            event.accept()
            return
        super().keyPressEvent(event)

    def populate(self, synonyms: List[str]):
        self.clear()
        for i, word in enumerate(synonyms, 1):
            idx_str = f"{i:02d}"
            item = QtWidgets.QListWidgetItem(f"[{idx_str}]  {word}")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, word)
            self.addItem(item)
        if self.count() > 0:
            self.setCurrentRow(0)

    def select_next(self):
        total = self.count()
        if total == 0:
            return
        row = (self.currentRow() + 1) % total
        self.setCurrentRow(row)

    def select_previous(self):
        total = self.count()
        if total == 0:
            return
        row = (self.currentRow() - 1 + total) % total
        self.setCurrentRow(row)

    def get_current_synonym(self) -> Optional[str]:
        item = self.currentItem()
        if item:
            return item.data(QtCore.Qt.ItemDataRole.UserRole)
        return None


class PyQtSynonymOverlay(QtWidgets.QWidget):
    """Sci-Fi black and white overlay positioned at the right edge of the screen."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.on_apply_callback: Optional[Callable[[str], None]] = None
        self._last_explicit_hide_ts: float = 0.0
        self._keep_alive_timer: Optional[QtCore.QTimer] = None
        self._allow_auto_hide: bool = False  # only Esc/Enter/system close may hide

        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # This is a modeless utility window.  Closing it must not destroy the
        # singleton or make QApplication exit when it is the only window.
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

        self._init_ui()

    def _init_ui(self):
        # Outer container layout
        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)

        # Card container with black background, rounded corners and crisp border
        self._card = QtWidgets.QFrame()
        self._card.setObjectName("SciFiCard")
        self._card.setStyleSheet(
            """
            QFrame#SciFiCard {
                background-color: #0A0A0A;
                border: 1px solid #333333;
                border-radius: 12px;
            }
            """
        )
        card_layout = QtWidgets.QVBoxLayout(self._card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(10)

        # 1. Header
        header_top = QtWidgets.QHBoxLayout()
        header_tag = QtWidgets.QLabel("// LEXICAL // RADAR")
        header_tag.setStyleSheet(
            "color: #777777; font-size: 9px; font-family: 'Consolas', monospace; letter-spacing: 1px; background: transparent;"
        )
        sys_tag = QtWidgets.QLabel("[SYS.ON]")
        sys_tag.setStyleSheet(
            "color: #FFFFFF; font-size: 8px; font-family: 'Consolas', monospace; font-weight: bold; background: transparent;"
        )
        header_top.addWidget(header_tag)
        header_top.addStretch()
        header_top.addWidget(sys_tag)
        card_layout.addLayout(header_top)

        self._target_label = QtWidgets.QLabel("TARGET: -")
        self._target_label.setStyleSheet(
            "color: #FFFFFF; font-size: 13px; font-family: 'Consolas', monospace; font-weight: bold; background: transparent;"
        )
        card_layout.addWidget(self._target_label)

        # Divider
        div1 = QtWidgets.QFrame()
        div1.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        div1.setStyleSheet("border: none; background-color: #222222; max-height: 1px;")
        card_layout.addWidget(div1)

        # 2. Content Stack (Page 0: Loading, Page 1: Loaded List)
        self._stack = QtWidgets.QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")

        self._loading_widget = SciFiLoadingWidget()
        self._stack.addWidget(self._loading_widget)

        self._list_widget = SciFiSynonymListWidget()
        self._list_widget.item_selected.connect(self._on_item_applied)
        self._stack.addWidget(self._list_widget)

        card_layout.addWidget(self._stack, 1)

        # Divider
        div2 = QtWidgets.QFrame()
        div2.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        div2.setStyleSheet("border: none; background-color: #222222; max-height: 1px;")
        card_layout.addWidget(div2)

        # 3. Footer instructions
        footer_layout = QtWidgets.QHBoxLayout()
        footer_label = QtWidgets.QLabel("[↑/↓] NAV   [ENTER] APPLY   [ESC] CANCEL")
        footer_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        footer_label.setStyleSheet(
            "color: #555555; font-size: 8px; font-family: 'Consolas', monospace; letter-spacing: 1px; background: transparent;"
        )
        footer_layout.addWidget(footer_label)
        card_layout.addLayout(footer_layout)

        root_layout.addWidget(self._card)

    def position_on_right_edge(self):
        """Calculates geometry flush to the right edge and centered vertically."""
        screen = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        width = OVERLAY_WIDTH
        height = min(OVERLAY_HEIGHT, screen.height() - 40)
        x = screen.x() + screen.width() - width - RIGHT_MARGIN
        y = screen.y() + (screen.height() - height) // 2
        self.setGeometry(x, y, width, height)

    def show_loading(self, target_word: str):
        self._loading_widget.show_dictionary_stage()
        """Displays overlay immediately in loading animation state."""
        self._target_label.setText(f'TARGET » "{target_word}"')
        self._stack.setCurrentIndex(0)
        self.position_on_right_edge()
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def show_filtering(self):
        """Switches the loading card to the Ling semantic-filter animation."""
        self._loading_widget.show_filtering_stage()

    def show_synonyms(self, target_word: str, synonyms: List[str], on_apply: Optional[Callable[[str], None]] = None):
        """Transitions overlay to loaded state with synonym list."""
        self.on_apply_callback = on_apply
        self._target_label.setText(f'TARGET » "{target_word}"')
        self._list_widget.populate(synonyms)
        self._stack.setCurrentIndex(1)
        self.position_on_right_edge()
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        self._list_widget.setFocus()

    def _on_item_applied(self, word: str):
        cb = self.on_apply_callback
        self.hide()
        if cb:
            if "pytest" in sys.modules:
                cb(word)
            else:
                import threading
                threading.Thread(target=cb, args=(word,), daemon=True).start()

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        key = event.key()

        if key == QtCore.Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return

        # If on list page
        if self._stack.currentIndex() == 1:
            if key in (QtCore.Qt.Key.Key_Down, QtCore.Qt.Key.Key_Tab):
                self._list_widget.select_next()
                event.accept()
                return
            elif key in (QtCore.Qt.Key.Key_Up, QtCore.Qt.Key.Key_Backtab):
                self._list_widget.select_previous()
                event.accept()
                return
            elif key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
                chosen = self._list_widget.get_current_synonym()
                if chosen:
                    self._on_item_applied(chosen)
                event.accept()
                return

        super().keyPressEvent(event)

    def closeEvent(self, event: QtGui.QCloseEvent):
        """Keep the reusable overlay alive; user cancellation is handled by Esc."""
        if self._allow_auto_hide:
            event.accept()
        else:
            event.ignore()


class SynonymOverlayBridge(QtCore.QObject):
    """Thread-safe signal dispatcher for cross-thread PyQt GUI invocations."""

    sig_show_loading = QtCore.pyqtSignal(str)
    sig_show_filtering = QtCore.pyqtSignal()
    sig_show_synonyms = QtCore.pyqtSignal(str, list, object)
    sig_close = QtCore.pyqtSignal()

    def __init__(self, overlay: PyQtSynonymOverlay):
        super().__init__()
        self.overlay = overlay
        queued = QtCore.Qt.ConnectionType.QueuedConnection
        self.sig_show_loading.connect(self.overlay.show_loading, queued)
        self.sig_show_filtering.connect(self.overlay.show_filtering, queued)
        self.sig_show_synonyms.connect(self.overlay.show_synonyms, queued)
        self.sig_close.connect(self.overlay.hide, queued)


# Global singleton instance holder
_GLOBAL_OVERLAY: Optional[PyQtSynonymOverlay] = None
_GLOBAL_BRIDGE: Optional[SynonymOverlayBridge] = None


def get_synonym_overlay_bridge() -> Optional[SynonymOverlayBridge]:
    """Returns the global thread-safe overlay bridge."""
    global _GLOBAL_OVERLAY, _GLOBAL_BRIDGE
    if _GLOBAL_BRIDGE is None:
        app = QtWidgets.QApplication.instance()
        if app is None:
            return None
        # QWidget construction is GUI-thread-only.  The hotkey callback runs
        # on a worker thread, so it must never lazily create this singleton.
        if QtCore.QThread.currentThread() != app.thread():
            log.warning("Synonym overlay requested before GUI-thread initialization")
            return None
        _GLOBAL_OVERLAY = PyQtSynonymOverlay()
        _GLOBAL_BRIDGE = SynonymOverlayBridge(_GLOBAL_OVERLAY)
    return _GLOBAL_BRIDGE
