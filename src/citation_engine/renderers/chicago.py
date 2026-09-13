"""Chicago 17th Edition (Author-Date) citation style renderer."""

from __future__ import annotations

from typing import List, Optional

from citation_engine.models import Author, ReferenceMetadata, SourceType
from citation_engine.renderers.base import BaseStyleRenderer
from citation_engine.renderers.mla import to_title_case


class ChicagoRenderer(BaseStyleRenderer):
    """Chicago 17th Edition (Author-Date) style implementation."""

    def render_bibliography(self, metadata: ReferenceMetadata) -> str:
        authors_str = self._format_authors(metadata.authors)
        year_str = str(metadata.date.year) if metadata.date.has_date and metadata.date.year else "n.d."
        title_str = to_title_case(metadata.title).rstrip(".")

        id_str = ""
        if metadata.doi:
            id_str = f"https://doi.org/{metadata.doi}."
        elif metadata.url:
            id_str = f"{metadata.url}."

        parts: List[str] = []

        # Lead: Author. Year.
        if authors_str:
            parts.append(f"{authors_str} {year_str}.")
        else:
            parts.append(f"{title_str}. {year_str}.")

        if metadata.source_type in {SourceType.ACADEMIC_PAPER, SourceType.BOOK_CHAPTER}:
            if authors_str:
                parts.append(f'"{title_str}."')
            journal_parts = []
            if metadata.container_title:
                journal_parts.append(f"*{to_title_case(metadata.container_title)}*")
            if metadata.volume:
                vol_str = metadata.volume
                if metadata.issue:
                    vol_str += f" ({metadata.issue})"
                journal_parts.append(vol_str)
            if metadata.pages:
                journal_parts.append(f": {metadata.pages}")

            if journal_parts:
                parts.append(" ".join(journal_parts) + ".")

        elif metadata.source_type == SourceType.BOOK:
            if authors_str:
                parts.append(f"*{title_str}*.")
            if metadata.publisher:
                parts.append(f"{metadata.publisher.strip()}.")

        else:  # Webpage / Report
            if authors_str:
                parts.append(f'"{title_str}."')
            site_name = metadata.container_title or metadata.publisher
            if site_name:
                parts.append(f"{to_title_case(site_name)}.")

        if id_str:
            parts.append(id_str)

        return " ".join(parts).strip()

    def _format_authors(self, authors: List[Author]) -> str:
        if not authors:
            return ""

        def _direct(a: Author) -> str:
            if a.is_corporate:
                return a.family
            parts = [a.given, a.middle, a.family]
            if a.suffix:
                parts.append(a.suffix)
            return " ".join(p for p in parts if p).strip()

        def _inverted(a: Author) -> str:
            return a.format_inverted(initials_only=False)

        n = len(authors)
        if n == 1:
            name = _inverted(authors[0])
            return name if name.endswith(".") else f"{name}."
        if n == 2:
            return f"{_inverted(authors[0])}, and {_direct(authors[1])}."
        if n == 3:
            return f"{_inverted(authors[0])}, {_direct(authors[1])}, and {_direct(authors[2])}."
        if 4 <= n <= 10:
            first = _inverted(authors[0])
            mids = ", ".join(_direct(a) for a in authors[1:-1])
            last = _direct(authors[-1])
            return f"{first}, {mids}, and {last}."

        # 10+ authors: first 7 followed by et al.
        first_7 = [_inverted(authors[0])] + [_direct(a) for a in authors[1:7]]
        return f"{', '.join(first_7)}, et al."

    def render_in_text(self, metadata: ReferenceMetadata, page_or_loc: Optional[str] = None) -> str:
        lead = self._in_text_author_lead(metadata)
        year_str = str(metadata.date.year) if metadata.date.has_date and metadata.date.year else "n.d."
        loc_str = f", {page_or_loc.strip()}" if page_or_loc else ""
        return f"({lead} {year_str}{loc_str})"

    def render_narrative(self, metadata: ReferenceMetadata, page_or_loc: Optional[str] = None) -> str:
        lead = self._in_text_author_lead(metadata)
        year_str = str(metadata.date.year) if metadata.date.has_date and metadata.date.year else "n.d."
        loc_str = f", {page_or_loc.strip()}" if page_or_loc else ""
        return f"{lead} ({year_str}{loc_str})"

    def _in_text_author_lead(self, metadata: ReferenceMetadata) -> str:
        authors = metadata.authors
        if not authors:
            words = metadata.title.split()
            short_title = " ".join(words[:3])
            return f'"{to_title_case(short_title)}"'

        if len(authors) == 1:
            return authors[0].family
        if len(authors) == 2:
            return f"{authors[0].family} and {authors[1].family}"
        if len(authors) == 3:
            return f"{authors[0].family}, {authors[1].family}, and {authors[2].family}"
        return f"{authors[0].family} et al."
