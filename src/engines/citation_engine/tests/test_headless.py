"""Tests for headless browser fallback mechanism."""

import asyncio
from unittest.mock import AsyncMock, patch

from engines.citation_engine.extractors.headless import HeadlessBrowserExtractor
from engines.citation_engine.models import Author, CitationDate, ReferenceMetadata, SourceType
from engines.citation_engine.service import CitationService


def test_headless_is_available_guard():
    extractor = HeadlessBrowserExtractor()
    # In an environment without playwright, is_available returns False gracefully
    assert isinstance(extractor.is_available(), bool)
    assert extractor.can_handle("https://spa-react-app.com/post/123")
    assert not extractor.can_handle("10.1038/nature12345")


def test_service_triggers_headless_fallback_when_static_insufficient():
    async def _run():
        service = CitationService()

        # Mock static meta_jsonld to return sparse / insufficient metadata
        insufficient_meta = ReferenceMetadata(
            title="",  # Missing title
            authors=[],
            date=CitationDate(has_date=False),
        )
        assert not insufficient_meta.is_sufficient()

        # Mock headless extractor to return recovered rich metadata
        recovered_meta = ReferenceMetadata(
            title="Rendered Single Page App Title",
            authors=[Author(family="Smith", given="Bob")],
            date=CitationDate(year=2024, has_date=True),
            source_type=SourceType.WEBPAGE,
            confidence_score=0.75,
            provenance_warnings=["Extracted via headless browser fallback (JS-rendered page)"],
        )

        with patch.object(service.meta_jsonld, "extract", new=AsyncMock(return_value=insufficient_meta)):
            with patch.object(service.headless, "extract", new=AsyncMock(return_value=recovered_meta)):
                res = await service.cite("https://spa-app.com/article/1")

                assert res.metadata.title == "Rendered Single Page App Title"
                assert "Smith, B. (2024)." in res.bibliography_entry
                assert any("headless browser fallback" in w for w in res.warnings)

    asyncio.run(_run())
