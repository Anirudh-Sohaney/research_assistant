"""Citation Engine package for automated academic and web citation generation."""

from citation_engine.cache import CitationCache
from citation_engine.extractors.base import BaseExtractor
from citation_engine.extractors.crossref import CrossrefExtractor
from citation_engine.extractors.meta_jsonld import MetaJsonLdExtractor
from citation_engine.extractors.openlibrary import OpenLibraryExtractor
from citation_engine.models import (
    Author,
    CitationDate,
    CitationResult,
    CitationStyle,
    FieldConfidence,
    ReferenceMetadata,
    SourceType,
)
from citation_engine.renderers.apa import APA7Renderer
from citation_engine.renderers.base import BaseStyleRenderer
from citation_engine.service import CitationService

__all__ = [
    "CitationService",
    "CitationCache",
    "BaseExtractor",
    "CrossrefExtractor",
    "MetaJsonLdExtractor",
    "OpenLibraryExtractor",
    "BaseStyleRenderer",
    "APA7Renderer",
    "Author",
    "CitationDate",
    "CitationResult",
    "CitationStyle",
    "FieldConfidence",
    "ReferenceMetadata",
    "SourceType",
]
