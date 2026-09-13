"""APA 7th Edition citation style renderer."""

from __future__ import annotations

import calendar
import re
from typing import List, Optional

from citation_engine.models import Author, CitationDate, ReferenceMetadata, SourceType
from citation_engine.renderers.base import BaseStyleRenderer


def to_sentence_case(title: str) -> str:
    """Converts a title to APA sentence case, preserving acronyms and subtitles."""
    if not title:
        return ""

    # If title is in ALL CAPS (more than 4 alphabetic chars and all upper), convert to lower first
    alpha_chars = [c for c in title if c.isalpha()]
    if len(alpha_chars) > 4 and all(c.isupper() for c in alpha_chars):
        title = title.lower()

    # Split on subtitle delimiters (: - —)
    subtitles = re.split(r"([:—\-] )", title)
    processed_parts = []

    for i, part in enumerate(subtitles):
        if i % 2 == 1:  # delimiter
            processed_parts.append(part)
            continue

        words = part.split()
        if not words:
            continue

        capitalized_words = []
        for w_idx, word in enumerate(words):
            # First word in title or subtitle is always capitalized
            if w_idx == 0:
                capitalized_words.append(word.capitalize() if word.islower() else word)
            else:
                # If word is ALL CAPS with length >= 2 (acronym like NASA, GPT, AI), preserve it
                if word.isupper() and len(word) >= 2:
                    capitalized_words.append(word)
                # If word has internal capitalization (e.g., iPhone, TensorFlow, PyTorch), preserve it
                elif any(c.isupper() for c in word[1:]):
                    capitalized_words.append(word)
                else:
                    capitalized_words.append(word.lower())

        processed_parts.append(" ".join(capitalized_words))

    return "".join(processed_parts)


class APA7Renderer(BaseStyleRenderer):
    """Full APA 7th Edition style implementation with omission and threshold rules."""

    def render_bibliography(self, metadata: ReferenceMetadata) -> str:
        """Formats the complete reference list entry in Markdown."""
        authors_str = self._format_authors(metadata.authors)
        date_str = self._format_date(metadata.date, metadata.source_type)
        title_str = to_sentence_case(metadata.title).rstrip(".")

        # Identifier (DOI or URL)
        id_str = ""
        if metadata.doi:
            id_str = f"https://doi.org/{metadata.doi}"
        elif metadata.url:
            id_str = metadata.url

        # Dispatch based on source type
        if metadata.source_type in {SourceType.ACADEMIC_PAPER, SourceType.BOOK_CHAPTER}:
            return self._render_journal_article(metadata, authors_str, date_str, title_str, id_str)
        elif metadata.source_type == SourceType.BOOK:
            return self._render_book(metadata, authors_str, date_str, title_str, id_str)
        else:
            return self._render_webpage(metadata, authors_str, date_str, title_str, id_str)

    def _render_journal_article(
        self,
        m: ReferenceMetadata,
        authors_str: str,
        date_str: str,
        title_str: str,
        id_str: str,
    ) -> str:
        # Title of article is plain text, container (journal) is italicized
        parts: List[str] = []

        # Authors & Date
        if authors_str:
            parts.append(f"{authors_str} {date_str}.")
            parts.append(f"{title_str}.")
        else:
            # Shift title to author position if no author
            parts.append(f"{title_str}. {date_str}.")

        # Journal / Periodical context: *Journal*, *volume*(issue), pages.
        journal_parts = []
        if m.container_title:
            journal_parts.append(f"*{m.container_title.strip()}*")

        if m.volume:
            vol_str = f"*{m.volume}*"
            if m.issue:
                vol_str += f"({m.issue})"
            journal_parts.append(vol_str)

        if m.pages:
            journal_parts.append(m.pages)

        if journal_parts:
            parts.append(", ".join(journal_parts) + ".")

        if id_str:
            parts.append(id_str)

        return " ".join(p for p in parts if p).strip()

    def _render_book(
        self,
        m: ReferenceMetadata,
        authors_str: str,
        date_str: str,
        title_str: str,
        id_str: str,
    ) -> str:
        # Book title is italicized
        parts: List[str] = []

        if authors_str:
            parts.append(f"{authors_str} {date_str}.")
            book_title = f"*{title_str}*"
            if m.edition:
                book_title += f" ({m.edition})"
            parts.append(f"{book_title}.")
        else:
            book_title = f"*{title_str}*"
            if m.edition:
                book_title += f" ({m.edition})"
            parts.append(f"{book_title}. {date_str}.")

        if m.publisher:
            parts.append(f"{m.publisher.strip()}.")

        if id_str:
            parts.append(id_str)

        return " ".join(p for p in parts if p).strip()

    def _render_webpage(
        self,
        m: ReferenceMetadata,
        authors_str: str,
        date_str: str,
        title_str: str,
        id_str: str,
    ) -> str:
        # Standalone webpage title is italicized
        parts: List[str] = []

        # Check if corporate author matches site name
        site_name = (m.container_title or m.publisher or "").strip()
        single_corp_author = (
            m.authors[0].family.strip()
            if len(m.authors) == 1 and m.authors[0].is_corporate
            else None
        )

        if authors_str:
            parts.append(f"{authors_str} {date_str}.")
            parts.append(f"*{title_str}*.")
        else:
            parts.append(f"*{title_str}*. {date_str}.")

        # Add website name if not redundant with corporate author
        if site_name:
            if not single_corp_author or single_corp_author.lower() != site_name.lower():
                parts.append(f"{site_name}.")

        if id_str:
            parts.append(id_str)

        return " ".join(p for p in parts if p).strip()

    def _format_authors(self, authors: List[Author]) -> str:
        """APA 7th author rules:
        - 1 author: Last, F. M.
        - 2 authors: Last, F. M., & Last, F. M.
        - 3 to 20 authors: All listed, with '&' before the last.
        - 21+ authors: First 19, comma, '...', comma, final author (no '&').
        - Corporate: Name as given.
        """
        if not authors:
            return ""

        formatted_names = [a.format_inverted(initials_only=True) for a in authors]
        n = len(formatted_names)

        def _ensure_dot(name: str) -> str:
            return name if name.endswith(".") else f"{name}."

        if n == 1:
            return _ensure_dot(formatted_names[0])

        if n == 2:
            return f"{formatted_names[0]}, & {_ensure_dot(formatted_names[1])}"

        if 3 <= n <= 20:
            all_but_last = ", ".join(formatted_names[:-1])
            return f"{all_but_last}, & {_ensure_dot(formatted_names[-1])}"

        # 21+ authors
        first_19 = ", ".join(formatted_names[:19])
        last_name = _ensure_dot(formatted_names[-1])
        return f"{first_19}, ... {last_name}"

    def _format_date(self, date: CitationDate, source_type: SourceType) -> str:
        """Formats date per APA 7th rules:
        - Journal / Book: (Year) or (n.d.)
        - Webpage / News: (Year, Month Day) or (Year, Month) or (Year) or (n.d.)
        """
        if not date.has_date or not date.year:
            return "(n.d.)"

        if source_type in {SourceType.ACADEMIC_PAPER, SourceType.BOOK, SourceType.BOOK_CHAPTER}:
            return f"({date.year})"

        # Webpages, news, blog posts include month and day if available
        if date.month and date.day:
            m_name = calendar.month_name[date.month]
            return f"({date.year}, {m_name} {date.day})"
        if date.month:
            m_name = calendar.month_name[date.month]
            return f"({date.year}, {m_name})"

        return f"({date.year})"

    def render_in_text(self, metadata: ReferenceMetadata, page_or_loc: Optional[str] = None) -> str:
        """Renders parenthetical citation: (Vaswani et al., 2017) or (Smith & Jones, 2020, p. 15)."""
        author_lead = self._in_text_author_lead(metadata)
        year_str = str(metadata.date.year) if metadata.date.has_date and metadata.date.year else "n.d."

        loc_str = ""
        if page_or_loc:
            p_clean = page_or_loc.strip()
            loc_label = "pp." if ("-" in p_clean or "," in p_clean) else "p."
            loc_str = f", {loc_label} {p_clean}"

        return f"({author_lead}, {year_str}{loc_str})"

    def render_narrative(self, metadata: ReferenceMetadata, page_or_loc: Optional[str] = None) -> str:
        """Renders narrative citation: Vaswani et al. (2017) or Smith and Jones (2020, p. 15)."""
        author_lead = self._in_text_author_lead(metadata, for_narrative=True)
        year_str = str(metadata.date.year) if metadata.date.has_date and metadata.date.year else "n.d."

        loc_str = ""
        if page_or_loc:
            p_clean = page_or_loc.strip()
            loc_label = "pp." if ("-" in p_clean or "," in p_clean) else "p."
            loc_str = f", {loc_label} {p_clean}"

        return f"{author_lead} ({year_str}{loc_str})"

    def _in_text_author_lead(self, metadata: ReferenceMetadata, for_narrative: bool = False) -> str:
        authors = metadata.authors
        amp = "and" if for_narrative else "&"

        if not authors:
            # Fallback to shortened title in quotes
            sentence_cased = to_sentence_case(metadata.title)
            words = sentence_cased.split()
            short_title = " ".join(words[:4])
            if len(words) > 4:
                short_title += "..."
            return f'"{short_title}"'

        if len(authors) == 1:
            return authors[0].family

        if len(authors) == 2:
            return f"{authors[0].family} {amp} {authors[1].family}"

        # 3 or more authors -> et al.
        return f"{authors[0].family} et al."
