# Text Injector Documentation

## Module Overview
`text_injector` replaces selected text in any active document (Word, Google Docs, VS Code, LaTeX, Terminal) using a multi-tier fallback mechanism while preserving clipboard contents.

## File Structure
- `models.py`: Data classes (`InjectionTier`, `WindowMetadata`, `InjectionResult`).
- `injector.py`: Core injector implementation containing `TextInjector`, `flush_modifiers`, `inject_text_replacement`, `inject_rich_content`, and `revert_last_injection`.
- `tests/test_text_injector.py`: Unit test suite verifying clipboard preservation, tier prioritization, modifier flushing, and undo stack.

## API Reference

### `replace_hovered_word_with_text(replacement_text: str) -> bool`
Executes hardware mouse double-click at current cursor position, then types the replacement string at high speed using synthetic Unicode events.

### `backspace_and_type(backspace_count: int, new_text: str, char_delay_ms: float = 1.5) -> bool`
Synthesizes `VK_BACK` (0x08) `backspace_count` times to delete the previously inserted synonym characters, then immediately invokes `type_text_high_speed(new_text)` to inject the next candidate without double-clicking or deselecting the active document range.

### `double_click_at_cursor() -> None`
Synthesizes `MOUSEEVENTF_LEFTDOWN` and `MOUSEEVENTF_LEFTUP` twice at current cursor coordinates to select the word under the cursor.

### `type_text_high_speed(text: str, char_delay_ms: float = 1.5) -> bool`
Types out text at high speed via synthetic Unicode keystrokes (`KEYEVENTF_UNICODE`).

### `inject_text_replacement(replacement_text: str, window_context: Optional[WindowMetadata] = None, original_text: Optional[str] = None) -> InjectionResult`
Replaces the selected text in the active application window.
- **`replacement_text`**: The text to insert.
- **`window_context`**: Target window details (`WindowMetadata(name, title, category, pid)`).
- **`original_text`**: Optional pre-replacement text pushed to undo stack.
- **Returns**: `InjectionResult(success, strategy, latency_ms, clipboard_restored, error)`.

### `inject_rich_content(image_png_bytes: bytes, alt_text: str = "", window_context: Optional[WindowMetadata] = None) -> InjectionResult`
Injects rendered chart images or markdown image fallbacks into documents.

### `revert_last_injection() -> bool`
Restores the last overwritten text snapshot from the in-memory undo buffer.

### `flush_modifiers() -> None`
Releases physical `Ctrl`, `Shift`, `Alt`, and `Win` keys in the OS message queue.

## Usage Example

```python
from text_injector import inject_text_replacement, revert_last_injection, WindowMetadata

# Swap active selection with replacement
context = WindowMetadata(name="chrome.exe", category="browser")
result = inject_text_replacement(
    replacement_text="ubiquitous",
    window_context=context,
    original_text="omnipresent"
)

if result.success:
    print(f"Injected via {result.strategy} in {result.latency_ms:.1f}ms")

# Revert if user changes mind
# revert_last_injection()
```

## Running Tests
```bash
python -m pytest text_injector/tests/test_text_injector.py -v
```
