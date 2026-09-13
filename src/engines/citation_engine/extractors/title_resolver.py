"""Bare-title → citation resolver: search-and-verify against Crossref and Semantic Scholar."""

from __future__ import annotations

import asyncio
import difflib
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from engines.citation_engine.extractors.base import BaseExtractor
from engines.citation_engine.models import (
    Author,
    CitationDate,
    FieldConfidence,
    ReferenceMetadata,
    SourceType,
)
from engines.citation_engine.normalizer import clean_doi, clean_isbn, sanitize_title

log = logging.getLogger("citation_engine.title_resolver")

CROSSREF_API_BASE = "https://api.crossref.org/works"
CROSSREF_USER_AGENT = "ResearchAssistant/1.0 (mailto:research-assistant@users.noreply.github.com)"
S2_API_BASE = "https://api.semanticscholar.org/graph/v1/paper/search"


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def is_bare_title_query(target: str) -> bool:
    """Quick check if target looks like a bare title rather than a URL/DOI/ISBN."""
    stripped = target.strip()
    if stripped.startswith("http://") or stripped.startswith("https://"):
        return False
    if clean_doi(stripped) is not None:
        return False
    if clean_isbn(stripped) is not None:
        return False
    return len(stripped) >= 8


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class TitleFragment:
    """Parsed components of a bare-title citation query."""
    raw: str = ""
    clean_title: str = ""
    author_hint: Optional[str] = None
    year_hint: Optional[int] = None


@dataclass
class CandidateScore:
    """Composite disambiguation score for a single aggregator candidate."""
    total_score: float = 0.0
    title_sim: float = 0.0
    author_overlap: float = 0.8
    year_proximity: float = 0.8
    confidence_tier: str = "LOW"
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fragment parser
# ---------------------------------------------------------------------------

def parse_title_fragment(text: str) -> TitleFragment:
    """Extracts title, optional author hint, and optional year from a citation fragment.

    The parser treats author/year as secondary metadata to verify against
    aggregator results — the clean_title is always the primary search key.
    """
    raw = text.strip()

    # 1. Year extraction (1900-2099)
    year_hint: Optional[int] = None
    m_year = re.search(r'\b(19\d\d|20\d\d)\b', raw)
    if m_year:
        year_hint = int(m_year.group(1))

    # 2. Author extraction — must start with uppercase to avoid matching title words
    author_hint: Optional[str] = None

    # "et al." pattern (highest priority)
    m_etal = re.search(r'\b([A-Z][A-Za-z\-]+)\s+et\s+al\.?', raw)
    # "by Author" pattern
    m_by = re.search(r'\bby\s+([A-Z][A-Za-z\-]+)', raw, re.IGNORECASE)

    if m_etal:
        author_hint = m_etal.group(0).strip()
    elif m_by:
        author_hint = m_by.group(1).strip()
    else:
        # Capitalized surname immediately before or near year
        if m_year:
            m_cap = re.search(r'\b([A-Z][a-z]+)\s*(?:,|\s+)\s*' + re.escape(str(year_hint)), raw)
            if m_cap:
                author_hint = m_cap.group(1).strip()
            else:
                # Capitalized word in parenthetical with year: (He 2016)
                m_paren = re.search(r'\(([A-Z][a-z]+)(?:\s+et\s+al\.?)?\s+' + re.escape(str(year_hint)) + r'\)', raw)
                if m_paren:
                    # Rebuild the full match in case "et al." was present
                    full_paren = raw[m_paren.start()+1:m_paren.end()-1].rsplit(str(year_hint), 1)[0].strip()
                    author_hint = full_paren if full_paren else m_paren.group(1).strip()

    # 3. Clean title — strip author and year, collapse whitespace/punctuation
    clean = raw
    if m_year:
        clean = clean[:m_year.start()] + " " + clean[m_year.end():]
    if author_hint:
        clean = clean.replace(author_hint, " ", 1)
    # Strip residual "by", "et al." leftovers
    clean = re.sub(r'\b(?:by|et al\.?)\b', ' ', clean, flags=re.IGNORECASE)
    clean = re.sub(r'[()[\]{},;:\'"]+', ' ', clean)
    clean = ' '.join(clean.split()).strip()

    return TitleFragment(raw=raw, clean_title=clean or raw, author_hint=author_hint, year_hint=year_hint)


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------

class TitleResolverExtractor(BaseExtractor):
    """Resolves bare paper titles into full ReferenceMetadata via federated search.

    Pipeline:
        1. Parse input fragment → (title, optional author, optional year)
        2. Query Crossref + Semantic Scholar concurrently (title-only queries)
        3. Score & disambiguate candidates using title similarity, author overlap,
           and year proximity
        4. Build ReferenceMetadata from the best candidate
        5. Assign confidence tier (HIGH / MEDIUM / LOW) with human-readable notes
    """

    def __init__(self, timeout_secs: float = 8.0):
        self._timeout = timeout_secs

    def can_handle(self, target: str) -> bool:
        return is_bare_title_query(target)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_candidate(
        self,
        candidate_title: str,
        candidate_authors: List[str],
        candidate_year: Optional[int],
        fragment: TitleFragment,
    ) -> CandidateScore:
        """Scores a single candidate against the parsed fragment."""

        def _norm(s: str) -> str:
            return re.sub(r'[^a-z0-9 ]', '', s.lower()).strip()

        q_title = _norm(fragment.clean_title)
        c_title = _norm(candidate_title)

        # --- Title similarity ---
        if q_title == c_title:
            title_sim = 1.0
        else:
            ratio = difflib.SequenceMatcher(None, q_title, c_title).ratio()
            if c_title.startswith(q_title) or q_title in c_title:
                title_sim = max(ratio, 0.90)
            else:
                q_words = set(q_title.split())
                c_words = set(c_title.split())
                if q_words and q_words.issubset(c_words):
                    title_sim = max(ratio, 0.88)
                else:
                    title_sim = ratio

        # --- Author overlap ---
        author_overlap = 0.8  # neutral when missing
        author_missing = fragment.author_hint is None
        author_contradiction = False

        if fragment.author_hint:
            hint_clean = _norm(re.sub(r'\bet al\.?\b', '', fragment.author_hint, flags=re.IGNORECASE))
            hint_tokens = [t for t in hint_clean.split() if len(t) > 2]

            found = any(
                tok in _norm(c_auth)
                for tok in hint_tokens
                for c_auth in candidate_authors
            )
            if found:
                author_overlap = 1.0
            else:
                author_overlap = 0.1
                author_contradiction = True

        # --- Year proximity ---
        year_proximity = 0.8  # neutral when missing
        year_missing = fragment.year_hint is None
        year_contradiction = False
        year_diff = 0

        if fragment.year_hint is not None and candidate_year is not None:
            year_diff = abs(candidate_year - fragment.year_hint)
            if year_diff == 0:
                year_proximity = 1.0
            elif year_diff == 1:
                year_proximity = 0.85
            elif year_diff == 2:
                year_proximity = 0.70
            else:
                year_proximity = 0.20
                year_contradiction = True

        # --- Aggregate score ---
        if not author_missing and not year_missing:
            total = 0.50 * title_sim + 0.30 * author_overlap + 0.20 * year_proximity
        elif not author_missing:
            total = 0.65 * title_sim + 0.35 * author_overlap
        elif not year_missing:
            total = 0.75 * title_sim + 0.25 * year_proximity
        else:
            total = min(title_sim * 0.85, 0.85) if title_sim >= 0.95 else title_sim * 0.80

        # --- Confidence tier ---
        notes: List[str] = []

        if author_contradiction:
            c_str = ", ".join(candidate_authors[:3])
            notes.append(f"Author mismatch: query specified '{fragment.author_hint}', but best match is by '{c_str}'")
        elif author_missing and candidate_authors:
            notes.append(f"Author not specified in query; verified match is '{candidate_authors[0]} et al.'")

        if year_contradiction:
            notes.append(f"Year mismatch: query specified {fragment.year_hint}, but publication year is {candidate_year}")
        elif not year_missing and year_diff > 0:
            notes.append(f"Year adjusted from {fragment.year_hint} to {candidate_year} (publication date)")
        elif year_missing and candidate_year:
            notes.append(f"Year not specified in query; using {candidate_year}")

        if author_contradiction or year_contradiction or title_sim < 0.65:
            tier = "LOW"
        elif (title_sim >= 0.88 and not author_missing and not year_missing
              and year_diff <= 1 and author_overlap >= 0.9):
            tier = "HIGH"
            notes.clear()  # High-confidence: auto-rendered without comment
        elif title_sim >= 0.75:
            tier = "MEDIUM"
        else:
            tier = "LOW"

        return CandidateScore(
            total_score=round(total, 4),
            title_sim=round(title_sim, 4),
            author_overlap=round(author_overlap, 4),
            year_proximity=round(year_proximity, 4),
            confidence_tier=tier,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Aggregator queries
    # ------------------------------------------------------------------

    async def _fetch_crossref_candidates(self, client: httpx.AsyncClient, title: str) -> List[Dict[str, Any]]:
        """Queries Crossref bibliographic search."""
        try:
            resp = await client.get(
                CROSSREF_API_BASE,
                params={"query.bibliographic": title, "rows": 5},
                headers={"User-Agent": CROSSREF_USER_AGENT, "Accept": "application/json"},
            )
            if resp.status_code != 200:
                log.debug("Crossref search returned %s for '%s'", resp.status_code, title[:60])
                return []
            return resp.json().get("message", {}).get("items", [])
        except Exception as exc:
            log.warning("Crossref search failed: %s", exc)
            return []

    async def _fetch_semantic_scholar_candidates(self, client: httpx.AsyncClient, title: str) -> List[Dict[str, Any]]:
        """Queries Semantic Scholar paper search."""
        try:
            resp = await client.get(
                S2_API_BASE,
                params={
                    "query": title,
                    "limit": 5,
                    "fields": "paperId,title,authors,year,venue,externalIds,citationCount,abstract",
                },
            )
            if resp.status_code != 200:
                log.debug("S2 search returned %s for '%s'", resp.status_code, title[:60])
                return []
            return resp.json().get("data", []) or []
        except Exception as exc:
            log.warning("Semantic Scholar search failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Metadata builders (from raw aggregator dicts)
    # ------------------------------------------------------------------

    def _build_metadata_from_crossref(self, item: Dict[str, Any]) -> Optional[ReferenceMetadata]:
        """Builds ReferenceMetadata from a Crossref works item dict."""
        raw_titles = item.get("title", [])
        title_str = raw_titles[0] if raw_titles else ""
        if not title_str:
            return None

        # Authors
        authors: List[Author] = []
        for a in item.get("author", []):
            family = a.get("family", "").strip()
            given = a.get("given", "").strip()
            if family:
                authors.append(Author(family=family, given=given, is_corporate=False))
            elif a.get("name"):
                authors.append(Author(family=a["name"].strip(), is_corporate=True))

        # Date
        date_parts = (
            item.get("published-print", {}).get("date-parts")
            or item.get("published-online", {}).get("date-parts")
            or item.get("issued", {}).get("date-parts")
            or item.get("created", {}).get("date-parts")
        )
        date = CitationDate(has_date=False)
        if date_parts and date_parts[0]:
            parts = date_parts[0]
            year = parts[0] if len(parts) >= 1 else None
            month = parts[1] if len(parts) >= 2 else None
            day = parts[2] if len(parts) >= 3 else None
            date = CitationDate(year=year, month=month, day=day, has_date=bool(year))

        doi = item.get("DOI")
        containers = item.get("container-title", [])
        container_title = containers[0].strip() if containers else None

        # Type detection
        csl_type = item.get("type", "")
        if "book" in csl_type and "chapter" not in csl_type:
            src_type = SourceType.BOOK
        elif "chapter" in csl_type:
            src_type = SourceType.BOOK_CHAPTER
        else:
            src_type = SourceType.ACADEMIC_PAPER

        return ReferenceMetadata(
            title=sanitize_title(title_str),
            authors=authors,
            date=date,
            source_type=src_type,
            container_title=container_title,
            publisher=item.get("publisher"),
            volume=str(item["volume"]).strip() if item.get("volume") else None,
            issue=str(item["issue"]).strip() if item.get("issue") else None,
            pages=str(item["page"]).strip() if item.get("page") else None,
            doi=doi,
            url=item.get("URL") or (f"https://doi.org/{doi}" if doi else None),
            confidence_score=0.0,  # set later by caller
            field_confidence={
                "title": FieldConfidence.AUTHORITATIVE,
                "authors": FieldConfidence.AUTHORITATIVE,
                "date": FieldConfidence.AUTHORITATIVE,
                "container_title": FieldConfidence.AUTHORITATIVE,
                "doi": FieldConfidence.AUTHORITATIVE,
            },
            raw_data=item,
        )

    def _build_metadata_from_s2(self, item: Dict[str, Any]) -> Optional[ReferenceMetadata]:
        """Builds ReferenceMetadata from a Semantic Scholar paper dict (no DOI fallback)."""
        title = item.get("title", "")
        if not title:
            return None

        # Authors
        authors: List[Author] = []
        for a in item.get("authors", []):
            name = a.get("name", "").strip()
            if not name:
                continue
            parts = name.split()
            if len(parts) == 1:
                authors.append(Author(family=parts[0]))
            else:
                family = parts[-1]
                given = parts[0]
                middle = " ".join(parts[1:-1]) if len(parts) > 2 else ""
                authors.append(Author(family=family, given=given, middle=middle))

        year = item.get("year")
        date = CitationDate(year=year, has_date=bool(year)) if year else CitationDate(has_date=False)

        external_ids = item.get("externalIds", {}) or {}
        doi = external_ids.get("DOI")

        return ReferenceMetadata(
            title=sanitize_title(title),
            authors=authors,
            date=date,
            source_type=SourceType.ACADEMIC_PAPER,
            container_title=item.get("venue") or None,
            doi=doi,
            url=f"https://doi.org/{doi}" if doi else None,
            confidence_score=0.0,  # set later by caller
            field_confidence={
                "title": FieldConfidence.HIGH,
                "authors": FieldConfidence.HIGH,
                "date": FieldConfidence.HIGH,
            },
            raw_data=item,
        )

    # ------------------------------------------------------------------
    # Main extract
    # ------------------------------------------------------------------

    async def extract(self, target: str) -> Optional[ReferenceMetadata]:
        """Resolves a bare title (with optional author/year hints) to ReferenceMetadata.

        Returns None if no candidate scores above the 0.50 threshold.
        """
        fragment = parse_title_fragment(target)

        # 1. Query both aggregators concurrently
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            cr_items, s2_items = await asyncio.gather(
                self._fetch_crossref_candidates(client, fragment.clean_title),
                self._fetch_semantic_scholar_candidates(client, fragment.clean_title),
            )

        # 2. Unify candidates into scoreable tuples
        candidates: List[Dict[str, Any]] = []

        for item in cr_items:
            raw_titles = item.get("title", [])
            title = raw_titles[0] if raw_titles else ""
            author_names = [a.get("family", "") for a in item.get("author", []) if a.get("family")]
            date_parts = (
                item.get("published-print", {}).get("date-parts")
                or item.get("published-online", {}).get("date-parts")
                or item.get("issued", {}).get("date-parts")
                or item.get("created", {}).get("date-parts")
            )
            year = date_parts[0][0] if date_parts and date_parts[0] and date_parts[0][0] else None
            candidates.append({"source": "crossref", "item": item, "title": title, "authors": author_names, "year": year})

        for item in s2_items:
            title = item.get("title", "")
            author_names = [a.get("name", "").split()[-1] for a in item.get("authors", []) if a.get("name")]
            year = item.get("year")
            candidates.append({"source": "s2", "item": item, "title": title, "authors": author_names, "year": year})

        if not candidates:
            return None

        # 3. Score every candidate
        scored: List[tuple[CandidateScore, Dict[str, Any]]] = []
        for c in candidates:
            score = self._score_candidate(c["title"], c["authors"], c["year"], fragment)
            scored.append((score, c))

        scored.sort(key=lambda x: x[0].total_score, reverse=True)

        best_score, best_cand = scored[0]

        if best_score.total_score < 0.50:
            return None

        # 4. Ambiguity check — top 2 within 5% of each other
        if len(scored) > 1:
            second_score, second_cand = scored[1]
            if (best_score.total_score - second_score.total_score) <= 0.05:
                # Check if they're actually the same paper (same DOI or near-identical title)
                best_doi = (best_cand["item"].get("DOI")
                            or (best_cand["item"].get("externalIds") or {}).get("DOI"))
                second_doi = (second_cand["item"].get("DOI")
                              or (second_cand["item"].get("externalIds") or {}).get("DOI"))
                same_doi = best_doi and second_doi and str(best_doi).lower() == str(second_doi).lower()
                same_title = difflib.SequenceMatcher(
                    None, best_cand["title"].lower(), second_cand["title"].lower()
                ).ratio() > 0.95

                if not same_doi and not same_title:
                    best_score.notes.append(
                        "Multiple plausible candidates (top 2 within 5% score); using highest-ranked match"
                    )
                    best_score.confidence_tier = "LOW"

        # 5. Build ReferenceMetadata from winner
        if best_cand["source"] == "crossref":
            meta = self._build_metadata_from_crossref(best_cand["item"])
        else:
            meta = self._build_metadata_from_s2(best_cand["item"])

        if meta is None:
            return None

        # 6. Apply confidence score based on tier
        if best_score.confidence_tier == "HIGH":
            meta.confidence_score = best_score.total_score
        elif best_score.confidence_tier == "MEDIUM":
            meta.confidence_score = best_score.total_score * 0.85
        else:
            meta.confidence_score = best_score.total_score * 0.65

        meta.provenance_warnings = best_score.notes

        log.info(
            "Title resolved: '%s' → '%s' [%s confidence, score=%.3f]",
            fragment.clean_title[:50], meta.title[:50],
            best_score.confidence_tier, meta.confidence_score,
        )

        return meta
