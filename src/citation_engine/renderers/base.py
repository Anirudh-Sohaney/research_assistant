"""Base style renderer interface for Citation Engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from citation_engine.models import ReferenceMetadata


class BaseStyleRenderer(ABC):
    """Abstract citation style formatter operating exclusively on ReferenceMetadata."""

    @abstractmethod
    def render_bibliography(self, metadata: ReferenceMetadata) -> str:
        """Renders reference list / bibliography entry in Markdown/plaintext."""
        pass

    @abstractmethod
    def render_in_text(self, metadata: ReferenceMetadata, page_or_loc: Optional[str] = None) -> str:
        """Renders in-text parenthetical citation, e.g. (Vaswani et al., 2017)."""
        pass

    @abstractmethod
    def render_narrative(self, metadata: ReferenceMetadata, page_or_loc: Optional[str] = None) -> str:
        """Renders in-text narrative citation, e.g. Vaswani et al. (2017)."""
        pass
