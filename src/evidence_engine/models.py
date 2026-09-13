"""Evidence Engine v2 — data models for the evidence funnel.

Every object crossing a stage boundary is a frozen dataclass so stages are
pure functions over immutable inputs. `PipelineMeta` carries the full funnel
trace (counts + per-stage timings) for debugging and SLA auditing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Stance(str, Enum):
    """Relationship of a piece of evidence to the claim.

    LIMITS: the sentence backs a restricted version of the claim (boundary
    conditions, subpopulations, dose ranges). Discovered during the NLI gate
    as high-entailment-but-hedged sentences; a first-class output category
    because reviewers value boundary evidence.
    UNVERIFIED: produced only by the degraded path (NLI unavailable).
    """

    SUPPORTS = "supports"
    OPPOSES = "opposes"
    LIMITS = "limits"
    UNVERIFIED = "unverified"


class InvalidClaimError(ValueError):
    """Raised when input text is outside the 4-30 word contract."""


@dataclass(frozen=True)
class PaperRef:
    """Citation identity for the paper a sentence came from."""

    title: str
    authors: str
    year: Optional[int]
    doi: Optional[str]
    url: Optional[str]
    venue: Optional[str] = None
    citation_count: Optional[int] = None
    source: str = ""  # which retrieval source produced it (epmc/openalex/...)
    open_access: bool = False


@dataclass(frozen=True)
class CandidateSentence:
    """One candidate evidence sentence assembled in Stage 2.

    `source_rank` is the rank within its originating source's result list
    (0-based), used by Reciprocal Rank Fusion in Stage 3.
    """

    text: str
    paper: PaperRef
    source: str
    source_rank: int = 0
    in_body: bool = False  # True if from paper body/snippet, False if abstract


@dataclass(frozen=True)
class ScoredSentence:
    """A sentence that survived Stage 3 rule-based filtering."""

    candidate: CandidateSentence
    rrf_score: float
    anchor_score: float
    matched_anchors: tuple = ()


@dataclass(frozen=True)
class StanceScoredSentence:
    """Output of Stage 4: NLI verdict for one sentence."""

    scored: ScoredSentence
    p_entail: float
    p_contradict: float
    p_neutral: float
    stance: Stance
    nli_model: str


@dataclass(frozen=True)
class EvidenceItem:
    """A final, curated piece of evidence: verbatim quote + citation + stance."""

    quote: str
    paper: PaperRef
    stance: Stance
    stance_probs: dict
    relevance_score: float
    nli_model: str
    in_body: bool
    checks: dict = field(default_factory=dict)
    rationale: Optional[str] = None


@dataclass(frozen=True)
class PipelineMeta:
    """Funnel trace: per-stage counts and timings, plus degradation flags."""

    claim: str
    mode: str
    query_variants: list
    funnel: dict
    stage_timings_ms: dict
    sources_report: dict
    nli_backend: str
    degraded: bool = False
    degraded_reason: Optional[str] = None
    total_ms: float = 0.0


@dataclass(frozen=True)
class EvidenceResult:
    """Public return value of supports()/opposes()."""

    claim: str
    mode: str  # "supports" | "opposes"
    items: list  # list[EvidenceItem], target 10
    pipeline_meta: PipelineMeta

    @property
    def consensus_summary(self) -> str:
        by = {"supports": 0, "opposes": 0, "limits": 0, "unverified": 0}
        for it in self.items:
            by[it.stance.value] += 1
        parts = [f"{n} {k}" for k, n in by.items() if n]
        return (
            f"{len(self.items)} items across "
            f"{len({it.paper.doi or it.paper.title for it in self.items})} papers: "
            + ", ".join(parts)
        )


def _fmt_ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000.0, 1)
