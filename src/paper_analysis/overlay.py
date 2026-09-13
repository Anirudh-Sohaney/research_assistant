"""Compact clickable results overlay for multi-judge paper analysis."""

from __future__ import annotations

from typing import Optional
from PyQt6 import QtCore, QtGui, QtWidgets
from paper_analysis.analysis import PaperAnalysisResult


class PaperAnalysisOverlay(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.WindowStaysOnTopHint | QtCore.Qt.WindowType.Tool)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        root = QtWidgets.QVBoxLayout(self); root.setContentsMargins(8, 8, 8, 8)
        card = QtWidgets.QFrame(); card.setStyleSheet("QFrame{background:#0A0A0A;border:1px solid #333;border-radius:12px;}")
        layout = QtWidgets.QVBoxLayout(card); layout.setContentsMargins(16, 16, 16, 16)
        self.title = QtWidgets.QLabel("PAPER ANALYSIS"); self.title.setStyleSheet("color:#FFF;font:bold 13px Consolas;background:transparent;")
        layout.addWidget(self.title)
        self.status = QtWidgets.QLabel("Waiting for judges..."); self.status.setStyleSheet("color:#888;font:10px Consolas;background:transparent;")
        layout.addWidget(self.status)
        self.scores = QtWidgets.QListWidget(); self.scores.setStyleSheet("QListWidget{color:#DDD;background:#111;border:1px solid #333;border-radius:7px;font:11px Consolas;} QListWidget::item{padding:8px;}")
        self.scores.currentRowChanged.connect(self._show_detail); layout.addWidget(self.scores, 1)
        self.detail = QtWidgets.QTextEdit(); self.detail.setReadOnly(True); self.detail.setStyleSheet("QTextEdit{color:#EEE;background:#111;border:1px solid #333;border-radius:7px;padding:8px;font:11px Consolas;}")
        layout.addWidget(self.detail, 2)
        self.footer = QtWidgets.QLabel("CLICK A JUDGE FOR FINDINGS   [ESC] CLOSE"); self.footer.setStyleSheet("color:#666;font:8px Consolas;background:transparent;"); layout.addWidget(self.footer)
        root.addWidget(card); self._result: Optional[PaperAnalysisResult] = None

    def _position(self):
        screen = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen.x() + screen.width() - 520, screen.y() + 80, 500, 700)

    def show_loading(self):
        self.scores.clear(); self.detail.clear(); self.status.setText("RUNNING 8 INDEPENDENT JUDGES..."); self._position(); self.show(); self.raise_(); self.activateWindow(); self.setFocus()

    def show_result(self, result: PaperAnalysisResult):
        self._result = result; self.scores.clear(); self.status.setText(f"OVERALL CURVED SCORE: {result.overall_score if result.overall_score is not None else '--'} / 100")
        for judge in result.judges:
            score = str(judge.score) if judge.score is not None else "ERR"
            self.scores.addItem(f"{score:>3}  {judge.name}")
        if self.scores.count(): self.scores.setCurrentRow(0)
        self._position(); self.show(); self.raise_(); self.activateWindow(); self.setFocus()

    def _show_detail(self, index: int):
        if not self._result or index < 0 or index >= len(self._result.judges): return
        judge = self._result.judges[index]
        if judge.error:
            self.detail.setPlainText(f"{judge.name}\n\nERROR: {judge.error}"); return
        lines = [f"{judge.name} — CURVED SCORE {judge.score}/100", ""]
        for number, finding in enumerate(judge.findings, 1):
            lines.extend([f"{number}. EXCERPT: {finding.excerpt}", f"ISSUE: {finding.issue}", f"FIX: {finding.fix}", ""])
        self.detail.setPlainText("\n".join(lines))

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if event.key() == QtCore.Qt.Key.Key_Escape: self.hide(); event.accept(); return
        super().keyPressEvent(event)


class PaperAnalysisBridge(QtCore.QObject):
    sig_show_loading = QtCore.pyqtSignal()
    sig_show_result = QtCore.pyqtSignal(object)
    sig_close = QtCore.pyqtSignal()

    def __init__(self, overlay: PaperAnalysisOverlay):
        super().__init__(); self.overlay = overlay; queued = QtCore.Qt.ConnectionType.QueuedConnection
        self.sig_show_loading.connect(overlay.show_loading, queued); self.sig_show_result.connect(overlay.show_result, queued); self.sig_close.connect(overlay.hide, queued)


_bridge: Optional[PaperAnalysisBridge] = None


def get_paper_analysis_bridge() -> Optional[PaperAnalysisBridge]:
    global _bridge
    app = QtWidgets.QApplication.instance()
    if _bridge is None and app is not None and QtCore.QThread.currentThread() == app.thread():
        _bridge = PaperAnalysisBridge(PaperAnalysisOverlay())
    return _bridge
