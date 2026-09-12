# Text Injection Module

Cross-platform text injection into any application for the Research Aid Desktop Assistant. Handles clipboard management, paste chord detection per application, fallback chains for injection methods, keyboard simulation, and accessibility API integration.

## Function Signatures

### `inject_text`

```python
def inject_text(
    text: str,
    target_app: str | None = None,
    method: str = "auto",
    save_clipboard: bool = True,
    restore_clipboard: bool = True,
    paste_chord: list[str] | None = None,
    typing_speed: float = 0.01,
    retry_attempts: int = 3,
    fallback_chain: list[str] | None = None,
    timeout_ms: int = 5000,
    verify_injection: bool = True,
    handle_elevated: bool = True,
    ime_safe: bool = False,
    log_operations: bool = False,
) -> dict:
    """
    Inject text into the currently focused application using the best available method.

    Args:
        text: Text to inject (supports multiline, unicode, special characters).
        target_app: Application name hint (e.g., "terminal", "browser"). Auto-detect if None.
        method: Injection method - "auto", "clipboard", "keyboard", "accessibility", "clipboard_only".
        save_clipboard: Preserve current clipboard content before injection.
        restore_clipboard: Restore original clipboard content after injection.
        paste_chord: Custom paste key combination (e.g., ['ctrl', 'v']). Auto-detect if None.
        typing_speed: Delay between keystrokes for keyboard simulation (seconds).
        retry_attempts: Number of retry attempts on failure.
        fallback_chain: Ordered list of methods to try on failure.
        timeout_ms: Maximum time to wait for injection (milliseconds).
        verify_injection: Attempt to verify text was injected correctly.
        handle_elevated: Attempt to handle elevated/admin context injection.
        ime_safe: Disable IME during injection to prevent composition interference.
        log_operations: Enable detailed logging of injection steps.

    Returns:
        dict with keys:
            - success (bool): Whether text was injected successfully.
            - method_used (str): Method that succeeded ("clipboard", "keyboard", "accessibility").
            - injection_time_ms (float): Total injection latency in milliseconds.
            - app_detected (str | None): Detected application type.
            - app_name (str | None): Specific application name if detected.
            - error_message (str | None): Error description if failed.
            - clipboard_saved (bool): Whether original clipboard was preserved.
            - clipboard_restored (bool): Whether clipboard was restored after injection.
            - fallback_methods_tried (list[str]): List of methods attempted before success/failure.
            - verification_passed (bool | None): Injection verification result.
            - characters_injected (int): Number of characters injected.
            - special_characters_handled (int): Count of special characters processed.
    """
```

### `get_paste_chord`

```python
def get_paste_chord(
    app_type: str | None = None,
    platform: str | None = None,
    app_name: str | None = None,
) -> list[str]:
    """
    Return the paste key combination for the specified application context.

    Args:
        app_type: Application category ("terminal", "ide", "browser", "word_processor", "text_editor").
        platform: Operating system ("windows", "macos", "linux"). Auto-detect if None.
        app_name: Specific application name for custom chord mapping (e.g., "vim", "tmux").

    Returns:
        list[str]: Ordered key names for paste operation (e.g., ['ctrl', 'v'], ['ctrl', 'shift', 'v']).
            Returns standard paste chord for platform if no specific mapping found.
    """
```

### `detect_app_type`

```python
def detect_app_type(
    window_info: dict | None = None,
    use_accessibility: bool = True,
    fallback_to_process: bool = True,
) -> dict:
    """
    Detect the currently focused application type and details.

    Args:
        window_info: Pre-fetched window information dict. Fetch if None.
        use_accessibility: Use accessibility API for accurate detection.
        fallback_to_process: Fall back to process name detection if accessibility fails.

    Returns:
        dict with keys:
            - app_type (str): Category - "terminal", "ide", "browser", "word_processor", "text_editor", "other".
            - app_name (str): Application name (e.g., "Visual Studio Code", "Alacritty").
            - process_name (str): Process executable name (e.g., "code", "alacritty").
            - window_title (str): Current window title.
            - supports_paste (bool): Whether app supports standard paste operation.
            - paste_chord (list[str]): Detected paste key combination.
            - is_elevated (bool): Whether app is running with elevated privileges.
            - is_focusable (bool): Whether app can receive keyboard focus.
            - platform (str): Detected platform ("windows", "macos", "linux").
            - detection_method (str): How app was detected ("accessibility", "process", "title_pattern").
    """
```

### Additional Utility Functions

```python
def save_clipboard_state() -> dict:
    """
    Save current clipboard content and format.

    Returns:
        dict with keys:
            - content (str): Clipboard text content.
            - content_type (str): Content type ("text", "image", "mixed").
            - timestamp (float): Unix timestamp of save.
            - success (bool): Whether clipboard was read successfully.
    """

def restore_clipboard_state(state: dict) -> bool:
    """
    Restore previously saved clipboard state.

    Args:
        state: Dict returned by save_clipboard_state().

    Returns:
        bool: Whether restoration succeeded.
    """

def list_available_methods() -> list[dict]:
    """
    List all available injection methods on current platform.

    Returns:
        list[dict] with keys:
            - name (str): Method identifier.
            - available (bool): Whether method is available on this system.
            - license (str): License type.
            - reliability (float): 0.0-1.0 reliability score.
            - speed (str): Speed rating ("fast", "medium", "slow").
            - limitations (list[str]): Known limitations.
    """

def sanitize_for_injection(text: str, method: str = "clipboard") -> str:
    """
    Sanitize text content for safe injection.

    Handles special characters, newlines, Unicode normalization, and method-specific escaping.

    Args:
        text: Raw text to sanitize.
        method: Target injection method.

    Returns:
        str: Sanitized text ready for injection.
    """
```

## Potential Solutions

### Primary: Clipboard + Paste

| Library | License | Platform | Stars | Notes |
|---------|---------|----------|-------|-------|
| **pyperclip** | BSD-3 | Cross-platform | 1.5K+ | Simple clipboard API. Requires system clipboard tools. |
| **pyperclip + pyautogui** | BSD-3 + LGPL-3 | Cross-platform | Mixed | 95% universal coverage. Standard approach. |
| **clipboard** | MIT | Cross-platform | 500+ | Lightweight alternative to pyperclip. |

**Recommendation:** pyperclip for clipboard operations, pyautogui for paste simulation. Most reliable across applications.

### Keyboard Simulation

| Library | License | Platform | Stars | Notes |
|---------|---------|----------|-------|-------|
| **pynput** | LGPL-3.0 | Cross-platform | 1.8K+ | Full keyboard/mouse control. Cross-platform. |
| **pyautogui** | LGPL-3 | Cross-platform | 16K+ | Simple API. Includes keyboard + mouse + screen. |
| **xdotool** | GPL-2.0 | Linux X11 | 1K+ | X11 native. Fast. Requires X server. |
| **ydotool** | GPLv3 | Linux Wayland | 1K+ | Wayland successor to xdotool. Requires daemon. |
| **dotool** | MIT | Linux | 200+ | Minimal, works without root. Newer alternative. |
| **keyboard** | MIT | Cross-platform | 3.8K+ | Global hotkeys + simulation. May need root on Linux. |

**Recommendation:** pynput for cross-platform Python projects. xdotool/ydotool as platform-specific fallbacks on Linux.

### Accessibility APIs

| API | Platform | License | Notes |
|-----|----------|---------|-------|
| **pywinauto (UIA)** | Windows | BSD | UI Automation, ValuePattern for text fields. |
| **pyautogui + ctypes** | Windows | LGPL-3 | SendInput API for synthetic input. |
| **pyobjc (AXUIElement)** | macOS | PSF | Native accessibility. Requires macOS permissions. |
| **pyatspi2** | Linux | LGPL-2.1 | AT-SPI2 bindings. Works with screen readers. |
| **pylinuxwheel** | Linux | GPL | AT-SPI2 alternative. Less maintained. |

**Recommendation:** Use accessibility APIs as highest-reliability fallback for difficult injection scenarios (elevated apps, protected fields).

### Advanced Solutions

| Library | License | Platform | Notes |
|---------|---------|----------|-------|
| **win-text-inject** | MIT | Windows | Clipboard privacy, modifier sanitization. Niche. |
| **keyboard-auto-type** | MIT | Cross-platform | C/C++ native, fast. Keyboard layout aware. |
| **IronPython.WindowsAccess** | MIT | Windows | Windows API bindings for injection. |

### Tiered Fallback Chain

**Recommended order:**

1. **Accessibility API** (if available and app supports it) — Most reliable, direct programmatic control.
2. **Clipboard + Paste** — 95% universal, handles most applications.
3. **Keyboard Simulation** — Character-by-character typing. Slow but bypasses paste blocking.
4. **Clipboard Only** — Set clipboard without paste. User must manually paste.

```
┌─────────────────┐
│ Accessibility    │  Try first if available
└────────┬────────┘
         │ Fail
         ▼
┌─────────────────┐
│ Clipboard+Paste  │  Primary method (95% success)
└────────┬────────┘
         │ Fail
         ▼
┌─────────────────┐
│ Keyboard Sim     │  Slow fallback, bypasses paste blocks
└────────┬────────┘
         │ Fail
         ▼
┌─────────────────┐
│ Clipboard Only   │  Last resort, requires manual paste
└─────────────────┘
```

## Alternatives and Issues

### Clipboard Race Conditions

Clipboard managers (CopyQ, Ditto, ClipIt) may overwrite clipboard content between save and paste operations. Mitigation:

- Use `save_clipboard=True` with atomic read-paste-restore sequence.
- Minimize time between clipboard set and paste chord execution.
- Consider clipboard history managers that use clipboard hooks vs polling.

### Terminal Application Paste Chords

Terminal emulators often require `Ctrl+Shift+V` instead of `Ctrl+V`:

- **Needs `Ctrl+Shift+V`:** GNOME Terminal, Konsole, Alacritty, Kitty, WezTerm, iTerm2
- **Supports `Ctrl+V`:** Windows Terminal, older xterm

Use `get_paste_chord(app_type="terminal")` to handle automatically.

### Elevated Application Context

Applications running as administrator (Windows) or root (Linux/macOS) may reject injection from non-elevated processes:

- **Windows:** Use UIAccess manifest or run assistant as admin.
- **Linux:** Accessibility APIs may require same session/uid.
- **macOS:** Grant Accessibility permissions in System Preferences.

### IME Interference

Input Method Editors (Chinese, Japanese, Korean) may intercept keystrokes:

- Set `ime_safe=True` to temporarily disable IME during injection.
- Use clipboard method for CJK text to avoid composition issues.
- Some IMEs have global hotkeys that conflict with paste chords.

### Wayland Limitations (Linux)

Wayland restricts input injection for security:

- **xdotool** does not work on Wayland.
- **ydotool** requires `ydotoold` daemon running as root.
- **dotool** requires `/dev/uinput` access.
- **AT-SPI2** accessibility API works but limited to accessible apps.

**Recommendation:** Detect Wayland vs X11 at runtime. Use accessibility API on Wayland, xdotool on X11.

### Password Field Paste Blocking

Some password managers and secure fields block programmatic paste:

- Banks, password managers, browser autofill fields.
- May detect clipboard operations or synthetic input.
- **Workaround:** Keyboard simulation sometimes bypasses detection.
- **No universal solution:** Some fields are intentionally protected.

### Unicode and Special Characters

- Clipboard method handles Unicode natively.
- Keyboard simulation may fail with complex Unicode (emoji, CJK).
- Use clipboard injection for Unicode-heavy text.
- Sanitize control characters before injection.

### Multi-Monitor Focus Issues

- Focus may shift during injection on multi-monitor setups.
- Use `target_app` parameter to verify focus before injection.
- Consider window activation before injection.

## Sources

### Clipboard Libraries

| Tool | URL | License |
|------|-----|---------|
| pyperclip | https://github.com/asweigart/pyperclip | BSD-3 |
| clipboard | https://github.com/terryyin/clipboard | MIT |

### Keyboard Simulation

| Tool | URL | License |
|------|-----|---------|
| pynput | https://github.com/moses-palmer/pynput | LGPL-3.0 |
| pyautogui | https://github.com/asweigart/pyautogui | LGPL-3 |
| xdotool | https://github.com/jordansissel/xdotool | GPL-2.0 |
| ydotool | https://github.com/ReimuNotMoe/ydotool | GPLv3 |
| dotool | https://github.com/karlseguin/dotool | MIT |
| keyboard | https://github.com/boppreh/keyboard | MIT |

### Accessibility APIs

| Tool | URL | License |
|------|-----|---------|
| pywinauto | https://github.com/pywinauto/pywinauto | BSD |
| pyobjc | https://pyobjc.readthedocs.io/ | PSF |
| AT-SPI2 | https://wiki.linuxfoundation.org/accessibility/atspi | LGPL-2.1 |

### Advanced Solutions

| Tool | URL | License |
|------|-----|---------|
| win-text-inject | https://github.com/andyholmes/win-text-inject | MIT |
| keyboard-auto-type | https://github.com/nicktimko/keyboard-auto-type | MIT |

## File Structure

```
text_injection/
├── __init__.py
├── injector.py             # Main injection logic with fallback chain
├── clipboard_manager.py    # Clipboard save/restore
├── keyboard_simulator.py   # Cross-platform keyboard simulation
├── app_detector.py         # Application type detection
├── paste_chord.py          # Per-app paste chord mapping
├── accessibility_api.py    # Platform-specific accessibility APIs
├── models.py               # Data models (InjectionResult, AppInfo, etc.)
└── config.py               # Configuration
```

### Component Responsibilities

| File | Responsibility |
|------|----------------|
| `injector.py` | Orchestrates fallback chain, coordinates all components, provides `inject_text()` entry point. |
| `clipboard_manager.py` | Clipboard read/write with save/restore, handles multiple content types, race condition mitigation. |
| `keyboard_simulator.py` | Cross-platform keystroke simulation via pynput, xdotool, ydotool, dotool. Handles modifiers and timing. |
| `app_detector.py` | Window focus detection, process identification, application type classification. |
| `paste_chord.py` | Maps application types to paste key combinations, platform-aware defaults. |
| `accessibility_api.py` | Platform-specific accessibility API wrappers (UIA, AXUIElement, AT-SPI2). |
| `models.py` | Dataclasses for InjectionResult, AppInfo, ClipboardState, PasteChord. |
| `config.py` | Default configurations, fallback chains, timeout settings, app-specific overrides. |

## Usage Examples

### Basic Text Injection

```python
from text_injection import inject_text

# Auto-detect method and app
result = inject_text("Hello, World!")
print(result["success"])  # True
print(result["method_used"])  # "clipboard"
print(result["injection_time_ms"])  # 45.2
```

### Terminal-Aware Injection

```python
result = inject_text(
    text="ls -la /tmp",
    target_app="terminal",
    method="auto",
    save_clipboard=True,
    restore_clipboard=True,
)
# Automatically uses Ctrl+Shift+V for terminal emulators
```

### Custom Fallback Chain

```python
result = inject_text(
    text="Long text content...",
    fallback_chain=["accessibility", "clipboard", "keyboard"],
    retry_attempts=2,
    timeout_ms=3000,
)
if not result["success"]:
    print(f"Failed after trying: {result['fallback_methods_tried']}")
```

### Clipboard Management

```python
from text_injection import save_clipboard_state, restore_clipboard_state

# Save before operation
saved = save_clipboard_state()

# Perform injection
inject_text("replacement text")

# Restore original
restore_clipboard_state(saved)
```

### Application Detection

```python
from text_injection import detect_app_type, get_paste_chord

app = detect_app_type()
print(f"App: {app['app_name']} ({app['app_type']})")
print(f"Paste chord: {get_paste_chord(app['app_type'])}")
```

## Configuration

Default settings in `config.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `DEFAULT_METHOD` | `"auto"` | Primary injection method. |
| `DEFAULT_TIMEOUT_MS` | `5000` | Maximum injection wait time. |
| `DEFAULT_RETRY_ATTEMPTS` | `3` | Retry count on failure. |
| `DEFAULT_TYPING_SPEED` | `0.01` | Seconds between keystrokes. |
| `SAVE_CLIPBOARD` | `True` | Preserve clipboard by default. |
| `RESTORE_CLIPBOARD` | `True` | Restore clipboard after injection. |
| `VERIFY_INJECTION` | `True` | Verify injection success. |
| `IME_SAFE` | `False` | Disable IME during injection. |
| `FALLBACK_CHAIN` | `["clipboard", "keyboard", "clipboard_only"]` | Default method order. |

## Considerations

- **Platform Detection:** Runtime detection of Windows, macOS, Linux. Wayland vs X11 on Linux. Accessibility API availability.
- **Elevated Contexts:** Some applications require elevated privileges for injection. Handle via UIAccess (Windows) or accessibility permissions (macOS).
- **Timing:** Clipboard operations have ~10-50ms latency. Keyboard simulation scales with text length. Consider `timeout_ms` for large injections.
- **Security:** Password fields may block injection. Some applications detect synthetic input. No universal bypass for intentionally protected fields.
- **IME:** Input method editors can interfere with keyboard simulation. Use `ime_safe=True` for CJK environments.
- **Multilingual:** Clipboard method handles all Unicode. Keyboard simulation may fail with complex scripts. Fall back to clipboard for non-Latin text.
