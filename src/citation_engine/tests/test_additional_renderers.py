"""Tests for additional citation styles: MLA 9th, Chicago 17th, IEEE, and BibTeX."""

from citation_engine.models import Author, CitationDate, ReferenceMetadata, SourceType
from citation_engine.renderers.bibtex import BibTeXRenderer
from citation_engine.renderers.chicago import ChicagoRenderer
from citation_engine.renderers.ieee import IEEERenderer
from citation_engine.renderers.mla import MLA9Renderer


def test_mla_single_and_two_authors():
    renderer = MLA9Renderer()

    # 1 Author
    m1 = ReferenceMetadata(
        title="To Kill a Mockingbird",
        authors=[Author(family="Lee", given="Harper")],
        date=CitationDate(year=1960, has_date=True),
        source_type=SourceType.BOOK,
        publisher="J. B. Lippincott & Co.",
    )
    bib1 = renderer.render_bibliography(m1)
    in_text1 = renderer.render_in_text(m1, page_or_loc="102")

    assert bib1 == "Lee, Harper. *To Kill a Mockingbird*. J. B. Lippincott & Co., 1960."
    assert in_text1 == "(Lee 102)"

    # 2 Authors: Second author in direct order (First Last)
    m2 = ReferenceMetadata(
        title="Thinking, Fast and Slow",
        authors=[
            Author(family="Kahneman", given="Daniel"),
            Author(family="Tversky", given="Amos"),
        ],
        date=CitationDate(year=1973, has_date=True),
        source_type=SourceType.BOOK,
        publisher="Farrar, Straus and Giroux",
    )
    bib2 = renderer.render_bibliography(m2)
    in_text2 = renderer.render_in_text(m2)

    assert "Kahneman, Daniel, and Amos Tversky." in bib2
    assert in_text2 == "(Kahneman and Tversky)"


def test_mla_three_plus_authors_journal():
    renderer = MLA9Renderer()
    m = ReferenceMetadata(
        title="Attention is all you need",
        authors=[
            Author(family="Vaswani", given="Ashish"),
            Author(family="Shazeer", given="Noam"),
            Author(family="Parmar", given="Niki"),
        ],
        date=CitationDate(year=2017, has_date=True),
        source_type=SourceType.ACADEMIC_PAPER,
        container_title="Advances in Neural Information Processing Systems",
        volume="30",
        pages="5998-6008",
        doi="10.5555/3295222.3295349",
    )
    bib = renderer.render_bibliography(m)
    in_text = renderer.render_in_text(m, page_or_loc="6001")

    assert "Vaswani, Ashish, et al." in bib
    assert '"Attention Is All You Need."' in bib
    assert "*Advances in Neural Information Processing Systems*" in bib
    assert "vol. 30" in bib
    assert "pp. 5998-6008" in bib
    assert in_text == "(Vaswani et al. 6001)"


def test_chicago_author_date():
    renderer = ChicagoRenderer()
    m = ReferenceMetadata(
        title="The Structure of Scientific Revolutions",
        authors=[Author(family="Kuhn", given="Thomas", middle="S.")],
        date=CitationDate(year=1962, has_date=True),
        source_type=SourceType.BOOK,
        publisher="University of Chicago Press",
    )
    bib = renderer.render_bibliography(m)
    in_text = renderer.render_in_text(m, page_or_loc="45")

    # Author. Year. Title. Publisher.
    assert bib == 'Kuhn, Thomas S. 1962. *The Structure of Scientific Revolutions*. University of Chicago Press.'
    assert in_text == "(Kuhn 1962, 45)"


def test_ieee_format():
    renderer = IEEERenderer(citation_number=3)
    m = ReferenceMetadata(
        title="Deep Residual Learning for Image Recognition",
        authors=[
            Author(family="He", given="Kaiming"),
            Author(family="Zhang", given="Xiangyu"),
            Author(family="Ren", given="Shaoqing"),
            Author(family="Sun", given="Jian"),
        ],
        date=CitationDate(year=2016, has_date=True),
        source_type=SourceType.ACADEMIC_PAPER,
        container_title="IEEE Conference on Computer Vision and Pattern Recognition",
        pages="770-778",
        doi="10.1109/CVPR.2016.90",
    )
    bib = renderer.render_bibliography(m)
    in_text = renderer.render_in_text(m, page_or_loc="772")

    assert bib.startswith("[3] K. He, X. Zhang, S. Ren, and J. Sun,")
    assert '"Deep Residual Learning for Image Recognition,"' in bib
    assert "doi: 10.1109/CVPR.2016.90." in bib
    assert in_text == "[3, p. 772]"


def test_bibtex_export():
    renderer = BibTeXRenderer()
    m = ReferenceMetadata(
        title="Attention is All You Need",
        authors=[
            Author(family="Vaswani", given="Ashish"),
            Author(family="Shazeer", given="Noam"),
        ],
        date=CitationDate(year=2017, month=12, has_date=True),
        source_type=SourceType.ACADEMIC_PAPER,
        container_title="NeurIPS",
        volume="30",
        pages="5998-6008",
        doi="10.5555/3295222.3295349",
    )
    bib = renderer.render_bibliography(m)
    in_text = renderer.render_in_text(m)

    assert bib.startswith("@article{vaswani2017,")
    assert "title = {Attention is All You Need}" in bib
    assert "author = {Vaswani, Ashish and Shazeer, Noam}" in bib
    assert "journal = {NeurIPS}" in bib
    assert "year = {2017}" in bib
    assert "doi = {10.5555/3295222.3295349}" in bib
    assert in_text == "\\cite{vaswani2017}"
