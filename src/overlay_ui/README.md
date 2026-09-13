# Overlay UI Subsystem

## 1. Final Deliverable
A non-intrusive visual overlay management subsystem providing:
- **PyQt6 Sci-Fi Black & White Synonym Overlay** (`overlay_ui.pyqt_synonym_overlay.PyQtSynonymOverlay`):
  - Automatically pops up flush to the **right edge of the screen (centered vertically)** when <kbd>Alt</kbd> + <kbd>O</kbd> is triggered on highlighted text.
  - **Sci-Fi Animated Scanner & Pulsing Dots**: Minimalist, high-contrast monochrome loading indicator while candidates are fetched from OpenRouter / lexical models.
  - **Keyboard-Navigable Synonym Selection List**:
    - <kbd>Up</kbd> / <kbd>Down</kbd> arrow keys to navigate the generated list with crisp high-contrast inverted white selection pill.
    - <kbd>Enter</kbd> to apply the chosen candidate in-place into the active word processor / editor.
    - <kbd>Esc</kbd> to cancel and immediately dismiss the popup.
  - **Thread-Safe Cross-Thread Bridge** (`overlay_ui.pyqt_synonym_overlay.SynonymOverlayBridge`):
    - Must be initialized on the Qt GUI thread (the application entry point pre-warms it before hotkey listeners start).
    - Worker-thread requests are delivered through queued Qt signals, so widget operations remain on the GUI thread.
    - Connects background hotkey and inference threads to the Qt GUI thread via `pyqtSignal` queued connections.
- **Cursor-Anchored Popups** (`overlay_ui.overlay.OverlayUIManager`):
  - Floating popup card display anchored to active selection coordinates (`display_popup_card`).
  - Screen boundary clamping and vertical collision flipping (e.g. flipping above text when near bottom edge).
  - Dynamic, flicker-free content updating (`update_popup_content`).
  - Immediate and graceful popup dismissal (`dismiss_popup`).
  - Strongly typed card payload and event data models (`PopupCardPayload`, `PopupItem`, `ScreenRect`, `PopupHandle`, `PopupActionEvent`).

## 2. Algorithm Used
- **Right-Edge Centered Placement**:
  1. Query primary screen available geometry: `screen = QGuiApplication.primaryScreen().availableGeometry()`.
  2. Overlay width $w = 280\text{px}$, height $h = \min(440\text{px}, \text{screen.height} - 40)$.
  3. Calculate right edge position: $x = \text{screen.x} + \text{screen.width} - w - 16$.
  4. Calculate vertical center position: $y = \text{screen.y} + (\text{screen.height} - h) // 2$.
  5. Apply geometry: `overlay.setGeometry(x, y, w, h)`.
- **Monochrome Sci-Fi Animation**:
  1. `SciFiScanLine`: 25ms `QTimer` drives a smooth bi-directional gradient sweep beam (`QLinearGradient`) across a dark track.
  2. `SciFiLoadingWidget`: 350ms `QTimer` cycles monospace state indicators `● ○ ○` -> `○ ● ○` -> `○ ○ ●`.
- **Asynchronous Pipeline Transitions**:
  1. Trigger <kbd>Alt</kbd> + <kbd>O</kbd> -> emit `sig_show_loading(target_word)` -> widget displays loading card instantly.
  2. Background thread queries OpenRouter / dictionary -> on completion emits `sig_show_synonyms(target_word, candidate_words, on_apply)`.
  3. Stack widget switches to page 1 (`SciFiSynonymListWidget`) and focuses the list.
  4. Selection event (<kbd>Enter</kbd>) hides overlay and restores foreground focus to the editor to inject replacement text.
  5. The reusable overlay ignores accidental window-manager close events and can be shown again for the next request.

## 3. Description
The `overlay_ui` subsystem is the visual companion layer for the research assistant. It renders minimalist, black-and-white, sci-fi overlays and floating cards for lexical synonym replacement, definitions, paper recommendations, and summaries. Its clean, frameless, translucent aesthetic ensures zero distraction while authoring research papers in Word, Google Docs, VS Code, or LaTeX.
