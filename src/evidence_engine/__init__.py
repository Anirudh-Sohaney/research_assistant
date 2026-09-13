"""Evidence Engine v2 — public surface.

    from evidence_engine import supports, opposes

    result = supports("Regular aerobic exercise improves executive function in older adults")
    for item in result.items:
        print(item.stance.value, "|", item.paper.title, "|", item.quote)

See README.md for the full architecture plan and implementation status.
"""

from evidence_engine.models import (
    CandidateSentence,
    EvidenceItem,
    EvidenceResult,
    InvalidClaimError,
    PaperRef,
    PipelineMeta,
    ScoredSentence,
    Stance,
    StanceScoredSentence,
)
from evidence_engine.pipeline import opposes, supports
from evidence_engine import nli as _nli

# Prewarm the NLI backend at import time (README section 8.2: "model warm at
# app start"): download + ORT session + cold-start inference happen in a
# daemon thread, completely off any supports()/opposes() call's SLA clock.
# Tests and callers that need the backend synchronously call nli.ensure_loaded().
import threading as _threading

_threading.Thread(target=_nli.ensure_loaded, name="nli-prewarm", daemon=True).start()

__all__ = [
    "supports",
    "opposes",
    "Stance",
    "EvidenceItem",
    "EvidenceResult",
    "PaperRef",
    "PipelineMeta",
    "InvalidClaimError",
    "CandidateSentence",
    "ScoredSentence",
    "StanceScoredSentence",
]
