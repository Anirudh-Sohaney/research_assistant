"""Single-section clickable results overlay for multi-judge paper analysis."""

from __future__ import annotations

from typing import Dict, Optional

from PyQt6 import QtCore, QtGui, QtWidgets

from paper_analysis.analysis import JudgeResult, PaperAnalysisResult


class PaperAnalysisOverlay(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.WindowStaysOnTopHint | QtCore.Qt.WindowType.Tool)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        card = QtWidgets.QFrame()
        card.setStyleSheet("QFrame{background:#0A0A0A;border:1px solid #333;border-radius:12px;}")
        layout = QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        self.title = QtWidgets.QLabel("PAPER ANALYSIS")
        self.title.setStyleSheet("color:#FFF;font:bold 13px Consolas;background:transparent;")
        layout.addWidget(self.title)
        self.status = QtWidgets.QLabel("Waiting for judges...")
        self.status.setStyleSheet("color:#888;font:10px Consolas;background:transparent;")
        layout.addWidget(self.status)

        self.content = QtWidgets.QStackedWidget()
        self.scores = QtWidgets.QListWidget()
        self.scores.setStyleSheet("QListWidget{color:#DDD;background:#111;border:1px solid #333;border-radius:7px;font:11px Consolas;} QListWidget::item{padding:10px;}")
        self.scores.currentRowChanged.connect(self._show_explanations)
        self.explanations = QtWidgets.QListWidget()
        self.explanations.setWordWrap(True)
        self.explanations.installEventFilter(self)
        self.explanations.setStyleSheet("QListWidget{color:#DDD;background:#111;border:1px solid #333;border-radius:7px;font:11px Consolas;} QListWidget::item{padding:10px;}")
        self.explanations.currentRowChanged.connect(self._show_finding)
        self.explanations.itemDoubleClicked.connect(lambda item: self._show_finding(self.explanations.row(item)))
        self.detail = QtWidgets.QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.installEventFilter(self)
        self.detail.setStyleSheet("QTextEdit{color:#EEE;background:#111;border:1px solid #333;border-radius:7px;padding:10px;font:11px Consolas;}")
        self.content.addWidget(self.scores)
        self.content.addWidget(self.explanations)
        self.content.addWidget(self.detail)
        layout.addWidget(self.content, 1)
        self.footer = QtWidgets.QLabel("JUDGES WILL APPEAR AS THEY FINISH   [ESC] CLOSE")
        self.footer.setStyleSheet("color:#666;font:8px Consolas;background:transparent;")
        layout.addWidget(self.footer)
        root.addWidget(card)
        self._judges: Dict[str, JudgeResult] = {}
        self._completed_count = 0

    def _position(self):
        screen = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        height = 420
        self.setGeometry(screen.x() + screen.width() - 520, screen.y() + (screen.height() - height) // 2, 500, height)

    def show_loading(self):
        self._judges.clear()
        self._completed_count = 0
        self.scores.clear()
        self.explanations.clear()
        self.detail.clear()
        self.content.setCurrentWidget(self.scores)
        self.status.setText("RUNNING 8 INDEPENDENT JUDGES...")
        self.footer.setText("JUDGES APPEAR AS THEY FINISH   [ESC] CLOSE")
        self._position(); self.show(); self.raise_(); self.activateWindow(); self.setFocus()

    def show_judge_result(self, judge: JudgeResult):
        self._completed_count += 1
        if judge.error:
            self.status.setText(f"JUDGES COMPLETE: {self._completed_count} / 8")
            return
        self._judges[judge.name] = judge
        rows = [self.scores.item(index).text().split("  ", 1)[-1] for index in range(self.scores.count())]
        score = str(judge.score) if judge.score is not None else "ERR"
        if judge.name not in rows:
            item = QtWidgets.QListWidgetItem(f"{score:>3}  {judge.name}")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, judge.name)
            self.scores.addItem(item)
        else:
            self.scores.item(rows.index(judge.name)).setText(f"{score:>3}  {judge.name}")
        self.status.setText(f"JUDGES COMPLETE: {self._completed_count} / 8")
        self._position(); self.show(); self.raise_(); self.activateWindow()

    def show_complete(self, result: PaperAnalysisResult):
        self.status.setText(f"OVERALL SCORE: {result.overall_score if result.overall_score is not None else '--'} / 100")
        self.footer.setText("CLICK A JUDGE FOR EXPLANATIONS   [ESC] CLOSE")
        self._position(); self.show(); self.raise_(); self.activateWindow(); self.setFocus()

    def show_result(self, result: PaperAnalysisResult):
        """Compatibility helper for callers that already have a complete result."""
        self.show_loading()
        for judge in result.judges:
            self.show_judge_result(judge)
        self.show_complete(result)

    def _show_explanations(self, index: int):
        if index < 0 or index >= self.scores.count():
            return
        name = self.scores.item(index).data(QtCore.Qt.ItemDataRole.UserRole) or self.scores.item(index).text().split("  ", 1)[-1]
        judge = self._judges.get(name)
        if judge is None:
            return
        self.explanations.blockSignals(True)
        self.explanations.clear()
        if judge.error:
            self.explanations.addItem(f"ERROR\n{judge.error}")
        else:
            for number, finding in enumerate(judge.findings, 1):
                item = QtWidgets.QListWidgetItem(f"EXPLANATION {number}\n{finding.explanation}")
                item.setData(QtCore.Qt.ItemDataRole.UserRole, number - 1)
                self.explanations.addItem(item)
        self.explanations.setCurrentRow(-1)
        self.explanations.clearSelection()
        self.explanations.blockSignals(False)
        # Defer the page switch until the judge-row mouse event has finished;
        # otherwise the release event can land on explanation 1 in the new page.
        QtCore.QTimer.singleShot(75, self._activate_explanation_list)

    def _activate_explanation_list(self):
        self.explanations.blockSignals(True)
        self.content.setCurrentWidget(self.explanations)
        self.explanations.setCurrentRow(-1)
        self.explanations.clearSelection()
        self.explanations.blockSignals(False)
        self.footer.setText("CLICK AN EXPLANATION FOR REPLACEMENT   [BACKSPACE] BACK TO JUDGES   [ESC] CLOSE")

    def _show_finding(self, index: int):
        if index < 0 or index >= self.explanations.count():
            return
        judge_index = self.scores.currentRow()
        if judge_index < 0:
            return
        name = self.scores.item(judge_index).data(QtCore.Qt.ItemDataRole.UserRole) or self.scores.item(judge_index).text().split("  ", 1)[-1]
        judge = self._judges.get(name)
        if judge is None or index >= len(judge.findings):
            return
        finding = judge.findings[index]
        self.detail.setPlainText(
            f"{judge.name.upper()} — EXPLANATION {index + 1}\n\n"
            f"EXACT TEXT TO REPLACE\n{finding.excerpt}\n\n"
            f"REPLACE WITH\n{finding.rewrite or '[DELETE THE AFFECTED TEXT]'}\n\n"
            f"ISSUE\n{finding.issue}\n\n"
            f"INSTRUCTION\n{finding.fix}"
        )
        self.content.setCurrentWidget(self.detail)
        self.detail.setFocus()
        self.footer.setText("[BACKSPACE] BACK TO EXPLANATIONS   [ESC] CLOSE")

    def _show_list(self):
        self.content.setCurrentWidget(self.scores)
        self.footer.setText("CLICK A JUDGE FOR EXPLANATIONS   [ESC] CLOSE")

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter) and self.content.currentWidget() is self.explanations:
            row = self.explanations.currentRow()
            if row >= 0:
                self._show_finding(row)
                event.accept(); return
        if event.key() == QtCore.Qt.Key.Key_Escape:
            self.hide(); event.accept(); return
        if event.key() == QtCore.Qt.Key.Key_Backspace and self.content.currentWidget() is self.detail:
            self.content.setCurrentWidget(self.explanations)
            self.footer.setText("CLICK AN EXPLANATION FOR REPLACEMENT   [BACKSPACE] BACK TO JUDGES   [ESC] CLOSE")
            event.accept(); return
        if event.key() == QtCore.Qt.Key.Key_Backspace and self.content.currentWidget() is self.explanations:
            self._show_list(); event.accept(); return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):
        detail = getattr(self, "detail", None)
        explanations = getattr(self, "explanations", None)
        if watched is detail and event.type() == QtCore.QEvent.Type.KeyPress:
            if event.key() == QtCore.Qt.Key.Key_Escape:
                self.hide(); return True
            if event.key() == QtCore.Qt.Key.Key_Backspace:
                self.content.setCurrentWidget(self.explanations)
                return True
        if watched is explanations and event.type() == QtCore.QEvent.Type.KeyPress:
            if event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
                row = self.explanations.currentRow()
                if row >= 0:
                    self._show_finding(row)
                    return True
        return super().eventFilter(watched, event)


class PaperAnalysisBridge(QtCore.QObject):
    sig_show_loading = QtCore.pyqtSignal()
    sig_judge_result = QtCore.pyqtSignal(object)
    sig_show_complete = QtCore.pyqtSignal(object)
    sig_close = QtCore.pyqtSignal()

    def __init__(self, overlay: PaperAnalysisOverlay):
        super().__init__()
        self.overlay = overlay
        queued = QtCore.Qt.ConnectionType.QueuedConnection
        self.sig_show_loading.connect(overlay.show_loading, queued)
        self.sig_judge_result.connect(overlay.show_judge_result, queued)
        self.sig_show_complete.connect(overlay.show_complete, queued)
        self.sig_close.connect(overlay.hide, queued)


_bridge: Optional[PaperAnalysisBridge] = None


def get_paper_analysis_bridge() -> Optional[PaperAnalysisBridge]:
    global _bridge
    app = QtWidgets.QApplication.instance()
    if _bridge is None and app is not None and QtCore.QThread.currentThread() == app.thread():
        _bridge = PaperAnalysisBridge(PaperAnalysisOverlay())
    return _bridge
