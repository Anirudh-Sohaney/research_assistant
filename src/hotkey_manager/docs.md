# Hotkey Manager Subsystem Documentation

## Overview
The `hotkey_manager` package enables global keyboard shortcut interception across any active desktop application. It guarantees low-latency key chord detection while protecting token budgets through a strict 350ms temporal debounce window.

---

## Architecture & Data Models

### `hotkey_manager.models`
- **`InterceptionMode`**: Enum specifying key consumption mode (`PASS_THROUGH`, `EXCLUSIVE_CONSUME`).
- **`HotkeyPressedEvent`**: Data model emitted when an authorized chord triggers.
  - `action`: Name of the triggered command (e.g., `"synonym"`, `"reword"`).
  - `chord`: The chord sequence pressed (e.g., `"<ctrl>+<shift>+s"`).
  - `timestamp`: Unix timestamp of the event.
- **`RegistrationResult`**:
  - `success`: Boolean indicating if registration succeeded.
  - `bound_chords`: Dictionary of currently active actions and chord mappings.
  - `conflicts`: List of conflicting chord strings.
- **`UnregistrationResult`**:
  - `released_count`: Number of shortcuts removed.
  - `remaining_count`: Number of active shortcuts retained.
- **`ListenerHandle`**:
  - `is_listening`: State of the background thread.
  - `backend`: Backend identifier (default `"pynput"`).

---

## API Reference

### `register_hotkeys(bindings=None, mode=InterceptionMode.PASS_THROUGH) -> RegistrationResult`
Registers a dictionary of action names to key combinations. Restarts the active listener if currently monitoring.

### `unregister_hotkeys(action_names=None) -> UnregistrationResult`
Unbinds specified actions or all actions if `action_names` is omitted.

### `listen_hotkey_stream(callback=None) -> ListenerHandle`
Starts the background listener thread and registers a callback invoked on `HotkeyPressedEvent`.

### `stop_listening() -> None`
Safely terminates background key hook threads.

---

## Usage Example

```python
from hotkey_manager.manager import (
    register_hotkeys,
    listen_hotkey_stream,
    stop_listening,
)
from hotkey_manager.models import HotkeyPressedEvent

def on_hotkey(event: HotkeyPressedEvent):
    print(f"Action triggered: {event.action} via {event.chord} at {event.timestamp}")

# Register custom or default shortcuts
register_hotkeys({"reword": "<ctrl>+<shift>+r", "synonym": "<ctrl>+<shift>+s"})

# Start listening
handle = listen_hotkey_stream(callback=on_hotkey)
print(f"Listening: {handle.is_listening}")

# Stop listening when done
stop_listening()
```

---

## Verification & Testing
Tests are located in `hotkey_manager/tests/test_hotkey_manager.py` and cover:
- Default binding registration and custom overrides.
- Specific and total unregistration.
- Rapid trigger suppression via 350ms debounce logic.
- Background listener thread startup and clean shutdown lifecycle.
