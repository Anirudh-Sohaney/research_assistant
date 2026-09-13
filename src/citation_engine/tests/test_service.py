"""Tests for CitationService orchestrator and caching."""

import asyncio

from citation_engine.cache import CitationCache
from citation_engine.models import Author, CitationDate, CitationStyle, ReferenceMetadata, SourceType
from citation_engine.renderers.base import BaseStyleRenderer
from citation_engine.service import CitationService


def test_citation_service_cache_hit():
    async def _run():
        cache = CitationCache()
        cached_meta = ReferenceMetadata(
            title="Attention Is All You Need",
            authors=[Author(family="Vaswani", given="Ashish")],
            date=CitationDate(year=2017, has_date=True),
            doi="10.5555/3295222.3295349",
            source_type=SourceType.ACADEMIC_PAPER,
        )
        cache.set("10.5555/3295222.3295349", cached_meta)

        service = CitationService(cache=cache)
        result = await service.cite("10.5555/3295222.3295349", style=CitationStyle.APA)

        assert result.metadata.title == "Attention Is All You Need"
        assert "Vaswani, A. (2017)." in result.bibliography_entry
        assert result.in_text_citation == "(Vaswani, 2017)"

    asyncio.run(_run())


def test_citation_service_renderer_error_boundary():
    async def _run():
        cache = CitationCache()
        meta = ReferenceMetadata(
            title="Fault Tolerant Citation",
            authors=[Author(family="Turing", given="Alan")],
            date=CitationDate(year=1950, has_date=True),
            doi="10.1093/mind/LIX.236.433",
        )
        cache.set("10.1093/mind/LIX.236.433", meta)

        service = CitationService(cache=cache)

        # Register a broken renderer
        class BrokenRenderer(BaseStyleRenderer):
            def render_bibliography(self, metadata: ReferenceMetadata) -> str:
                raise RuntimeError("Renderer explosion!")

            def render_in_text(self, metadata: ReferenceMetadata, page_or_loc=None) -> str:
                raise RuntimeError("In-text explosion!")

            def render_narrative(self, metadata: ReferenceMetadata, page_or_loc=None) -> str:
                raise RuntimeError("Narrative explosion!")

        service.register_renderer(CitationStyle.MLA, BrokenRenderer())

        # Rendering in MLA should NOT raise exception, should return fallback and warning
        res = await service.cite("10.1093/mind/LIX.236.433", style=CitationStyle.MLA)

        assert res.metadata.title == "Fault Tolerant Citation"
        assert "Fault Tolerant Citation" in res.bibliography_entry
        assert any("explosion" in w for w in res.warnings)

    asyncio.run(_run())
