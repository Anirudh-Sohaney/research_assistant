"""Interactive PyQt popup for full-sentence rewording."""

from __future__ import annotations

import sys
from typing import Callable, Optional

from PyQt6 import QtCore, QtGui, QtWidgets


class RewordOverlay(QtWidgets.QWidget):
    """Mode picker and preview card for reword, detail, and simplify actions."""

    mode_selected = QtCore.pyqtSignal(str)
    apply_requested = QtCore.pyqtSignal()
    regenerate_requested = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self._build_ui()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        card = QtWidgets.QFrame()
        card.setStyleSheet("QFrame { background:#0A0A0A; border:1px solid #333; border-radius:12px; }")
        layout = QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self._header = QtWidgets.QLabel("// SENTENCE // FORGE")
        self._header.setStyleSheet("color:#888; font: bold 9px Consolas; background:transparent;")
        layout.addWidget(self._header)
        self._target = QtWidgets.QLabel("FULL REWORD")
        self._target.setWordWrap(True)
        self._target.setStyleSheet("color:#FFF; font: bold 13px Consolas; background:transparent;")
        layout.addWidget(self._target)

        self._stack = QtWidgets.QStackedWidget()
        self._mode_page = QtWidgets.QWidget()
        mode_layout = QtWidgets.QVBoxLayout(self._mode_page)
        mode_layout.setContentsMargins(0, 12, 0, 12)
        mode_layout.setSpacing(8)
        self._mode_buttons = []
        for key, label, description in (
            ("reword", "REWORD", "preserve meaning / fix English"),
            ("add_detail", "ADD DETAIL", "expand explanation / evidence"),
            ("simplify", "SIMPLIFY", "reduce complexity / word load"),
        ):
            button = QtWidgets.QPushButton(f"[{len(self._mode_buttons) + 1}]  {label}\n      {description}")
            button.setMinimumHeight(52)
            button.setStyleSheet("QPushButton { color:#DDD; background:#111; border:1px solid #333; border-radius:7px; text-align:left; padding:7px; font:11px Consolas; } QPushButton:hover { background:#FFF; color:#000; }")
            button.clicked.connect(lambda checked=False, selected=key: self.mode_selected.emit(selected))
            mode_layout.addWidget(button)
            self._mode_buttons.append(button)

        self._loading_page = QtWidgets.QLabel("LING // GENERATING\n\n  [ .. ]  APPLYING EDITORIAL DIRECTIVE")
        self._loading_page.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._loading_page.setStyleSheet("color:#DDD; font: bold 11px Consolas; background:transparent;")
        self._result_page = QtWidgets.QTextEdit()
        self._result_page.setReadOnly(True)
        self._result_page.installEventFilter(self)
        self._result_page.setStyleSheet("QTextEdit { color:#EEE; background:#111; border:1px solid #333; border-radius:7px; padding:8px; font:12px Consolas; }")
        self._stack.addWidget(self._mode_page)
        self._stack.addWidget(self._loading_page)
        self._stack.addWidget(self._result_page)
        layout.addWidget(self._stack, 1)

        self._footer = QtWidgets.QLabel("[1-3] SELECT MODE   [ESC] CANCEL")
        self._footer.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._footer.setStyleSheet("color:#666; font:8px Consolas; background:transparent;")
        layout.addWidget(self._footer)
        root.addWidget(card)

    def position_on_right_edge(self):
        screen = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        width, height = 390, 440
        self.setGeometry(screen.x() + screen.width() - width - 16, screen.y() + (screen.height() - height) // 2, width, height)

    def show_modes(self, selected_text: str):
        self._target.setText(f'FULL REWORD  |  "{selected_text[:80]}{"..." if len(selected_text) > 80 else ""}"')
        self._stack.setCurrentWidget(self._mode_page)
        self._footer.setText("[1-3] SELECT MODE   [ESC] CANCEL")
        self.position_on_right_edge()
        self.showNormal(); self.show(); self.raise_(); self.activateWindow(); self.setFocus()

    def show_loading(self, mode: str):
        self._stack.setCurrentWidget(self._loading_page)
        self._loading_page.setText(f"LING // GENERATING\n\n  [ .. ]  {mode.upper()} DIRECTIVE")
        self._footer.setText("GENERATING WITH OPENROUTER LING   [ESC] CANCEL")
        self.position_on_right_edge()
        self.showNormal(); self.show(); self.raise_(); self.activateWindow(); self.setFocus()

    def show_result(self, replacement: str):
        self._result_page.setPlainText(replacement)
        self._stack.setCurrentWidget(self._result_page)
        self._footer.setText("[ENTER] APPLY   [R] REGENERATE   [ESC] CANCEL")
        self.showNormal(); self.show(); self.raise_(); self.activateWindow(); self._result_page.setFocus()

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        key = event.key()
        if key == QtCore.Qt.Key.Key_Escape:
            self.hide(); event.accept(); return
        if self._stack.currentWidget() is self._mode_page:
            mapping = {QtCore.Qt.Key.Key_1: "reword", QtCore.Qt.Key.Key_2: "add_detail", QtCore.Qt.Key.Key_3: "simplify"}
            if key in mapping:
                self.mode_selected.emit(mapping[key]); event.accept(); return
        elif self._stack.currentWidget() is self._result_page:
            if key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
                self.apply_requested.emit(); event.accept(); return
            if key == QtCore.Qt.Key.Key_R:
                self.regenerate_requested.emit(); event.accept(); return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        if watched is self._result_page and event.type() == QtCore.QEvent.Type.KeyPress:
            if event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
                self.apply_requested.emit()
                return True
            if event.key() == QtCore.Qt.Key.Key_R:
                self.regenerate_requested.emit()
                return True
            if event.key() == QtCore.Qt.Key.Key_Escape:
                self.hide()
                return True
        return super().eventFilter(watched, event)


class RewordOverlayBridge(QtCore.QObject):
    """Queued GUI bridge used by the hotkey worker and reword worker."""

    sig_show_modes = QtCore.pyqtSignal(str)
    sig_show_loading = QtCore.pyqtSignal(str)
    sig_show_result = QtCore.pyqtSignal(str)
    sig_close = QtCore.pyqtSignal()
    mode_selected = QtCore.pyqtSignal(str)
    apply_requested = QtCore.pyqtSignal()
    regenerate_requested = QtCore.pyqtSignal()

    def __init__(self, overlay: RewordOverlay):
        super().__init__()
        self.overlay = overlay
        queued = QtCore.Qt.ConnectionType.QueuedConnection
        self.sig_show_modes.connect(overlay.show_modes, queued)
        self.sig_show_loading.connect(overlay.show_loading, queued)
        self.sig_show_result.connect(overlay.show_result, queued)
        self.sig_close.connect(overlay.hide, queued)
        overlay.mode_selected.connect(self.mode_selected)
        overlay.apply_requested.connect(self.apply_requested)
        overlay.regenerate_requested.connect(self.regenerate_requested)


_GLOBAL_REWORD_OVERLAY: Optional[RewordOverlay] = None
_GLOBAL_REWORD_BRIDGE: Optional[RewordOverlayBridge] = None


def get_reword_overlay_bridge() -> Optional[RewordOverlayBridge]:
    global _GLOBAL_REWORD_OVERLAY, _GLOBAL_REWORD_BRIDGE
    if _GLOBAL_REWORD_BRIDGE is None:
        app = QtWidgets.QApplication.instance()
        if app is None or QtCore.QThread.currentThread() != app.thread():
            return None
        _GLOBAL_REWORD_OVERLAY = RewordOverlay()
        _GLOBAL_REWORD_BRIDGE = RewordOverlayBridge(_GLOBAL_REWORD_OVERLAY)
    return _GLOBAL_REWORD_BRIDGE
