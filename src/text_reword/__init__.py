"""Text Reword Subsystem for Research Aid."""

from text_reword.models import (
    RewordStyle,
    SurroundingContext,
    EntityMaskReport,
    RewordResult,
)
from text_reword.reword import (
    TextRewordEngine,
    reword_text_segment,
    mask_scholarly_entities,
    restore_scholarly_entities,
)

__all__ = [
    "RewordStyle",
    "SurroundingContext",
    "EntityMaskReport",
    "RewordResult",
    "TextRewordEngine",
    "reword_text_segment",
    "mask_scholarly_entities",
    "restore_scholarly_entities",
]
