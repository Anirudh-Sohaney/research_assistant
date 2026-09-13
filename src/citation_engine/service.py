"""Unified citation service orchestrating cache, extractors, and style renderers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from citation_engine.cache import CitationCache
from citation_engine.extractors.crossref import CrossrefExtractor
from citation_engine.extractors.meta_jsonld import MetaJsonLdExtractor
from citation_engine.extractors.openlibrary import OpenLibraryExtractor
from citation_engine.models import (
    CitationResult,
    CitationStyle,
    ReferenceMetadata,
)
from citation_engine.normalizer import clean_doi, clean_isbn, clean_url
from citation_engine.renderers.apa import APA7Renderer
from citation_engine.renderers.base import BaseStyleRenderer

log = logging.getLogger("citation_engine.service")


class CitationService:
    """End-to-end orchestrator resolving URLs, DOIs, and ISBNs into formatted citations."""

    def __init__(
        self,
        cache: Optional[CitationCache] = None,
        timeout_secs: float = 8.0,
    ):
        self.cache = cache or CitationCache()
        self.crossref = CrossrefExtractor(timeout_secs=timeout_secs)
        self.openlibrary = OpenLibraryExtractor(timeout_secs=timeout_secs)
        self.meta_jsonld = MetaJsonLdExtractor(timeout_secs=timeout_secs)

        # Style renderers registry
        self._renderers: Dict[CitationStyle, BaseStyleRenderer] = {
            CitationStyle.APA: APA7Renderer(),
        }

    def register_renderer(self, style: CitationStyle, renderer: BaseStyleRenderer):
        """Allows registering new style renderers dynamically without modifying extractors."""
        self._renderers[style] = renderer

    async def get_metadata(self, target: str) -> Optional[ReferenceMetadata]:
        """Resolves target to normalized ReferenceMetadata, using cache if available."""
        target_str = (target or "").strip()
        if not target_str:
            return None

        # 1. Check cache
        cached = self.cache.get(target_str)
        if cached:
            return cached

        # 2. Check if DOI
        doi = clean_doi(target_str)
        if doi:
            meta = await self.crossref.extract(doi)
            if meta:
                self.cache.set(doi, meta)
                return meta

        # 3. Check if ISBN
        isbn = clean_isbn(target_str)
        if isbn:
            meta = await self.openlibrary.extract(isbn)
            if meta:
                self.cache.set(isbn, meta)
                return meta

        # 4. Handle HTTP/HTTPS URL
        clean_target_url = clean_url(target_str)
        if clean_target_url and (clean_target_url.startswith("http://") or clean_target_url.startswith("https://")):
            # Check if URL directly contains a DOI (e.g. https://doi.org/10.1038/...)
            url_doi = clean_doi(clean_target_url)
            if url_doi and "doi.org" in clean_target_url.lower():
                meta = await self.crossref.extract(url_doi)
                if meta:
                    self.cache.set(clean_target_url, meta)
                    return meta

            meta = await self.meta_jsonld.extract(clean_target_url)
            if meta:
                # If extracted metadata discovered a DOI that Crossref can enhance
                if meta.doi and not meta.authors:
                    crossref_meta = await self.crossref.extract(meta.doi)
                    if crossref_meta:
                        meta = crossref_meta

                self.cache.set(clean_target_url, meta)
                return meta

        return None

    async def cite(
        self,
        target: str,
        style: CitationStyle = CitationStyle.APA,
        page_or_loc: Optional[str] = None,
    ) -> CitationResult:
        """Extracts metadata and renders a styled citation with full error isolation."""
        metadata = await self.get_metadata(target)
        if not metadata:
            # Fallback for completely unreachable or unparseable target
            empty_meta = ReferenceMetadata(
                title=f"Source: {target}",
                url=clean_url(target) if target.startswith("http") else None,
                confidence_score=0.1,
                provenance_warnings=["Failed to resolve metadata from target identifier or URL"],
            )
            return CitationResult(
                bibliography_entry=empty_meta.title,
                in_text_citation=f"({target})",
                style=style,
                metadata=empty_meta,
                confidence_score=0.1,
                warnings=empty_meta.provenance_warnings,
            )

        # Rendering with isolated error boundaries
        renderer = self._renderers.get(style)
        if not renderer:
            # Fallback to APA if style not registered yet
            renderer = self._renderers[CitationStyle.APA]

        bib_entry = ""
        in_text = ""
        warnings = list(metadata.provenance_warnings)

        try:
            bib_entry = renderer.render_bibliography(metadata)
        except Exception as exc:
            log.exception("Renderer error for bibliography (%s): %s", style, exc)
            bib_entry = f"{metadata.title}. {metadata.url or ''}".strip()
            warnings.append(f"Style formatting warning for {style}: {exc}")

        try:
            in_text = renderer.render_in_text(metadata, page_or_loc=page_or_loc)
        except Exception as exc:
            log.exception("Renderer error for in-text (%s): %s", style, exc)
            in_text = f"({metadata.title[:20]})"
            warnings.append(f"In-text formatting warning for {style}: {exc}")

        return CitationResult(
            bibliography_entry=bib_entry,
            in_text_citation=in_text,
            style=style,
            metadata=metadata,
            confidence_score=metadata.confidence_score,
            warnings=warnings,
        )

    async def batch_cite(
        self,
        targets: List[str],
        style: CitationStyle = CitationStyle.APA,
        max_concurrency: int = 6,
    ) -> List[CitationResult]:
        """Resolves and renders multiple citations concurrently with bounded concurrency."""
        sem = asyncio.Semaphore(max_concurrency)

        async def _bounded_cite(target: str) -> CitationResult:
            async with sem:
                return await self.cite(target, style=style)

        tasks = [_bounded_cite(t) for t in targets]
        return await asyncio.gather(*tasks)
