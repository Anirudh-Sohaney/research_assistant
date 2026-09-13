# App Subsystem (Master Orchestrator)

## 1. Final Deliverable
A master application orchestrator (`app.orchestrator.AppOrchestrator`) that unifies all desktop assistant subsystems:
- Application lifecycle bootstrapping and clean shutdown coordination (`init_application`, `shutdown_application`).
- Two-Tier processing nerve center (`dispatch_action_pipeline`) separating Tier 1 (zero-token local/lexical) from Tier 2 (budgeted RAG + LLM).
- Universal actuation routing outputs to right-edge Sci-Fi overlay cards (`overlay_ui`), cursor-anchored popups, or direct editor replacement (`text_injector`).
- Interactive full reword flow on <kbd>Alt</kbd> + <kbd>P</kbd>: choose **Reword**, **Add Detail**, or **Simplify**, preview the OpenRouter/Ling result, press <kbd>Enter</kbd> to replace the highlighted text, or <kbd>R</kbd> to regenerate.
- Background daemon supervisor integration (`daemon_service`) and global hotkey wiring (`hotkey_manager`).
- Typed runtime context and execution telemetry models (`AppRuntimeContext`, `ActionResult`, `ActionTrigger`, `AppExitReport`, `ShutdownReason`).

## 2. Algorithm Used
- **Event Bus Routing & Synonym Pipeline**:
  1. Intercept global hotkey trigger and extract foreground selection via `selection_reader.extractor.extract_selection`.
  2. If selected text is empty, short-circuit immediately with a zero-cost error status.
  3. Route based on action type:
     - **Tier 1 (Lexical & Overlay Execution)**:
       - `FIND_SYNONYMS` (<kbd>Alt</kbd> + <kbd>O</kbd>):
         - Detects highlighted text and hovered word under the mouse cursor.
         - Records active foreground window handle (`target_hwnd`) and mouse position (`cursor_pos`).
         - Immediately displays the **PyQt6 Sci-Fi Synonym Overlay** on the **right edge of the screen (vertically centered)** in its loading state with animated sweep scanline and pulsing dots. The singleton is pre-warmed on the Qt GUI thread before hotkey processing begins.
         - Asynchronously queries OpenRouter `inclusionai/ling-3.0-flash-vl:free` (with local Qwen2.5-1.5B fallback) for 8–12 contextually ranked academic synonyms.
         - On candidate arrival, switches the overlay to the interactive list view (`SciFiSynonymListWidget`) through queued Qt signals, keeping all widget work on the GUI thread.
         - Allows the author to use <kbd>Up</kbd> / <kbd>Down</kbd> arrow keys to browse, <kbd>Esc</kbd> to cancel, and <kbd>Enter</kbd> to apply.
         - Upon pressing <kbd>Enter</kbd>, `apply_chosen_synonym` preserves original casing (UPPERCASE, Capitalized, lowercase) and trailing space, refocuses the author's document window, and executes high-speed in-place replacement.
       - `FIND_DEFINITIONS`: Query FreeDictionary + WordNet + WSD via `lexical_definitions`; render definition card in `overlay_ui`.
       - `GENERATE_GRAPH`: Parse tabular data via Polars + render Matplotlib Agg figure via `data_to_graph`; render preview in `overlay_ui`.
     - **Tier 2 (Hybrid RAG + Budgeted LLM Execution)**:
       - `REWORD_TEXT`: Mask scholarly citations and math, call OpenRouter/Nemotron via `text_reword`, unmask entities, and inject replacement via `text_injector`.
       - `DISCOVER_PAPERS`: RAG filter candidates down to top 4-6 papers, assess claim relevance via `paper_discovery`, and render interactive paper cards in `overlay_ui`.
       - `RETRIEVE_EVIDENCE`: Extract claim and retrieve dual-stream supporting/opposing evidence via `evidence_engine`; render consensus card in `overlay_ui`.
       - `SUMMARIZE_SOURCE`: Profile codebase AST or tabular dataset schema via `source_summary`; render metrics card in `overlay_ui`.
  4. Aggregate token telemetry and measure execution latency ($t_{latency} = (t_{end} - t_{start}) \times 1000\text{ ms}$).
  5. Return structured `ActionResult`.

## 3. Description
The `app` module serves as the central command center of the Research Aid Desktop Assistant. Operating invisibly in the background while authors compose papers in Word, Google Docs, LaTeX editors (Overleaf, TeXstudio, VS Code), or Markdown, it bridges low-level hardware hooks, text extraction, local lexical algorithms, RAG vector retrieval, and the PyQt6 visual overlay.
