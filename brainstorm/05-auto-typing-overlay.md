# Text Injection and Overlay UI — Universal Compatibility

## The Problem

The research aid must "write directly into your screen" — inject text into any application (Google Docs, Notepad, Word, VS Code, etc.). It must also display results in a non-intrusive popup overlay. This is the hardest technical challenge: there is no single API that works everywhere.

---

## 1. Text Injection Strategies

### Strategy 1: Clipboard + Paste (Recommended Primary)

**How:** Copy text to clipboard, simulate Ctrl+V (or Cmd+V on macOS)

**Pros:**
- Works in ~95% of apps
- Handles Unicode/CJK
- Fast for long text
- Target app already knows how to handle paste

**Cons:**
- Overwrites user's clipboard (must save and restore)
- Race conditions with clipboard managers
- Some apps use Ctrl+Shift+V (terminals) or Shift+Insert
- Password fields may block paste

**Implementation:**
```python
import pyperclip
import pyautogui

def inject_text(text):
    # Save current clipboard
    original = pyperclip.paste()
    # Set new text
    pyperclip.copy(text)
    # Paste
    pyautogui.hotkey('ctrl', 'v')
    # Restore clipboard (after delay)
    time.sleep(0.1)
    pyperclip.copy(original)
```

### Strategy 2: Direct Keyboard Simulation

**How:** Send individual KEYEVENTF_UNICODE key events via OS API

**Pros:**
- Does not touch clipboard
- Works in password fields
- Works in some elevated contexts

**Cons:**
- Slow for long text (character-by-character)
- Can be blocked by anti-cheat/security tools
- IME interference on some systems

**Libraries:**
- `pynput` — cross-platform, `keyboard.type('Hello')`
- `xdotool` — Linux X11 only, `xdotool type 'Hello'`
- `ydotool` — Linux (any), uses kernel uinput
- `pyautogui` — cross-platform, `pyautogui.write('Hello')`

### Strategy 3: Accessibility API Text Insertion

**How:** Use UIA `ValuePattern::SetValue` (Windows), `AXSelectedText` (macOS), `EditableText.InsertText` (Linux AT-SPI)

**Pros:** Atomic, fast, no clipboard side effects  
**Cons:** Many apps do not expose ValuePattern. Chromium/Electron apps inconsistent. Cannot insert into all control types.

### Strategy 4: win-text-inject (Advanced Reference)

**GitHub:** https://github.com/emerson-d-lopes/win-text-inject  
**Platforms:** Windows

Key innovations:
- **Clipboard privacy formats:** Attaches opt-out formats to prevent clipboard history/cloud sync from capturing dictated text
- **Modifier sanitization:** Releases held modifier keys before synthesizing input
- **Integrity level checks:** Detects UIPI blocking for elevated windows
- **Delayed clipboard rendering:** Uses "promise" instead of data — Windows sends WM_RENDERFORMAT when consumer reads
- **Per-app paste chord selection:** Ctrl+Shift+V for terminals, Ctrl+V for others

### The Tiered Fallback Chain (Best Practice)

Based on real-world implementations (win-text-inject, micoracle, Athena Whisper, voicetype):

```
1. Try UIA/Accessibility API insertion (fastest, no side effects)
2. Fall back to clipboard + paste chord (Ctrl+V, Ctrl+Shift+V, or Shift+Insert)
3. Fall back to direct keyboard simulation (for paste-blocked contexts)
4. Fall back to clipboard-only (tell user to paste manually)
```

Each tier is chosen based on:
- Target app detection (terminal vs editor vs browser)
- Privilege level (elevated apps block SendInput)
- Platform (Windows/macOS/Linux need different backends)
- User's keyboard state (release held modifiers before injection)

---

## 2. Cross-Platform Keyboard Simulation

### pynput (Recommended)

**GitHub:** https://github.com/moses-palmer/pynput  
**License:** LGPL-3.0

Cross-platform (Windows, macOS, Linux). Monitors AND controls keyboard and mouse.

```python
from pynput.keyboard import Controller, Key
keyboard = Controller()
keyboard.type('Hello World')
keyboard.press(Key.ctrl_l)
keyboard.press('v')
keyboard.release('v')
keyboard.release(Key.ctrl_l)
```

**For the research aid:** Best single library for both hotkey listening and text typing.

### xdotool (Linux X11)

**GitHub:** https://github.com/jordansissel/xdotool  
**License:** GPL-2.0

```bash
xdotool type 'Hello World'
xdotool key ctrl+v
xdotool windowactivate <wid>
```

**Limitation:** X11 only. Does NOT work on Wayland.

### ydotool (Linux Any)

**GitHub:** https://github.com/ReimuNotMoe/ydotool  
**License:** GPLv3

Uses Linux kernel uinput. Works on Wayland, X11, TTY, framebuffer. Requires root or udev rules.

### dotool (Linux)

**URL:** https://sr.ht/~geb/dotool  
Reads commands from stdin, simulates input via uinput. Works on X11, Wayland, and TTYs.

### keyboard-auto-type (C/C++)

**GitHub:** https://github.com/antelle/keyboard-auto-type  
**License:** MIT

Cross-platform C++ library. Layout-aware text entry, emoji/CJK support, window information. Used by password managers.

---

## 3. Overlay/Popup UI Frameworks

### Tauri v2 (Recommended)

**GitHub:** https://github.com/tauri-apps/tauri  
**License:** MIT/Apache-2.0

Rust backend + web frontend (any framework). Bundle sizes ~5-10MB (vs Electron's ~150MB).

**Key features for overlay:**
- Transparent windows (`transparent: true`)
- Always-on-top (`setAlwaysOnTop(true)`)
- System tray (`tray-icon` feature)
- Global shortcuts (built-in plugin)
- Click-through windows
- Frameless windows

**Reference:** tauri-overlay-demo (https://github.com/sobol-sudo/tauri-overlay-demo) — working example of translucent always-on-top overlay with global shortcuts, click-through, and WebSocket streaming.

**For the research aid:** Best choice for the popup overlay. Tiny footprint, always-on-top overlay, system tray, global shortcuts all built-in.

### Electron (Alternative)

**GitHub:** https://github.com/electron/electron  
**License:** MIT

Full Chromium + Node.js. Mature system tray API. `BrowserWindow` supports `alwaysOnTop`, `transparent`, `frameless`.

**electron-tray-window:** Quick tray popup windows.

**Limitation:** Bundle size ~150MB+. High memory usage. Overkill for a lightweight writing tool.

### PyQt / PySide (Alternative)

Can create frameless, always-on-top, transparent widgets. `QSystemTrayIcon` for tray. Well-suited for Python-native overlays.

**Limitation:** GPL/commercial licensing for PyQt. Heavier than Tauri.

---

## 4. How Overlays Achieve "Always on Top"

| Platform | Mechanism |
|----------|-----------|
| macOS | NSPanel with `NSWindow.Level.floating` or `.statusBar`. Works across all Spaces. |
| Windows | `SetWindowPos(HWND_TOPMOST)` or `WS_EX_TOPMOST` extended style. |
| Linux X11 | `_NET_WM_STATE_ABOVE` via EWMH. Window-manager dependent. |
| Linux Wayland | `wlr-layer-shell` for panels/docks. Regular clients cannot guarantee always-on-top. |

**KoBar's Ghost Window Pattern:** A large transparent window (6000x4000px on Windows) enables free-floating positioning while maintaining always-on-top behavior. Mouse events are dynamically forwarded or ignored based on hover detection.

---

## 5. Global Hotkey Libraries

### pynput (Recommended)

**GitHub:** https://github.com/moses-palmer/pynput  
**License:** LGPL-3.0

Built-in `GlobalHotKeys` class for registering system-wide shortcuts.

```python
from pynput import keyboard

def on_activate():
    print('Hotkey pressed!')

with keyboard.GlobalHotKeys({
    '<ctrl>+<alt>+h': on_activate,
    '<ctrl>+<shift>+s': on_find_synonyms,
    '<ctrl>+<shift>+e': on_find_evidence,
    '<ctrl>+<shift>+r': on_reword,
}) as h:
    h.join()
```

### Tauri Global Shortcuts Plugin

Built into Tauri v2. Register shortcuts from both Rust and JS. No external dependency needed.

```typescript
import { register } from '@tauri-apps/plugin-global-shortcut';
await register('CommandOrControl+Shift+R', (event) => {
  if (event.state === 'Pressed') { triggerReword(); }
});
```

---

## 6. Cursor-Aware Positioning

The overlay popup should appear near the user's cursor or the selected text. To achieve this:

1. **selection-hook** returns screen coordinates of the selection
2. **Tauri window** positions itself at those coordinates (with offset)
3. **Window bounds** are checked to ensure popup stays on screen

**Pseudocode:**
```rust
fn position_popup(selection_coords: Rect) {
    let screen_bounds = get_monitor_bounds();
    let popup_size = (300, 200);

    let x = selection_coords.x + selection_coords.width + 10;
    let y = selection_coords.y;

    // Ensure popup stays on screen
    let x = x.min(screen_bounds.width - popup_size.0);
    let y = y.min(screen_bounds.height - popup_size.1);

    window.set_position(LogicalPosition::new(x, y));
}
```

---

## 7. The Dictation Pattern (Voice + Text Injection)

Most speech-to-text dictation tools follow the same injection pattern:

1. Capture target window handle at hotkey press (not injection time)
2. Record audio, transcribe with Whisper/Moonshine
3. Save clipboard, write text to clipboard, simulate paste chord, restore clipboard
4. Fallback chain: UIA ValuePattern, SendInput, clipboard paste

**For the research aid:** This pattern is identical for voice dictation, synonym insertion, paraphrase insertion, and evidence snippet insertion. The only difference is the text source (transcription vs. API response vs. model output).

---

## Key Insights

1. **There is no universal "inject text anywhere" API.** Every solution is a compromise. The best real-world tools use a fallback chain.

2. **Clipboard + paste is the 95% solution.** It is what clipboard managers, translation tools, and dictation apps all converge on.

3. **Accessibility APIs are powerful but incomplete.** They can read UI trees and interact with elements, but text insertion is limited to controls that expose the right patterns.

4. **Wayland broke the Linux automation model.** xdotool does not work. The successors (wdotool, ydotool, dotool) each have tradeoffs. There is no single "xdotool for Wayland."

5. **The overlay/popup problem is solved** by Tauri/Electron apps using platform-specific always-on-top mechanisms. Tauri v2 is the best choice for minimal footprint.

6. **Cross-platform desktop automation is fundamentally three engineering projects, not one.** The abstraction layers leak platform differences at the edges. The practical approach is "per-platform readers, one schema."
