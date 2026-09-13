"""Crossref REST API extractor for academic DOIs."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from citation_engine.extractors.base import BaseExtractor
from citation_engine.models import (
    Author,
    CitationDate,
    FieldConfidence,
    ReferenceMetadata,
    SourceType,
)
from citation_engine.normalizer import clean_doi, parse_authors_list, sanitize_title

log = logging.getLogger("citation_engine.crossref")

CROSSREF_API_BASE = "https://api.crossref.org/works"
CROSSREF_USER_AGENT = "ResearchAssistant/1.0 (mailto:research-assistant@users.noreply.github.com)"


class CrossrefExtractor(BaseExtractor):
    """Authoritative metadata resolver for academic publications via Crossref API."""

    def __init__(self, timeout_secs: float = 6.0):
        self._timeout = timeout_secs
        self._headers = {
            "User-Agent": CROSSREF_USER_AGENT,
            "Accept": "application/json",
        }

    def can_handle(self, target: str) -> bool:
        return bool(clean_doi(target))

    async def extract(self, target: str) -> Optional[ReferenceMetadata]:
        doi = clean_doi(target)
        if not doi:
            return None

        url = f"{CROSSREF_API_BASE}/{doi}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                resp = await client.get(url, headers=self._headers)
                if resp.status_code != 200:
                    log.debug("Crossref returned status %s for DOI %s", resp.status_code, doi)
                    return None
                data = resp.json()
        except Exception as exc:
            log.debug("Crossref lookup failed for DOI %s: %s", doi, exc)
            return None

        message = data.get("message", {})
        return self._map_message_to_metadata(message, doi)

    async def batch_extract(self, targets: List[str], max_concurrency: int = 8) -> List[Optional[ReferenceMetadata]]:
        """Resolves multiple DOIs concurrently with polite pool throttling."""
        sem = asyncio.Semaphore(max_concurrency)

        async def _bounded_extract(target: str) -> Optional[ReferenceMetadata]:
            async with sem:
                return await self.extract(target)

        tasks = [_bounded_extract(t) for t in targets]
        return await asyncio.gather(*tasks, return_exceptions=False)

    def _map_message_to_metadata(self, msg: Dict[str, Any], canonical_doi: str) -> ReferenceMetadata:
        # 1. Title
        raw_titles = msg.get("title", [])
        title_str = raw_titles[0] if raw_titles else "Untitled Academic Paper"
        title = sanitize_title(title_str)

        # 2. Authors
        authors: List[Author] = []
        for a_dict in msg.get("author", []):
            family = a_dict.get("family", "").strip()
            given = a_dict.get("given", "").strip()
            if family:
                # Check for corporate name in family field
                if not given and " " in family:
                    authors.append(parse_authors_list(family)[0])
                else:
                    authors.append(Author(family=family, given=given, is_corporate=False))
            elif a_dict.get("name"):
                authors.append(Author(family=a_dict["name"].strip(), is_corporate=True))

        # 3. Date
        date_parts = (
            msg.get("published-print", {}).get("date-parts")
            or msg.get("published-online", {}).get("date-parts")
            or msg.get("created", {}).get("date-parts")
        )
        date = CitationDate(has_date=False)
        if date_parts and date_parts[0]:
            parts = date_parts[0]
            year = parts[0] if len(parts) >= 1 else None
            month = parts[1] if len(parts) >= 2 else None
            day = parts[2] if len(parts) >= 3 else None
            date = CitationDate(year=year, month=month, day=day, has_date=bool(year))

        # 4. Container & Publication metadata
        containers = msg.get("container-title", [])
        container_title = containers[0].strip() if containers else None
        publisher = msg.get("publisher")
        volume = str(msg["volume"]).strip() if msg.get("volume") else None
        issue = str(msg["issue"]).strip() if msg.get("issue") else None
        pages = str(msg["page"]).strip() if msg.get("page") else None
        doi_url = msg.get("URL") or f"https://doi.org/{canonical_doi}"

        # 5. Type detection
        csl_type = msg.get("type", "")
        if "book" in csl_type and "chapter" not in csl_type:
            src_type = SourceType.BOOK
        elif "chapter" in csl_type:
            src_type = SourceType.BOOK_CHAPTER
        else:
            src_type = SourceType.ACADEMIC_PAPER

        field_conf = {
            "title": FieldConfidence.AUTHORITATIVE,
            "authors": FieldConfidence.AUTHORITATIVE,
            "date": FieldConfidence.AUTHORITATIVE,
            "container_title": FieldConfidence.AUTHORITATIVE,
            "doi": FieldConfidence.AUTHORITATIVE,
        }

        return ReferenceMetadata(
            title=title,
            authors=authors,
            date=date,
            source_type=src_type,
            container_title=container_title,
            publisher=publisher,
            volume=volume,
            issue=issue,
            pages=pages,
            doi=canonical_doi,
            url=doi_url,
            confidence_score=1.0,
            field_confidence=field_conf,
            raw_data=msg,
        )
