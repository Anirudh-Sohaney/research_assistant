"""Unit tests for paper_discovery subsystem."""

import os
import sys
from unittest.mock import patch

import pytest

_src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from api_gateway.models import ApiResponse
from paper_discovery.models import (
    AcademicPaperRecommendation,
    CitationGraphResult,
    LiteratureSynthesis,
    PaperDiscoveryResult,
    TraversalDirection,
)
from paper_discovery.discovery import (
    PaperDiscoveryEngine,
    _generate_citation_key,
    discover_similar_papers,
    synthesize_literature_context,
    traverse_citation_network,
)


class TestModelsAndHelpers:
    def test_citation_key_generation(self):
        key = _generate_citation_key("Vaswani et al.", 2017, "Attention Is All You Need")
        assert key == "vaswani2017attention"


class TestPaperDiscovery:
    @pytest.mark.asyncio
    @patch("paper_discovery.discovery.dispatch_api_request")
    async def test_discover_via_semantic_scholar(self, mock_dispatch):
        mock_dispatch.return_value = ApiResponse(
            status_code=200,
            data={
                "data": [
                    {
                        "paperId": "p12345",
                        "title": "BERT: Pre-training of Deep Bidirectional Transformers",
                        "authors": [{"name": "Jacob Devlin"}, {"name": "Ming-Wei Chang"}],
                        "year": 2018,
                        "venue": "NAACL",
                        "citationCount": 60000,
                        "abstract": "We introduce a new language representation model called BERT.",
                        "externalIds": {"DOI": "10.18653/v1/N19-1423"},
                    }
                ]
            },
            latency_ms=30.0,
        )

        res = await discover_similar_papers("Bidirectional language representation models", limit=3)
        assert isinstance(res, PaperDiscoveryResult)
        assert len(res.papers) >= 1
        paper = res.papers[0]
        assert "BERT" in paper.title
        assert paper.year == 2018
        assert paper.doi == "10.18653/v1/N19-1423"
        assert "devlin2018bert" in paper.suggested_citation_key

    @pytest.mark.asyncio
    @patch("paper_discovery.discovery.dispatch_api_request")
    async def test_offline_fallback_matching(self, mock_dispatch):
        mock_dispatch.return_value = ApiResponse(
            status_code=500,
            data=None,
            latency_ms=5.0,
            error="API down",
        )

        res = await discover_similar_papers("Transformers rely entirely on self-attention for sequence modeling.")
        assert len(res.papers) >= 1
        assert any("Vaswani" in p.authors for p in res.papers)

    def test_literature_synthesis(self):
        papers = [
            AcademicPaperRecommendation(
                paper_id="p1",
                doi="10.1/test",
                title="Attention Is All You Need",
                authors="Vaswani et al.",
                year=2017,
                suggested_citation_key="vaswani2017attention",
            ),
            AcademicPaperRecommendation(
                paper_id="p2",
                doi="10.2/test",
                title="Deep Residual Learning",
                authors="He et al.",
                year=2016,
                suggested_citation_key="he2016deep",
            ),
        ]
        synthesis = synthesize_literature_context("We propose an improved attention mechanism.", papers)
        assert isinstance(synthesis, LiteratureSynthesis)
        assert "Vaswani et al., 2017" in synthesis.synthesis_paragraph
        assert "vaswani2017attention" in synthesis.cited_keys
