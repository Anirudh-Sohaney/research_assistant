"""MLA 9th Edition citation style renderer."""

from __future__ import annotations

import re
from typing import List, Optional

from engines.citation_engine.models import Author, CitationDate, ReferenceMetadata, SourceType
from engines.citation_engine.renderers.base import BaseStyleRenderer

LOWERCASE_WORDS = {
    "a", "an", "the", "and", "but", "or", "for", "nor", "on", "in",
    "at", "to", "from", "by", "with", "of", "as", "into", "onto",
}


def to_title_case(title: str) -> str:
    """Converts a title to Title Case per MLA standards."""
    if not title:
        return ""

    words = title.split()
    if not words:
        return ""

    cased_words = []
    for i, word in enumerate(words):
        w_clean = re.sub(r"^[^\w]+|[^\w]+$", "", word)
        # Acronyms or words with internal capital
        if (word.isupper() and len(word) >= 2) or any(c.isupper() for c in word[1:]):
            cased_words.append(word)
        elif i == 0 or i == len(words) - 1 or w_clean.lower() not in LOWERCASE_WORDS:
            cased_words.append(word.capitalize())
        else:
            cased_words.append(word.lower())

    return " ".join(cased_words)


class MLA9Renderer(BaseStyleRenderer):
    """MLA 9th Edition style implementation."""

    def render_bibliography(self, metadata: ReferenceMetadata) -> str:
        authors_str = self._format_authors(metadata.authors)
        title_str = to_title_case(metadata.title).rstrip(".")
        date_str = metadata.date.format_mla()

        id_str = ""
        if metadata.doi:
            id_str = f"https://doi.org/{metadata.doi}"
        elif metadata.url:
            id_str = metadata.url

        if metadata.source_type in {SourceType.ACADEMIC_PAPER, SourceType.BOOK_CHAPTER}:
            return self._render_journal(metadata, authors_str, title_str, date_str, id_str)
        elif metadata.source_type == SourceType.BOOK:
            return self._render_book(metadata, authors_str, title_str, date_str, id_str)
        else:
            return self._render_web(metadata, authors_str, title_str, date_str, id_str)

    def _render_journal(
        self,
        m: ReferenceMetadata,
        authors_str: str,
        title_str: str,
        date_str: str,
        id_str: str,
    ) -> str:
        parts: List[str] = []
        lead = f'{authors_str} "{title_str}."' if authors_str else f'"{title_str}."'
        parts.append(lead)

        # Journal details
        container_elements = []
        if m.container_title:
            container_elements.append(f"*{to_title_case(m.container_title)}*")
        if m.volume:
            container_elements.append(f"vol. {m.volume}")
        if m.issue:
            container_elements.append(f"no. {m.issue}")
        if date_str and date_str != "n.d.":
            container_elements.append(date_str)
        if m.pages:
            p_label = "pp." if ("-" in m.pages or "," in m.pages) else "p."
            container_elements.append(f"{p_label} {m.pages}")

        if container_elements:
            parts.append(", ".join(container_elements) + ".")

        if id_str:
            parts.append(id_str + ".")

        return " ".join(parts).strip()

    def _render_book(
        self,
        m: ReferenceMetadata,
        authors_str: str,
        title_str: str,
        date_str: str,
        id_str: str,
    ) -> str:
        parts: List[str] = []
        lead = f"{authors_str} *{title_str}*." if authors_str else f"*{title_str}*."
        parts.append(lead)

        pub_parts = []
        if m.publisher:
            pub_parts.append(m.publisher.strip())
        if date_str and date_str != "n.d.":
            pub_parts.append(date_str)

        if pub_parts:
            parts.append(", ".join(pub_parts) + ".")

        if id_str:
            parts.append(id_str + ".")

        return " ".join(parts).strip()

    def _render_web(
        self,
        m: ReferenceMetadata,
        authors_str: str,
        title_str: str,
        date_str: str,
        id_str: str,
    ) -> str:
        parts: List[str] = []
        lead = f'{authors_str} "{title_str}."' if authors_str else f'"{title_str}."'
        parts.append(lead)

        site_name = m.container_title or m.publisher
        web_parts = []
        if site_name:
            web_parts.append(f"*{to_title_case(site_name)}*")
        if date_str and date_str != "n.d.":
            web_parts.append(date_str)

        if web_parts:
            parts.append(", ".join(web_parts) + ",")

        if id_str:
            parts.append(id_str + ".")

        return " ".join(parts).strip()

    def _format_authors(self, authors: List[Author]) -> str:
        """MLA 9 author formatting:
        - 1 author: Last, First.
        - 2 authors: Last, First, and First Last.
        - 3+ authors: Last, First, et al.
        """
        if not authors:
            return ""

        def _name_direct(a: Author) -> str:
            if a.is_corporate:
                return a.family
            parts = [a.given, a.middle, a.family]
            if a.suffix:
                parts.append(a.suffix)
            return " ".join(p for p in parts if p).strip()

        def _name_inverted(a: Author) -> str:
            return a.format_inverted(initials_only=False)

        n = len(authors)
        if n == 1:
            name = _name_inverted(authors[0])
            return name if name.endswith(".") else f"{name}."
        if n == 2:
            return f"{_name_inverted(authors[0])}, and {_name_direct(authors[1])}."
        # 3 or more authors
        return f"{_name_inverted(authors[0])}, et al."

    def render_in_text(self, metadata: ReferenceMetadata, page_or_loc: Optional[str] = None) -> str:
        """MLA in-text parenthetical: (Last Page) or (Last and Last Page) without commas."""
        lead = self._in_text_author_lead(metadata)
        loc_str = f" {page_or_loc.strip()}" if page_or_loc else ""
        return f"({lead}{loc_str})"

    def render_narrative(self, metadata: ReferenceMetadata, page_or_loc: Optional[str] = None) -> str:
        """MLA in-text narrative: Last (Page)."""
        lead = self._in_text_author_lead(metadata)
        loc_str = f" ({page_or_loc.strip()})" if page_or_loc else ""
        return f"{lead}{loc_str}"

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
        return f"{authors[0].family} et al."
