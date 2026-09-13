"""Open Library REST API extractor for ISBN book metadata."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from engines.citation_engine.extractors.base import BaseExtractor
from engines.citation_engine.models import (
    Author,
    CitationDate,
    FieldConfidence,
    ReferenceMetadata,
    SourceType,
)
from engines.citation_engine.normalizer import (
    clean_isbn,
    parse_author,
    parse_date_string,
    sanitize_title,
)

log = logging.getLogger("citation_engine.openlibrary")

OPEN_LIBRARY_API_BASE = "https://openlibrary.org/api/books"


class OpenLibraryExtractor(BaseExtractor):
    """Metadata resolver for books and volumes via Open Library API."""

    def __init__(self, timeout_secs: float = 6.0):
        self._timeout = timeout_secs
        self._headers = {
            "User-Agent": "ResearchAssistant/1.0 (mailto:research-assistant@users.noreply.github.com)",
            "Accept": "application/json",
        }

    def can_handle(self, target: str) -> bool:
        return bool(clean_isbn(target))

    async def extract(self, target: str) -> Optional[ReferenceMetadata]:
        isbn = clean_isbn(target)
        if not isbn:
            return None

        bibkey = f"ISBN:{isbn}"
        params = {
            "bibkeys": bibkey,
            "format": "json",
            "jscmd": "data",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                resp = await client.get(OPEN_LIBRARY_API_BASE, params=params, headers=self._headers)
                if resp.status_code != 200:
                    log.debug("OpenLibrary returned status %s for ISBN %s", resp.status_code, isbn)
                    return None
                data = resp.json()
        except Exception as exc:
            log.debug("OpenLibrary request failed for ISBN %s: %s", isbn, exc)
            return None

        book_data = data.get(bibkey)
        if not book_data:
            return None

        return self._map_data_to_metadata(book_data, isbn)

    def _map_data_to_metadata(self, data: Dict[str, Any], canonical_isbn: str) -> ReferenceMetadata:
        title = sanitize_title(data.get("title", "Untitled Book"))

        authors: List[Author] = []
        for a_dict in data.get("authors", []):
            name = a_dict.get("name", "").strip()
            if name:
                authors.append(parse_author(name))

        # Date
        raw_pub_date = data.get("publish_date")
        date = parse_date_string(raw_pub_date)

        # Publisher
        publishers = data.get("publishers", [])
        publisher_name = publishers[0].get("name").strip() if publishers and publishers[0].get("name") else None

        # Number of pages
        pages = str(data.get("number_of_pages")) if data.get("number_of_pages") else None

        # URL
        url = data.get("url")

        field_conf = {
            "title": FieldConfidence.AUTHORITATIVE,
            "authors": FieldConfidence.AUTHORITATIVE,
            "date": FieldConfidence.AUTHORITATIVE if date.has_date else FieldConfidence.LOW,
            "publisher": FieldConfidence.AUTHORITATIVE if publisher_name else FieldConfidence.LOW,
            "isbn": FieldConfidence.AUTHORITATIVE,
        }

        return ReferenceMetadata(
            title=title,
            authors=authors,
            date=date,
            source_type=SourceType.BOOK,
            publisher=publisher_name,
            pages=pages,
            isbn=canonical_isbn,
            url=url,
            confidence_score=0.95,
            field_confidence=field_conf,
            raw_data=data,
        )
