# Desktop Automation — Cross-Platform Compatibility Deep Dive

## The Problem

The research aid must work with ANY text editor on ANY platform. This means handling the differences between Windows, macOS, and Linux (X11 and Wayland). This document deep-dives into the desktop automation layer and how to achieve true cross-platform compatibility.

---

## 1. The Platform Matrix

| Capability | Windows | macOS | Linux X11 | Linux Wayland |
|------------|---------|-------|-----------|---------------|
| Screen capture | Direct3D11 | ScreenCaptureKit | XDG portals, Xlib | PipeWire |
| Text selection | UI Automation | AXAPI | X11 PRIMARY | wlr-data-control (partial) |
| Active window | Win32 API | NSWorkspace | EWMH | Limited (security) |
| Keyboard input | SendInput | CGEvent | Xlib/XTest | uinput (requires root) |
| Mouse input | SendInput | CGEvent | XTest | uinput (requires root) |
| Always-on-top | WS_EX_TOPMOST | NSPanel.floating | _NET_WM_STATE_ABOVE | wlr-layer-shell |
| Global hotkeys | RegisterHotKey | CGEvent tap | XGrabKey | Portals (limited) |
| Accessibility | UIA/MSAA | AXUIElement | AT-SPI2 | Limited |

**Key insight:** There is no single library that hides all platforms behind one function call without losing fidelity. Every cross-platform tool is "per-platform readers, one schema."

---

## 2. Accessibility APIs

### Windows: UI Automation (UIA)

**Technology:** COM (IUIAutomation)  
**Strengths:** Strongest typed model — fixed ControlType enums and Control Patterns. Can prefetch entire subtrees in one call.

**Key patterns for text injection:**
- `ValuePattern::SetValue` — set text in editable controls
- `ValuePattern::SetValue` via `IUIAutomationValuePattern`
- `TextPattern::RangeFromChild` — get text ranges

**Libraries:**
- `pywinauto` (Python, BSD) — Win32 + UIA backends, very mature
- `FlaUI` (C#/.NET, MIT) — Wraps UIA2/UIA3, strong for WPF/WinForms
- `win-text-inject` (Rust) — clipboard privacy, modifier sanitization

### macOS: AXUIElement

**Technology:** Mach IPC (Cocoa/CoreFoundation)  
**Requirement:** Accessibility TCC permission (user must grant in System Preferences)

**Key patterns:**
- `AXUIElementCopyAttributeValue` — read element attributes
- `AXUIElementSetAttributeValue` — write element attributes
- `AXSelectedText` — get/set selected text
- `AXINSERTTEXT` — insert text at cursor

**Libraries:**
- `atomacos` (Python, GPL-3.0) — raw AXUIElement exposure
- `xa11y` (Rust, MIT) — cross-platform abstraction

### Linux: AT-SPI2

**Technology:** D-Bus (`org.a11y.atspi`)  
**Strength:** Works with GTK/Qt apps  
**Weakness:** Chromium/Electron apps need `--force-renderer-accessibility` flag

**Libraries:**
- `dogtail` (Python, GPL-2.0) — AT-SPI2-based, exposes raw object model
- `xa11y` (Rust, MIT) — cross-platform abstraction

### xa11y — Cross-Platform Abstraction

**GitHub:** https://github.com/crowecawcaw/xa11y  
**License:** MIT  
**Languages:** Rust, Python, JavaScript

Playwright-style API for desktop accessibility:
- CSS-like selectors (`button[name='Submit']`, `textfield[name^='Search']`)
- Locators that re-resolve on every operation
- Auto-wait for elements
- Normalizes roles, actions, and queries across platforms

**Platform behavior:**
- Windows: `FindAllBuildCache` for fast subtree reads
- macOS: `AXUIElementCopyMultipleAttributeValues` for batch reads
- Linux AT-SPI2: per-property D-Bus calls (slowest)

**Limitation:** Cannot reach widgets that expose no accessibility data. The abstraction is shallow — role/property names are still platform-shaped.

---

## 3. The Chromium/Electron Caveat

On Linux and macOS, Chromium-based apps gate their accessibility tree behind launch flags:
- `--force-renderer-accessibility` — must be set at app launch
- Without it, `button.count()` returns 0 even though buttons are visible
- On macOS, the app must hold the Accessibility TCC permission

**For Google Docs specifically:** Chrome with the flag enabled exposes the Docs editing canvas as an accessible text field. Without the flag, the canvas is opaque. This is a significant limitation for "universal compatibility."

**Workaround:** For Chromium apps where accessibility fails, fall back to:
1. Screen capture + OCR (PaddleOCR)
2. Clipboard + paste for injection

---

## 4. Wayland — The Linux Problem

Wayland's security model blocks most automation tools. xdotool does not work.

### Successors to xdotool

**wdotool:**
- GitHub: https://github.com/cushycush/wdotool
- Uses libei (XDG RemoteDesktop portal), wlr-* protocols (Sway/Hyprland), KWin scripting (KDE), GNOME Shell extension
- Falls back to `/dev/uinput`
- Unicode type works fully on wlr-protocols

**ydotool:**
- GitHub: https://github.com/ReimuNotMoe/ydotool
- GPLv3 license
- Uses Linux kernel uinput module
- Works on anything that accepts keyboard/mouse input
- Requires root or udev rules

**dotool:**
- URL: https://sr.ht/~geb/dotool
- Reads actions from stdin, simulates via uinput
- Works on X11, Wayland, and TTYs

**kdotool:**
- GitHub: https://github.com/jinliu/kdotool
- KDE Plasma 5/6 (Wayland + X11)
- Uses KWin scripting API over D-Bus

### The Practical Wayland Strategy

For the research aid on Wayland:
1. **Text selection:** selection-hook with wlr-data-control protocol (partial support)
2. **Keyboard injection:** ydotool or dotool (requires udev rules or root)
3. **Overlay:** wlr-layer-shell for always-on-top panels
4. **Fallback:** clipboard + paste (most reliable on Wayland)

---

## 5. Application-Specific Handling

### Google Docs (Browser)

**Selection detection:** selection-hook works via browser accessibility tree or clipboard monitoring.

**Text injection:**
- Clipboard + Ctrl+V works reliably
- Direct typing via CGEvent/SendInput works
- Accessibility API insertion may not work (canvas-based editor)

**Keybind conflict:** Google Docs uses many Ctrl+ combinations. Choose keybinds that do not conflict (e.g., Ctrl+Shift+R instead of Ctrl+R).

### Microsoft Word

**Selection detection:** UIA exposes text ranges directly.

**Text injection:**
- UIA ValuePattern works for simple text
- Clipboard + Ctrl+V is most reliable
- Direct typing works but may trigger spell-check popup

### Notepad / TextEdit

**Selection detection:** UIA/AXAPI works (simple text controls).

**Text injection:** All methods work (simple controls). Clipboard + Ctrl+V is simplest.

### VS Code / IDEs

**Selection detection:** Works via accessibility tree (Electron-based, needs flag on Linux).

**Text injection:** Clipboard + Ctrl+V works. Direct typing works.

**Keybind conflict:** VS Code uses many keybinds. Choose unused combinations.

### Terminal / Command Line

**Selection detection:** Terminal selection is application-specific.

**Text injection:**
- Must use Ctrl+Shift+V (not Ctrl+V) for paste
- Direct typing may be intercepted by terminal emulator
- Accessibility API may not work

**For the research aid:** Detect terminal applications and switch paste chord automatically.

---

## 6. Application Detection

### Recommended: active-win / get-windows

Detects the active window's name, process, and path. Use this to:
1. Identify the application type (editor, browser, terminal, IDE)
2. Choose the appropriate paste chord (Ctrl+V vs Ctrl+Shift+V)
3. Choose the appropriate injection method (accessibility vs clipboard)
4. Adjust overlay positioning (terminal may need different offset)

### Application Type Heuristics

```python
def detect_app_type(window_info):
    name = window_info.name.lower()
    path = window_info.path.lower()

    if 'terminal' in name or 'iterm' in name or 'alacritty' in name:
        return 'terminal'
    elif 'code' in name or 'vscode' in path:
        return 'ide'
    elif 'chrome' in name or 'firefox' in name or 'safari' in name:
        return 'browser'
    elif 'word' in name or 'pages' in name or 'docs' in name:
        return 'word_processor'
    else:
        return 'text_editor'

def get_paste_chord(app_type):
    if app_type == 'terminal':
        return ['ctrl', 'shift', 'v']
    else:
        return ['ctrl', 'v']
```

---

## 7. The Universal Compatibility Strategy

Based on all research, the practical approach is:

### For Text Injection:
```
1. Detect target application type (active-win)
2. Try accessibility API insertion (fastest)
3. Fall back to clipboard + app-specific paste chord
4. Fall back to direct keyboard simulation
5. Fall back to clipboard-only (user pastes manually)
```

### For Text Reading:
```
1. Try selection-hook (cross-app text selection)
2. Fall back to clipboard monitoring (user copies text)
3. Fall back to screen capture + OCR (last resort)
```

### For Overlay Display:
```
1. Tauri transparent always-on-top window
2. Position near cursor/selection coordinates
3. Ensure stays on screen bounds
4. Click-through when not interacting
```

---

## Key Insights

1. **"Universal compatibility" means "fallback chain, not single API."** The tiered approach is what every successful cross-platform tool uses.

2. **Application detection is critical.** Different apps need different injection strategies. active-win provides the information needed to make these decisions.

3. **Wayland is the hardest platform.** The security model blocks most automation. ydotool/dotool work but require elevated privileges. Clipboard + paste is the most reliable approach.

4. **Chromium apps are problematic.** Google Docs, VS Code, and other Electron apps hide their accessibility trees behind flags. For these, OCR + clipboard injection is the fallback.

5. **Terminal apps need special handling.** They use Ctrl+Shift+V instead of Ctrl+V for paste. Some intercept direct keyboard input. Detection + chord switching is essential.

6. **The paste chord detection problem is solvable.** active-win tells you what app is focused. A simple heuristic map (terminal = Ctrl+Shift+V, everything else = Ctrl+V) handles 90% of cases.
