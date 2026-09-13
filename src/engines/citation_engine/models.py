"""Canonical data models for the Citation Engine subsystem."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SourceType(str, Enum):
    """Categorical source type governing style template selection."""
    ACADEMIC_PAPER = "ACADEMIC_PAPER"
    NEWS_ARTICLE = "NEWS_ARTICLE"
    BLOG_POST = "BLOG_POST"
    BOOK = "BOOK"
    BOOK_CHAPTER = "BOOK_CHAPTER"
    WEBPAGE = "WEBPAGE"
    REPORT = "REPORT"


class FieldConfidence(str, Enum):
    """Confidence tier for extracted metadata fields."""
    AUTHORITATIVE = "AUTHORITATIVE"  # 1.0: Crossref, Open Library, Schema.org JSON-LD
    HIGH = "HIGH"                    # 0.85: Standard OpenGraph, Highwire Press, Dublin Core
    MEDIUM = "MEDIUM"                # 0.65: DOM selectors (<time>, byline heuristics)
    LOW = "LOW"                      # 0.40: Inferred from URL path/slug


class CitationStyle(str, Enum):
    """Supported citation styles."""
    APA = "APA"          # 7th Edition
    MLA = "MLA"          # 9th Edition
    CHICAGO = "CHICAGO"  # 17th Edition (Author-Date)
    IEEE = "IEEE"        # Numbered Standard
    HARVARD = "HARVARD"  # Author-Date
    BIBTEX = "BIBTEX"    # Raw BibTeX entry


@dataclass
class Author:
    """Normalized author representation supporting individuals and corporate bodies."""
    family: str                          # e.g., "Vaswani" or "World Health Organization"
    given: str = ""                       # e.g., "Ashish"
    middle: str = ""                      # e.g., "K."
    suffix: str = ""                      # e.g., "Jr.", "III"
    is_corporate: bool = False            # When True, formatted as an indivisible corporate name

    @property
    def full_name(self) -> str:
        if self.is_corporate:
            return self.family
        parts = [self.given, self.middle, self.family]
        if self.suffix:
            parts.append(self.suffix)
        return " ".join(p for p in parts if p).strip()

    def format_inverted(self, initials_only: bool = True) -> str:
        """Formats name as 'Family, G. M.' (APA) or 'Family, Given Middle' (MLA)."""
        if self.is_corporate:
            return self.family

        if initials_only:
            g_init = f"{self.given[0]}." if self.given else ""
            m_init = f"{self.middle[0]}." if self.middle else ""
            inits = " ".join(i for i in (g_init, m_init) if i).strip()
            res = f"{self.family}, {inits}" if inits else self.family
        else:
            given_part = f"{self.given} {self.middle}".strip()
            res = f"{self.family}, {given_part}" if given_part else self.family

        if self.suffix:
            res = f"{res}, {self.suffix}"
        return res.strip()


@dataclass
class CitationDate:
    """Normalized date structure parsed once, formatted per citation style."""
    year: Optional[int] = None
    month: Optional[int] = None           # 1-12
    day: Optional[int] = None             # 1-31
    raw_str: Optional[str] = None
    has_date: bool = True

    def __post_init__(self):
        if self.year is None and not self.raw_str:
            self.has_date = False

    def format_apa(self) -> str:
        """APA 7th: '(2023)' or '(2023, April 15)' or '(n.d.)'."""
        if not self.has_date or self.year is None:
            return "(n.d.)"
        if self.month and self.day:
            import calendar
            month_name = calendar.month_name[self.month]
            return f"({self.year}, {month_name} {self.day})"
        return f"({self.year})"

    def format_mla(self) -> str:
        """MLA 9th: '15 Apr. 2023' or '2023' or 'n.d.'."""
        if not self.has_date or self.year is None:
            return "n.d."
        if self.month and self.day:
            import calendar
            m_abbr = calendar.month_abbr[self.month]
            return f"{self.day} {m_abbr}. {self.year}"
        return str(self.year)


@dataclass
class ReferenceMetadata:
    """Unified normalized metadata schema feeding all downstream citation templates."""
    title: str
    authors: List[Author] = field(default_factory=list)
    date: CitationDate = field(default_factory=lambda: CitationDate(has_date=False))
    source_type: SourceType = SourceType.WEBPAGE

    # Publication & Container Context
    container_title: Optional[str] = None  # Journal name, website name, or book title
    publisher: Optional[str] = None        # Publishing organization or platform
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None            # e.g., "145-160" or "42"
    edition: Optional[str] = None          # e.g., "2nd ed."

    # Identifiers & Location
    doi: Optional[str] = None              # Canonical 10.xxxx/...
    isbn: Optional[str] = None             # Standardized ISBN-10 or 13
    url: Optional[str] = None              # Clean canonical URL
    access_date: Optional[CitationDate] = None

    # Confidence & Provenance
    confidence_score: float = 1.0          # 0.0 - 1.0
    field_confidence: Dict[str, FieldConfidence] = field(default_factory=dict)
    provenance_warnings: List[str] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def is_sufficient(self) -> bool:
        """Evaluates whether metadata is adequate without falling back to headless scraping."""
        has_title = bool(self.title and len(self.title.strip()) > 3)
        has_context = bool(self.authors or self.date.has_date or self.container_title or self.doi)
        return has_title and has_context

    def to_csl_json(self) -> Dict[str, Any]:
        """Serializes normalized schema to standard CSL-JSON for Zotero/Mendeley compatibility."""
        type_mapping = {
            SourceType.ACADEMIC_PAPER: "article-journal",
            SourceType.NEWS_ARTICLE: "article-newspaper",
            SourceType.BLOG_POST: "post-weblog",
            SourceType.BOOK: "book",
            SourceType.BOOK_CHAPTER: "chapter",
            SourceType.WEBPAGE: "webpage",
            SourceType.REPORT: "report",
        }
        csl: Dict[str, Any] = {
            "type": type_mapping.get(self.source_type, "webpage"),
            "title": self.title,
        }

        if self.authors:
            csl["author"] = [
                {"literal": a.family} if a.is_corporate else {"family": a.family, "given": a.given}
                for a in self.authors
            ]

        if self.date.year:
            parts = [self.date.year]
            if self.date.month:
                parts.append(self.date.month)
                if self.date.day:
                    parts.append(self.date.day)
            csl["issued"] = {"date-parts": [parts]}

        if self.container_title:
            csl["container-title"] = self.container_title
        if self.publisher:
            csl["publisher"] = self.publisher
        if self.volume:
            csl["volume"] = self.volume
        if self.issue:
            csl["issue"] = self.issue
        if self.pages:
            csl["page"] = self.pages
        if self.doi:
            csl["DOI"] = self.doi
        if self.isbn:
            csl["ISBN"] = self.isbn
        if self.url:
            csl["URL"] = self.url

        return csl


@dataclass
class CitationResult:
    """Final rendered citation output with metadata and confidence telemetry."""
    bibliography_entry: str               # Formatted reference list entry (Markdown / Plain Text)
    in_text_citation: str                 # In-text parenthetical / numeric callout
    style: CitationStyle
    metadata: ReferenceMetadata
    confidence_score: float = 1.0
    warnings: List[str] = field(default_factory=list)
