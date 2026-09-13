"""Tests for metadata normalizer and sanitization functions."""

from citation_engine.models import Author, CitationDate
from citation_engine.normalizer import (
    clean_doi,
    clean_isbn,
    clean_url,
    parse_author,
    parse_authors_list,
    parse_date_string,
    sanitize_title,
)


def test_parse_author_individual():
    a1 = parse_author("Vaswani, Ashish")
    assert a1.family == "Vaswani"
    assert a1.given == "Ashish"
    assert not a1.is_corporate

    a2 = parse_author("Guido van Rossum")
    assert a2.family == "van Rossum"
    assert a2.given == "Guido"
    assert not a2.is_corporate

    a3 = parse_author("Martin Luther King, Jr.")
    assert a3.family == "King"
    assert a3.suffix.lower().startswith("jr")


def test_parse_author_corporate():
    c1 = parse_author("World Health Organization")
    assert c1.is_corporate
    assert c1.family == "World Health Organization"

    c2 = parse_author("OpenAI Research Team")
    assert c2.is_corporate

    c3 = parse_author("By The New York Times Editorial Board")
    assert c3.is_corporate
    assert "Editorial" in c3.family or "Board" in c3.family


def test_parse_authors_list():
    # Semicolon delimited
    res = parse_authors_list("Smith, John; Doe, Jane; Brown, Charlie")
    assert len(res) == 3
    assert res[0].family == "Smith"
    assert res[1].family == "Doe"

    # 'and' delimited
    res2 = parse_authors_list("Alice Walker and Bob Marley")
    assert len(res2) == 2
    assert res2[0].family == "Walker"
    assert res2[1].family == "Marley"

    # List of dicts (e.g. CSL / Schema.org)
    raw_dicts = [
        {"family": "Turing", "given": "Alan"},
        {"name": "National Aeronautics and Space Administration"},
    ]
    res3 = parse_authors_list(raw_dicts)
    assert len(res3) == 2
    assert res3[0].family == "Turing"
    assert res3[1].is_corporate


def test_parse_date_string():
    # ISO-8601
    d1 = parse_date_string("2023-04-15")
    assert d1.has_date
    assert d1.year == 2023 and d1.month == 4 and d1.day == 15

    # Month Day, Year
    d2 = parse_date_string("October 12, 2021")
    assert d2.year == 2021 and d2.month == 10 and d2.day == 12

    # Year only
    d3 = parse_date_string("1998")
    assert d3.year == 1998 and d3.month is None

    # Invalid / empty
    d4 = parse_date_string("")
    assert not d4.has_date


def test_sanitize_title():
    # Strips trailing site suffixes
    t1 = sanitize_title("Quantum Supremacy Achieved | Nature News")
    assert t1 == "Quantum Supremacy Achieved"

    # HTML entity unescape
    t2 = sanitize_title("Cats &amp; Dogs: A Study &mdash; Science Daily")
    assert "Cats & Dogs" in t2

    # ALL CAPS conversion
    t3 = sanitize_title("A NOVEL ARCHITECTURE FOR ATTENTION MECHANISMS")
    assert t3 != "A NOVEL ARCHITECTURE FOR ATTENTION MECHANISMS"
    assert t3.startswith("A Novel Architecture")


def test_clean_identifiers():
    # DOI extraction
    assert clean_doi("https://doi.org/10.1038/s41586-020-2649-2") == "10.1038/s41586-020-2649-2"
    assert clean_doi("doi: 10.1145/3357384.3357999.") == "10.1145/3357384.3357999"

    # ISBN
    assert clean_isbn("978-0-13-235088-4") == "9780132350884"
    assert clean_isbn("invalid-isbn") is None

    # URL cleaning (strip trackers)
    url = "https://example.com/article?utm_source=twitter&utm_medium=social&ref=feed#header"
    cleaned = clean_url(url)
    assert "utm_source" not in cleaned
    assert "ref=" not in cleaned
    assert "#header" not in cleaned
    assert cleaned == "https://example.com/article"
