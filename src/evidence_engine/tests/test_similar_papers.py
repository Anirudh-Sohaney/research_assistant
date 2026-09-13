"""Tests for the similar_papers module."""

import asyncio

import pytest

from evidence_engine.models import PaperRef, RetrievalResult
from evidence_engine.similar_papers import (
    SimilarPaper,
    SimilarityResult,
    _tokenize,
    _score_paper,
    find_similar_papers,
    find_similar_papers_sync,
)


# ------------------------------------------------------- helpers

def _make_paper(**overrides) -> PaperRef:
    defaults = {
        "title": "Test Paper",
        "authors": "Author A",
        "year": 2023,
        "doi": "10.1/test",
        "url": "https://example.com",
        "abstract": "This is a test abstract about machine learning.",
        "citation_count": 100,
        "open_access": True,
        "source": "test",
    }
    defaults.update(overrides)
    return PaperRef(**defaults)


# ------------------------------------------------------- tokenization

class TestTokenize:
    def test_basic_extraction(self):
        tokens = _tokenize("Multilayer perceptron is dominant for inverse kinematics")
        assert "multilayer" in tokens
        assert "perceptron" in tokens
        assert "inverse" in tokens
        assert "kinematics" in tokens
        assert "is" not in tokens
        assert "the" not in tokens

    def test_min_length_filter(self):
        tokens = _tokenize("A I and M L are big")
        assert "a" not in tokens  # single char filtered
        assert "i" not in tokens
        assert "big" in tokens

    def test_empty_input(self):
        assert _tokenize("") == []
        assert _tokenize("   ") == []


# ------------------------------------------------------- scoring

class TestScoring:
    def test_high_score_for_relevant_paper(self):
        paper = _make_paper(
            title="Deep Learning for Inverse Kinematics",
            abstract="We propose a neural network approach to solve inverse kinematics problems.",
        )
        query_tokens = ["inverse", "kinematics", "neural", "network"]
        score = _score_paper(paper, query_tokens)
        assert score > 0.3

    def test_low_score_for_irrelevant_paper(self):
        paper = _make_paper(
            title="Quantum Computing Basics",
            abstract="Introduction to qubits and quantum gates.",
        )
        query_tokens = ["inverse", "kinematics", "neural", "network"]
        score = _score_paper(paper, query_tokens)
        assert score < 0.1

    def test_citation_boost(self):
        paper_high = _make_paper(citation_count=10000)
        paper_low = _make_paper(citation_count=10)
        query_tokens = ["test"]
        score_high = _score_paper(paper_high, query_tokens)
        score_low = _score_paper(paper_low, query_tokens)
        assert score_high > score_low

    def test_recency_boost(self):
        paper_new = _make_paper(year=2024)
        paper_old = _make_paper(year=2015)
        query_tokens = ["test"]
        score_new = _score_paper(paper_new, query_tokens)
        score_old = _score_paper(paper_old, query_tokens)
        assert score_new > score_old


# ------------------------------------------------------- end-to-end (mocked)

class TestFindSimilarPapers:
    @pytest.mark.asyncio
    async def test_returns_papers_from_multiple_sources(self, monkeypatch):
        """Mock the extract_papers function to return test data."""
        async def mock_extract(claim, per_source_limit=100, deadline_s=8.0):
            papers = [
                _make_paper(title="Paper A", source="europepmc",
                           abstract="Study about inverse kinematics using neural networks"),
                _make_paper(title="Paper B", source="openalex",
                           abstract="Deep learning approach for robot kinematics"),
                _make_paper(title="Paper C", source="semanticscholar",
                           abstract="Reinforcement learning for control systems"),
            ]
            return RetrievalResult(
                papers=papers,
                sources={"europepmc": {"papers": 1, "status": "ok"},
                         "openalex": {"papers": 1, "status": "ok"},
                         "semanticscholar": {"papers": 1, "status": "ok"}},
                wall_ms=150.0,
            )

        from evidence_engine import similar_papers
        monkeypatch.setattr(similar_papers, "extract_papers", mock_extract)

        result = await find_similar_papers(
            "Inverse kinematics using neural networks",
            target_count=10,
            deadline_s=4.0,
        )

        assert isinstance(result, SimilarityResult)
        assert len(result.papers) == 3
        assert result.total_candidates == 3
        assert len(result.sources_used) == 3
        assert all(isinstance(p, SimilarPaper) for p in result.papers)

    @pytest.mark.asyncio
    async def test_papers_sorted_by_relevance(self, monkeypatch):
        """Papers with more query term overlap should rank higher."""
        async def mock_extract(claim, per_source_limit=100, deadline_s=8.0):
            papers = [
                _make_paper(title="Unrelated Topic", source="s1",
                           abstract="Quantum entanglement in particles"),
                _make_paper(title="Inverse Kinematics Neural Network", source="s2",
                           abstract="Solving inverse kinematics with neural networks"),
            ]
            return RetrievalResult(
                papers=papers,
                sources={"s1": {"papers": 1, "status": "ok"},
                         "s2": {"papers": 1, "status": "ok"}},
                wall_ms=100.0,
            )

        from evidence_engine import similar_papers
        monkeypatch.setattr(similar_papers, "extract_papers", mock_extract)

        result = await find_similar_papers(
            "inverse kinematics neural network",
            target_count=10,
        )

        assert result.papers[0].title == "Inverse Kinematics Neural Network"
        assert result.papers[0].relevance_score > result.papers[1].relevance_score

    @pytest.mark.asyncio
    async def test_target_count_limits_results(self, monkeypatch):
        async def mock_extract(claim, per_source_limit=100, deadline_s=8.0):
            papers = [_make_paper(title=f"Paper {i}", source="s") for i in range(50)]
            return RetrievalResult(
                papers=papers,
                sources={"s": {"papers": 50, "status": "ok"}},
                wall_ms=200.0,
            )

        from evidence_engine import similar_papers
        monkeypatch.setattr(similar_papers, "extract_papers", mock_extract)

        result = await find_similar_papers("test query", target_count=20)
        assert len(result.papers) == 20

    def test_sync_wrapper(self, monkeypatch):
        async def mock_extract(claim, per_source_limit=100, deadline_s=8.0):
            return RetrievalResult(
                papers=[_make_paper()],
                sources={"s": {"papers": 1, "status": "ok"}},
                wall_ms=50.0,
            )

        from evidence_engine import similar_papers
        monkeypatch.setattr(similar_papers, "extract_papers", mock_extract)

        result = find_similar_papers_sync("test query", target_count=5)
        assert isinstance(result, SimilarityResult)
        assert len(result.papers) == 1
