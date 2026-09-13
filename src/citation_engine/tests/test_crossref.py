"""Tests for Crossref API extractor and CSL mapping."""

import pytest

from citation_engine.extractors.crossref import CrossrefExtractor
from citation_engine.models import SourceType


def test_map_message_to_metadata():
    extractor = CrossrefExtractor()

    csl_message = {
        "title": ["Attention Is All You Need"],
        "author": [
            {"given": "Ashish", "family": "Vaswani"},
            {"given": "Noam", "family": "Shazeer"},
            {"given": "Niki", "family": "Parmar"},
        ],
        "published-print": {
            "date-parts": [[2017, 12]]
        },
        "container-title": ["Advances in Neural Information Processing Systems"],
        "volume": "30",
        "page": "5998-6008",
        "publisher": "Curran Associates, Inc.",
        "type": "proceedings-article",
    }

    meta = extractor._map_message_to_metadata(csl_message, "10.5555/3295222.3295349")

    assert meta.title == "Attention Is All You Need"
    assert len(meta.authors) == 3
    assert meta.authors[0].family == "Vaswani"
    assert meta.authors[0].given == "Ashish"
    assert meta.date.year == 2017
    assert meta.date.month == 12
    assert meta.volume == "30"
    assert meta.pages == "5998-6008"
    assert meta.source_type == SourceType.ACADEMIC_PAPER
    assert meta.doi == "10.5555/3295222.3295349"
    assert meta.confidence_score == 1.0


def test_crossref_corporate_author_mapping():
    extractor = CrossrefExtractor()

    csl_message = {
        "title": ["Global Tuberculosis Report"],
        "author": [
            {"name": "World Health Organization"}
        ],
        "published-online": {
            "date-parts": [[2022]]
        },
        "type": "report",
    }

    meta = extractor._map_message_to_metadata(csl_message, "10.2471/9789240061729")

    assert len(meta.authors) == 1
    assert meta.authors[0].is_corporate
    assert meta.authors[0].family == "World Health Organization"
    assert meta.date.year == 2022
