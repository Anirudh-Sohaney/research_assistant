"""Tests for APA 7th Edition style renderer."""

from citation_engine.models import Author, CitationDate, ReferenceMetadata, SourceType
from citation_engine.renderers.apa import APA7Renderer, to_sentence_case


def test_to_sentence_case():
    assert to_sentence_case("ATTENTION IS ALL YOU NEED") == "Attention is all you need"
    assert to_sentence_case("Deep learning: A practical guide to AI") == "Deep learning: A practical guide to AI"
    assert to_sentence_case("Evaluating GPT-4 and LLMs on Code") == "Evaluating GPT-4 and LLMs on code"


def test_apa_single_author_journal():
    renderer = APA7Renderer()
    meta = ReferenceMetadata(
        title="Attention is all you need",
        authors=[Author(family="Vaswani", given="Ashish")],
        date=CitationDate(year=2017, has_date=True),
        source_type=SourceType.ACADEMIC_PAPER,
        container_title="Advances in Neural Information Processing Systems",
        volume="30",
        pages="5998-6008",
        doi="10.5555/3295222.3295349",
    )

    bib = renderer.render_bibliography(meta)
    in_text = renderer.render_in_text(meta)
    narrative = renderer.render_narrative(meta)

    assert "Vaswani, A. (2017)." in bib
    assert "Attention is all you need." in bib
    assert "*Advances in Neural Information Processing Systems*" in bib
    assert "*30*" in bib
    assert "https://doi.org/10.5555/3295222.3295349" in bib
    assert in_text == "(Vaswani, 2017)"
    assert narrative == "Vaswani (2017)"


def test_apa_two_authors():
    renderer = APA7Renderer()
    meta = ReferenceMetadata(
        title="Thinking, Fast and Slow",
        authors=[
            Author(family="Kahneman", given="Daniel"),
            Author(family="Tversky", given="Amos"),
        ],
        date=CitationDate(year=1973, has_date=True),
        source_type=SourceType.BOOK,
        publisher="Farrar, Straus and Giroux",
    )

    bib = renderer.render_bibliography(meta)
    in_text = renderer.render_in_text(meta, page_or_loc="45-50")
    narrative = renderer.render_narrative(meta)

    assert "Kahneman, D., & Tversky, A. (1973)." in bib
    assert "*Thinking, fast and slow*." in bib
    assert "Farrar, Straus and Giroux." in bib
    assert in_text == "(Kahneman & Tversky, 1973, pp. 45-50)"
    assert narrative == "Kahneman and Tversky (1973)"


def test_apa_twenty_plus_authors():
    renderer = APA7Renderer()
    # 22 authors
    authors = [Author(family=f"Author{i}", given=f"G{i}") for i in range(1, 23)]
    meta = ReferenceMetadata(
        title="Genomic analysis of human evolution",
        authors=authors,
        date=CitationDate(year=2021, has_date=True),
        source_type=SourceType.ACADEMIC_PAPER,
        container_title="Nature",
        volume="500",
        pages="1-10",
        doi="10.1038/nature12345",
    )

    bib = renderer.render_bibliography(meta)
    in_text = renderer.render_in_text(meta)

    # First 19 listed, then ellipsis, then 22nd author (no &)
    assert "Author1, G." in bib
    assert "Author19, G." in bib
    assert "... Author22, G." in bib
    assert "Author20" not in bib
    assert in_text == "(Author1 et al., 2021)"


def test_apa_corporate_author_webpage():
    renderer = APA7Renderer()
    meta = ReferenceMetadata(
        title="Depression and Other Common Mental Disorders",
        authors=[Author(family="World Health Organization", is_corporate=True)],
        date=CitationDate(year=2017, has_date=True),
        source_type=SourceType.WEBPAGE,
        container_title="World Health Organization",
        url="https://www.who.int/publications/i/item/9789241565448",
    )

    bib = renderer.render_bibliography(meta)
    in_text = renderer.render_in_text(meta)

    # When corporate author matches website name, site name is not duplicated
    assert bib.startswith("World Health Organization. (2017). *Depression and other common mental disorders*.")
    assert "World Health Organization. World Health Organization." not in bib
    assert in_text == "(World Health Organization, 2017)"


def test_apa_no_author_omission():
    renderer = APA7Renderer()
    meta = ReferenceMetadata(
        title="Quantum Computing in 2024",
        authors=[],
        date=CitationDate(year=2024, month=3, day=12, has_date=True),
        source_type=SourceType.WEBPAGE,
        container_title="TechCrunch",
        url="https://techcrunch.com/2024/03/12/quantum-computing-in-2024",
    )

    bib = renderer.render_bibliography(meta)
    in_text = renderer.render_in_text(meta)

    # Title shifts to author position
    assert bib.startswith("*Quantum computing in 2024*. (2024, March 12). TechCrunch.")
    assert in_text.startswith('("Quantum computing in 2024"')
