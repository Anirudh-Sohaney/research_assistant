"""IEEE citation style renderer."""

from __future__ import annotations

from typing import List, Optional

from engines.citation_engine.models import Author, ReferenceMetadata, SourceType
from engines.citation_engine.renderers.base import BaseStyleRenderer
from engines.citation_engine.renderers.mla import to_title_case


class IEEERenderer(BaseStyleRenderer):
    """IEEE standard numbered reference format."""

    def __init__(self, citation_number: int = 1):
        self.citation_number = citation_number

    def render_bibliography(self, metadata: ReferenceMetadata) -> str:
        authors_str = self._format_authors(metadata.authors)
        title_str = to_title_case(metadata.title).rstrip(".")
        year_str = str(metadata.date.year) if metadata.date.has_date and metadata.date.year else ""

        id_str = ""
        if metadata.doi:
            id_str = f"doi: {metadata.doi}."
        elif metadata.url:
            id_str = f"[Online]. Available: {metadata.url}."

        parts: List[str] = []
        if authors_str:
            parts.append(f"{authors_str},")

        if metadata.source_type in {SourceType.ACADEMIC_PAPER, SourceType.BOOK_CHAPTER}:
            parts.append(f'"{title_str},"')
            j_parts = []
            if metadata.container_title:
                j_parts.append(f"*{to_title_case(metadata.container_title)}*,")
            if metadata.volume:
                j_parts.append(f"vol. {metadata.volume},")
            if metadata.issue:
                j_parts.append(f"no. {metadata.issue},")
            if metadata.pages:
                p_lbl = "pp." if ("-" in metadata.pages or "," in metadata.pages) else "p."
                j_parts.append(f"{p_lbl} {metadata.pages},")
            if year_str:
                j_parts.append(f"{year_str}.")
            if j_parts:
                parts.append(" ".join(j_parts))

        elif metadata.source_type == SourceType.BOOK:
            parts.append(f"*{title_str}*.")
            b_parts = []
            if metadata.publisher:
                b_parts.append(f"{metadata.publisher.strip()},")
            if year_str:
                b_parts.append(f"{year_str}.")
            if b_parts:
                parts.append(" ".join(b_parts))

        else:
            parts.append(f'"{title_str}."')
            site_name = metadata.container_title or metadata.publisher
            if site_name:
                parts.append(f"{to_title_case(site_name)},")
            if year_str:
                parts.append(f"{year_str}.")

        if id_str:
            parts.append(id_str)

        body = " ".join(parts).strip()
        return f"[{self.citation_number}] {body}"

    def _format_authors(self, authors: List[Author]) -> str:
        """IEEE authors format: Initials followed by Surname, e.g. A. Vaswani, N. Shazeer."""
        if not authors:
            return ""

        def _format_single(a: Author) -> str:
            if a.is_corporate:
                return a.family
            initials = []
            if a.given:
                initials.append(f"{a.given[0]}.")
            if a.middle:
                initials.append(f"{a.middle[0]}.")
            init_str = " ".join(initials)
            res = f"{init_str} {a.family}".strip()
            if a.suffix:
                res = f"{res}, {a.suffix}"
            return res

        n = len(authors)
        if n == 1:
            return _format_single(authors[0])
        if n == 2:
            return f"{_format_single(authors[0])} and {_format_single(authors[1])}"
        if 3 <= n <= 6:
            all_but_last = ", ".join(_format_single(a) for a in authors[:-1])
            return f"{all_but_last}, and {_format_single(authors[-1])}"

        # > 6 authors: first author et al.
        return f"{_format_single(authors[0])} et al."

    def render_in_text(self, metadata: ReferenceMetadata, page_or_loc: Optional[str] = None) -> str:
        if page_or_loc:
            p_clean = page_or_loc.strip()
            p_lbl = "pp." if ("-" in p_clean or "," in p_clean) else "p."
            return f"[{self.citation_number}, {p_lbl} {p_clean}]"
        return f"[{self.citation_number}]"

    def render_narrative(self, metadata: ReferenceMetadata, page_or_loc: Optional[str] = None) -> str:
        return self.render_in_text(metadata, page_or_loc)
