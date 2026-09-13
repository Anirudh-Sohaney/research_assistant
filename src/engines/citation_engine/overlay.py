"""Interactive PyQt6 Citation Overlay for word processors (Google Docs, Word, Overleaf, Notion).

Adheres strictly to pure white UI styling (clean white background #FFFFFF, crisp typography,
no dark/black backgrounds).
Supports live inline metadata editing, field customization, style switching, and atomic injection.
"""

from __future__ import annotations

import sys
from typing import Dict, List, Optional

from PyQt6 import QtCore, QtGui, QtWidgets

from engines.citation_engine.models import Author, CitationDate, CitationResult, CitationStyle
from engines.citation_engine.normalizer import parse_authors_list, parse_date_string
from engines.citation_engine.service import CitationService


class CitationOverlay(QtWidgets.QWidget):
    """Floating pure-white card with extracted citation metadata, editable fields, and direct insertion."""

    style_changed = QtCore.pyqtSignal(str)
    apply_requested = QtCore.pyqtSignal(str)  # Emits formatted text to inject into active document
    copy_requested = QtCore.pyqtSignal(str)

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

        self._active_target = ""
        self._target_hwnd: Optional[int] = None
        self._current_result: Optional[CitationResult] = None
        self._results_by_style: Dict[CitationStyle, CitationResult] = {}
        self._active_style = CitationStyle.APA
        self._is_editing_meta = False

        self._build_ui()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        # Pure white main card with soft drop shadow and subtle border
        self._card = QtWidgets.QFrame()
        self._card.setStyleSheet(
            """
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #D1D5DB;
                border-radius: 12px;
            }
            """
        )
        # Drop shadow
        shadow = QtWidgets.QGraphicsDropShadowEffect(self._card)
        shadow.setBlurRadius(24)
        shadow.setColor(QtGui.QColor(0, 0, 0, 40))
        shadow.setOffset(0, 6)
        self._card.setGraphicsEffect(shadow)

        layout = QtWidgets.QVBoxLayout(self._card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        # Header bar
        header_layout = QtWidgets.QHBoxLayout()
        header_icon = QtWidgets.QLabel("📚")
        header_icon.setStyleSheet("font-size: 16px; background: transparent; border: none;")
        header_layout.addWidget(header_icon)

        self._header_title = QtWidgets.QLabel("Citation Assistant")
        self._header_title.setStyleSheet(
            "font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; font-weight: bold; color: #111827; background: transparent; border: none;"
        )
        header_layout.addWidget(self._header_title)

        header_layout.addStretch(1)

        # Edit Metadata toggle button
        self._btn_edit_meta = QtWidgets.QPushButton("✏️ Edit Metadata")
        self._btn_edit_meta.setCheckable(True)
        self._btn_edit_meta.setFixedHeight(24)
        self._btn_edit_meta.setStyleSheet(
            """
            QPushButton {
                background-color: #F3F4F6;
                color: #374151;
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                font-family: 'Segoe UI', Arial;
                font-size: 10px;
                font-weight: 600;
                padding: 0 8px;
            }
            QPushButton:hover {
                background-color: #E5E7EB;
                color: #111827;
            }
            QPushButton:checked {
                background-color: #EEF2FF;
                color: #4F46E5;
                border: 1px solid #C7D2FE;
            }
            """
        )
        self._btn_edit_meta.clicked.connect(self._toggle_edit_metadata)
        header_layout.addWidget(self._btn_edit_meta)

        self._confidence_badge = QtWidgets.QLabel("")
        self._confidence_badge.setStyleSheet(
            "font-family: 'Segoe UI', Arial; font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 6px; background: #ECFDF5; color: #065F46; border: 1px solid #A7F3D0;"
        )
        header_layout.addWidget(self._confidence_badge)

        self._btn_close = QtWidgets.QPushButton("✕")
        self._btn_close.setFixedSize(22, 22)
        self._btn_close.setStyleSheet(
            """
            QPushButton {
                background: #F3F4F6;
                color: #4B5563;
                border: none;
                border-radius: 11px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #E5E7EB;
                color: #111827;
            }
            """
        )
        self._btn_close.clicked.connect(self.hide)
        header_layout.addWidget(self._btn_close)
        layout.addLayout(header_layout)

        # Stack for Loading vs Result
        self._stack = QtWidgets.QStackedWidget()
        self._stack.setStyleSheet("background: transparent; border: none;")

        # Page 1: Loading
        self._loading_page = QtWidgets.QWidget()
        load_layout = QtWidgets.QVBoxLayout(self._loading_page)
        load_layout.setContentsMargins(0, 20, 0, 20)
        self._load_spinner = QtWidgets.QLabel("Resolving source metadata...\nChecking Crossref, OpenLibrary & Page Head")
        self._load_spinner.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._load_spinner.setStyleSheet(
            "font-family: 'Segoe UI', Arial; font-size: 12px; color: #4B5563; line-height: 1.5; background: transparent; border: none;"
        )
        load_layout.addWidget(self._load_spinner)
        self._stack.addWidget(self._loading_page)

        # Page 2: Ready Content
        self._content_page = QtWidgets.QWidget()
        self._content_layout = QtWidgets.QVBoxLayout(self._content_page)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(8)

        # Collapsible Edit Metadata Form
        self._meta_form_widget = QtWidgets.QWidget()
        self._meta_form_layout = QtWidgets.QFormLayout(self._meta_form_widget)
        self._meta_form_layout.setContentsMargins(10, 8, 10, 8)
        self._meta_form_layout.setSpacing(6)
        self._meta_form_widget.setStyleSheet(
            """
            QWidget {
                background-color: #F9FAFB;
                border: 1px solid #E5E7EB;
                border-radius: 8px;
            }
            QLabel {
                font-family: 'Segoe UI', Arial;
                font-size: 11px;
                font-weight: 600;
                color: #374151;
                background: transparent;
                border: none;
            }
            QLineEdit {
                background-color: #FFFFFF;
                color: #111827;
                border: 1px solid #D1D5DB;
                border-radius: 4px;
                padding: 4px 8px;
                font-family: 'Segoe UI', Arial;
                font-size: 11px;
            }
            QLineEdit:focus {
                border: 1px solid #2563EB;
            }
            """
        )

        self._in_title = QtWidgets.QLineEdit()
        self._in_title.setPlaceholderText("Article or Paper Title")
        self._in_title.textChanged.connect(self._on_metadata_field_changed)
        self._meta_form_layout.addRow("Title:", self._in_title)

        self._in_authors = QtWidgets.QLineEdit()
        self._in_authors.setPlaceholderText("Authors (separated by comma or 'and', e.g. Smith, John; Doe, Jane)")
        self._in_authors.textChanged.connect(self._on_metadata_field_changed)
        self._meta_form_layout.addRow("Authors:", self._in_authors)

        self._in_year = QtWidgets.QLineEdit()
        self._in_year.setPlaceholderText("Year or Date (e.g. 2024 or 2023-08-15)")
        self._in_year.textChanged.connect(self._on_metadata_field_changed)
        self._meta_form_layout.addRow("Date:", self._in_year)

        self._in_container = QtWidgets.QLineEdit()
        self._in_container.setPlaceholderText("Journal, Website, or Book Publisher")
        self._in_container.textChanged.connect(self._on_metadata_field_changed)
        self._meta_form_layout.addRow("Source:", self._in_container)

        self._meta_form_widget.setVisible(False)
        self._content_layout.addWidget(self._meta_form_widget)

        # Style switcher buttons
        style_layout = QtWidgets.QHBoxLayout()
        style_layout.setSpacing(6)
        self._style_buttons: Dict[CitationStyle, QtWidgets.QPushButton] = {}

        styles = [
            (CitationStyle.APA, "APA 7th"),
            (CitationStyle.MLA, "MLA 9th"),
            (CitationStyle.CHICAGO, "Chicago"),
            (CitationStyle.IEEE, "IEEE"),
            (CitationStyle.BIBTEX, "BibTeX"),
        ]

        for st, label in styles:
            btn = QtWidgets.QPushButton(label)
            btn.setFixedHeight(26)
            btn.setCheckable(True)
            btn.setStyleSheet(
                """
                QPushButton {
                    background-color: #F9FAFB;
                    color: #374151;
                    border: 1px solid #D1D5DB;
                    border-radius: 6px;
                    font-family: 'Segoe UI', Arial;
                    font-size: 11px;
                    font-weight: 500;
                    padding: 0 10px;
                }
                QPushButton:hover {
                    background-color: #F3F4F6;
                    color: #111827;
                }
                QPushButton:checked {
                    background-color: #2563EB;
                    color: #FFFFFF;
                    border: 1px solid #1D4ED8;
                    font-weight: 600;
                }
                """
            )
            btn.clicked.connect(lambda checked, s=st: self._select_style(s))
            style_layout.addWidget(btn)
            self._style_buttons[st] = btn

        self._style_buttons[CitationStyle.APA].setChecked(True)
        self._content_layout.addLayout(style_layout)

        # Formatted citation preview box (Editable directly by user!)
        self._preview_box = QtWidgets.QTextEdit()
        self._preview_box.setReadOnly(False)  # User can tweak text directly before inserting!
        self._preview_box.setFixedHeight(95)
        self._preview_box.setPlaceholderText("Formatted citation preview (you can edit directly here)...")
        self._preview_box.setStyleSheet(
            """
            QTextEdit {
                background-color: #F9FAFB;
                color: #111827;
                border: 1px solid #E5E7EB;
                border-radius: 8px;
                padding: 10px;
                font-family: 'Segoe UI', Georgia, serif;
                font-size: 12px;
                line-height: 1.4;
            }
            QTextEdit:focus {
                background-color: #FFFFFF;
                border: 1px solid #2563EB;
            }
            """
        )
        self._content_layout.addWidget(self._preview_box)

        # In-text callout label
        self._intext_label = QtWidgets.QLabel("In-Text: (Vaswani et al., 2017)")
        self._intext_label.setStyleSheet(
            "font-family: 'Segoe UI', Arial; font-size: 11px; color: #4B5563; font-style: italic; background: transparent; border: none;"
        )
        self._content_layout.addWidget(self._intext_label)

        # Action Buttons
        actions_layout = QtWidgets.QHBoxLayout()
        actions_layout.setSpacing(8)

        self._btn_inject_bib = QtWidgets.QPushButton("Insert Bibliography [Enter]")
        self._btn_inject_bib.setFixedHeight(34)
        self._btn_inject_bib.setStyleSheet(
            """
            QPushButton {
                background-color: #2563EB;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                font-family: 'Segoe UI', Arial;
                font-size: 11px;
                font-weight: 600;
                padding: 0 14px;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
            }
            """
        )
        self._btn_inject_bib.clicked.connect(self._apply_bibliography)
        actions_layout.addWidget(self._btn_inject_bib)

        self._btn_inject_intext = QtWidgets.QPushButton("Insert In-Text [Shift+Enter]")
        self._btn_inject_intext.setFixedHeight(34)
        self._btn_inject_intext.setStyleSheet(
            """
            QPushButton {
                background-color: #FFFFFF;
                color: #2563EB;
                border: 1px solid #2563EB;
                border-radius: 6px;
                font-family: 'Segoe UI', Arial;
                font-size: 11px;
                font-weight: 600;
                padding: 0 12px;
            }
            QPushButton:hover {
                background-color: #EFF6FF;
            }
            """
        )
        self._btn_inject_intext.clicked.connect(self._apply_intext)
        actions_layout.addWidget(self._btn_inject_intext)

        self._btn_copy = QtWidgets.QPushButton("Copy [C]")
        self._btn_copy.setFixedHeight(34)
        self._btn_copy.setStyleSheet(
            """
            QPushButton {
                background-color: #F3F4F6;
                color: #374151;
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                font-family: 'Segoe UI', Arial;
                font-size: 11px;
                font-weight: 500;
                padding: 0 10px;
            }
            QPushButton:hover {
                background-color: #E5E7EB;
                color: #111827;
            }
            """
        )
        self._btn_copy.clicked.connect(self._copy_citation)
        actions_layout.addWidget(self._btn_copy)

        self._content_layout.addLayout(actions_layout)
        self._stack.addWidget(self._content_page)

        layout.addWidget(self._stack, 1)

        # Footer tips
        self._footer = QtWidgets.QLabel("Compatible with Google Docs, Word, Notion, and Overleaf")
        self._footer.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._footer.setStyleSheet(
            "font-family: 'Segoe UI', Arial; font-size: 9px; color: #9CA3AF; background: transparent; border: none;"
        )
        layout.addWidget(self._footer)

        root.addWidget(self._card)
        self.resize(480, 310)

    def position_centered_or_near_cursor(self):
        cursor_pos = QtGui.QCursor.pos()
        screen = QtGui.QGuiApplication.screenAt(cursor_pos) or QtGui.QGuiApplication.primaryScreen()
        geom = screen.availableGeometry()

        width, height = self.width(), self.height()
        x = min(max(cursor_pos.x() - width // 2, geom.x() + 20), geom.x() + geom.width() - width - 20)
        y = cursor_pos.y() + 24
        if y + height > geom.y() + geom.height() - 20:
            y = cursor_pos.y() - height - 24

        self.setGeometry(x, y, width, height)

    def _toggle_edit_metadata(self):
        self._is_editing_meta = not self._is_editing_meta
        self._btn_edit_meta.setChecked(self._is_editing_meta)
        self._meta_form_widget.setVisible(self._is_editing_meta)

        # Adjust height smoothly
        if self._is_editing_meta:
            self.resize(480, 470)
        else:
            self.resize(480, 310)

    def _on_metadata_field_changed(self):
        """Re-renders all citations in real time when any metadata field is edited."""
        if not self._current_result:
            return

        meta = self._current_result.metadata
        # 1. Title
        title_text = self._in_title.text().strip()
        if title_text:
            meta.title = title_text

        # 2. Authors
        auth_text = self._in_authors.text().strip()
        meta.authors = parse_authors_list(auth_text)

        # 3. Date
        date_text = self._in_year.text().strip()
        meta.date = parse_date_string(date_text)

        # 4. Container / Publisher
        container_text = self._in_container.text().strip()
        meta.container_title = container_text
        meta.publisher = container_text

        # Re-render across all styles
        service = CitationService()
        for st, renderer in service._renderers.items():
            self._results_by_style[st] = CitationResult(
                bibliography_entry=renderer.render_bibliography(meta),
                in_text_citation=renderer.render_in_text(meta),
                style=st,
                metadata=meta,
                confidence_score=self._current_result.confidence_score,
            )

        self._update_display_for_current_style()

    def show_loading(self, target_text: str, target_hwnd: Optional[int] = None):
        self._active_target = target_text
        self._target_hwnd = target_hwnd
        self._results_by_style.clear()
        self._is_editing_meta = False
        self._meta_form_widget.setVisible(False)
        self._btn_edit_meta.setChecked(False)
        self.resize(480, 310)

        self._confidence_badge.setText("SEARCHING")
        self._confidence_badge.setStyleSheet(
            "font-family: 'Segoe UI', Arial; font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 6px; background: #FEF3C7; color: #92400E; border: 1px solid #FCD34D;"
        )
        self._stack.setCurrentWidget(self._loading_page)
        self.position_centered_or_near_cursor()
        self.show()
        self.raise_()
        self.activateWindow()

    def show_result(self, result: CitationResult, target_hwnd: Optional[int] = None):
        self._current_result = result
        self._results_by_style[result.style] = result
        if target_hwnd:
            self._target_hwnd = target_hwnd

        # Populate editable metadata form fields
        meta = result.metadata
        self._in_title.blockSignals(True)
        self._in_authors.blockSignals(True)
        self._in_year.blockSignals(True)
        self._in_container.blockSignals(True)

        self._in_title.setText(meta.title or "")
        authors_str = "; ".join(a.full_name for a in meta.authors)
        self._in_authors.setText(authors_str)
        date_str = str(meta.date.year) if meta.date.has_date and meta.date.year else ""
        if meta.date.month:
            date_str += f"-{meta.date.month:02d}"
        self._in_year.setText(date_str)
        self._in_container.setText(meta.container_title or meta.publisher or "")

        self._in_title.blockSignals(False)
        self._in_authors.blockSignals(False)
        self._in_year.blockSignals(False)
        self._in_container.blockSignals(False)

        # Update confidence badge
        pct = int(result.confidence_score * 100)
        self._confidence_badge.setText(f"{pct}% CONFIDENCE")
        if pct >= 80:
            self._confidence_badge.setStyleSheet(
                "font-family: 'Segoe UI', Arial; font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 6px; background: #ECFDF5; color: #065F46; border: 1px solid #A7F3D0;"
            )
        else:
            self._confidence_badge.setStyleSheet(
                "font-family: 'Segoe UI', Arial; font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 6px; background: #FEF3C7; color: #92400E; border: 1px solid #FCD34D;"
            )

        self._update_display_for_current_style()
        self._stack.setCurrentWidget(self._content_page)
        self.show()
        self.raise_()
        self.activateWindow()

    def show_error(self, message: str):
        self._confidence_badge.setText("NOT FOUND")
        self._confidence_badge.setStyleSheet(
            "font-family: 'Segoe UI', Arial; font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 6px; background: #FEE2E2; color: #991B1B; border: 1px solid #FCA5A5;"
        )
        self._preview_box.setPlainText(f"Could not resolve citation for target:\n\n{message}\n\nYou can click 'Edit Metadata' above to enter details manually.")
        self._intext_label.setText("")
        self._stack.setCurrentWidget(self._content_page)
        self.show()

    def _select_style(self, style: CitationStyle):
        self._active_style = style
        for s, btn in self._style_buttons.items():
            btn.setChecked(s == style)

        if style in self._results_by_style:
            self._current_result = self._results_by_style[style]
            self._update_display_for_current_style()
        else:
            if self._current_result:
                import asyncio
                service = CitationService()
                new_res = asyncio.run(service.cite(self._active_target, style=style))
                self._results_by_style[style] = new_res
                self._current_result = new_res
                self._update_display_for_current_style()

    def _update_display_for_current_style(self):
        if not self._current_result:
            return
        self._preview_box.setPlainText(self._current_result.bibliography_entry)
        if self._active_style == CitationStyle.BIBTEX:
            self._intext_label.setText(f"LaTeX Citation: {self._current_result.in_text_citation}")
            self._btn_inject_bib.setText("Insert BibTeX [Enter]")
            self._btn_inject_intext.setText("Insert \\cite [Shift+Enter]")
        else:
            self._intext_label.setText(f"In-Text: {self._current_result.in_text_citation}")
            self._btn_inject_bib.setText("Insert Bibliography [Enter]")
            self._btn_inject_intext.setText("Insert In-Text [Shift+Enter]")

    def _apply_bibliography(self):
        if not self._current_result:
            return
        # Grabs the exact text from the preview box, including any user edits!
        text_to_inject = self._preview_box.toPlainText().strip() or self._current_result.bibliography_entry
        self.hide()
        self.apply_requested.emit(text_to_inject)

    def _apply_intext(self):
        if not self._current_result:
            return
        text_to_inject = self._current_result.in_text_citation
        self.hide()
        self.apply_requested.emit(text_to_inject)

    def _copy_citation(self):
        if not self._current_result:
            return
        text = self._preview_box.toPlainText().strip() or self._current_result.bibliography_entry
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(text)
        self._btn_copy.setText("Copied! ✓")
        QtCore.QTimer.singleShot(1500, lambda: self._btn_copy.setText("Copy [C]"))

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        key = event.key()
        modifiers = event.modifiers()

        # If user is actively typing in a single-line input field, don't intercept standard typing
        focused = self.focusWidget()
        if isinstance(focused, QtWidgets.QLineEdit):
            if key == QtCore.Qt.Key.Key_Escape:
                self.hide()
                event.accept()
                return
            elif key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
                self._apply_bibliography()
                event.accept()
                return
            super().keyPressEvent(event)
            return

        if key == QtCore.Qt.Key.Key_Escape:
            self.hide()
            event.accept()
        elif key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            if modifiers & QtCore.Qt.KeyboardModifier.ShiftModifier:
                self._apply_intext()
            else:
                self._apply_bibliography()
            event.accept()
        elif key == QtCore.Qt.Key.Key_C and not (modifiers & QtCore.Qt.KeyboardModifier.ControlModifier):
            self._copy_citation()
            event.accept()
        elif key == QtCore.Qt.Key.Key_1:
            self._select_style(CitationStyle.APA)
        elif key == QtCore.Qt.Key.Key_2:
            self._select_style(CitationStyle.MLA)
        elif key == QtCore.Qt.Key.Key_3:
            self._select_style(CitationStyle.CHICAGO)
        elif key == QtCore.Qt.Key.Key_4:
            self._select_style(CitationStyle.IEEE)
        elif key == QtCore.Qt.Key.Key_5:
            self._select_style(CitationStyle.BIBTEX)
        else:
            super().keyPressEvent(event)


class CitationOverlayBridge(QtCore.QObject):
    """Bridge communicating between Python background hotkey listener and the Qt GUI thread."""

    sig_show_loading = QtCore.pyqtSignal(str, object)
    sig_show_result = QtCore.pyqtSignal(object, object)
    sig_show_error = QtCore.pyqtSignal(str)
    sig_close = QtCore.pyqtSignal()
    citation_applied = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._overlay: Optional[CitationOverlay] = None

    def mount(self):
        if self._overlay is None:
            self._overlay = CitationOverlay()
            self.sig_show_loading.connect(self._overlay.show_loading)
            self.sig_show_result.connect(self._overlay.show_result)
            self.sig_show_error.connect(self._overlay.show_error)
            self.sig_close.connect(self._overlay.hide)
            self._overlay.apply_requested.connect(self.citation_applied.emit)


_global_bridge: Optional[CitationOverlayBridge] = None


def get_citation_overlay_bridge() -> Optional[CitationOverlayBridge]:
    """Returns singleton bridge instance mounted on Qt GUI thread."""
    global _global_bridge
    if _global_bridge is None:
        app = QtWidgets.QApplication.instance()
        if app is not None:
            _global_bridge = CitationOverlayBridge()
            _global_bridge.mount()
    return _global_bridge
