"""Text Injector Subsystem for Research Aid."""

from text_injector.models import InjectionResult, InjectionTier, WindowMetadata
from text_injector.injector import (
    TextInjector,
    inject_text_replacement,
    inject_rich_content,
    revert_last_injection,
    double_click_at_cursor,
    type_text_high_speed,
    replace_hovered_word_with_text,
    backspace_and_type,
)

__all__ = [
    "InjectionResult",
    "InjectionTier",
    "WindowMetadata",
    "TextInjector",
    "inject_text_replacement",
    "inject_rich_content",
    "revert_last_injection",
    "double_click_at_cursor",
    "type_text_high_speed",
    "replace_hovered_word_with_text",
    "backspace_and_type",
]
