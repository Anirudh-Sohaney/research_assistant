"""Headless browser fallback extractor for JavaScript-rendered SPAs and dynamic pages.

Added last in the extraction hierarchy: only invoked when lightweight static fetch
and API lookups fail to extract sufficient metadata.
"""

from __future__ import annotations

import importlib.util
import logging
from typing import Optional

from citation_engine.extractors.base import BaseExtractor
from citation_engine.extractors.meta_jsonld import HeadHTMLParser, MetaJsonLdExtractor
from citation_engine.models import FieldConfidence, ReferenceMetadata
from citation_engine.normalizer import clean_url

log = logging.getLogger("citation_engine.headless")


class HeadlessBrowserExtractor(BaseExtractor):
    """Costly fallback using headless Playwright browser to render JS-driven pages."""

    def __init__(self, timeout_secs: float = 12.0):
        self._timeout = timeout_secs
        self._parser_helper = MetaJsonLdExtractor()

    @classmethod
    def is_available(cls) -> bool:
        """Verifies whether Playwright is installed in the current environment."""
        return importlib.util.find_spec("playwright") is not None

    def can_handle(self, target: str) -> bool:
        clean = (target or "").strip().lower()
        return clean.startswith("http://") or clean.startswith("https://")

    async def extract(self, target: str) -> Optional[ReferenceMetadata]:
        url = clean_url(target)
        if not url:
            return None

        if not self.is_available():
            log.info(
                "Headless browser fallback skipped for %s: 'playwright' is not installed in the environment.",
                url,
            )
            return None

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return None

        log.info("Triggering headless browser fallback for JS-rendered target: %s", url)

        try:
            async with async_playwright() as p:
                # Launch lightweight chromium instance
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 (ResearchAssistantBot/1.0)"
                    ),
                    viewport={"width": 1280, "height": 720},
                )

                # Route-block heavy resources (images, media, stylesheets, fonts) to minimize CPU/bandwidth
                page = await context.new_page()
                await page.route(
                    "**/*",
                    lambda route: route.abort()
                    if route.request.resource_type in {"image", "media", "font", "stylesheet"}
                    else route.continue_(),
                )

                # Navigate with bounded timeout
                await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout * 1000)

                # Wait for any deferred client-side JSON-LD or title rendering
                try:
                    await page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass  # Non-fatal if networkidle times out; proceed with DOM snapshot

                html_content = await page.content()
                final_url = page.url

                await context.close()
                await browser.close()

                if not html_content.strip():
                    return None

                parser = HeadHTMLParser()
                parser.feed(html_content)

                metadata = self._parser_helper.parse_html_metadata(
                    html_parser=parser,
                    canonical_url=final_url,
                )

                if metadata:
                    metadata.provenance_warnings.append(
                        "Extracted via headless browser fallback (JS-rendered page)"
                    )
                    # Slightly lower confidence than pure static structured metadata
                    metadata.confidence_score = min(metadata.confidence_score, 0.75)

                return metadata

        except Exception as exc:
            log.warning("Headless browser fallback failed for %s: %s", url, exc)
            return None
