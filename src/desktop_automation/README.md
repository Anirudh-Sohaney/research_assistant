# Desktop Automation Module

Cross-platform desktop automation for the Research Aid Desktop Assistant. Handles application detection, global hotkey registration, window management, and platform-specific API abstractions across Windows, macOS, Linux X11, and Linux Wayland.

## Function Signatures

### `detect_platform`

```python
def detect_platform() -> dict:
    """
    Detect the current OS, display server, and available automation capabilities.

    Returns:
        {
            "os": str,                          # "windows", "macos", "linux"
            "display_server": str | None,       # "x11", "wayland", "xwayland", None
            "accessibility_available": bool,    # True if a11y API is reachable
            "automation_level": str,            # "full", "partial", "restricted"
            "supported_methods": {
                "screen_capture": list[str],    # ["screencapturekit", "xdg_portal"]
                "text_injection": list[str],    # ["uia", "cgevent", "xtest", "uinput"]
                "window_detection": list[str],  # ["nsworkspace", "ewmh", "limited"]
                "hotkeys": list[str],           # ["cgevent_tap", "xgrabkey", "portals"]
                "always_on_top": list[str],     # ["nspanel", "ewmh", "wlr_layer_shell"]
            },
            "permissions": {
                "accessibility_granted": bool,  # macOS TCC
                "input_monitoring": bool,        # macOS Input Monitoring
                "root_available": bool,          # Linux uinput
            },
            "fallback_chain": list[str],        # Ordered list of fallback methods
            "platform_method": str,             # Recommended method string
        }
    """
```

### `register_hotkeys`

```python
def register_hotkeys(
    shortcut_map: dict,
    callback: callable | None = None,
    scope: str = "global",          # "global", "application"
    allow_conflicts: bool = False,
    register_paused: bool = False,
    restart_on_error: bool = True,
) -> dict:
    """
    Register global keyboard shortcuts.

    Args:
        shortcut_map: {"synonym": "ctrl+shift+s", "evidence": "ctrl+shift+e", ...}
        callback: Function called with (shortcut_id, keys_pressed)
        scope: "global" for system-wide, "application" for focused app only

    Returns:
        {
            "registered": dict[str, bool],      # {"synonym": True, "evidence": True}
            "failed_shortcuts": list[str],       # Shortcuts that failed to register
            "platform_method": str,             # Method used: "cgevent_tap", "xgrabkey", etc.
            "conflicts": list[str],             # Conflicting shortcut IDs (if detected)
            "error_messages": dict[str, str],   # Per-shortcut error details
            "requires_restart": bool,           # True if registration needs app restart
        }
    """
```

### `get_active_window`

```python
def get_active_window(
    include_browser_url: bool = True,
    include_bounds: bool = True,
    detect_app_type: bool = True,
    timeout_ms: int = 100,
) -> dict:
    """
    Get information about the currently focused window.

    Returns:
        {
            "title": str,
            "process_name": str,
            "pid": int,
            "bundle_id": str | None,       # macOS bundle ID
            "path": str,                   # Full executable path
            "bounds": {                    # Window geometry
                "x": int, "y": int,
                "width": int, "height": int,
            } | None,
            "is_browser": bool,
            "browser_url": str | None,
            "focused": bool,
            "app_type": str | None,        # "terminal", "ide", "browser", "word_processor", "text_editor"
            "paste_chord": list[str],       # ["ctrl", "v"] or ["ctrl", "shift", "v"]
            "injection_method": str,        # "clipboard_paste", "accessibility", "keyboard_simulation"
            "platform_info": dict,          # Platform-specific raw window data
        }
    """
```

### `manage_window`

```python
def manage_window(
    action: str,
    window_id: str | None = None,
    position: tuple[int, int] | None = None,
    size: tuple[int, int] | None = None,
    always_on_top: bool | None = None,
    title_pattern: str | None = None,
    process_name: str | None = None,
    include_bounds: bool = True,
    include_minimized: bool = False,
    respect_wayland_security: bool = True,
) -> dict:
    """
    Window management operations.

    Actions:
        "get_active"  - Get the currently focused window
        "list_all"    - List all visible windows (filtered by title_pattern/process_name)
        "position"    - Move window to (x, y)
        "resize"      - Resize window to (width, height)
        "focus"       - Bring window to foreground
        "minimize"    - Minimize window
        "maximize"    - Maximize window

    Returns:
        {
            "success": bool,
            "window_info": dict | None,    # WindowInfo dict (same schema as get_active_window)
            "error_message": str | None,
            "windows": list[dict] | None,  # For list_all action
            "platform_method": str,        # Method used on this platform
            "wayland_warning": str | None, # Set if operation degraded on Wayland
        }
    """
```

---

## Potential Solutions

### Window Detection

| Solution | License | Pros | Cons | When to Use |
|----------|---------|------|------|-------------|
| **active-win / get-windows** | MIT | Returns title, bounds, owner, PID, browser URL. Node.js native. | No Wayland on Linux. | Primary choice for app detection. |
| **focus-tracker** (Rust) | Apache-2.0 | Event-driven callbacks. Configurable polling. Ignore rules. | Rust-only. | Continuous monitoring with minimal CPU. |
| **PyWinCtl** | BSD-3-Clause | Built-in watchdog for focus changes. Window control included. | Python GIL affects high-frequency monitoring. | Python-first projects needing window control. |

**Recommendation:** active-win for detection, focus-tracker for event-driven monitoring, PyWinCtl for Python-native window control.

### Global Hotkeys

| Solution | License | Pros | Cons | When to Use |
|----------|---------|------|------|-------------|
| **pynput GlobalHotKeys** | LGPL-3.0 | Pure Python. Cross-platform. | License copyleft concerns. Limited to modifier+key combos. | Quick prototyping. |
| **Tauri global-shortcuts** | MIT | Built into Tauri v2. Native performance. | Tauri-only. | Production Tauri apps. |
| **XGrabKey** (Linux X11) | MIT/X11 | Direct Xlib. Zero dependencies. | X11 only. No Wayland. | Linux X11 native apps. |

**Recommendation:** Tauri plugin for production. pynput as Python fallback. XGrabKey for X11-only deployments.

### Accessibility APIs

| API | Platform | Library | License | Notes |
|-----|----------|---------|---------|-------|
| **UI Automation** | Windows | pywinauto (BSD), FlaUI (MIT) | — | Strongest typed model. COM-based. |
| **AXUIElement** | macOS | atomacos (GPL-3.0), xa11y (MIT) | — | Requires TCC permission. |
| **AT-SPI2** | Linux | dogtail (GPL-2.0), xa11y (MIT) | — | D-Bus. Chromium needs flag. |
| **xa11y** | Cross-platform | Rust, Python, JS | MIT | Playwright-style API. Shallow abstraction. |

**Recommendation:** xa11y for cross-platform abstraction where possible. Platform-native libraries for edge cases.

### Platform-Specific Automation

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

### Application-Specific Handling

| Application | Detection | Injection Strategy | Notes |
|-------------|-----------|-------------------|-------|
| **Google Docs** | Chrome + URL match | Clipboard + Ctrl+V | Canvas-based editor. Accessibility needs flag. |
| **Microsoft Word** | Process "WINWORD" | UIA ValuePattern or Ctrl+V | UIA exposes text ranges directly. |
| **VS Code** | Process "Code" or "electron" | Ctrl+V. Accessibility tree on macOS/Windows. | Electron. Linux needs `--force-renderer-accessibility`. |
| **Terminal** | Process name heuristic | Ctrl+Shift+V (not Ctrl+V) | Must detect terminal and switch paste chord. |
| **Notepad/TextEdit** | Process heuristic | Any method (simple controls) | Simple Win32/Cocoa text controls. |

---

## Alternatives and Issues

### Wayland Security Model

Wayland blocks most automation tools. `xdotool` does not work. Window detection returns limited information. Text injection requires elevated privileges or compositor-specific protocols.

**Strategy:**
1. Detect display server at startup via `XDG_SESSION_TYPE` and `WAYLAND_DISPLAY`
2. Fall back to ydotool/dotool (uinput, requires udev rules or root)
3. Clipboard + paste is the most reliable injection method on Wayland
4. wlr-layer-shell for overlay display on wlroots compositors

### Chromium/Electron Accessibility

On Linux and macOS, Chromium-based apps gate their accessibility tree behind launch flags:
- `--force-renderer-accessibility` must be set at app launch
- Without it, `button.count()` returns 0 even though buttons are visible
- Google Docs with the flag exposes the editing canvas as an accessible text field

**Fallback:** Screen capture + OCR (PaddleOCR) when accessibility fails.

### macOS Permissions

The Accessibility API requires TCC permission. Users must grant access in System Preferences > Privacy & Security > Accessibility. The Input Monitoring permission is required for keyboard/mouse simulation. Both trigger a system dialog on first use.

### Performance Targets

| Operation | Target | Strategy |
|-----------|--------|----------|
| Platform detection | <10ms | One-time call, cached |
| Hotkey registration | <50ms | Direct OS API |
| Active window detection | <20ms | Single OS call |
| Window management | <30ms | Direct OS API |
| App-type classification | <5ms | Heuristic string matching |

### Error Handling

All functions return structured dicts with `error_message` keys. Never crash the caller. Fallback chains:
- Window detection: active-win → PyWinCtl → None
- Hotkeys: Tauri plugin → pynput → XGrabKey → None
- Text injection: accessibility → clipboard+paste → keyboard simulation → None

---

## Codebase Structure

```
desktop_automation/
├── __init__.py               # Public API: detect_platform, register_hotkeys, etc.
├── platform_detector.py      # OS and display server detection
├── hotkey_manager.py         # Global shortcut registration with fallback chain
├── window_manager.py         # Window detection, positioning, and control
├── accessibility.py          # Platform-specific accessibility API abstraction
├── app_classifier.py         # Application type detection and paste chord selection
├── models.py                 # Data models (PlatformInfo, WindowInfo, HotkeyResult, etc.)
└── config.py                 # Configuration and platform defaults
```

### Module Responsibilities

| Module | Responsibility | Key Dependencies |
|--------|---------------|-----------------|
| `platform_detector.py` | Detect OS, display server, permissions, and available methods | `platform`, `sys`, `subprocess` |
| `hotkey_manager.py` | Register/unregister global shortcuts with per-platform fallbacks | Tauri plugin, pynput, Xlib |
| `window_manager.py` | Get active window, list windows, position/resize/focus | active-win, PyWinCtl, platform APIs |
| `accessibility.py` | Abstract UIA/AXAPI/AT-SPI2 behind unified interface | pywinauto, atomacos, dogtail, xa11y |
| `app_classifier.py` | Classify focused app type, select paste chord and injection method | Window info from `window_manager` |
| `models.py` | Typed dataclasses for all module interfaces | `dataclasses`, `typing` |
| `config.py` | Defaults, timeouts, fallback chains, platform overrides | — |

---

## Usage Examples

```python
from desktop_automation import (
    detect_platform,
    register_hotkeys,
    get_active_window,
    manage_window,
)

# Detect platform capabilities
platform = detect_platform()
print(platform["os"])                    # "linux"
print(platform["display_server"])        # "wayland"
print(platform["automation_level"])      # "restricted"

# Register hotkeys
result = register_hotkeys(
    shortcut_map={
        "synonym": "ctrl+shift+s",
        "evidence": "ctrl+shift+e",
        "reword": "ctrl+shift+r",
    },
    callback=lambda sid, keys: print(f"Pressed: {sid}"),
)
print(result["platform_method"])         # "portals"
print(result["failed_shortcuts"])        # []

# Get active window info
window = get_active_window()
print(window["app_type"])                # "browser"
print(window["paste_chord"])             # ["ctrl", "v"]
print(window["browser_url"])             # "https://docs.google.com/..."

# Position overlay near cursor
manage_window(
    action="position",
    window_id=window.get("window_id"),
    position=(460, 330),
)
```

---

## Sources

- active-win: https://github.com/sindresorhus/active-win
- focus-tracker: https://crates.io/crates/focus-tracker
- PyWinCtl: https://github.com/Kalmat/PyWinCtl
- pynput: https://github.com/moses-palmer/pynput
- xa11y: https://github.com/crowecawcaw/xa11y
- pywinauto: https://github.com/pywinauto/pywinauto
- FlaUI: https://github.com/FlaUI/FlaUI
- atomacos: https://github.com/nickvdyck/atomacos
- dogtail: https://github.com/dogtail/dogtail
- ydotool: https://github.com/ReimuNotMoe/ydotool
- wdotool: https://github.com/cushycush/wdotool
- dotool: https://sr.ht/~geb/dotool
- kdotool: https://github.com/jinliu/kdotool
- Tauri global-shortcuts: https://v2.tauri.app/plugin/global-shortcut/
