# Overlay UI Subsystem Documentation

## Overview
The `overlay_ui` package provides cursor-anchored, non-intrusive floating card interfaces and the new **PyQt6 Sci-Fi Black & White Synonym Overlay**. It supports right-edge screen alignment, live loading animations, keyboard navigation, screen boundary collision detection, and instant hotkey-driven selection.

---

## Architecture & Components

### 1. PyQt6 Sci-Fi Synonym Overlay (`overlay_ui.pyqt_synonym_overlay`)
- **`PyQtSynonymOverlay`**:
  - Frameless, translucent, stay-on-top window (`WindowStaysOnTopHint | Tool | FramelessWindowHint`).
  - Flush to the **right edge of the screen (centered vertically)**.
  - Palette: Strictly monochrome black & white (`#0A0A0A` card background, `#333333` rounded borders, `#FFFFFF` text and active highlight).
  - Contains a `QStackedWidget` with 2 pages:
    - Page 0: `SciFiLoadingWidget` (animated sweep scanline and pulsing dots).
    - Page 1: `SciFiSynonymListWidget` (numbered candidate list).
- **`SciFiScanLine`**:
  - Bi-directional scanning beam widget with smooth gradient animation running on a 25ms timer.
- **`SciFiLoadingWidget`**:
  - Minimalist terminal-inspired loading state showing `TARGET » "<word>"`, pulsing dots, scanline, and `"ANALYZING CONTEXT"` status.
- **`SciFiSynonymListWidget`**:
  - High-contrast list widget displaying candidates formatted as `[01] candidate`.
  - Keyboard handlers:
    - <kbd>Up</kbd> / <kbd>Down</kbd>: Navigates selection.
    - <kbd>Enter</kbd> / <kbd>Return</kbd>: Emits `item_selected(word)` and triggers apply callback.
    - <kbd>Esc</kbd>: Immediately hides the window.
- **`SynonymOverlayBridge`**:
  - Thread-safe signal dispatcher (`sig_show_loading`, `sig_show_synonyms`, `sig_close`) enabling worker threads to command the Qt GUI thread seamlessly.

### 2. Cursor-Anchored Card Models (`overlay_ui.models`)
- **`CardType`**: Enum representing active card domains (`DEFINITION`, `SYNONYMS`, `EVIDENCE_STANCE`, `SIMILAR_PAPERS`, `SOURCE_SUMMARY`, `GRAPH_PREVIEW`).
- **`ScreenRect`**: Geometric structure representing coordinates (`x`, `y`, `width`, `height`).
- **`PopupItem`**: Represents an individual item within the card (`id`, `title`, `subtitle`, `badge`, `metadata`).
- **`PopupCardPayload`**: Full card structure passed to the renderer.
- **`PopupHandle`**: Active handle returned upon display (`window_id`, `is_visible`, `bounds`, `active_payload`).
- **`PopupActionEvent`**: Emitted event from user interactions (`select_item`, `dismiss`, `submit`).

---

## API Reference

### `get_synonym_overlay_bridge() -> Optional[SynonymOverlayBridge]`
Returns the global thread-safe bridge to control the PyQt6 Sci-Fi Synonym Overlay.

### `display_popup_card(payload: PopupCardPayload, anchor_bounds: ScreenRect, screen_size=None, on_action=None) -> PopupHandle`
Computes clamped coordinates and activates the floating popup card adjacent to the anchor rectangle.

### `update_popup_content(window_id: str, new_payload: PopupCardPayload) -> bool`
Updates the card payload of an existing active popup without flickering or repositioning.

### `dismiss_popup(window_id: str, immediate: bool = True) -> bool`
Dismisses and removes the popup window.

---

## Usage Example

```python
from PyQt6 import QtWidgets
from overlay_ui import get_synonym_overlay_bridge

# 1. Obtain bridge
bridge = get_synonym_overlay_bridge()

# 2. Show loading animation immediately when hotkey is pressed
bridge.sig_show_loading.emit("objective")

# 3. Populate with generated candidates and attach apply callback
def on_apply(chosen_word: str):
    print(f"User picked: {chosen_word}")

candidates = ["aim", "goal", "purpose", "target", "intention"]
bridge.sig_show_synonyms.emit("objective", candidates, on_apply)
```
