"""Citation Engine package for automated academic and web citation generation."""

from engines.citation_engine.cache import CitationCache
from engines.citation_engine.extractors.base import BaseExtractor
from engines.citation_engine.extractors.crossref import CrossrefExtractor
from engines.citation_engine.extractors.headless import HeadlessBrowserExtractor
from engines.citation_engine.extractors.meta_jsonld import MetaJsonLdExtractor
from engines.citation_engine.extractors.openlibrary import OpenLibraryExtractor
from engines.citation_engine.models import (
    Author,
    CitationDate,
    CitationResult,
    CitationStyle,
    FieldConfidence,
    ReferenceMetadata,
    SourceType,
)
from engines.citation_engine.renderers.apa import APA7Renderer
from engines.citation_engine.renderers.base import BaseStyleRenderer
from engines.citation_engine.renderers.bibtex import BibTeXRenderer
from engines.citation_engine.renderers.chicago import ChicagoRenderer
from engines.citation_engine.renderers.ieee import IEEERenderer
from engines.citation_engine.renderers.mla import MLA9Renderer
from engines.citation_engine.service import CitationService

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
