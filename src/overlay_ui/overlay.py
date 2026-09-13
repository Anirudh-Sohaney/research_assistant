"""Overlay UI subsystem for floating, non-intrusive contextual card display."""

from __future__ import annotations

import logging
import sys
import threading
import uuid
from typing import Callable, Dict, Optional, Tuple

from overlay_ui.models import (
    CardType,
    PopupActionEvent,
    PopupCardPayload,
    PopupHandle,
    PopupItem,
    ScreenRect,
)

log = logging.getLogger("overlay_ui")

DEFAULT_POPUP_WIDTH = 420
DEFAULT_POPUP_HEIGHT = 320
MARGIN = 16
OFFSET_Y = 8


def get_screen_dimensions() -> Tuple[int, int]:
    """Detects primary screen dimensions with fallback."""
    if sys.platform == "win32":
        try:
            import ctypes
            w = ctypes.windll.user32.GetSystemMetrics(0)
            h = ctypes.windll.user32.GetSystemMetrics(1)
            if w > 0 and h > 0:
                return w, h
        except Exception:
            pass
    return 1920, 1080


def get_cursor_position() -> Tuple[int, int]:
    """Detects current mouse cursor position on Windows."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            pt = wintypes.POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                return pt.x, pt.y
        except Exception:
            pass
    return 400, 300


def calculate_clamped_bounds(
    anchor: ScreenRect,
    popup_width: int = DEFAULT_POPUP_WIDTH,
    popup_height: int = DEFAULT_POPUP_HEIGHT,
    screen_width: int = 1920,
    screen_height: int = 1080,
) -> ScreenRect:
    """Calculates anchored popup coordinates clamped to screen boundaries."""
    # Vertical placement: prefer below selection
    preferred_y = anchor.y + anchor.height + OFFSET_Y
    if preferred_y + popup_height > screen_height - MARGIN:
        # Flip above selection
        preferred_y = anchor.y - popup_height - OFFSET_Y
        if preferred_y < MARGIN:
            preferred_y = max(MARGIN, screen_height - popup_height - MARGIN)

    # Horizontal placement: align with selection start
    preferred_x = anchor.x
    if preferred_x + popup_width > screen_width - MARGIN:
        preferred_x = screen_width - popup_width - MARGIN
    if preferred_x < MARGIN:
        preferred_x = MARGIN

    return ScreenRect(
        x=int(preferred_x),
        y=int(preferred_y),
        width=int(popup_width),
        height=int(popup_height),
    )


def _launch_tkinter_window(
    handle: PopupHandle,
    payload: PopupCardPayload,
    bounds: ScreenRect,
    on_action: Optional[Callable[[PopupActionEvent], None]] = None,
):
    """Spawns a sleek, frameless floating dark-mode card on the user's screen."""
    if "pytest" in sys.modules:
        return

    def run_gui():
        try:
            import tkinter as tk
            root = tk.Tk()
            root.title("Research Aid")
            root.overrideredirect(True)
            root.wm_attributes("-topmost", True)
            root.geometry(f"{bounds.width}x{bounds.height}+{bounds.x}+{bounds.y}")
            root.configure(bg="#181825", highlightbackground="#89b4fa", highlightthickness=2)

            # Header
            header = tk.Label(
                root,
                text=f"✨ {payload.title}",
                bg="#181825",
                fg="#89b4fa",
                font=("Segoe UI", 11, "bold"),
                anchor="w",
                padx=12,
                pady=8,
            )
            header.pack(fill="x")

            # Items
            items_frame = tk.Frame(root, bg="#181825")
            items_frame.pack(fill="both", expand=True, padx=12, pady=4)

            for idx, item in enumerate(payload.items[:8]):
                badge = item.badge or f"[{idx+1}]"
                sub = f" ({item.subtitle})" if item.subtitle else ""
                txt = f"{badge}  {item.title}{sub}"
                row = tk.Label(
                    items_frame,
                    text=txt,
                    bg="#181825",
                    fg="#cdd6f4",
                    font=("Segoe UI", 10),
                    anchor="w",
                    padx=6,
                    pady=2,
                    cursor="hand2",
                )
                row.pack(fill="x")

                def make_click(i_id=item.id, i_txt=item.title):
                    def on_click(_):
                        if on_action:
                            on_action(
                                PopupActionEvent(
                                    window_id=handle.window_id,
                                    action="select_item",
                                    item_id=i_id,
                                    text_input=i_txt,
                                )
                            )
                        root.destroy()
                    return on_click

                row.bind("<Button-1>", make_click())

            # Footer
            footer_text = "  •  ".join(payload.interactive_actions) if payload.interactive_actions else "[1-8] Select  •  [Esc] Dismiss"
            foot = tk.Label(
                root,
                text=footer_text,
                bg="#11111b",
                fg="#a6adc8",
                font=("Segoe UI", 8),
                pady=4,
            )
            foot.pack(side="bottom", fill="x")

            # Keyboard shortcuts inside popup
            def on_key(e):
                if e.keysym in ("Escape", "esc"):
                    if on_action:
                        on_action(PopupActionEvent(handle.window_id, "dismiss"))
                    root.destroy()
                elif e.char.isdigit() and 1 <= int(e.char) <= len(payload.items):
                    sel_item = payload.items[int(e.char) - 1]
                    if on_action:
                        on_action(
                            PopupActionEvent(
                                window_id=handle.window_id,
                                action="select_item",
                                item_id=sel_item.id,
                                text_input=sel_item.title,
                            )
                        )
                    root.destroy()

            root.bind("<Key>", on_key)
            root.focus_force()

            # Auto close after 25 seconds
            root.after(25000, lambda: root.destroy())
            root.mainloop()
        except Exception as exc:
            log.debug("GUI display skipped: %s", exc)

    t = threading.Thread(target=run_gui, daemon=True)
    t.start()


class OverlayUIManager:
    """Manages creation, updates, coordinate clamping, and dismissal of overlay cards."""

    def __init__(self):
        self.active_popups: Dict[str, PopupHandle] = {}

    def display_popup_card(
        self,
        payload: PopupCardPayload,
        anchor_bounds: ScreenRect,
        screen_size: Optional[Tuple[int, int]] = None,
        on_action: Optional[Callable[[PopupActionEvent], None]] = None,
    ) -> PopupHandle:
        """Positions, records, and reveals the overlay card adjacent to anchor bounds."""
        s_width, s_height = screen_size or get_screen_dimensions()

        # If anchor is default, snap to current mouse cursor
        if anchor_bounds.x == 400 and anchor_bounds.y == 300:
            cx, cy = get_cursor_position()
            anchor_bounds = ScreenRect(x=cx, y=cy, width=anchor_bounds.width, height=anchor_bounds.height)

        bounds = calculate_clamped_bounds(
            anchor=anchor_bounds,
            popup_width=DEFAULT_POPUP_WIDTH,
            popup_height=DEFAULT_POPUP_HEIGHT,
            screen_width=s_width,
            screen_height=s_height,
        )

        window_id = f"popup_{uuid.uuid4().hex[:8]}"
        handle = PopupHandle(
            window_id=window_id,
            is_visible=True,
            bounds=bounds,
            active_payload=payload,
            on_action=on_action,
        )
        self.active_popups[window_id] = handle

        # Launch real floating visual card
        _launch_tkinter_window(handle, payload, bounds, on_action)

        return handle

    def update_popup_content(
        self, window_id: str, new_payload: PopupCardPayload
    ) -> bool:
        """Hot-reloads content in an active overlay without shifting coordinates."""
        if window_id not in self.active_popups:
            return False
        handle = self.active_popups[window_id]
        if not handle.is_visible:
            return False
        handle.active_payload = new_payload
        return True

    def dismiss_popup(self, window_id: str, immediate: bool = True) -> bool:
        """Closes the popup window and marks it invisible."""
        if window_id not in self.active_popups:
            return False
        handle = self.active_popups[window_id]
        handle.is_visible = False
        del self.active_popups[window_id]
        return True

    def handle_user_input(
        self,
        window_id: str,
        key_or_action: str,
        text_input: Optional[str] = None,
    ) -> Optional[PopupActionEvent]:
        """Processes keystroke / action input against active popup items."""
        if window_id not in self.active_popups:
            return None
        handle = self.active_popups[window_id]
        payload = handle.active_payload
        if not payload:
            return None

        event: Optional[PopupActionEvent] = None

        # Number key selection [1-8]
        if key_or_action.isdigit():
            idx = int(key_or_action) - 1
            if 0 <= idx < len(payload.items):
                item = payload.items[idx]
                event = PopupActionEvent(
                    window_id=window_id,
                    action="select_item",
                    item_id=item.id,
                    text_input=item.title,
                )
        elif key_or_action.lower() in ("esc", "escape"):
            self.dismiss_popup(window_id)
            event = PopupActionEvent(window_id=window_id, action="dismiss")
        elif key_or_action.lower() == "enter":
            event = PopupActionEvent(
                window_id=window_id,
                action="submit",
                text_input=text_input,
            )
        else:
            event = PopupActionEvent(
                window_id=window_id,
                action=key_or_action,
                text_input=text_input,
            )

        if event and handle.on_action:
            try:
                handle.on_action(event)
            except Exception as exc:
                log.error("Error in popup action callback: %s", exc)

        return event


_default_overlay_manager = OverlayUIManager()


def display_popup_card(
    payload: PopupCardPayload,
    anchor_bounds: ScreenRect,
    screen_size: Optional[Tuple[int, int]] = None,
    on_action: Optional[Callable[[PopupActionEvent], None]] = None,
) -> PopupHandle:
    return _default_overlay_manager.display_popup_card(
        payload, anchor_bounds, screen_size=screen_size, on_action=on_action
    )


def update_popup_content(window_id: str, new_payload: PopupCardPayload) -> bool:
    return _default_overlay_manager.update_popup_content(window_id, new_payload)


def dismiss_popup(window_id: str, immediate: bool = True) -> bool:
    return _default_overlay_manager.dismiss_popup(window_id, immediate=immediate)
