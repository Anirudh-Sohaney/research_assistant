"""Evidence Engine — Part 1 data models.

Only what paper extraction needs: an immutable reference to a paper and the
per-source retrieval report. Stance/evidence models arrive in later parts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class PaperRef:
    """Normalized identity of one paper, independent of which source produced it.

    `source` records the adapter that yielded this row (first source wins on
    cross-source duplicates, keyed by DOI when present).
    """

    title: str
    authors: str
    year: Optional[int]
    doi: Optional[str]
    url: Optional[str]
    venue: Optional[str] = None
    citation_count: Optional[int] = None
    abstract: str = ""
    open_access: bool = False
    source: str = ""


@dataclass
class SourceReport:
    """Outcome of one source adapter run — never an exception."""

    name: str
    papers: int = 0
    status: str = "ok"  # "ok" | "ok (N/M variants failed)" | "degraded: ..."

    def as_dict(self) -> dict:
        return {"papers": self.papers, "status": self.status}


@dataclass
class RetrievalResult:
    """Aggregate Stage-1 output: papers + per-source report + wall time."""

    papers: list  # list[PaperRef]
    sources: dict = field(default_factory=dict)  # name -> SourceReport.as_dict()
    wall_ms: float = 0.0

    def summary(self) -> str:
        src = ", ".join(f"{k}={v['papers']}" for k, v in self.sources.items())
        return (f"{len(self.papers)} unique papers in {self.wall_ms:.0f} ms "
                f"[{src}]")
