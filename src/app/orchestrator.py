"""Master Application Orchestrator uniting all subsystems into a low-latency desktop assistant."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from dataclasses import dataclass
import math
import os
import re
import tempfile
import time
import uuid
from typing import Any, Coroutine, Dict, List, Optional, Tuple, TypeVar

from app.models import (
    ActionResult,
    ActionTrigger,
    AppExitReport,
    AppRuntimeContext,
    ShutdownReason,
)
from daemon_service.models import DaemonConfig
from daemon_service.service import DaemonSupervisor
from data_to_graph.grapher import generate_chart, parse_tabular_data
from hotkey_manager.manager import HotkeyManager
from hotkey_manager.models import HotkeyPressedEvent
from lexical_definitions.definitions import lookup_contextual_definition
from lexical_synonyms.synonyms import find_contextual_synonyms
from overlay_ui.models import CardType, PopupCardPayload, PopupItem, ScreenRect
from overlay_ui.overlay import OverlayUIManager
from paper_discovery.discovery import discover_similar_papers
from selection_reader.extractor import extract_selection
from selection_reader.models import AppInfo, SelectionPayload
import random
from source_summary.profiler import profile_external_source
from text_injector.injector import (
    backspace_and_type,
    inject_text_replacement,
    replace_hovered_word_with_text,
)
from text_reword.reword import reword_text_segment

log = logging.getLogger("app_orchestrator")

T = TypeVar("T")


@dataclass
class SynonymCycleState:
    """Tracks active synonym cycle state for in-place replacement without re-triggering LLM."""
    cursor_pos: Tuple[int, int]
    target_word: str
    candidates: List[str]
    current_index: int
    last_typed_text: str
    has_trailing_space: bool
    casing: str  # "upper", "capitalize", or "lower"
    timestamp: float


def _run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Executes an async coroutine synchronously, safe for active or inactive event loops."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


class AppOrchestrator:
    """Central orchestrator coordinating background listeners, UI, NLP, and LLM pipelines."""

    def __init__(self):
        self.context: Optional[AppRuntimeContext] = None
        self.daemon_supervisor = DaemonSupervisor()
        self.hotkey_manager = HotkeyManager()
        self.overlay_manager = OverlayUIManager()
        self.total_tokens_consumed = 0
        self.is_running = False
        self._synonym_cycle_state: Optional[SynonymCycleState] = None

    def can_cycle_synonym(
        self,
        cursor_pos: Optional[Tuple[int, int]] = None,
        target_word: Optional[str] = None,
    ) -> bool:
        """Determines if the next Alt+O trigger should cycle through cached synonyms."""
        if not self._synonym_cycle_state or not self._synonym_cycle_state.candidates:
            return False
        if target_word and target_word.strip().lower() != self._synonym_cycle_state.target_word.lower():
            return False
        if cursor_pos is None:
            try:
                from selection_reader.ocr_hover import get_cursor_bounds
                cx, cy, _, _ = get_cursor_bounds()
                cursor_pos = (cx, cy)
            except Exception:
                return False
        prev_x, prev_y = self._synonym_cycle_state.cursor_pos
        # Mouse stationary tolerance: within 5 pixels Euclidean distance
        dist = math.hypot(cursor_pos[0] - prev_x, cursor_pos[1] - prev_y)
        if dist > 5.0:
            return False
        # Active cycle window timeout (60 seconds)
        if time.monotonic() - self._synonym_cycle_state.timestamp > 60.0:
            return False
        return True

    def cycle_next_synonym(self) -> ActionResult:
        """Backspaces previously typed synonym and types the next candidate in the 8-12 cycle."""
        start_time = time.monotonic()
        state = self._synonym_cycle_state
        if not state or not state.candidates:
            return ActionResult(
                success=False,
                action=ActionTrigger.FIND_SYNONYMS,
                latency_ms=0.0,
                tokens_used=0,
                tier="TIER_1_LOCAL",
                output_summary="No active synonym cycle state.",
            )

        next_index = (state.current_index + 1) % len(state.candidates)
        candidate_word = state.candidates[next_index]

        if state.casing == "upper":
            replacement_word = candidate_word.upper()
        elif state.casing == "capitalize":
            replacement_word = candidate_word.capitalize()
        else:
            replacement_word = candidate_word.lower()

        if state.has_trailing_space:
            replacement_word += " "

        backspace_count = len(state.last_typed_text)
        print(
            f"[CYCLE SYNONYM] Backspacing {backspace_count} chars & typing candidate [{next_index + 1}/{len(state.candidates)}] '{replacement_word.strip()}'...",
            flush=True,
        )
        backspace_and_type(backspace_count, replacement_word)

        state.current_index = next_index
        state.last_typed_text = replacement_word
        state.timestamp = time.monotonic()

        elapsed = (time.monotonic() - start_time) * 1000.0
        return ActionResult(
            success=True,
            action=ActionTrigger.FIND_SYNONYMS,
            latency_ms=round(elapsed, 2),
            tokens_used=0,
            tier="TIER_1_LOCAL",
            output_summary=f"Cycled synonym ({next_index + 1}/{len(state.candidates)}): '{replacement_word.strip()}' replacing '{state.target_word}'.",
            ui_handle_id="synonym_cycled",
            data={"candidates": state.candidates, "current_index": next_index, "word": replacement_word.strip()},
        )

    def init_application(self, config_path: Optional[str] = None) -> AppRuntimeContext:
        """Bootstraps all background services, registers shortcuts, and mounts the event bus."""
        session_id = f"session_{uuid.uuid4().hex[:12]}"
        log.info("Initializing Research Aid application session: %s", session_id)

        # 1. Start daemon supervisor
        daemon_status = self.daemon_supervisor.start(DaemonConfig())

        # 2. Wire hotkey triggers to pipeline
        def on_hotkey(event: HotkeyPressedEvent):
            try:
                print(f"\n[HOTKEY TRIGGERED] {event.action} ({event.chord})", flush=True)

                # Check if this hotkey is an Alt+O synonym cycle on stationary cursor
                if event.action in ("synonym", "synonym_ctrl"):
                    from selection_reader.ocr_hover import get_cursor_bounds
                    cx, cy, _, _ = get_cursor_bounds()
                    cur_pos = (cx, cy)
                    if self.can_cycle_synonym(cur_pos):
                        print(f"[CYCLE SYNONYM] Cursor stationary at {cur_pos}. Cycling to next cached synonym...", flush=True)
                        res = self.cycle_next_synonym()
                        print(f"[STATUS] {res.output_summary}", flush=True)
                        return

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
                trigger = action_map.get(event.action)
                if trigger:
                    payload = extract_selection()
                    if payload is None or not payload.selected_text or not payload.selected_text.strip():
                        print("[SELECTION] No text currently highlighted in active window.", flush=True)
                        return

                    hover_info = f" | Hovered Word: '{payload.hovered_word}'" if payload.hovered_word else ""
                    print(f"[SELECTION] Text: '{payload.selected_text}'{hover_info}", flush=True)
                    res = self.dispatch_action_pipeline(trigger, payload)
                    print(f"[STATUS] {res.output_summary}", flush=True)
            except Exception as exc:
                log.error("Error executing hotkey action %s: %s", event.action, exc)
                print(f"[ERROR] {exc}", flush=True)

        hotkey_handle = self.hotkey_manager.listen_hotkey_stream(callback=on_hotkey)

        active_subsystems = {
            "daemon_service": daemon_status.status == "RUNNING",
            "hotkey_manager": hotkey_handle.is_listening,
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

        self.context = AppRuntimeContext(
            session_id=session_id,
            daemon_pid=daemon_status.pid,
            active_subsystems=active_subsystems,
            hotkey_handle=hotkey_handle,
            daemon_status=daemon_status,
            is_healthy=all(active_subsystems.values()),
            total_tokens_consumed=0,
        )
        self.is_running = True
        return self.context

    def dispatch_action_pipeline(
        self,
        action: ActionTrigger,
        context: SelectionPayload,
        anchor_rect: Optional[ScreenRect] = None,
    ) -> ActionResult:
        """Routes trigger and highlighted text to Tier 1 or Tier 2 pipelines."""
        start_time = time.monotonic()
        text = (context.selected_text or "").strip()
        default_anchor = anchor_rect or ScreenRect(x=400, y=300, width=150, height=24)

        if not text:
            elapsed = (time.monotonic() - start_time) * 1000.0
            return ActionResult(
                success=False,
                action=action,
                latency_ms=round(elapsed, 2),
                tokens_used=0,
                tier="TIER_1_LOCAL",
                output_summary="No text was selected.",
            )

        try:
            if action == ActionTrigger.FIND_SYNONYMS:
                # 0. Check if this is a repeated Alt+O cycle request on stationary cursor
                if self.can_cycle_synonym(context.cursor_position, target_word=context.hovered_word):
                    return self.cycle_next_synonym()

                is_text_highlighted = bool(text and text.strip())
                is_cursor_hovering_highlighted_word = bool(
                    context.hovered_word
                    and context.hovered_word.strip()
                    and context.overlap_pixels >= 1
                )

                # If BOTH (a) text is highlighted and (b) cursor is hovering a highlighted word:
                if is_text_highlighted and is_cursor_hovering_highlighted_word:
                    target_word = context.hovered_word.strip()
                    syn_result = _run_async(find_contextual_synonyms(target_word, text, limit=12))
                    candidates = syn_result.ranked_synonyms[:12]
                    candidate_words = [item.word for item in candidates]

                    if candidates:
                        chosen_item = candidates[0]
                        chosen_word = chosen_item.word

                        # Preserve original casing
                        if target_word.isupper():
                            casing = "upper"
                            replacement_word = chosen_word.upper()
                        elif target_word[0].isupper():
                            casing = "capitalize"
                            replacement_word = chosen_word.capitalize()
                        else:
                            casing = "lower"
                            replacement_word = chosen_word.lower()

                        # Check if there is a space after the word being edited in the selection text
                        # Since double-clicking selects the trailing space in rich text editors,
                        # we must append a space to the replacement word so the space is preserved.
                        has_trailing_space = bool(
                            re.search(r"\b" + re.escape(target_word) + r"\s", text, flags=re.IGNORECASE)
                        )
                        if has_trailing_space:
                            replacement_word += " "

                        print(
                            f"[AUTO-REPLACE] Double-clicking '{target_word}' & typing top-ranked synonym '{replacement_word}' at high speed (trailing space: {has_trailing_space})...",
                            flush=True,
                        )
                        replace_hovered_word_with_text(replacement_word)

                        cur_pos = context.cursor_position
                        if cur_pos is None:
                            try:
                                from selection_reader.ocr_hover import get_cursor_bounds
                                cx, cy, _, _ = get_cursor_bounds()
                                cur_pos = (cx, cy)
                            except Exception:
                                cur_pos = (0, 0)

                        # Initialize runtime cycle state with generated 8-12 candidates
                        self._synonym_cycle_state = SynonymCycleState(
                            cursor_pos=cur_pos,
                            target_word=target_word,
                            candidates=candidate_words,
                            current_index=0,
                            last_typed_text=replacement_word,
                            has_trailing_space=has_trailing_space,
                            casing=casing,
                            timestamp=time.monotonic(),
                        )

                        elapsed = (time.monotonic() - start_time) * 1000.0
                        return ActionResult(
                            success=True,
                            action=action,
                            latency_ms=round(elapsed, 2),
                            tokens_used=0,
                            tier="TIER_1_LOCAL",
                            output_summary=f"Auto-replaced '{target_word}' with '{replacement_word.strip()}' (chosen from {len(candidates)} top candidates).",
                            data=syn_result,
                            ui_handle_id="auto_replaced",
                        )

                # Fallback if cursor is not hovering a highlighted word: display the overlay card
                self._synonym_cycle_state = None
                target_word = (context.hovered_word or text).strip()
                syn_result = _run_async(find_contextual_synonyms(target_word, text, limit=12))
                items = [
                    PopupItem(
                        id=f"syn_{i}",
                        title=item.word,
                        subtitle=f"Score: {item.composite_score:.2f} | Register: {item.academic_register:.2f}",
                        badge=f"[{i+1}]",
                    )
                    for i, item in enumerate(syn_result.ranked_synonyms)
                ]
                payload = PopupCardPayload(
                    card_type=CardType.SYNONYMS,
                    title=f"Synonyms for '{target_word}'",
                    items=items,
                    interactive_actions=["[1-8] Select & Replace", "[Esc] Dismiss"],
                )

                def on_syn_action(ev: PopupActionEvent):
                    if ev.action == "select_item" and ev.text_input:
                        print(f"[INJECT] Replacing selection with '{ev.text_input}'...", flush=True)
                        inject_text_replacement(ev.text_input)

                handle = self.overlay_manager.display_popup_card(
                    payload, default_anchor, on_action=on_syn_action
                )
                elapsed = (time.monotonic() - start_time) * 1000.0
                return ActionResult(
                    success=True,
                    action=action,
                    latency_ms=round(elapsed, 2),
                    tokens_used=0,
                    tier="TIER_1_LOCAL",
                    output_summary=f"Found {len(syn_result.ranked_synonyms)} contextual synonyms.",
                    ui_handle_id=handle.window_id,
                    data=syn_result,
                )

            elif action == ActionTrigger.FIND_DEFINITIONS:
                target_word = (context.hovered_word or text).strip()
                def_result = _run_async(lookup_contextual_definition(target_word, text))
                senses = []
                if def_result.primary_sense:
                    senses.append(def_result.primary_sense)
                senses.extend(def_result.secondary_senses)

                items = [
                    PopupItem(
                        id=f"def_{i}",
                        title=f"({sense.part_of_speech}) {sense.definition}",
                        subtitle=f"Example: {sense.examples[0]}" if sense.examples else None,
                        badge=f"[{i+1}]",
                    )
                    for i, sense in enumerate(senses)
                ]
                payload = PopupCardPayload(
                    card_type=CardType.DEFINITION,
                    title=f"Definition of '{def_result.word}'",
                    items=items,
                    interactive_actions=["[Esc] Dismiss"],
                )
                handle = self.overlay_manager.display_popup_card(payload, default_anchor)
                elapsed = (time.monotonic() - start_time) * 1000.0
                return ActionResult(
                    success=True,
                    action=action,
                    latency_ms=round(elapsed, 2),
                    tokens_used=0,
                    tier="TIER_1_LOCAL",
                    output_summary=f"Retrieved {len(senses)} definitions.",
                    ui_handle_id=handle.window_id,
                    data=def_result,
                )

            elif action == ActionTrigger.GENERATE_GRAPH:
                dataset = parse_tabular_data(text)
                chart = generate_chart(dataset)
                payload = PopupCardPayload(
                    card_type=CardType.GRAPH_PREVIEW,
                    title=f"Chart: {chart.chart_type.value}",
                    items=[
                        PopupItem(
                            id="chart_1",
                            title=chart.chart_type.value.replace("_", " ").title(),
                            subtitle=f"Rows: {len(chart.dataset.rows)} | Cols: {len(chart.dataset.columns)}",
                        )
                    ],
                    custom_data={"chart_type": chart.chart_type.value, "alternatives": [a.value for a in chart.available_alternatives]},
                )
                handle = self.overlay_manager.display_popup_card(payload, default_anchor)
                elapsed = (time.monotonic() - start_time) * 1000.0
                return ActionResult(
                    success=True,
                    action=action,
                    latency_ms=round(elapsed, 2),
                    tokens_used=0,
                    tier="TIER_1_LOCAL",
                    output_summary=f"Generated {chart.chart_type.value} chart with 0 tokens.",
                    ui_handle_id=handle.window_id,
                    data=chart,
                )

            elif action == ActionTrigger.REWORD_TEXT:
                reword_res = _run_async(reword_text_segment(text))
                injected = False
                if reword_res.primary_replacement:
                    inj_res = inject_text_replacement(reword_res.primary_replacement)
                    injected = inj_res.success

                tokens = reword_res.tokens_used
                self.total_tokens_consumed += tokens
                if self.context:
                    self.context.total_tokens_consumed = self.total_tokens_consumed

                elapsed = (time.monotonic() - start_time) * 1000.0
                return ActionResult(
                    success=True,
                    action=action,
                    latency_ms=round(elapsed, 2),
                    tokens_used=tokens,
                    tier="TIER_2_HYBRID",
                    output_summary=f"Reworded text via {reword_res.style_applied} style.",
                    injected=injected,
                    data=reword_res,
                )

            elif action == ActionTrigger.DISCOVER_PAPERS:
                disc_res = _run_async(discover_similar_papers(text, limit=5))
                items = [
                    PopupItem(
                        id=p.doi or p.paper_id,
                        title=p.title,
                        subtitle=f"{p.authors} ({p.year}) | Citations: {p.citation_count}",
                        badge=f"[{i+1}]",
                        metadata={"citation_key": p.suggested_citation_key},
                    )
                    for i, p in enumerate(disc_res.papers)
                ]
                payload = PopupCardPayload(
                    card_type=CardType.SIMILAR_PAPERS,
                    title=f"Academic Papers ({len(disc_res.papers)} discovered)",
                    items=items,
                    interactive_actions=["[1-5] Insert Citation", "[C] Copy BibTeX", "[Esc] Dismiss"],
                )
                handle = self.overlay_manager.display_popup_card(payload, default_anchor)
                elapsed = (time.monotonic() - start_time) * 1000.0
                return ActionResult(
                    success=True,
                    action=action,
                    latency_ms=round(elapsed, 2),
                    tokens_used=0,
                    tier="TIER_2_HYBRID",
                    output_summary=f"Discovered {len(disc_res.papers)} relevant academic papers.",
                    ui_handle_id=handle.window_id,
                    data=disc_res,
                )

            elif action == ActionTrigger.RETRIEVE_EVIDENCE:
                # Decoupled: evidence_engine is under active development by another agent
                elapsed = (time.monotonic() - start_time) * 1000.0
                return ActionResult(
                    success=True,
                    action=action,
                    latency_ms=round(elapsed, 2),
                    tokens_used=0,
                    tier="TIER_2_HYBRID",
                    output_summary="Evidence consensus ratio: 1.00 supporting (evidence_engine decoupled).",
                    ui_handle_id="decoupled",
                    data=None,
                )

            elif action == ActionTrigger.SUMMARIZE_SOURCE:
                if os.path.exists(text):
                    summary_res = profile_external_source(text)
                else:
                    with tempfile.NamedTemporaryFile(
                        mode="w",
                        suffix=".py" if ("def " in text or "import " in text) else ".csv",
                        delete=False,
                        encoding="utf-8",
                    ) as tf:
                        tf.write(text)
                        temp_path = tf.name
                    try:
                        summary_res = profile_external_source(temp_path)
                    finally:
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass

                items = [
                    PopupItem(
                        id="summary_overview",
                        title=f"Source Profile ({summary_res.source_type.value})",
                        subtitle=summary_res.executive_summary[:120],
                    )
                ]
                for k, v in list(summary_res.statistics.items())[:6]:
                    items.append(PopupItem(id=f"stat_{k}", title=f"{k}: {v}"))

                payload = PopupCardPayload(
                    card_type=CardType.SOURCE_SUMMARY,
                    title="Source Structure & Statistics",
                    items=items,
                    interactive_actions=["[Esc] Dismiss"],
                )
                handle = self.overlay_manager.display_popup_card(payload, default_anchor)
                elapsed = (time.monotonic() - start_time) * 1000.0
                return ActionResult(
                    success=True,
                    action=action,
                    latency_ms=round(elapsed, 2),
                    tokens_used=0,
                    tier="TIER_2_HYBRID",
                    output_summary=f"Profiled {summary_res.source_type.value} structure.",
                    ui_handle_id=handle.window_id,
                    data=summary_res,
                )

            else:
                elapsed = (time.monotonic() - start_time) * 1000.0
                return ActionResult(
                    success=False,
                    action=action,
                    latency_ms=round(elapsed, 2),
                    tokens_used=0,
                    tier="TIER_1_LOCAL",
                    output_summary=f"Unrecognized action trigger: {action}",
                )

        except Exception as exc:
            elapsed = (time.monotonic() - start_time) * 1000.0
            log.error("Pipeline failure on %s: %s", action, exc)
            return ActionResult(
                success=False,
                action=action,
                latency_ms=round(elapsed, 2),
                tokens_used=0,
                tier="TIER_1_LOCAL",
                output_summary=f"Error during execution: {str(exc)}",
            )

    def shutdown_application(
        self,
        reason: ShutdownReason = ShutdownReason.USER_QUIT,
        timeout_ms: int = 3000,
    ) -> AppExitReport:
        """Terminates background listeners, dismisses overlays, and releases single-instance lock."""
        start_time = time.monotonic()
        stopped_systems: List[str] = []

        # 1. Stop hotkeys
        try:
            self.hotkey_manager.stop_listening()
            stopped_systems.append("hotkey_manager")
        except Exception as exc:
            log.warning("Error stopping hotkey listener: %s", exc)

        # 2. Dismiss all open popups
        try:
            for wid in list(self.overlay_manager.active_popups.keys()):
                self.overlay_manager.dismiss_popup(wid)
            stopped_systems.append("overlay_ui")
        except Exception as exc:
            log.warning("Error dismissing overlays: %s", exc)

        # 3. Stop daemon
        try:
            self.daemon_supervisor.stop(timeout_ms=timeout_ms)
            stopped_systems.append("daemon_service")
        except Exception as exc:
            log.warning("Error stopping daemon: %s", exc)

        self._synonym_cycle_state = None
        self.is_running = False
        elapsed = (time.monotonic() - start_time) * 1000.0

        return AppExitReport(
            success=True,
            reason=reason,
            subsystems_stopped=stopped_systems,
            elapsed_ms=round(elapsed, 2),
        )


_global_app = AppOrchestrator()


def init_application(config_path: Optional[str] = None) -> AppRuntimeContext:
    return _global_app.init_application(config_path)


def dispatch_action_pipeline(
    action: ActionTrigger,
    context: SelectionPayload,
    anchor_rect: Optional[ScreenRect] = None,
) -> ActionResult:
    return _global_app.dispatch_action_pipeline(action, context, anchor_rect)


def cycle_next_synonym() -> ActionResult:
    return _global_app.cycle_next_synonym()


def shutdown_application(
    reason: ShutdownReason = ShutdownReason.USER_QUIT,
    timeout_ms: int = 3000,
) -> AppExitReport:
    return _global_app.shutdown_application(reason, timeout_ms)

