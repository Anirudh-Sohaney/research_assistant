# App Subsystem (Master Orchestrator) Documentation

## Overview
The `app` module orchestrates all underlying subsystems into a cohesive background desktop assistant. It enforces token efficiency via a strict Two-Tier Processing Architecture: Tier 1 resolves frequent lexical and visualization tasks locally with zero tokens, while Tier 2 employs targeted RAG filtering and budgeted LLM generation.

---

## Architecture & Data Models

### `app.models`
- **`ActionTrigger`**: Enum of all user-triggered actions:
  - `FIND_SYNONYMS`: Contextual synonym lookup.
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
  - `ui_handle_id`: Optional identifier of active floating card.
  - `injected`: True if text was directly replaced in the editor.
  - `data`: Raw data payload returned by the underlying engine.
- **`SynonymCycleState`**:
  - `cursor_pos`: `(x, y)` tuple representing the initial desktop mouse coordinates.
  - `target_word`: The word originally hovered over in the document.
  - `candidates`: List of 8–12 contextually ranked academic synonyms returned by OpenAI `gpt-5.6-luna` (or local Qwen2.5-1.5B fallback).
  - `current_index`: Pointer to currently inserted candidate within the candidates list.
  - `last_typed_text`: Exact string typed in the last swap (including trailing space if present).
  - `has_trailing_space`: Boolean indicating whether word had a trailing whitespace.
  - `casing`: Target casing style (`"upper"`, `"capitalize"`, or `"lower"`).
  - `timestamp`: Monotonic timestamp of the last injection.
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
Ingests selected text, routes execution across Tier 1 or Tier 2 engines, and commands the overlay UI or text injector. Detects stationary cursor on subsequent `FIND_SYNONYMS` requests and transparently delegates to `cycle_next_synonym()`.

### `cycle_next_synonym() -> ActionResult`
Cycles to the next candidate in the 8–12 synonym list:
1. Advances `current_index = (current_index + 1) % len(candidates)`.
2. Synthesizes `VK_BACK` backspaces for the exact character length of `last_typed_text`.
3. Injects the new candidate at high speed while preserving original casing and trailing whitespace.
4. Completes in $< 50\text{ ms}$ with zero LLM inference.

### `shutdown_application(reason: ShutdownReason = ShutdownReason.USER_QUIT, timeout_ms: int = 3000) -> AppExitReport`
Safely stops keyboard listeners, closes floating overlay windows, clears runtime cycle states, and terminates daemon services.

---

## Usage Example

```python
from app import (
    ActionTrigger,
    ShutdownReason,
    dispatch_action_pipeline,
    init_application,
    shutdown_application,
)
from selection_reader.models import AppInfo, SelectionPayload

# 1. Start application
context = init_application()
print(f"Research Aid running in session {context.session_id} (PID: {context.daemon_pid})")

# 2. Dispatch a Tier 1 contextual synonym action
payload = SelectionPayload(
    selected_text="empirical",
    app=AppInfo(name="WINWORD.EXE", title="Draft - Word", category="word_processor", pid=1024),
)
result = dispatch_action_pipeline(ActionTrigger.FIND_SYNONYMS, payload)
print(f"Action: {result.action}, Tier: {result.tier}, Latency: {result.latency_ms}ms, Tokens: {result.tokens_used}")

# 3. Clean shutdown
report = shutdown_application(ShutdownReason.USER_QUIT)
print(f"Shutdown complete: {report.success}")
```

---

## Verification & Testing
Tests in `app/tests/test_app.py` verify:
- Complete lifecycle bootstrap and clean teardown.
- Short-circuiting of empty selections with zero-cost error reporting.
- Tier 1 actions (`FIND_SYNONYMS`, `FIND_DEFINITIONS`, `GENERATE_GRAPH`) consuming 0 tokens.
- Tier 2 actions (`REWORD_TEXT`, `DISCOVER_PAPERS`, `RETRIEVE_EVIDENCE`, `SUMMARIZE_SOURCE`) routing properly to hybrid RAG/LLM pipelines.
- Text injection and floating overlay card creation.
- Stationary cursor synonym cycling on repeated `Alt + O` with backspace substitution.
- Automatic cycle abortion and re-generation when mouse cursor position moves > 5px.
- Circular candidate index wraparound across the 8–12 candidate list.
