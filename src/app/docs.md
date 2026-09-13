# App Subsystem (Master Orchestrator) Documentation

## Overview
The `app` module orchestrates all underlying subsystems into a cohesive background desktop assistant. It enforces token efficiency via a strict Two-Tier Processing Architecture: Tier 1 resolves frequent lexical and visualization tasks locally or through low-latency inference, while Tier 2 employs targeted RAG filtering and budgeted LLM generation.

---

## Architecture & Data Models

### `app.models`
- **`ActionTrigger`**: Enum of all user-triggered actions:
  - `FIND_SYNONYMS`: Contextual synonym lookup and right-edge Sci-Fi overlay presentation.
  - `FIND_DEFINITIONS`: Contextual definition and sense disambiguation.
  - `REWORD_TEXT`: Academic sentence/paragraph rewording.
  - `DISCOVER_PAPERS`: Literature recommendation and BibTeX retrieval.
  - `RETRIEVE_EVIDENCE`: Dual-stream literature stance verification.
  - `GENERATE_GRAPH`: In-place chart generation from tabular data.
  - `SUMMARIZE_SOURCE`: Codebase and dataset structural profiling.
- **`ShutdownReason`**: Reason for application termination (`USER_QUIT`, `OS_LOGOUT`, `FATAL_PANIC`).
- **`AppRuntimeContext`**:
  - `session_id`: Unique identifier for the active session.
  - `daemon_pid`: Operating system PID of the daemon supervisor.
  - `active_subsystems`: Dictionary tracking health of each component.
  - `hotkey_handle`: Active keyboard listener handle.
  - `daemon_status`: Status record from `daemon_service`.
  - `is_healthy`: True if all subsystems are operational.
  - `total_tokens_consumed`: Running counter of LLM tokens used.
- **`ActionResult`**:
  - `success`: Execution status flag.
  - `action`: Triggered `ActionTrigger`.
  - `latency_ms`: Total execution latency in milliseconds.
  - `tokens_used`: Number of LLM tokens consumed (0 for Tier 1).
  - `tier`: Architectural tier (`"TIER_1_LOCAL"` or `"TIER_2_HYBRID"`).
  - `output_summary`: User-facing summary text.
  - `ui_handle_id`: Optional identifier of active floating card or overlay.
  - `injected`: True if text was directly replaced in the editor.
  - `data`: Raw data payload returned by the underlying engine.
- **`AppExitReport`**:
  - `success`: Shutdown confirmation flag.
  - `reason`: `ShutdownReason`.
  - `subsystems_stopped`: List of cleanly terminated subsystems.
  - `elapsed_ms`: Shutdown duration in milliseconds.

---

## API Reference

### `init_application(config_path: Optional[str] = None) -> AppRuntimeContext`
Initializes the daemon supervisor, hotkey manager, and all subsystems, returning the active runtime context.

### `dispatch_action_pipeline(action: ActionTrigger, context: SelectionPayload, anchor_rect: Optional[ScreenRect] = None) -> ActionResult`
Ingests selected text and hovered word, triggers the PyQt6 Sci-Fi right-edge overlay in loading state, asynchronously populates candidates, and attaches the apply callback. The overlay bridge is initialized on the GUI thread and receives worker results through queued signals so the popup remains visible instead of flashing away.

### `apply_chosen_synonym(chosen_word: str, target_word: str, original_text: str, cursor_pos: Optional[Tuple[int, int]] = None, target_hwnd: Optional[int] = None, is_hovered: bool = False) -> str`
Formats the selected replacement with original casing and trailing space, refocuses the original document window, and replaces text in-place.

### `shutdown_application(reason: ShutdownReason = ShutdownReason.USER_QUIT, timeout_ms: int = 3000) -> AppExitReport`
Safely stops keyboard listeners, closes the PyQt overlay and floating cards, and terminates daemon services.

### Interactive full reword (`Alt` + `P`)
The hotkey opens a PyQt mode picker for **Reword**, **Add Detail**, and **Simplify**. The selected text is sent to OpenRouter/Ling with the corresponding editorial instruction. The generated replacement is previewed in the popup; <kbd>Enter</kbd> injects it into the original editor selection, <kbd>R</kbd> requests a fresh generation, and <kbd>Esc</kbd> cancels.

### Multi-judge paper analysis (`Alt` + `J`)
The hotkey sends the complete selection to eight independent academic-review judges covering consistency, grammar, clarity, organization, evidence, style, methodology, and contribution. The overlay lists curved 50–100 scores and displays 3–6 excerpt-specific repair instructions when a judge is selected.

---

## Verification & Testing
Tests in `app/tests/test_app.py` verify:
- Complete lifecycle bootstrap and clean teardown.
- Short-circuiting of empty selections with zero-cost error reporting.
- Tier 1 actions (`FIND_SYNONYMS`, `FIND_DEFINITIONS`, `GENERATE_GRAPH`).
- Tier 2 actions (`REWORD_TEXT`, `DISCOVER_PAPERS`, `RETRIEVE_EVIDENCE`, `SUMMARIZE_SOURCE`).
- Triggering of PyQt6 Sci-Fi loading and synonym list signals.
- In-place replacement with proper casing preservation (UPPERCASE, Capitalized, lowercase) and trailing whitespace handling.
- Keyboard navigation (<kbd>Up</kbd>, <kbd>Down</kbd>, <kbd>Enter</kbd>, <kbd>Esc</kbd>) on the PyQt6 overlay.
