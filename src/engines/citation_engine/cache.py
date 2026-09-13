"""Canonical caching layer for normalized reference metadata."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Dict, Optional, Tuple

from engines.citation_engine.models import Author, CitationDate, FieldConfidence, ReferenceMetadata, SourceType
from engines.citation_engine.normalizer import clean_doi, clean_isbn, clean_url

log = logging.getLogger("citation_engine.cache")


class CitationCache:
    """Two-tier (In-Memory LRU + Optional Disk Cache) canonical cache."""

    def __init__(self, max_size: int = 1000, disk_dir: Optional[str] = None):
        self._max_size = max_size
        self._memory_cache: Dict[str, Tuple[float, ReferenceMetadata]] = {}
        self._disk_dir = disk_dir

        if self._disk_dir:
            try:
                os.makedirs(self._disk_dir, exist_ok=True)
            except Exception as exc:
                log.debug("Could not create citation disk cache directory: %s", exc)
                self._disk_dir = None

    def get_canonical_key(
        self,
        query: str,
        doi: Optional[str] = None,
        isbn: Optional[str] = None,
        url: Optional[str] = None,
    ) -> str:
        """Derives a normalized canonical key from DOI, ISBN, or clean URL."""
        if doi:
            c_doi = clean_doi(doi)
            if c_doi:
                return f"doi:{c_doi.lower()}"

        if isbn:
            c_isbn = clean_isbn(isbn)
            if c_isbn:
                return f"isbn:{c_isbn}"

        if url:
            c_url = clean_url(url)
            if c_url:
                return f"url:{c_url}"

        # Fallback to normalized query string
        q_clean = query.strip().lower()
        c_doi = clean_doi(q_clean)
        if c_doi:
            return f"doi:{c_doi.lower()}"

        c_isbn = clean_isbn(q_clean)
        if c_isbn:
            return f"isbn:{c_isbn}"

        return f"q:{hashlib.sha256(q_clean.encode('utf-8')).hexdigest()[:16]}"

    def get(self, key: str) -> Optional[ReferenceMetadata]:
        """Retrieves cached metadata by canonical key."""
        c_key = self.get_canonical_key(key)
        # 1. Memory cache check
        for k in (c_key, key):
            if k in self._memory_cache:
                ts, meta = self._memory_cache[k]
                del self._memory_cache[k]
                self._memory_cache[c_key] = (time.time(), meta)
                return meta

        # 2. Disk cache check
        if self._disk_dir:
            file_path = os.path.join(self._disk_dir, f"{hashlib.md5(c_key.encode()).hexdigest()}.json")
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    meta = self._deserialize(data)
                    self.put(c_key, meta)  # Promote to memory
                    return meta
                except Exception as exc:
                    log.debug("Failed to read disk cache for %s: %s", c_key, exc)

        return None

    def put(self, key: str, metadata: ReferenceMetadata) -> None:
        """Stores normalized metadata in memory and disk."""
        c_key = self.get_canonical_key(key)
        if len(self._memory_cache) >= self._max_size:
            # Evict oldest
            oldest_key = next(iter(self._memory_cache))
            del self._memory_cache[oldest_key]

        self._memory_cache[c_key] = (time.time(), metadata)

        # Persist to disk
        if self._disk_dir:
            file_path = os.path.join(self._disk_dir, f"{hashlib.md5(c_key.encode()).hexdigest()}.json")
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(self._serialize(metadata), f)
            except Exception as exc:
                log.debug("Failed to write disk cache for %s: %s", c_key, exc)

    set = put

    def _serialize(self, meta: ReferenceMetadata) -> Dict:
        return {
            "title": meta.title,
            "authors": [
                {
                    "family": a.family,
                    "given": a.given,
                    "middle": a.middle,
                    "suffix": a.suffix,
                    "is_corporate": a.is_corporate,
                }
                for a in meta.authors
            ],
            "date": {
                "year": meta.date.year,
                "month": meta.date.month,
                "day": meta.date.day,
                "raw_str": meta.date.raw_str,
                "has_date": meta.date.has_date,
            },
            "source_type": meta.source_type.value,
            "container_title": meta.container_title,
            "publisher": meta.publisher,
            "volume": meta.volume,
            "issue": meta.issue,
            "pages": meta.pages,
            "doi": meta.doi,
            "isbn": meta.isbn,
            "url": meta.url,
            "confidence_score": meta.confidence_score,
            "field_confidence": {k: v.value for k, v in meta.field_confidence.items()},
            "provenance_warnings": meta.provenance_warnings,
        }

    def _deserialize(self, d: Dict) -> ReferenceMetadata:
        authors = [
            Author(
                family=a.get("family", ""),
                given=a.get("given", ""),
                middle=a.get("middle", ""),
                suffix=a.get("suffix", ""),
                is_corporate=a.get("is_corporate", False),
            )
            for a in d.get("authors", [])
        ]
        dt = d.get("date", {})
        date = CitationDate(
            year=dt.get("year"),
            month=dt.get("month"),
            day=dt.get("day"),
            raw_str=dt.get("raw_str"),
            has_date=dt.get("has_date", True),
        )
        return ReferenceMetadata(
            title=d.get("title", "Untitled"),
            authors=authors,
            date=date,
            source_type=SourceType(d.get("source_type", SourceType.WEBPAGE.value)),
            container_title=d.get("container_title"),
            publisher=d.get("publisher"),
            volume=d.get("volume"),
            issue=d.get("issue"),
            pages=d.get("pages"),
            doi=d.get("doi"),
            isbn=d.get("isbn"),
            url=d.get("url"),
            confidence_score=float(d.get("confidence_score", 1.0)),
            field_confidence={k: FieldConfidence(v) for k, v in d.get("field_confidence", {}).items()},
            provenance_warnings=d.get("provenance_warnings", []),
        )
