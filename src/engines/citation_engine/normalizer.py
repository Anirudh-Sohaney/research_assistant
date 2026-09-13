"""Normalization and sanitization routines for raw extracted metadata fields."""

from __future__ import annotations

import html
import re
import urllib.parse
from typing import List, Optional, Tuple

from engines.citation_engine.models import Author, CitationDate

# Curated keywords identifying institutional / corporate bodies (should not be inverted)
CORPORATE_KEYWORDS = {
    "organization", "organisation", "institute", "institution", "department",
    "ministry", "ministries", "association", "committee", "commission", "agency", "council",
    "foundation", "society", "university", "college", "center", "centre",
    "group", "team", "lab", "laboratory", "corporation", "corp", "inc", "llc",
    "ltd", "gmbh", "bureau", "service", "office", "who", "cdc", "nasa", "nih",
    "un", "unesco", "unicef", "oecd", "imf", "ieee", "acm", "openai", "google",
    "microsoft", "meta", "apple", "amazon", "press", "staff", "reporters", "editorial",
    "administration", "board", "government", "consortium", "panel", "bank",
}

# Common name particles that should remain attached to the surname
PARTICLES = {"van", "von", "de", "der", "den", "du", "la", "le", "del", "della", "di", "da"}

# Known suffix abbreviations
SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "phd", "md"}

# Tracking query parameters to strip from URLs
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "source", "ref_src", "spm", "_hsenc", "_hsmi",
}

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def parse_author(raw_name: str) -> Author:
    """Parses a single author string into a structured Author model."""
    if not raw_name or not raw_name.strip():
        return Author(family="Unknown", is_corporate=True)

    clean = html.unescape(raw_name).strip()
    # Strip leading "By " or "Written by "
    clean = re.sub(r"^(?:by|written by|authored by)\s+", "", clean, flags=re.IGNORECASE).strip()

    # Corporate detection
    words_lower = [w.strip(".,;:()") for w in clean.lower().split()]
    if any(w in CORPORATE_KEYWORDS for w in words_lower) or len(clean.split()) > 5:
        return Author(family=clean, is_corporate=True)

    # Inverted name format: "Last, First Middle Suffix"
    if "," in clean:
        parts = [p.strip() for p in clean.split(",") if p.strip()]
        # Check if direct name with suffix e.g. "Martin Luther King, Jr."
        if len(parts) == 2 and parts[1].lower().strip(".") in SUFFIXES:
            tokens = parts[0].split()
            suffix = parts[1]
            if len(tokens) == 1:
                return Author(family=tokens[0], suffix=suffix, is_corporate=False)
            family_tokens = [tokens[-1]]
            i = len(tokens) - 2
            while i >= 0 and tokens[i].lower() in PARTICLES:
                family_tokens.insert(0, tokens[i])
                i -= 1
            family = " ".join(family_tokens)
            remaining = tokens[:i + 1]
            given = remaining[0] if remaining else ""
            middle = " ".join(remaining[1:]) if len(remaining) > 1 else ""
            return Author(family=family, given=given, middle=middle, suffix=suffix, is_corporate=False)

        family = parts[0]
        given = ""
        middle = ""
        suffix = ""

        if len(parts) >= 2:
            subparts = parts[1].split()
            if subparts:
                given = subparts[0]
                if len(subparts) > 1:
                    middle = " ".join(subparts[1:])

        if len(parts) >= 3 and parts[2].lower().strip(".") in SUFFIXES:
            suffix = parts[2]

        return Author(family=family, given=given, middle=middle, suffix=suffix, is_corporate=False)

    # Direct name format: "First Middle Last [Suffix]"
    tokens = clean.split()
    if len(tokens) == 1:
        return Author(family=tokens[0], is_corporate=False)

    suffix = ""
    if tokens[-1].lower().strip(".") in SUFFIXES:
        suffix = tokens.pop()

    if len(tokens) == 1:
        return Author(family=tokens[0], suffix=suffix, is_corporate=False)

    # Check for particles (e.g., "Guido van Rossum")
    family_tokens = [tokens[-1]]
    i = len(tokens) - 2
    while i >= 0 and tokens[i].lower() in PARTICLES:
        family_tokens.insert(0, tokens[i])
        i -= 1

    family = " ".join(family_tokens)
    remaining = tokens[:i + 1]

    given = remaining[0] if remaining else ""
    middle = " ".join(remaining[1:]) if len(remaining) > 1 else ""

    return Author(family=family, given=given, middle=middle, suffix=suffix, is_corporate=False)


def parse_authors_list(raw_authors: Any) -> List[Author]:
    """Handles single strings with delimiters ('and', ';', ',') or lists of strings/dicts."""
    if not raw_authors:
        return []

    if isinstance(raw_authors, list):
        authors: List[Author] = []
        for item in raw_authors:
            if isinstance(item, dict):
                family = item.get("family") or item.get("familyName") or item.get("name") or ""
                given = item.get("given") or item.get("givenName") or ""
                if family and not given and " " in family:
                    authors.append(parse_author(family))
                elif family:
                    authors.append(Author(family=family.strip(), given=given.strip()))
            elif isinstance(item, str) and item.strip():
                authors.append(parse_author(item))
        return authors

    if isinstance(raw_authors, str):
        text = raw_authors.strip()
        # Check semicolon delimited
        if ";" in text:
            return [parse_author(p) for p in text.split(";") if p.strip()]
        # Check " and " delimited
        if " and " in text.lower():
            splits = re.split(r"\s+and\s+", text, flags=re.IGNORECASE)
            return [parse_author(p) for p in splits if p.strip()]
        return [parse_author(text)]

    return []


def parse_date_string(raw_date: Optional[str]) -> CitationDate:
    """Parses variable date formats into normalized (year, month, day)."""
    if not raw_date or not str(raw_date).strip():
        return CitationDate(has_date=False)

    text = str(raw_date).strip()

    # 1. ISO-8601: YYYY-MM-DD or YYYY-MM
    iso_match = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", text)
    if iso_match:
        y, m, d = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
        if 1 <= m <= 12 and 1 <= d <= 31:
            return CitationDate(year=y, month=m, day=d, raw_str=text, has_date=True)

    iso_month_match = re.search(r"(\d{4})[/-](\d{1,2})", text)
    if iso_month_match:
        y, m = int(iso_month_month := iso_month_match.group(1)), int(iso_month_match.group(2))
        if 1 <= m <= 12:
            return CitationDate(year=y, month=m, raw_str=text, has_date=True)

    # 2. Natural language: "April 15, 2023" or "15 Apr 2023"
    nat_match = re.search(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", text)
    if nat_match:
        m_str, d, y = nat_match.group(1).lower(), int(nat_match.group(2)), int(nat_match.group(3))
        m = MONTH_MAP.get(m_str)
        if m:
            return CitationDate(year=y, month=m, day=d, raw_str=text, has_date=True)

    day_first_match = re.search(r"(\d{1,2})\s+([A-Za-z]+)\.?\s+(\d{4})", text)
    if day_first_match:
        d, m_str, y = int(day_first_match.group(1)), day_first_match.group(2).lower(), int(day_first_match.group(3))
        m = MONTH_MAP.get(m_str)
        if m:
            return CitationDate(year=y, month=m, day=d, raw_str=text, has_date=True)

    # 3. Year only: "2023"
    year_match = re.search(r"\b(1[89]\d{2}|20\d{2})\b", text)
    if year_match:
        return CitationDate(year=int(year_match.group(1)), raw_str=text, has_date=True)

    return CitationDate(raw_str=text, has_date=False)


def sanitize_title(raw_title: Optional[str]) -> str:
    """Unescapes HTML, strips site branding pipes/dashes, and formats casing."""
    if not raw_title or not raw_title.strip():
        return "Untitled"

    cleaned = html.unescape(raw_title).strip()
    # Strip site branding suffix: "Deep Learning | Nature News" -> "Deep Learning"
    cleaned = re.sub(r"\s+[|–—:-]\s+[^|–—:-]{3,35}$", "", cleaned).strip()

    # Convert ALL CAPS titles to Title Case if all uppercase
    letters = [c for c in cleaned if c.isalpha()]
    if letters and all(c.isupper() for c in letters) and len(letters) > 8:
        cleaned = cleaned.title()

    return cleaned


def clean_doi(raw_doi: Optional[str]) -> Optional[str]:
    """Extracts and normalizes canonical DOI format (10.xxxx/yyyy)."""
    if not raw_doi:
        return None

    # Find standard DOI pattern
    match = re.search(r"10\.\d{4,9}/[^\s\"<>]+", str(raw_doi).strip())
    if not match:
        return None

    doi = match.group(0)
    # Strip trailing punctuation (e.g. from end of sentences)
    doi = re.sub(r"[.,;:/\)\]]+$", "", doi)
    # Unquote URL-encoded chars
    doi = urllib.parse.unquote(doi)
    return doi.strip()


def clean_isbn(raw_isbn: Optional[str]) -> Optional[str]:
    """Normalizes ISBN-10 or ISBN-13 into digits with uppercase check digit."""
    if not raw_isbn:
        return None

    digits = re.sub(r"[-\s]", "", str(raw_isbn)).upper()
    if re.fullmatch(r"(?:97[89])?\d{9}[\dX]", digits):
        return digits
    return None


def clean_url(raw_url: Optional[str]) -> Optional[str]:
    """Removes marketing trackers and anchors from canonical URLs."""
    if not raw_url:
        return None

    try:
        parsed = urllib.parse.urlparse(raw_url.strip())
        if not parsed.scheme or not parsed.netloc:
            return raw_url.strip()

        # Filter query params
        query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        filtered_query = [(k, v) for k, v in query_pairs if k.lower() not in TRACKING_PARAMS]
        new_query = urllib.parse.urlencode(filtered_query)

        cleaned = urllib.parse.urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,
            parsed.params,
            new_query,
            "",  # Strip fragment/anchor
        ))
        return cleaned.rstrip("/")
    except Exception:
        return raw_url.strip()
