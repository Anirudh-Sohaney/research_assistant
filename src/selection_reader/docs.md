# Selection Reader Documentation

## Module Overview
`selection_reader` extracts selected/highlighted text from any foreground desktop window on Windows without simulating keyboard shortcuts (`Ctrl+C`) or modifying the system clipboard. It also performs cursor-targeted on-device OCR to detect the exact word currently hovered by the user's cursor, gating it strictly to ensure only words within the highlighted text are extracted.

## File Structure
- `models.py`: Defines data schemas `AppInfo`, `HoveredWordMatch`, and `SelectionPayload`.
- `ocr_hover.py`: Cursor position tracking, Windows native OCR execution (`winrt.windows.media.ocr`), 2D bounding-box pixel overlap calculations, collision resolution, and selection membership gating.
- `extractor.py`: Zero-clipboard selection extraction cascade (UIA `TextPattern`, Win32 `EM_GETSEL`, Word COM), foreground window inspection, and integration of Part A + Part B.
- `daemon.py`: Background HTTP server listening on port `8901` and global `Alt+O` hotkey listener.
- `test.py`: Interactive command-line test script.
- `tests/test_selection_reader.py`: Pytest unit and integration test suite covering 1-pixel overlap boundaries, conflict resolution, selection gating, and accessibility fallbacks.

## Architecture

```
[ Active Desktop Window ] 
       │
       ├─► Part A: Highlight Extraction Cascade
       │     ├─► Canvas Fast-Path (Google Docs, Sheets) -> Atomic Clipboard
       │     ├─► Tier 1: UI Automation (TextPattern.GetSelection)
       │     ├─► Tier 2: Win32 Edit Controls (EM_GETSEL)
       │     ├─► Tier 3: Microsoft Word COM (Word.Application.Selection.Text)
       │     ├─► Tier 4: Atomic Clipboard (Ctrl+C + RAM Restore)
       │     └─► Tier 5: Visual Native OCR Fallback (PDF viewers, images)
       │           │
       │           ▼
       │     selected_text
       │
       └─► Part B: OCR Cursor Hover Extraction
             ├─► GetCursorPos() -> (cx, cy)
             ├─► Native Windows OCR (winrt.windows.media.ocr) + Background Normalization
             ├─► 2D Overlap Area: max(0, min(x2)-max(x1)) * max(0, min(y2)-max(y1))
             │     ├─► Overlap >= 1 px ? (qualifies)
             │     └─► Conflict ? Highest overlap area wins (1-px difference breaks tie)
             ├─► Canonical Selection Gating & Alignment:
             │     ├─► Matches true token in selected_text (exact, clipped, or edit-dist <= 1)
             │     ├─► Yes -> hovered_word = canonical_token
             │     └─► No  -> hovered_word = None (cursor not on highlighted text)
             │
             ▼
     SelectionPayload(
         selected_text=...,
         hovered_word=...,
         cursor_position=...,
         overlap_pixels=...,
         app=AppInfo(...)
     )
```

## API Reference

### `extract_selection(cursor_pos: Optional[Tuple[int, int]] = None) -> Optional[SelectionPayload]`
Extracts highlighted text and resolves the hovered word at the cursor position.
- **Arguments**:
  - `cursor_pos`: Optional explicit `(x, y)` screen coordinates. If omitted, queries `GetCursorPos()`.
- **Returns**: A `SelectionPayload` if text is highlighted, or `None` if no text is selected.

### `resolve_hovered_word(cursor_pos: Tuple[int, int], selected_text: str) -> Optional[HoveredWordMatch]`
Determines the word hovered by the cursor using on-device OCR and strict selection gating.
- **Criteria**:
  - Requires $\ge 1$-pixel overlap between the cursor bounding box and OCR word bounding box.
  - Multi-candidate conflicts are resolved by greatest pixel overlap area.
  - Candidate word must be contained within `selected_text`. If the cursor is outside the highlighted text, returns `None`.

### `compute_pixel_overlap(box1: Tuple[int, int, int, int], box2: Tuple[int, int, int, int]) -> int`
Computes the exact rectangular intersection area in pixels between two bounding boxes `(x1, y1, x2, y2)`.

### `is_word_in_selection(word: str, selected_text: str) -> bool`
Returns `True` if `word` matches a word token in `selected_text` (case-insensitive, ignoring punctuation).

### `inspect_active_window() -> AppInfo`
Retrieves metadata about the currently active foreground window (`name`, `title`, `category`, `pid`).

### Data Models
```python
@dataclass
class HoveredWordMatch:
    word: str
    bounding_box: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    overlap_pixels: int
    is_part_of_selection: bool

@dataclass
class SelectionPayload:
    selected_text: str
    app: AppInfo
    timestamp: str  # HH:MM:SS
    hovered_word: Optional[str] = None
    cursor_position: Optional[Tuple[int, int]] = None
    overlap_pixels: int = 0
    def to_dict(self) -> Dict[str, Any]: ...
```

## Running Tests & Usage

### Running Unit Tests
```bash
python -m pytest selection_reader/tests/test_selection_reader.py -v
```

### Direct Programmatic Usage
```python
from selection_reader import extract_selection, inspect_active_window

app_info = inspect_active_window()
print(f"Active App: {app_info.name} ({app_info.category})")

payload = extract_selection()
if payload:
    print(f"Selected Text: '{payload.selected_text}'")
    if payload.hovered_word:
        print(f"Hovered Word: '{payload.hovered_word}' (overlap: {payload.overlap_pixels}px)")
    else:
        print("Cursor is not hovering on a word in the selection.")
```
