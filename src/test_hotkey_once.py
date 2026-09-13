"""One-shot test script for Research Aid.

Listens in the background until the initial hotkey is pressed on a highlighted text selection,
prints out the complete extraction diagnostics (zero-clipboard highlighted text, cursor
position, hovered word, overlap pixels, and pipeline output), and exits cleanly.
"""

from __future__ import annotations

import logging
import sys
import threading
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.models import ActionTrigger, ShutdownReason
from app.orchestrator import AppOrchestrator
from hotkey_manager.models import HotkeyPressedEvent
from selection_reader.extractor import extract_selection, ensure_desktop_attachment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
)
log = logging.getLogger("test_hotkey_once")


def run_test():
    ensure_desktop_attachment()
    print("=" * 70, flush=True)
    print("[*] RESEARCH AID ONE-SHOT HOTKEY TEST RUNNER", flush=True)
    print("=" * 70, flush=True)
    print("Initializing application subsystems...", flush=True)

    orchestrator = AppOrchestrator()
    # Start daemon supervisor
    daemon_status = orchestrator.daemon_supervisor.start()

    active_subsystems = {
        "daemon_service": daemon_status.status == "RUNNING",
        "hotkey_manager": True,
        "overlay_ui": True,
        "selection_reader": True,
        "text_injector": True,
        "api_gateway": True,
        "lexical_synonyms": True,
        "lexical_definitions": True,
        "data_to_graph": True,
        "rag_indexer": True,
        "text_reword": True,
        "paper_discovery": True,
        "source_summary": True,
    }

    orchestrator.context = orchestrator.context or None
    orchestrator.is_running = True

    done_event = threading.Event()
    results_captured = {}

    action_map = {
        "synonym": ActionTrigger.FIND_SYNONYMS,
        "synonym_ctrl": ActionTrigger.FIND_SYNONYMS,
        "definition": ActionTrigger.FIND_DEFINITIONS,
        "table_graph": ActionTrigger.GENERATE_GRAPH,
        "reword": ActionTrigger.REWORD_TEXT,
        "similar_papers": ActionTrigger.DISCOVER_PAPERS,
        "evidence": ActionTrigger.RETRIEVE_EVIDENCE,
        "source_summary": ActionTrigger.SUMMARIZE_SOURCE,
    }

    def on_hotkey_triggered(event: HotkeyPressedEvent):
        try:
            print("\n" + "#" * 70, flush=True)
            print(f"[HOTKEY EVENT DETECTED] Action: {event.action} | Chord: {event.chord}", flush=True)
            print("#" * 70, flush=True)

            trigger = action_map.get(event.action)
            if not trigger:
                print(f"[WARNING] Unrecognized hotkey action: {event.action}", flush=True)
                return

            print("[SELECTION_READER] Querying active window and cursor...", flush=True)
            t0 = time.monotonic()
            payload = extract_selection()
            extract_duration_ms = round((time.monotonic() - t0) * 1000.0, 2)

            if payload is None or not payload.selected_text or not payload.selected_text.strip():
                from selection_reader.extractor import inspect_active_window
                app_meta = inspect_active_window()
                print(f"[SELECTION_READER] Inspected Foreground App: {app_meta.name} (PID: {app_meta.pid}) | Title: \"{app_meta.title}\"", flush=True)
                print("[SELECTION_READER] No text currently highlighted in active foreground window.", flush=True)
                print("[NOTICE] Please highlight some text in an editor/browser and press Alt+O again.", flush=True)
                return

            print("\n" + "=" * 70, flush=True)
            print(">>> EXTRACTION RESULTS (Atomic Clipboard / UIA + Native OCR Hover) <<<", flush=True)
            print("=" * 70, flush=True)
            print(f"Extraction Latency    : {extract_duration_ms} ms", flush=True)
            print(f"Active Foreground App : {payload.app.name} (PID: {payload.app.pid})", flush=True)
            print(f"Window Category       : {payload.app.category}", flush=True)
            print(f"Window Title          : {payload.app.title}", flush=True)
            print(f"Cursor Position       : {payload.cursor_position}", flush=True)
            print(f"Part A (Selected Text): \"{payload.selected_text}\"", flush=True)
            print(f"Part B (Hovered Word) : \"{payload.hovered_word}\"", flush=True)
            print(f"Hover Overlap Area    : {payload.overlap_pixels} pixels", flush=True)

            if payload.hovered_word:
                print("Selection Gate Status : PASSED (Word is within highlighted selection)", flush=True)
            else:
                print("Selection Gate Status : GATED (Cursor is not on a highlighted word; using full text)", flush=True)

            print("-" * 70, flush=True)
            print(f"[PIPELINE] Dispatching action: {trigger.value}...", flush=True)
            action_res = orchestrator.dispatch_action_pipeline(trigger, payload)

            print(f"Pipeline Success      : {action_res.success}", flush=True)
            print(f"Pipeline Tier         : {action_res.tier}", flush=True)
            print(f"Pipeline Latency      : {action_res.latency_ms} ms", flush=True)
            print(f"Tokens Used           : {action_res.tokens_used}", flush=True)
            print(f"Summary               : {action_res.output_summary}", flush=True)

            if trigger == ActionTrigger.FIND_SYNONYMS and action_res.data:
                syn_data = action_res.data
                print("\n[RANKED SYNONYMS RETRIEVED]:", flush=True)
                for i, item in enumerate(syn_data.ranked_synonyms[:8], start=1):
                    print(f"  [{i}] {item.word:<18} (Composite: {item.composite_score:.2f} | Register: {item.academic_register:.2f} | Similarity: {item.semantic_similarity:.2f})", flush=True)

            elif trigger == ActionTrigger.FIND_DEFINITIONS and action_res.data:
                def_data = action_res.data
                print(f"\n[DEFINITIONS FOR '{def_data.word}']:", flush=True)
                if def_data.primary_sense:
                    print(f"  * Primary: ({def_data.primary_sense.part_of_speech}) {def_data.primary_sense.definition}", flush=True)
                for s in def_data.secondary_senses:
                    print(f"  * Secondary: ({s.part_of_speech}) {s.definition}", flush=True)

            print("=" * 70, flush=True)
            results_captured["success"] = True
            results_captured["payload"] = payload.to_dict()
            results_captured["action"] = trigger.value
            results_captured["summary"] = action_res.output_summary

            if action_res.ui_handle_id == "auto_replaced":
                print("\n[AUTO-REPLACE] Word selected and high-speed typed successfully. Test complete!", flush=True)
                time.sleep(1.0)
            else:
                print("\n[OVERLAY] Floating visual card displayed at cursor. Keeping active for 4 seconds...", flush=True)
                time.sleep(4.0)

            # Signal test completion
            done_event.set()

        except Exception as exc:
            log.error("Exception during hotkey test execution: %s", exc, exc_info=True)
            done_event.set()

    # Register listener
    hotkey_handle = orchestrator.hotkey_manager.listen_hotkey_stream(callback=on_hotkey_triggered)

    print("-" * 70, flush=True)
    print("READY & LISTENING FOR HOTKEY TRIGGER", flush=True)
    print("Available hotkeys to test:")
    print("  * Synonyms       : Alt + O (or Ctrl + Alt + O)")
    print("  * Definitions    : Ctrl + Shift + D")
    print("  * Reword Text    : Ctrl + Shift + R")
    print("  * Table to Graph : Ctrl + Shift + G")
    print("  * Discover Papers: Ctrl + Shift + P")
    print("  * Verify Evidence: Ctrl + Shift + E")
    print("  * Source Summary : Ctrl + Shift + U")
    print("-" * 70, flush=True)
    print("Instructions:")
    print("  1. Highlight any word or sentence in Notepad, Word, VS Code, or your browser.")
    print("  2. Place your mouse cursor over any word in that highlighted text.")
    print("  3. Press Alt + O (or Ctrl + Alt + O).")
    print("=" * 70, flush=True)
    print("Awaiting trigger (timeout: 30 minutes)...", flush=True)

    # Wait for the hotkey to be triggered and completed
    triggered = done_event.wait(timeout=1800.0)

    print("\nShutting down test runner...", flush=True)
    try:
        orchestrator.shutdown_application(ShutdownReason.USER_QUIT)
    except Exception as exc:
        log.warning("Error during shutdown: %s", exc)

    if triggered and results_captured.get("success"):
        print("\n" + "=" * 70, flush=True)
        print("[TEST COMPLETED SUCCESSFULLY] Initial hotkey processed and results recorded.", flush=True)
        print("=" * 70, flush=True)
    elif not triggered:
        print("\n[TEST TIMED OUT] No hotkey pressed within 30 minutes.", flush=True)

    print("Exiting.", flush=True)


if __name__ == "__main__":
    run_test()
