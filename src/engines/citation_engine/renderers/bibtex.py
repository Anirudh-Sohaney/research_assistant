"""BibTeX citation exporter."""

from __future__ import annotations

import re
from typing import List, Optional

from engines.citation_engine.models import Author, ReferenceMetadata, SourceType
from engines.citation_engine.renderers.base import BaseStyleRenderer


class BibTeXRenderer(BaseStyleRenderer):
    """Generates standard RFC-compliant BibTeX entries."""

    def render_bibliography(self, metadata: ReferenceMetadata) -> str:
        entry_type = self._determine_entry_type(metadata.source_type)
        cite_key = self._generate_cite_key(metadata)

        fields: List[str] = []
        fields.append(f"  title = {{{metadata.title}}}")

        if metadata.authors:
            authors_bib = " and ".join(
                a.family if a.is_corporate else f"{a.family}, {a.given}".strip(", ")
                for a in metadata.authors
            )
            fields.append(f"  author = {{{authors_bib}}}")

        if metadata.date.has_date and metadata.date.year:
            fields.append(f"  year = {{{metadata.date.year}}}")
            if metadata.date.month:
                import calendar
                m_abbr = calendar.month_abbr[metadata.date.month].lower()
                fields.append(f"  month = {{{m_abbr}}}")

        if metadata.container_title:
            if entry_type == "article":
                fields.append(f"  journal = {{{metadata.container_title}}}")
            else:
                fields.append(f"  booktitle = {{{metadata.container_title}}}")

        if metadata.volume:
            fields.append(f"  volume = {{{metadata.volume}}}")
        if metadata.issue:
            fields.append(f"  number = {{{metadata.issue}}}")
        if metadata.pages:
            fields.append(f"  pages = {{{metadata.pages}}}")
        if metadata.publisher:
            fields.append(f"  publisher = {{{metadata.publisher}}}")
        if metadata.doi:
            fields.append(f"  doi = {{{metadata.doi}}}")
        if metadata.url:
            fields.append(f"  url = {{{metadata.url}}}")

        fields_body = ",\n".join(fields)
        return f"@{entry_type}{{{cite_key},\n{fields_body}\n}}"

    def render_in_text(self, metadata: ReferenceMetadata, page_or_loc: Optional[str] = None) -> str:
        key = self._generate_cite_key(metadata)
        if page_or_loc:
            return f"\\cite[{page_or_loc.strip()}]{{{key}}}"
        return f"\\cite{{{key}}}"

    def render_narrative(self, metadata: ReferenceMetadata, page_or_loc: Optional[str] = None) -> str:
        key = self._generate_cite_key(metadata)
        if page_or_loc:
            return f"\\citet[{page_or_loc.strip()}]{{{key}}}"
        return f"\\citet{{{key}}}"

    def _determine_entry_type(self, source_type: SourceType) -> str:
        if source_type == SourceType.ACADEMIC_PAPER:
            return "article"
        if source_type == SourceType.BOOK:
            return "book"
        if source_type == SourceType.BOOK_CHAPTER:
            return "incollection"
        return "misc"

    def _generate_cite_key(self, metadata: ReferenceMetadata) -> str:
        lead = ""
        if metadata.authors:
            first_author = metadata.authors[0].family
            lead = re.sub(r"\W+", "", first_author)
        else:
            first_word = metadata.title.split()[0] if metadata.title else "source"
            lead = re.sub(r"\W+", "", first_word)

        year = str(metadata.date.year) if metadata.date.has_date and metadata.date.year else "nodate"
        return f"{lead.lower()}{year}"
