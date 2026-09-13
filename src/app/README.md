# App Subsystem (Master Orchestrator)

## 1. Final Deliverable
A master application orchestrator (`app.orchestrator.AppOrchestrator`) that unifies all desktop assistant subsystems:
- Application lifecycle bootstrapping and clean shutdown coordination (`init_application`, `shutdown_application`).
- Two-Tier processing nerve center (`dispatch_action_pipeline`) separating Tier 1 (zero-token local/lexical) from Tier 2 (budgeted RAG + LLM).
- Universal actuation routing outputs to cursor-anchored overlay cards (`overlay_ui`) or direct editor replacement (`text_injector`).
- Background daemon supervisor integration (`daemon_service`) and global hotkey wiring (`hotkey_manager`).
- Typed runtime context and execution telemetry models (`AppRuntimeContext`, `ActionResult`, `ActionTrigger`, `AppExitReport`, `ShutdownReason`).

## 2. Algorithm Used
- **Two-Tier Event Bus Routing**:
  1. Intercept global hotkey trigger and extract foreground selection via `selection_reader.extractor.extract_selection`.
  2. If selected text is empty, short-circuit immediately with a zero-cost error status.
  3. Route based on action type:
     - **Tier 1 (Zero-Token Local Execution)**:
       - `FIND_SYNONYMS`:
         - **Initial `Alt + O` (Hovered Word Auto-Replace)**: When text is highlighted and cursor hovers a highlighted word, queries OpenAI `gpt-5.6-luna` (at low reasoning effort and highest speed, with local Qwen2.5-1.5B fallback) to generate 8–12 context-perfect academic synonyms. Synthesizes a mouse double-click and types the top-ranked synonym at high speed, caching the 8–12 candidates in runtime memory.
         - **Subsequent `Alt + O` (Stationary Cursor Synonym Cycling)**: If `Alt + O` is pressed again while the mouse cursor remains stationary ($\le 5\text{px}$ jitter tolerance), the orchestrator automatically backspaces the previously typed synonym and types the next candidate in the 8–12 cycle without re-triggering the LLM or extraction pipeline.
         - **Visual Card Fallback**: If the cursor is outside the highlighted selection, renders an anchored interactive floating card in `overlay_ui`.
       - `FIND_DEFINITIONS`: Query FreeDictionary + WordNet + WSD via `lexical_definitions`; render definition card in `overlay_ui`.
       - `GENERATE_GRAPH`: Parse tabular data via Polars + render Matplotlib Agg figure via `data_to_graph`; render preview in `overlay_ui`.
     - **Tier 2 (Hybrid RAG + Budgeted LLM Execution)**:
       - `REWORD_TEXT`: Mask scholarly citations and math, call LLM/offline rules via `text_reword`, unmask entities, and inject replacement via `text_injector`.
       - `DISCOVER_PAPERS`: RAG filter candidates down to top 4-6 papers, assess claim relevance via `paper_discovery`, and render interactive paper cards in `overlay_ui`.
       - `RETRIEVE_EVIDENCE`: Extract claim and retrieve dual-stream supporting/opposing evidence via `evidence_engine`; render consensus card in `overlay_ui`.
       - `SUMMARIZE_SOURCE`: Profile codebase AST or tabular dataset schema via `source_summary`; render metrics card in `overlay_ui`.
  4. Aggregate token telemetry and measure execution latency ($t_{latency} = (t_{end} - t_{start}) \times 1000\text{ ms}$).
  5. Return structured `ActionResult`.

## 3. Description
The `app` module serves as the central command center of the Research Aid Desktop Assistant. Operating invisibly in the background while authors compose papers in Word, Google Docs, LaTeX editors (Overleaf, TeXstudio, VS Code), or Markdown, it bridges low-level hardware hooks, text extraction, local lexical algorithms, RAG vector retrieval, and floating UI cards. Its two-tier architecture guarantees that high-frequency writing queries consume zero tokens, reserving external LLM capacity exclusively for deep contextual synthesis and citation-grounded reasoning.
