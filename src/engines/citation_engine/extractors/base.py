"""Abstract base extractor interface for Citation Engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from engines.citation_engine.models import ReferenceMetadata


class BaseExtractor(ABC):
    """Stateless, decoupled extractor converting raw sources into ReferenceMetadata."""

    @abstractmethod
    async def extract(self, target: str) -> Optional[ReferenceMetadata]:
        """Extracts and normalizes metadata from target (URL, DOI, or ISBN)."""
        pass

    @abstractmethod
    def can_handle(self, target: str) -> bool:
        """Predicate checking if this extractor is suitable for the given target."""
        pass
