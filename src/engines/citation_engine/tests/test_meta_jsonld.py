"""Tests for HTML meta-tag and JSON-LD extractor."""

import pytest

from engines.citation_engine.extractors.meta_jsonld import HeadHTMLParser, MetaJsonLdExtractor
from engines.citation_engine.models import FieldConfidence, SourceType


def test_head_html_parser():
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Machine Learning Advances - AI Hub</title>
        <meta name="author" content="Jane Doe" />
        <meta property="og:title" content="Machine Learning Advances" />
        <meta property="og:site_name" content="AI Hub" />
        <meta property="article:published_time" content="2023-08-10T14:30:00Z" />
        <link rel="canonical" href="https://aihub.org/ml-advances" />
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "TechArticle",
            "headline": "Machine Learning Advances in Practice",
            "datePublished": "2023-08-10",
            "author": [{"@type": "Person", "name": "Jane Doe"}],
            "publisher": {"@type": "Organization", "name": "AI Hub"}
        }
        </script>
    </head>
    <body><p>Content</p></body>
    </html>
    """
    parser = HeadHTMLParser()
    parser.feed(sample_html)

    assert "Machine Learning Advances" in (parser.title or "")
    assert parser.canonical_url == "https://aihub.org/ml-advances"
    assert len(parser.json_ld_raw) == 1
    assert len(parser.meta_tags) >= 4


def test_meta_jsonld_precedence_and_mapping():
    extractor = MetaJsonLdExtractor()
    parser = HeadHTMLParser()

    html = """
    <head>
        <title>Old Title Tag</title>
        <meta property="og:title" content="Better OG Title" />
        <meta name="citation_journal_title" content="Journal of AI Research" />
        <meta name="citation_volume" content="42" />
        <meta name="citation_issue" content="3" />
        <meta name="citation_doi" content="10.1234/jair.2023.001" />
        <script type="application/ld+json">
        {
            "@type": "ScholarlyArticle",
            "headline": "Authoritative Scholarly Title",
            "datePublished": "2023-05-20",
            "author": [
                {"@type": "Person", "familyName": "Shannon", "givenName": "Claude"}
            ]
        }
        </script>
    </head>
    """
    parser.feed(html)
    meta = extractor.parse_html_metadata(parser, "https://jair.org/paper-1")

    # Authoritative JSON-LD title preferred over OG and <title>
    assert meta.title == "Authoritative Scholarly Title"
    assert meta.source_type == SourceType.ACADEMIC_PAPER
    assert len(meta.authors) == 1
    assert meta.authors[0].family == "Shannon"
    assert meta.authors[0].given == "Claude"
    assert meta.date.year == 2023
    assert meta.volume == "42"
    assert meta.issue == "3"
    assert meta.doi == "10.1234/jair.2023.001"
    assert meta.confidence_score >= 0.85


def test_meta_highwire_press():
    extractor = MetaJsonLdExtractor()
    parser = HeadHTMLParser()

    html = """
    <head>
        <title>Deep Residual Learning for Image Recognition</title>
        <meta name="citation_title" content="Deep Residual Learning for Image Recognition" />
        <meta name="citation_author" content="He, Kaiming" />
        <meta name="citation_author" content="Zhang, Xiangyu" />
        <meta name="citation_publication_date" content="2016/06/27" />
        <meta name="citation_journal_title" content="IEEE CVPR" />
        <meta name="citation_doi" content="10.1109/CVPR.2016.90" />
    </head>
    """
    parser.feed(html)
    meta = extractor.parse_html_metadata(parser, "https://ieeexplore.ieee.org/document/7780459")

    assert meta.title == "Deep Residual Learning for Image Recognition"
    assert meta.source_type == SourceType.ACADEMIC_PAPER
    assert len(meta.authors) == 2
    assert meta.authors[0].family == "He"
    assert meta.authors[1].family == "Zhang"
    assert meta.date.year == 2016
    assert meta.container_title == "IEEE CVPR"
    assert meta.doi == "10.1109/CVPR.2016.90"


def test_missing_author_assigned_to_publisher_or_shifts():
    extractor = MetaJsonLdExtractor()
    parser = HeadHTMLParser()

    # No personal author, but site_name present
    html = """
    <head>
        <title>Global Health Report 2024</title>
        <meta property="og:site_name" content="World Health Organization" />
        <meta property="article:published_time" content="2024-01-15" />
    </head>
    """
    parser.feed(html)
    meta = extractor.parse_html_metadata(parser, "https://who.int/report-2024")

    assert len(meta.authors) == 1
    assert meta.authors[0].is_corporate
    assert meta.authors[0].family == "World Health Organization"
    assert meta.field_confidence["authors"] == FieldConfidence.MEDIUM


def test_date_hierarchy_fallback():
    extractor = MetaJsonLdExtractor()
    parser = HeadHTMLParser()

    # No publish date, but Last-Modified header provided
    html = """
    <head>
        <title>Python 3.12 Release Notes</title>
    </head>
    """
    parser.feed(html)
    meta = extractor.parse_html_metadata(
        parser,
        canonical_url="https://docs.python.org/3.12/",
        last_modified_header="Wed, 02 Oct 2024 12:00:00 GMT",
    )

    assert meta.date.has_date
    assert meta.date.year == 2024
    assert meta.date.month == 10
    assert any("Last-Modified" in w for w in meta.provenance_warnings)
