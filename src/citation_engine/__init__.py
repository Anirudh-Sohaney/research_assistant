"""Citation Engine package for automated academic and web citation generation."""

from citation_engine.cache import CitationCache
from citation_engine.extractors.base import BaseExtractor
from citation_engine.extractors.crossref import CrossrefExtractor
from citation_engine.extractors.headless import HeadlessBrowserExtractor
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
from citation_engine.renderers.bibtex import BibTeXRenderer
from citation_engine.renderers.chicago import ChicagoRenderer
from citation_engine.renderers.ieee import IEEERenderer
from citation_engine.renderers.mla import MLA9Renderer
from citation_engine.service import CitationService

__all__ = [
    "CitationService",
    "CitationCache",
    "BaseExtractor",
    "CrossrefExtractor",
    "MetaJsonLdExtractor",
    "OpenLibraryExtractor",
    "HeadlessBrowserExtractor",
    "BaseStyleRenderer",
    "APA7Renderer",
    "MLA9Renderer",
    "ChicagoRenderer",
    "IEEERenderer",
    "BibTeXRenderer",
    "Author",
    "CitationDate",
    "CitationResult",
    "CitationStyle",
    "FieldConfidence",
    "ReferenceMetadata",
    "SourceType",
]
