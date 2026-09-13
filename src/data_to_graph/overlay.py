"""Interactive PyQt popup overlay for table-to-graph visualization.

Imitates the cyber-academic Consolas monospace design language of RewordOverlay
and PyQtSynonymOverlay for real-time scientific chart previewing and switching.
"""

from __future__ import annotations

import base64
import ctypes
import io
import logging
import os
import sys
import tempfile
import threading
import time
from typing import Callable, Dict, List, Optional

from PyQt6 import QtCore, QtGui, QtWidgets

from data_to_graph.chart_selector import get_compatible_chart_types
from data_to_graph.grapher import TableGraphEngine, generate_chart, parse_tabular_data, toggle_chart_type
from data_to_graph.models import (
    ChartCollection,
    ChartStyleConfig,
    ChartType,
    ParsedTableDataset,
    RenderedChart,
)
from data_to_graph.segmenter import TableSegmenter

log = logging.getLogger(__name__)

# Clean emoji/icon mappings for compatible chart types
CHART_ICONS: Dict[ChartType, str] = {
    ChartType.BAR_CHART: "📊 BAR",
    ChartType.HORIZONTAL_BAR: "📊 H-BAR",
    ChartType.LINE_CHART: "📈 LINE",
    ChartType.AREA_CHART: "📉 AREA",
    ChartType.STACKED_BAR: "📊 STACK-BAR",
    ChartType.STACKED_AREA: "📉 STACK-AREA",
    ChartType.PIE_CHART: "🥧 PIE",
    ChartType.DONUT_CHART: "🍩 DONUT",
    ChartType.SCATTER_DOT: "⁘ SCATTER",
    ChartType.BUBBLE_CHART: "🫧 BUBBLE",
    ChartType.HISTOGRAM: "📶 HISTOGRAM",
    ChartType.BOX_PLOT: "📦 BOX PLOT",
    ChartType.HEATMAP: "⬛ HEATMAP",
    ChartType.RADAR_CHART: "🕸️ RADAR",
    ChartType.GAUGE_CHART: "⏱️ GAUGE",
    ChartType.WATERFALL_CHART: "🌊 WATERFALL",
    ChartType.TREEMAP: "🔲 TREEMAP",
    ChartType.GANTT_CHART: "📅 GANTT",
    ChartType.FUNNEL_CHART: "🔻 FUNNEL",
    ChartType.CANDLESTICK_CHART: "🕯️ CANDLESTICK",
    ChartType.PAIR_PLOT: "▦ PAIR PLOT",
    ChartType.TABLE_VIEW: "📋 TABLE",
}


class TableGraphToast(QtWidgets.QWidget):
    """Cyber-academic floating notification toast for instant visual feedback."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool
            | QtCore.Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_QuitOnClose, False)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        card = QtWidgets.QFrame()
        card.setStyleSheet(
            "QFrame { background:#0A0A0A; border:1px solid #00E5FF; border-radius:8px; }"
        )
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(14, 10, 14, 10)
        card_layout.setSpacing(4)

        self._title = QtWidgets.QLabel("// TABLE // GRAPH")
        self._title.setStyleSheet("color:#00E5FF; font:bold 9px Consolas; background:transparent;")
        card_layout.addWidget(self._title)

        self._msg = QtWidgets.QLabel("✓ FIGURE COPIED & PASTED")
        self._msg.setStyleSheet("color:#FFFFFF; font:bold 11px Consolas; background:transparent;")
        card_layout.addWidget(self._msg)

        self._hint = QtWidgets.QLabel("Pasted below table. Press [Ctrl+V] in any app.")
        self._hint.setStyleSheet("color:#888888; font:9px Consolas; background:transparent;")
        card_layout.addWidget(self._hint)

        layout.addWidget(card)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_toast(self, message: str, hint: str = "", duration_ms: int = 3000):
        self._msg.setText(message)
        if hint:
            self._hint.setText(hint)
            self._hint.show()
        else:
            self._hint.hide()

        cursor_pos = QtGui.QCursor.pos()
        screen_obj = QtGui.QGuiApplication.screenAt(cursor_pos) or QtGui.QGuiApplication.primaryScreen()
        screen = screen_obj.availableGeometry() if screen_obj else QtCore.QRect(0, 0, 1920, 1080)
        w, h = 420, 80
        self.setGeometry(screen.x() + screen.width() - w - 24, screen.y() + screen.height() - h - 40, w, h)
        self.show()
        self._timer.start(duration_ms)


class TableGraphOverlay(QtWidgets.QWidget):
    """Interactive chart viewer and type switcher imitating RewordOverlay UI."""

    chart_selected = QtCore.pyqtSignal(str)
    dataset_selected = QtCore.pyqtSignal(int)
    copy_requested = QtCore.pyqtSignal()
    apply_requested = QtCore.pyqtSignal()
    dismissed = QtCore.pyqtSignal()

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

        self._engine = TableGraphEngine()
        self._segmenter = TableSegmenter(engine=self._engine)

        self._collection: Optional[ChartCollection] = None
        self._datasets: List[ParsedTableDataset] = []
        self._current_dataset_idx: int = 0
        self._current_chart: Optional[RenderedChart] = None
        self._compatible_types: List[ChartType] = []
        self._type_buttons: List[QtWidgets.QPushButton] = []
        self._target_hwnd: Optional[int] = None
        self._raw_table_text: str = ""
        self._toast: Optional[TableGraphToast] = None

        self._build_ui()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        card = QtWidgets.QFrame()
        card.setStyleSheet("QFrame { background:#0A0A0A; border:1px solid #333; border-radius:12px; }")
        layout = QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Header tag matching sentence forge
        self._header = QtWidgets.QLabel("// TABLE // GRAPH")
        self._header.setStyleSheet("color:#888; font: bold 9px Consolas; background:transparent;")
        layout.addWidget(self._header)

        # Main title strictly matching table heading
        self._target = QtWidgets.QLabel("DATASET PREVIEW")
        self._target.setWordWrap(True)
        self._target.setStyleSheet("color:#FFF; font: bold 14px Consolas; background:transparent;")
        layout.addWidget(self._target)

        # Dataset group bar (if table has multiple segmented headings)
        self._dataset_bar = QtWidgets.QFrame()
        self._dataset_bar.setStyleSheet("background:transparent; border:none;")
        self._dataset_bar_layout = QtWidgets.QHBoxLayout(self._dataset_bar)
        self._dataset_bar_layout.setContentsMargins(0, 0, 0, 0)
        self._dataset_bar_layout.setSpacing(6)
        layout.addWidget(self._dataset_bar)
        self._dataset_bar.hide()

        # Type switcher pill bar
        self._type_scroll = QtWidgets.QScrollArea()
        self._type_scroll.setFixedHeight(44)
        self._type_scroll.setWidgetResizable(True)
        self._type_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._type_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._type_scroll.setStyleSheet("QScrollArea { background:transparent; border:none; }")

        self._type_container = QtWidgets.QWidget()
        self._type_container.setStyleSheet("background:transparent;")
        self._type_layout = QtWidgets.QHBoxLayout(self._type_container)
        self._type_layout.setContentsMargins(0, 2, 0, 2)
        self._type_layout.setSpacing(6)
        self._type_scroll.setWidget(self._type_container)
        layout.addWidget(self._type_scroll)

        # Stacked display: Loading vs Chart vs Empty/Error
        self._stack = QtWidgets.QStackedWidget()
        self._stack.setStyleSheet("background:transparent; border:none;")

        # Loading page
        self._loading_page = QtWidgets.QLabel("MATRIX // VISUALIZER\n\n  [ .. ]  PARSING MATRIX & RENDERING FIGURE")
        self._loading_page.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._loading_page.setStyleSheet("color:#DDD; font: bold 11px Consolas; background:transparent;")
        self._stack.addWidget(self._loading_page)

        # Chart preview page
        self._chart_page = QtWidgets.QWidget()
        chart_page_layout = QtWidgets.QVBoxLayout(self._chart_page)
        chart_page_layout.setContentsMargins(0, 0, 0, 0)
        chart_page_layout.setSpacing(6)

        self._image_frame = QtWidgets.QFrame()
        self._image_frame.setStyleSheet("QFrame { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:8px; }")
        img_layout = QtWidgets.QVBoxLayout(self._image_frame)
        img_layout.setContentsMargins(6, 6, 6, 6)

        self._image_label = QtWidgets.QLabel()
        self._image_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._image_label.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self._image_label.setStyleSheet("background:transparent; border:none;")
        img_layout.addWidget(self._image_label)
        chart_page_layout.addWidget(self._image_frame, 1)

        # Meta detail strip
        self._meta_label = QtWidgets.QLabel("READY")
        self._meta_label.setStyleSheet("color:#888; font:9px Consolas; background:transparent;")
        chart_page_layout.addWidget(self._meta_label)

        # Prominent single action button: Copy to Clipboard across all formats
        self._copy_button = QtWidgets.QPushButton("📋  COPY TO CLIPBOARD  [ENTER]")
        self._copy_button.setMinimumHeight(40)
        self._copy_button.setCursor(QtGui.QCursor(QtCore.Qt.CursorShape.PointingHandCursor))
        self._copy_button.setStyleSheet(
            "QPushButton { color:#000000; background:#FFFFFF; border:1px solid #FFFFFF; border-radius:7px; font: bold 11px Consolas; padding:8px; }"
            "QPushButton:hover { background:#E2E8F0; }"
            "QPushButton:pressed { background:#CBD5E1; }"
        )
        self._copy_button.clicked.connect(self.paste_chart_below_table)
        chart_page_layout.addWidget(self._copy_button)

        # Maintain aliases for programmatic / test compatibility
        self._paste_button = self._copy_button
        self._paste_both_button = self._copy_button

        self._stack.addWidget(self._chart_page)

        # Error / Empty page
        self._error_page = QtWidgets.QLabel("NO COMPATIBLE TABULAR DATA DETECTED\n\nSelect a valid table and press Ctrl + Shift + G")
        self._error_page.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._error_page.setStyleSheet("color:#888; font: 10px Consolas; background:transparent;")
        self._stack.addWidget(self._error_page)

        layout.addWidget(self._stack, 1)

        # Footer guidance
        self._footer = QtWidgets.QLabel("[ENTER] COPY TO CLIPBOARD   [1-9 / TAB] CHANGE CHART   [←/→] DATASETS   [ESC] CANCEL")
        self._footer.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._footer.setStyleSheet("color:#666; font:8px Consolas; background:transparent;")
        layout.addWidget(self._footer)

        root.addWidget(card)

    def position_on_right_edge(self):
        """Positions overlay neatly along the right display edge of active screen."""
        cursor_pos = QtGui.QCursor.pos()
        screen_obj = QtGui.QGuiApplication.screenAt(cursor_pos) or QtGui.QGuiApplication.primaryScreen()
        screen = screen_obj.availableGeometry() if screen_obj else QtCore.QRect(0, 0, 1920, 1080)
        width, height = 540, 580
        width = min(width, screen.width() - 32)
        height = min(height, screen.height() - 32)
        self.setGeometry(
            screen.x() + screen.width() - width - 16,
            screen.y() + (screen.height() - height) // 2,
            width,
            height,
        )

    def show_loading(self, table_title: Optional[str] = None):
        """Displays loading view."""
        title_text = table_title or "EXTRACTING DATA MATRIX"
        self._target.setText(f'VISUALIZE  |  "{title_text[:60]}"')
        self._stack.setCurrentWidget(self._loading_page)
        self._footer.setText("RENDERING SCIENTIFIC FIGURE   [ESC] CANCEL")
        self.position_on_right_edge()
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def _show_toast(self, message: str, hint: str = ""):
        """Displays non-intrusive floating feedback toast."""
        try:
            if self._toast is None:
                self._toast = TableGraphToast()
            self._toast.show_toast(message, hint)
        except Exception as exc:
            log.debug("Toast notice: %s", exc)

    def show_table(self, raw_table_text: str, target_hwnd: Optional[int] = None):
        """Segments raw table text, selects compatible charts, and displays the UI."""
        if not raw_table_text or not raw_table_text.strip():
            self.show_error("Empty selection")
            return

        self._raw_table_text = raw_table_text
        self._target_hwnd = target_hwnd
        if self._target_hwnd is None and sys.platform == "win32":
            try:
                fg = ctypes.windll.user32.GetForegroundWindow()
                if fg and fg != int(self.winId()):
                    self._target_hwnd = fg
            except Exception:
                pass

        self.show_loading()
        try:
            segmented_datasets = self._segmenter.segment_table(raw_table_text)
            if not segmented_datasets:
                ds = self._engine.parse_tabular_data(raw_table_text)
                segmented_datasets = [ds] if ds.columns else []

            if not segmented_datasets:
                self.show_error("No tabular structure found")
                return

            self._datasets = segmented_datasets
            self._current_dataset_idx = 0
            self._display_dataset(0)
        except Exception as exc:
            log.error("Failed to render table graph: %s", exc)
            self.show_error(str(exc))

    def show_chart(self, chart: RenderedChart):
        """Displays an already rendered chart."""
        self._datasets = [chart.dataset]
        self._current_dataset_idx = 0
        self._current_chart = chart
        self._render_current_chart()

    def show_error(self, message: str):
        """Displays error or fallback notice."""
        self._target.setText("NO TABULAR DATA DETECTED")
        self._error_page.setText(f"TABLE PARSE ERROR:\n\n{message}\n\n[ESC] Dismiss")
        self._stack.setCurrentWidget(self._error_page)
        self._footer.setText("[ESC] CANCEL")
        self.position_on_right_edge()
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _display_dataset(self, dataset_idx: int):
        """Loads and displays dataset at specified index."""
        if dataset_idx < 0 or dataset_idx >= len(self._datasets):
            return

        self._current_dataset_idx = dataset_idx
        ds = self._datasets[dataset_idx]

        # Strictly extract and clean heading
        heading = getattr(ds, "group_name", None) or (ds.columns[0] if ds.columns else "Tabular Data")
        clean_heading = str(heading).strip()
        self._target.setText(clean_heading)

        # Render dataset buttons if multiple datasets exist
        self._update_dataset_buttons()

        # Generate primary chart for this dataset with clean white theme
        style = ChartStyleConfig(dark_mode=False, figure_size=(6.2, 3.8), title=clean_heading)
        self._current_chart = self._engine.generate_chart(ds, chart_type=ds.suggested_chart_type, style=style)
        self._render_current_chart()

    def _update_dataset_buttons(self):
        """Populates dataset group tabs if multiple segmented datasets exist."""
        # Clear existing
        while self._dataset_bar_layout.count():
            item = self._dataset_bar_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if len(self._datasets) <= 1:
            self._dataset_bar.hide()
            return

        self._dataset_bar.show()
        for idx, ds in enumerate(self._datasets):
            name = getattr(ds, "group_name", None) or f"Table {idx+1}"
            btn = QtWidgets.QPushButton(f"[{idx+1}] {name[:16]}")
            is_active = (idx == self._current_dataset_idx)
            btn.setStyleSheet(
                "QPushButton { color:#FFF; background:#222; border:1px solid #444; border-radius:5px; padding:3px 8px; font:9px Consolas; }"
                if is_active
                else "QPushButton { color:#888; background:#111; border:1px solid #222; border-radius:5px; padding:3px 8px; font:9px Consolas; } QPushButton:hover { color:#FFF; background:#1E1E1E; }"
            )
            btn.clicked.connect(lambda checked=False, i=idx: self._display_dataset(i))
            self._dataset_bar_layout.addWidget(btn)

    def _render_current_chart(self):
        """Updates the type bar and displays the rendered chart pixmap."""
        if not self._current_chart:
            return

        ds = self._current_chart.dataset
        current_type = self._current_chart.chart_type

        # Strictly determine compatible types for this dataset
        self._compatible_types = get_compatible_chart_types(ds)
        if current_type not in self._compatible_types:
            self._compatible_types.insert(0, current_type)

        # Populate type switcher buttons
        self._update_type_buttons(current_type)

        # Render PNG image onto label with high-DPI awareness
        pixmap = QtGui.QPixmap()
        pixmap.loadFromData(self._current_chart.png_bytes, "PNG")
        if not pixmap.isNull():
            dpr = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else float(self.devicePixelRatio())
            dpr = max(1.0, dpr)
            target_w = int(500 * dpr)
            target_h = int(320 * dpr)
            scaled = pixmap.scaled(
                QtCore.QSize(target_w, target_h),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(dpr)
            self._image_label.setPixmap(scaled)

        # Update metadata info
        n_rows = len(ds.rows)
        n_cols = len(ds.columns)
        conf = int(getattr(ds, "confidence_score", 1.0) * 100)
        self._meta_label.setText(
            f"SHAPE: {n_rows} ROWS × {n_cols} COLS  |  MATCH CONFIDENCE: {conf}%  |  FORMAT: {ds.format_detected}"
        )

        self._stack.setCurrentWidget(self._chart_page)
        self._footer.setText("[1-9 / TAB] SELECT CHART   [←/→] DATASETS   [ENTER] COPY IMAGE   [ESC] CANCEL")
        self.position_on_right_edge()
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def _update_type_buttons(self, current_type: ChartType):
        """Draws compatible chart type pills matching RewordOverlay's button style."""
        while self._type_layout.count():
            item = self._type_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._type_buttons = []
        for idx, t in enumerate(self._compatible_types[:9]):
            icon_label = CHART_ICONS.get(t, t.value.replace("_", " "))
            label_text = f"[{idx+1}] {icon_label}"
            btn = QtWidgets.QPushButton(label_text)
            btn.setFixedHeight(28)
            is_active = (t == current_type)
            btn.setStyleSheet(
                "QPushButton { color:#000; background:#FFF; border:1px solid #FFF; border-radius:6px; padding:2px 8px; font: bold 9px Consolas; }"
                if is_active
                else "QPushButton { color:#DDD; background:#111; border:1px solid #333; border-radius:6px; padding:2px 8px; font:9px Consolas; } QPushButton:hover { background:#333; color:#FFF; }"
            )
            btn.clicked.connect(lambda checked=False, target_t=t: self.switch_chart_type(target_t))
            self._type_layout.addWidget(btn)
            self._type_buttons.append(btn)

    def switch_chart_type(self, target_type: ChartType):
        """Switches chart type with sub-40ms re-rendering."""
        if not self._current_chart:
            return
        if self._current_chart.chart_type == target_type:
            return

        try:
            self._current_chart = self._engine.toggle_chart_type(self._current_chart, target_type)
            self._render_current_chart()
            self.chart_selected.emit(target_type.value)
        except Exception as exc:
            log.error("Failed to toggle chart type: %s", exc)

    def cycle_chart_type(self, forward: bool = True):
        """Cycles to next or previous compatible chart type."""
        if not self._compatible_types or not self._current_chart:
            return
        try:
            idx = self._compatible_types.index(self._current_chart.chart_type)
        except ValueError:
            idx = 0
        step = 1 if forward else -1
        next_idx = (idx + step) % len(self._compatible_types)
        self.switch_chart_type(self._compatible_types[next_idx])

    def cycle_dataset(self, forward: bool = True):
        """Navigates to next or previous table group."""
        if len(self._datasets) <= 1:
            return
        step = 1 if forward else -1
        next_idx = (self._current_dataset_idx + step) % len(self._datasets)
        self._display_dataset(next_idx)
        self.dataset_selected.emit(next_idx)

    def copy_chart_to_clipboard(self):
        """Copies rendered PNG figure directly to system clipboard across image, file, text, and rich HTML."""
        if not self._current_chart or not self._current_chart.png_bytes:
            return

        clipboard = QtGui.QGuiApplication.clipboard()
        if clipboard is None:
            return

        # 1. Save PNG bytes to temp file for file-based pasting (Slack, Discord, VSCode, Obsidian, etc.)
        chart_file = os.path.join(tempfile.gettempdir(), "research_assistant_chart.png")
        try:
            with open(chart_file, "wb") as f:
                f.write(self._current_chart.png_bytes)
        except Exception as exc:
            log.debug("Failed to write temp chart file: %s", exc)

        safe_url = chart_file.replace("\\", "/")
        title_str = getattr(self._current_chart, "group_name", None) or self._target.text() or "Chart"

        # 2. Build multi-format QMimeData
        mime = QtCore.QMimeData()

        # Format 1: QImage / CF_DIB / CF_BITMAP (Word, WordPad, Paint, Office)
        image = QtGui.QImage()
        image.loadFromData(self._current_chart.png_bytes, "PNG")
        if not image.isNull():
            # Set high-res print quality: 300 DPI = 11811 dots per meter
            image.setDotsPerMeterX(11811)
            image.setDotsPerMeterY(11811)
            mime.setImageData(image)

        # Format 2: CF_HDROP File Drop (Notion, Slack, Teams, Discord, Obsidian, GitHub)
        if os.path.exists(chart_file):
            mime.setUrls([QtCore.QUrl.fromLocalFile(chart_file)])

        # Format 3: CF_UNICODETEXT Markdown tag (Notepad, VSCode, Markdown editors, terminal)
        mime.setText(f"![{title_str}](file:///{safe_url})")

        # Format 4: HTML Format (Google Docs, web rich-text editors)
        try:
            b64 = base64.b64encode(self._current_chart.png_bytes).decode("ascii")
            mime.setHtml(f'<p><img src="data:image/png;base64,{b64}" alt="{title_str}" /></p>')
        except Exception:
            pass

        clipboard.setMimeData(mime)
        self._footer.setText("✓ COPIED FIGURE TO CLIPBOARD   [ESC] CANCEL")
        self.copy_requested.emit()

    def paste_chart_below_table(self):
        """Pastes the rendered chart figure immediately below the table on the active application."""
        if not self._current_chart:
            return

        target_hwnd = self._target_hwnd

        # 1. Place image onto system clipboard across all standard formats
        self.copy_chart_to_clipboard()

        # 2. Grant foreground activation permission before hiding
        if sys.platform == "win32" and target_hwnd:
            try:
                ctypes.windll.user32.AllowSetForegroundWindow(-1)
            except Exception:
                pass

        # 3. Hide overlay window
        self.hide()
        self.apply_requested.emit()

        # 4. Show instant non-intrusive floating confirmation toast
        self._show_toast(
            "✓ FIGURE COPIED TO CLIPBOARD",
            "Ready to paste with [Ctrl+V] into any application.",
        )

        # 5. Restore target application and paste below table
        self._perform_paste_below_table(target_hwnd)

    def paste_table_and_chart(self):
        """Pastes the table followed immediately by the rendered chart figure."""
        if not self._current_chart:
            return

        target_hwnd = self._target_hwnd

        # 1. Save PNG bytes to temp file
        chart_file = os.path.join(tempfile.gettempdir(), "research_assistant_chart.png")
        try:
            with open(chart_file, "wb") as f:
                f.write(self._current_chart.png_bytes)
        except Exception as exc:
            log.debug("Failed to write temp chart file: %s", exc)

        safe_url = chart_file.replace("\\", "/")
        title_str = getattr(self._current_chart, "group_name", None) or self._target.text() or "Chart"
        raw_table = (self._raw_table_text or "").strip()
        combined_text = f"{raw_table}\n\n![{title_str}](file:///{safe_url})\n"

        clipboard = QtGui.QGuiApplication.clipboard()
        if clipboard is not None:
            mime = QtCore.QMimeData()
            image = QtGui.QImage()
            image.loadFromData(self._current_chart.png_bytes, "PNG")
            if not image.isNull():
                mime.setImageData(image)
            if os.path.exists(chart_file):
                mime.setUrls([QtCore.QUrl.fromLocalFile(chart_file)])
            mime.setText(combined_text)
            try:
                b64 = base64.b64encode(self._current_chart.png_bytes).decode("ascii")
                mime.setHtml(f"<pre>{raw_table}</pre><br/><img src=\"data:image/png;base64,{b64}\" alt=\"{title_str}\"/>")
            except Exception:
                pass
            clipboard.setMimeData(mime)

        if sys.platform == "win32" and target_hwnd:
            try:
                ctypes.windll.user32.AllowSetForegroundWindow(-1)
            except Exception:
                pass

        self.hide()
        self.apply_requested.emit()

        self._show_toast(
            "✓ TABLE + GRAPH READY",
            "Pasting table & graph... Press [Ctrl+V] anytime in any app.",
        )

        self._perform_direct_paste(target_hwnd)

    def _perform_paste_below_table(self, target_hwnd: Optional[int] = None):
        """Restores target window focus, moves cursor below selected table, and sends paste chord."""
        if sys.platform != "win32":
            return

        def _worker():
            try:
                u32 = ctypes.windll.user32
                time.sleep(0.06)

                # 1. Restore target application window to foreground
                if target_hwnd and u32.IsWindow(target_hwnd):
                    try:
                        u32.AllowSetForegroundWindow(-1)
                    except Exception:
                        pass

                    # Tap Alt key to unlock Windows 10/11 foreground lock
                    VK_MENU = 0x12
                    KEYEVENTF_KEYUP = 0x0002
                    u32.keybd_event(VK_MENU, 0, 0, 0)
                    u32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
                    time.sleep(0.02)

                    # Restore if minimized
                    SW_RESTORE = 9
                    SW_SHOW = 5
                    if u32.IsIconic(target_hwnd):
                        u32.ShowWindow(target_hwnd, SW_RESTORE)
                    else:
                        u32.ShowWindow(target_hwnd, SW_SHOW)

                    # Attach thread input between current foreground thread and target thread
                    fore_hwnd = u32.GetForegroundWindow()
                    fore_tid = u32.GetWindowThreadProcessId(fore_hwnd, None)
                    target_tid = u32.GetWindowThreadProcessId(target_hwnd, None)
                    if fore_tid and target_tid and fore_tid != target_tid:
                        u32.AttachThreadInput(fore_tid, target_tid, True)
                        u32.BringWindowToTop(target_hwnd)
                        u32.SetForegroundWindow(target_hwnd)
                        u32.SetActiveWindow(target_hwnd)
                        u32.AttachThreadInput(fore_tid, target_tid, False)
                    else:
                        u32.BringWindowToTop(target_hwnd)
                        u32.SetForegroundWindow(target_hwnd)
                        u32.SetActiveWindow(target_hwnd)

                    try:
                        u32.SwitchToThisWindow(target_hwnd, True)
                    except Exception:
                        pass

                    time.sleep(0.12)

                # 2. Flush any stuck modifier keys (Shift, Ctrl, Alt, Win)
                for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C):
                    u32.keybd_event(vk, 0, 0x0002, 0)
                time.sleep(0.04)

                # 3. Send Right Arrow (extended key with scan code 77) to move cursor immediately after the selected table
                VK_RIGHT = 0x27
                KEYEVENTF_EXTENDEDKEY = 0x0001
                u32.keybd_event(VK_RIGHT, 77, KEYEVENTF_EXTENDEDKEY, 0)
                time.sleep(0.035)
                u32.keybd_event(VK_RIGHT, 77, KEYEVENTF_EXTENDEDKEY | 0x0002, 0)
                time.sleep(0.06)

                # 4. Send Enter to insert a clean new line below the table
                VK_RETURN = 0x0D
                u32.keybd_event(VK_RETURN, 28, 0, 0)
                time.sleep(0.035)
                u32.keybd_event(VK_RETURN, 28, 0x0002, 0)
                time.sleep(0.08)

                # 5. Send Ctrl + V to paste the chart figure
                VK_CONTROL = 0x11
                VK_KEY_V = 0x56
                u32.keybd_event(VK_CONTROL, 29, 0, 0)
                time.sleep(0.02)
                u32.keybd_event(VK_KEY_V, 47, 0, 0)
                time.sleep(0.04)
                u32.keybd_event(VK_KEY_V, 47, 0x0002, 0)
                time.sleep(0.02)
                u32.keybd_event(VK_CONTROL, 29, 0x0002, 0)
                time.sleep(0.05)

                log.info("Successfully pasted chart below table into HWND %s", target_hwnd)
            except Exception as exc:
                log.error("Failed to paste chart below table: %s", exc)

        threading.Thread(target=_worker, daemon=True).start()

    def _perform_direct_paste(self, target_hwnd: Optional[int] = None):
        """Restores target window focus and sends Ctrl + V directly."""
        if sys.platform != "win32":
            return

        def _worker():
            try:
                u32 = ctypes.windll.user32
                time.sleep(0.06)

                if target_hwnd and u32.IsWindow(target_hwnd):
                    try:
                        u32.AllowSetForegroundWindow(-1)
                    except Exception:
                        pass
                    VK_MENU = 0x12
                    KEYEVENTF_KEYUP = 0x0002
                    u32.keybd_event(VK_MENU, 0, 0, 0)
                    u32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
                    time.sleep(0.02)

                    SW_RESTORE = 9
                    SW_SHOW = 5
                    if u32.IsIconic(target_hwnd):
                        u32.ShowWindow(target_hwnd, SW_RESTORE)
                    else:
                        u32.ShowWindow(target_hwnd, SW_SHOW)

                    fore_hwnd = u32.GetForegroundWindow()
                    fore_tid = u32.GetWindowThreadProcessId(fore_hwnd, None)
                    target_tid = u32.GetWindowThreadProcessId(target_hwnd, None)
                    if fore_tid and target_tid and fore_tid != target_tid:
                        u32.AttachThreadInput(fore_tid, target_tid, True)
                        u32.BringWindowToTop(target_hwnd)
                        u32.SetForegroundWindow(target_hwnd)
                        u32.SetActiveWindow(target_hwnd)
                        u32.AttachThreadInput(fore_tid, target_tid, False)
                    else:
                        u32.BringWindowToTop(target_hwnd)
                        u32.SetForegroundWindow(target_hwnd)
                        u32.SetActiveWindow(target_hwnd)

                    try:
                        u32.SwitchToThisWindow(target_hwnd, True)
                    except Exception:
                        pass
                    time.sleep(0.12)

                for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C):
                    u32.keybd_event(vk, 0, 0x0002, 0)
                time.sleep(0.04)

                VK_CONTROL = 0x11
                VK_KEY_V = 0x56
                u32.keybd_event(VK_CONTROL, 29, 0, 0)
                time.sleep(0.02)
                u32.keybd_event(VK_KEY_V, 47, 0, 0)
                time.sleep(0.04)
                u32.keybd_event(VK_KEY_V, 47, 0x0002, 0)
                time.sleep(0.02)
                u32.keybd_event(VK_CONTROL, 29, 0x0002, 0)
                time.sleep(0.05)

                log.info("Successfully pasted table + chart directly into HWND %s", target_hwnd)
            except Exception as exc:
                log.error("Failed direct paste: %s", exc)

        threading.Thread(target=_worker, daemon=True).start()

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        key = event.key()
        if key == QtCore.Qt.Key.Key_Escape:
            self.hide()
            self.dismissed.emit()
            event.accept()
            return

        # Numeric shortcuts [1-9] for quick chart type selection
        num_keys = {
            QtCore.Qt.Key.Key_1: 0,
            QtCore.Qt.Key.Key_2: 1,
            QtCore.Qt.Key.Key_3: 2,
            QtCore.Qt.Key.Key_4: 3,
            QtCore.Qt.Key.Key_5: 4,
            QtCore.Qt.Key.Key_6: 5,
            QtCore.Qt.Key.Key_7: 6,
            QtCore.Qt.Key.Key_8: 7,
            QtCore.Qt.Key.Key_9: 8,
        }
        if key in num_keys:
            target_idx = num_keys[key]
            if target_idx < len(self._compatible_types):
                self.switch_chart_type(self._compatible_types[target_idx])
                event.accept()
                return

        # Tab / T cycles chart types
        if key in (QtCore.Qt.Key.Key_Tab, QtCore.Qt.Key.Key_T):
            self.cycle_chart_type(forward=True)
            event.accept()
            return

        # Backtab cycles chart types backwards
        if key == QtCore.Qt.Key.Key_Backtab:
            self.cycle_chart_type(forward=False)
            event.accept()
            return

        # Left / Right arrows navigate datasets
        if key == QtCore.Qt.Key.Key_Left:
            self.cycle_dataset(forward=False)
            event.accept()
            return
        if key == QtCore.Qt.Key.Key_Right:
            self.cycle_dataset(forward=True)
            event.accept()
            return

        # Enter or Return pastes chart below table (Shift+Enter pastes table + chart)
        if key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            if event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier:
                self.paste_table_and_chart()
            else:
                self.paste_chart_below_table()
            event.accept()
            return

        # C key copies to clipboard only
        if key == QtCore.Qt.Key.Key_C:
            self.copy_chart_to_clipboard()
            event.accept()
            return

        super().keyPressEvent(event)


class TableGraphOverlayBridge(QtCore.QObject):
    """Thread-safe signal bridge for cross-thread GUI invocation."""

    sig_show_table = QtCore.pyqtSignal([str], [str, object])
    sig_show_chart = QtCore.pyqtSignal(object)
    sig_show_loading = QtCore.pyqtSignal(str)
    sig_close = QtCore.pyqtSignal()
    chart_selected = QtCore.pyqtSignal(str)
    dataset_selected = QtCore.pyqtSignal(int)
    copy_requested = QtCore.pyqtSignal()
    apply_requested = QtCore.pyqtSignal()

    def __init__(self, overlay: TableGraphOverlay):
        super().__init__()
        self.overlay = overlay
        queued = QtCore.Qt.ConnectionType.QueuedConnection
        self.sig_show_table[str].connect(overlay.show_table, queued)
        self.sig_show_table[str, object].connect(overlay.show_table, queued)
        self.sig_show_chart.connect(overlay.show_chart, queued)
        self.sig_show_loading.connect(overlay.show_loading, queued)
        self.sig_close.connect(overlay.hide, queued)
        overlay.chart_selected.connect(self.chart_selected)
        overlay.dataset_selected.connect(self.dataset_selected)
        overlay.copy_requested.connect(self.copy_requested)
        overlay.apply_requested.connect(self.apply_requested)


_GLOBAL_TABLE_GRAPH_OVERLAY: Optional[TableGraphOverlay] = None
_GLOBAL_TABLE_GRAPH_BRIDGE: Optional[TableGraphOverlayBridge] = None


def get_table_graph_overlay_bridge() -> Optional[TableGraphOverlayBridge]:
    """Returns or creates the thread-safe TableGraphOverlayBridge singleton."""
    global _GLOBAL_TABLE_GRAPH_OVERLAY, _GLOBAL_TABLE_GRAPH_BRIDGE
    if _GLOBAL_TABLE_GRAPH_BRIDGE is None:
        app = QtWidgets.QApplication.instance()
        if app is None or QtCore.QThread.currentThread() != app.thread():
            return None
        _GLOBAL_TABLE_GRAPH_OVERLAY = TableGraphOverlay()
        _GLOBAL_TABLE_GRAPH_BRIDGE = TableGraphOverlayBridge(_GLOBAL_TABLE_GRAPH_OVERLAY)
    return _GLOBAL_TABLE_GRAPH_BRIDGE


def show_table_graph_overlay(raw_table_text: str) -> bool:
    """Convenience helper to display the overlay for a given tabular string."""
    bridge = get_table_graph_overlay_bridge()
    if bridge is None:
        return False
    bridge.sig_show_table.emit(raw_table_text)
    return True
