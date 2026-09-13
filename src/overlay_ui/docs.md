# Overlay UI Subsystem Documentation

## Overview
The `overlay_ui` package provides cursor-anchored, non-intrusive floating card interfaces. It supports progressive disclosure, multi-card navigation, screen boundary collision detection, and instant hotkey-driven selection.

---

## Architecture & Data Models

### `overlay_ui.models`
- **`CardType`**: Enum representing active card domains (`DEFINITION`, `SYNONYMS`, `EVIDENCE_STANCE`, `SIMILAR_PAPERS`, `SOURCE_SUMMARY`, `GRAPH_PREVIEW`).
- **`ScreenRect`**: Geometric structure representing coordinates (`x`, `y`, `width`, `height`).
- **`PopupItem`**: Represents an individual item within the card:
  - `id`: Unique identifier (e.g. synonym index or paper DOI).
  - `title`: Primary display label.
  - `subtitle`: Secondary metadata / explanation.
  - `badge`: Display badge (e.g., `"[1]"`).
  - `metadata`: Auxiliary payload data dictionary.
- **`PopupCardPayload`**: Full card structure passed to the renderer:
  - `card_type`: `CardType`.
  - `title`: Header text.
  - `items`: List of `PopupItem` objects.
  - `interactive_actions`: List of active shortcut actions.
  - `allow_user_prompts`: Flag enabling inline prompt input.
  - `custom_data`: Dictionary for auxiliary rendering data (e.g., plot data).
- **`PopupHandle`**: Active handle returned upon display:
  - `window_id`: String UUID of the window.
  - `is_visible`: Boolean visibility state.
  - `bounds`: Computed `ScreenRect`.
  - `active_payload`: Current `PopupCardPayload`.
- **`PopupActionEvent`**:
  - `window_id`: String ID of originating window.
  - `action`: Emitted action (e.g. `"select_item"`, `"dismiss"`, `"submit"`).
  - `item_id`: Optional target item identifier.
  - `text_input`: Optional text data.

---

## API Reference

### `display_popup_card(payload: PopupCardPayload, anchor_bounds: ScreenRect, screen_size=None, on_action=None) -> PopupHandle`
Computes clamped coordinates and activates the floating popup card adjacent to the anchor rectangle.

### `update_popup_content(window_id: str, new_payload: PopupCardPayload) -> bool`
Updates the card payload of an existing active popup without flickering or repositioning.

### `dismiss_popup(window_id: str, immediate: bool = True) -> bool`
Dismisses and removes the popup window.

### `calculate_clamped_bounds(anchor: ScreenRect, popup_width: int, popup_height: int, screen_width: int, screen_height: int) -> ScreenRect`
Computes optimal bounding box with collision detection and vertical flipping.

---

## Usage Example

```python
from overlay_ui import (
    CardType,
    OverlayUIManager,
    PopupCardPayload,
    PopupItem,
    ScreenRect,
    display_popup_card,
    dismiss_popup,
)

# Define items with hotkey badges
items = [
    PopupItem(id="syn_1", title="robust", badge="[1]"),
    PopupItem(id="syn_2", title="durable", badge="[2]"),
]
payload = PopupCardPayload(
    card_type=CardType.SYNONYMS,
    title="Select Synonym",
    items=items,
)

# Anchor at selection coordinates
anchor = ScreenRect(x=400, y=300, width=120, height=24)
handle = display_popup_card(payload, anchor)

print(f"Popup active at ({handle.bounds.x}, {handle.bounds.y}) with ID: {handle.window_id}")

# Dismiss when done
dismiss_popup(handle.window_id)
```

---

## Verification & Testing
Tests in `overlay_ui/tests/test_overlay_ui.py` verify:
- Placement below selection under normal conditions.
- Upward flipping when overflowing bottom screen margins.
- Horizontal clamping at right screen boundaries.
- Live content updating and dismissal lifecycle.
- Numeric keypress translation into selected item action events.
