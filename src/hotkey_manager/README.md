# Hotkey Manager Subsystem

## 1. Final Deliverable
A cross-platform, non-blocking global hotkey monitoring subsystem (`hotkey_manager.manager.HotkeyManager`) providing:
- Dynamic key chord registration and unregistration (`register_hotkeys`, `unregister_hotkeys`).
- Real-time global keystroke interception and asynchronous event dispatching (`listen_hotkey_stream`, `stop_listening`).
- Token conservation through automatic 350ms temporal debouncing and physical key latching.
- Typed event data structures (`HotkeyPressedEvent`, `RegistrationResult`, `UnregistrationResult`, `ListenerHandle`).

## 2. Algorithm Used
- **Stateful Chord Debouncing & Latching**:
  1. Intercept global key combination triggers via OS-level hooks (`pynput.keyboard.GlobalHotKeys`).
  2. Compute monotonic time delta: $\Delta t = t_{now} - t_{last}$.
  3. If $\Delta t < \tau_{debounce}$ ($350\text{ ms}$), discard the trigger event to suppress hardware bounce, key repeats, and accidental multi-clicks.
  4. If $\Delta t \ge \tau_{debounce}$, update $t_{last} \leftarrow t_{now}$, construct a structured `HotkeyPressedEvent(action, chord, timestamp)`, and dispatch asynchronously to the subscriber callback.
- **Dynamic Hook Rebinding**:
  1. Acquire a thread lock around the internal chord dictionary.
  2. Safely terminate existing background listener threads.
  3. Instantiate a fresh listener mapping active key combinations to debounced action wrappers.

## 3. Description
The `hotkey_manager` subsystem acts as the global keyboard listener for the desktop companion. Operating silently across any foreground application (e.g., Microsoft Word, Google Docs, Overleaf, VS Code, or web browsers), it translates configured key chords into domain-specific actions (such as synonyms, definitions, graph generation, rewording, paper discovery, and evidence lookup). By enforcing a 350ms debounce window and key latching, it completely eliminates accidental duplicate triggers, protecting downstream LLM token budgets and system resources.
