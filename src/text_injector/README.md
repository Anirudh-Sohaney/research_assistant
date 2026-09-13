# Text Injector Subsystem

## 1. Final Deliverable
A multi-tier universal text and rich content output actuator (`text_injector`) providing:
- In-place replacement of active selections across Microsoft Word, Google Docs, LaTeX editors (Overleaf, TeXstudio, VS Code), and terminals (`inject_text_replacement()`).
- Instant hardware mouse double-click selection at cursor position (`double_click_at_cursor()`).
- High-speed synthetic Unicode typing actuator (`type_text_high_speed()`).
- Atomic hovered word replacement (`replace_hovered_word_with_text()`).
- High-speed backspace character deletion and replacement typing for synonym cycling (`backspace_and_type()`).
- Rich media / chart image injection with markdown fallbacks (`inject_rich_content()`).
- Undo history stack allowing instant reversion of reworded or substituted text (`revert_last_injection()`).
- Atomic clipboard preservation with 100% restoration guarantee.
- Modifier key flush mechanism preventing stuck `Ctrl`/`Shift`/`Alt`/`Win` shortcut states.

## 2. Algorithm Used
**Tiered Universal Output & Typing Hierarchy**:
1. **Modifier Key Flush**: Synthesizes `KeyUp` events for `VK_CONTROL`, `VK_SHIFT`, `VK_MENU` (Alt), and `VK_LWIN`/`VK_RWIN` to clear chord states.
2. **Instant Mouse Double-Click Selection**:
   - Synthesizes `MOUSEEVENTF_LEFTDOWN` and `MOUSEEVENTF_LEFTUP` twice (20ms interval) to isolate the hovered word under the cursor.
3. **High-Speed Synthetic Unicode Typing**:
   - Streams Unicode character events directly into the OS queue via `KEYEVENTF_UNICODE` (1.5ms per character) to replace the selected word instantly.
4. **Tier 1 (Direct OS Accessibility / Win32 Edit)**:
   - For native Win32 Edit/RichEdit controls, sends `EM_REPLACESEL` (0x00C2) directly to the focused HWND, replacing selection with zero clipboard impact.
5. **Tier 2 (Atomic Clipboard + Contextual Paste Chord)**:
   - Buffers pre-existing clipboard contents in RAM, copies replacement, dispatches `Ctrl+V` or `Ctrl+Shift+V`, and restores original clipboard.
6. **Tier 3 (Synthetic Unicode Keystrokes)**:
   - Streams virtual unicode character events directly for arbitrary short strings.

## 3. Description
The `text_injector` subsystem acts as the universal writing actuator for the Research Aid Desktop Assistant. It executes in-place text rewrites, synonym swaps, and citation insertions into any active text editor without losing window focus, corrupting the author's private clipboard, or requiring manual copy-pasting.
