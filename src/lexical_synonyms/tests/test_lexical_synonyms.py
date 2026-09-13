"""Unit tests for lexical_synonyms subsystem."""

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

_src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from api_gateway.models import ApiResponse
from lexical_synonyms.models import RawCandidate, SynonymGroupResult, SynonymItem
from lexical_synonyms.synonyms import (
    LexicalSynonymsEngine,
    find_contextual_synonyms,
    harvest_candidate_synonyms,
    rank_candidates_in_context,
)


class TestModels:
    def test_raw_candidate_creation(self):
        c = RawCandidate(word="omnipresent", source="DATAMUSE", pos="adj", frequency=14.5)
        assert c.word == "omnipresent"
        assert c.source == "DATAMUSE"
        assert c.pos == "adj"

    def test_synonym_item_scoring(self):
        item = SynonymItem(word="pervasive", composite_score=0.88, academic_register=1.0)
        assert item.composite_score == 0.88
        assert item.academic_register == 1.0


@pytest.mark.asyncio
class TestHarvesting:
    @patch("lexical_synonyms.synonyms.dispatch_api_request")
    async def test_harvest_from_datamuse(self, mock_dispatch):
        mock_dispatch.return_value = ApiResponse(
            status_code=200,
            data=[
                {"word": "omnipresent", "tags": ["adj", "f:22.4"]},
                {"word": "pervasive", "tags": ["adj", "f:18.1"]},
            ],
            latency_ms=12.0,
            cache_hit=False,
            tokens_consumed=0,
        )
        engine = LexicalSynonymsEngine()
        candidates = await engine.harvest_candidate_synonyms("ubiquitous")
        assert len(candidates) >= 2
        words = [c.word for c in candidates]
        assert "omnipresent" in words
        assert "pervasive" in words

    @patch("lexical_synonyms.synonyms.dispatch_api_request")
    async def test_offline_fallback_when_api_empty(self, mock_dispatch):
        mock_dispatch.return_value = ApiResponse(
            status_code=500,
            data=None,
            latency_ms=5.0,
            error="Network down",
        )
        engine = LexicalSynonymsEngine()
        candidates = await engine.harvest_candidate_synonyms("ubiquitous")
        assert len(candidates) > 0
        words = [c.word for c in candidates]
        assert "omnipresent" in words


class TestRanking:
    def test_academic_register_boost(self):
        engine = LexicalSynonymsEngine()
        candidates = [
            RawCandidate(word="everywhere", frequency=30.0),  # colloquial
            RawCandidate(word="omnipresent", frequency=20.0), # academic AWL
        ]
        ranked = engine.rank_candidates_in_context(
            candidates,
            target_word="ubiquitous",
            sentence="Smartphones have become ubiquitous in daily life.",
        )
        assert len(ranked) == 2
        assert ranked[0].word == "omnipresent"
        assert ranked[0].academic_register > ranked[1].academic_register

    def test_morphology_alignment(self):
        engine = LexicalSynonymsEngine()
        candidates = [
            RawCandidate(word="demonstrate", frequency=20.0),
            RawCandidate(word="demonstrated", frequency=20.0),
        ]
        ranked = engine.rank_candidates_in_context(
            candidates,
            target_word="illustrated",
            sentence="The author illustrated the findings with precision.",
        )
        assert ranked[0].word == "demonstrated"


@pytest.mark.asyncio
class TestFullPipeline:
    @patch("lexical_synonyms.synonyms.dispatch_api_request")
    async def test_find_contextual_synonyms(self, mock_dispatch):
        mock_dispatch.return_value = ApiResponse(
            status_code=200,
            data=[
                {"word": "omnipresent", "tags": ["adj", "f:25.0"]},
                {"word": "pervasive", "tags": ["adj", "f:20.0"]},
                {"word": "universal", "tags": ["adj", "f:35.0"]},
            ],
            latency_ms=10.0,
        )
        result = await find_contextual_synonyms(
            target_word="ubiquitous",
            sentence_context="Network partitions are ubiquitous in distributed computing.",
            limit=3,
            use_llm=False,
        )
        assert isinstance(result, SynonymGroupResult)
        assert result.query_word == "ubiquitous"
        assert len(result.ranked_synonyms) == 3
        assert result.ranked_synonyms[0].composite_score > 0

    async def test_inflect_candidate_tenses(self):
        from lexical_synonyms.synonyms import inflect_candidate

        # 3rd-person singular present (VBZ)
        assert inflect_candidate("describe", "VBZ") == "describes"
        assert inflect_candidate("detail", "VBZ") == "details"
        assert inflect_candidate("teach", "VBZ") == "teaches"
        assert inflect_candidate("study", "VBZ") == "studies"

        # Past participle (VBN)
        assert inflect_candidate("train", "VBN") == "trained"
        assert inflect_candidate("teach", "VBN") == "taught"
        assert inflect_candidate("acquire", "VBN") == "acquired"
        assert inflect_candidate("study", "VBN") == "studied"

        # Plural noun (NNS)
        assert inflect_candidate("benchmark", "NNS") == "benchmarks"
        assert inflect_candidate("hypothesis", "NNS") == "hypothesises"

    @patch("lexical_synonyms.synonyms.dispatch_api_request")
    async def test_describes_preserves_vbz_tense(self, mock_dispatch):
        mock_dispatch.return_value = ApiResponse(
            status_code=200,
            data=[
                {"word": "define", "tags": ["v", "f:20.0"]},
                {"word": "outline", "tags": ["v", "f:15.0"]},
                {"word": "detail", "tags": ["v", "f:10.0"]},
            ],
            latency_ms=10.0,
        )
        result = await find_contextual_synonyms(
            target_word="describes",
            sentence_context="The paper describes the system architecture.",
            limit=5,
            use_llm=False,
        )
        words = [s.word for s in result.ranked_synonyms]
        assert len(words) > 0
        # All returned verb candidates must be inflected to 3rd-person singular present (ending with 's')
        for w in words:
            assert w.endswith("s"), f"Expected 3rd person singular present ending with 's', got '{w}'"
        assert "defined" not in words  # Never regress to past tense 'defined'

    @patch("lexical_synonyms.synonyms.dispatch_api_request")
    async def test_learned_preserves_vbn_and_contextual_fit(self, mock_dispatch):
        mock_dispatch.return_value = ApiResponse(
            status_code=200,
            data=[
                {"word": "teach", "tags": ["v", "f:25.0"]},
                {"word": "instruct", "tags": ["v", "f:15.0"]},
                {"word": "scholarly", "tags": ["adj", "f:10.0"]},
            ],
            latency_ms=10.0,
        )
        result = await find_contextual_synonyms(
            target_word="Learned",
            sentence_context="Learned inverse kinematics benchmark",
            limit=5,
            use_llm=False,
        )
        words = [s.word for s in result.ranked_synonyms]
        assert len(words) > 0
        # Top candidates must be proper verb inflections (e.g., trained, taught, acquired)
        assert "scholarly" not in words  # Adjective sense must be excluded for verb context
        assert any(w in words for w in ("trained", "taught", "acquired", "instructed", "derived"))

    @patch("lexical_synonyms.synonyms.dispatch_api_request")
    async def test_objective_adjective_context_excludes_normal_and_antonyms(self, mock_dispatch):
        async def fake_dispatch(service, endpoint, payload):
            params = payload.params if payload else {}
            if "ml" in params:
                return ApiResponse(
                    status_code=200,
                    data=[
                        # 'normal' is a loose co-occurrence association lacking 'syn' tag -> must be rejected
                        {"word": "normal", "tags": ["adj", "f:80.0"]},
                        # 'subjective' is tagged 'syn' but is a known antonym -> must be rejected
                        {"word": "subjective", "tags": ["adj", "syn", "f:25.0"]},
                    ],
                    latency_ms=5.0,
                )
            return ApiResponse(
                status_code=200,
                data=[
                    {"word": "neutral", "tags": ["adj", "f:20.0"]},
                    {"word": "empirical", "tags": ["adj", "f:15.0"]},
                ],
                latency_ms=5.0,
            )

        mock_dispatch.side_effect = fake_dispatch
        result = await find_contextual_synonyms(
            target_word="objective",
            sentence_context="We need an objective evaluation of the model.",
            limit=5,
            use_llm=False,
        )
        words = [s.word for s in result.ranked_synonyms]
        assert len(words) > 0
        assert "normal" not in words  # Normal is not a synonym of objective
        assert "subjective" not in words  # Antonym must be excluded
        assert any(w in words for w in ("unbiased", "impartial", "neutral", "empirical", "dispassionate"))

    @patch("lexical_synonyms.synonyms.dispatch_api_request")
    async def test_objective_noun_context_selects_noun_synonyms(self, mock_dispatch):
        mock_dispatch.return_value = ApiResponse(
            status_code=200,
            data=[
                {"word": "goal", "tags": ["n", "syn", "f:40.0"]},
                {"word": "target", "tags": ["n", "syn", "f:35.0"]},
                {"word": "aim", "tags": ["n", "syn", "f:30.0"]},
                {"word": "neutral", "tags": ["adj", "f:20.0"]},
            ],
            latency_ms=10.0,
        )
        result = await find_contextual_synonyms(
            target_word="objective",
            sentence_context="The primary objective of this study is to evaluate performance.",
            limit=5,
            use_llm=False,
        )
        words = [s.word for s in result.ranked_synonyms]
        assert len(words) > 0
        assert "neutral" not in words  # Adjective must not pollute noun context
        assert any(w in words for w in ("goal", "target", "aim", "purpose", "intent"))

    async def test_qwen_1_5b_llm_synonym_generation(self):
        """Validates 1.5B instruction-tuned LLM generates tense-accurate academic synonyms in context."""
        engine = LexicalSynonymsEngine()
        res = await engine.find_contextual_synonyms(
            target_word="observed",
            sentence_context="Chen et al. observed this in a similar study",
            limit=5,
            use_llm=True,
        )
        words = [s.word.lower() for s in res.ranked_synonyms]
        assert len(words) > 0
        assert "seen" not in words  # Colloquial bad grammar excluded
        assert any(w in words for w in ("documented", "noted", "recorded", "examined", "investigated", "studied"))

    @patch("lexical_synonyms.synonyms.dispatch_api_request")
    async def test_openai_gpt_5_6_luna_synonym_generation(self, mock_dispatch):
        """Validates temporary swap to OpenAI gpt-5.6-luna at low reasoning and highest speed."""
        import json
        mock_dispatch.return_value = ApiResponse(
            status_code=200,
            data={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps([
                                "documented", "noted", "recorded", "scrutinized",
                                "investigated", "witnessed", "detected", "identified",
                                "ascertained", "evaluated", "verified", "analyzed"
                            ]),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 120, "completion_tokens": 45, "total_tokens": 165},
            },
            latency_ms=180.0,
            tokens_consumed=165,
        )

        engine = LexicalSynonymsEngine()
        res = await engine.find_contextual_synonyms(
            target_word="observed",
            sentence_context="Chen et al. observed this in a similar study",
            limit=12,
            use_llm=True,
        )

        assert mock_dispatch.called
        # Verify call arguments sent to LLM_SERVICE
        call_kwargs = mock_dispatch.call_args[1] if mock_dispatch.call_args[1] else mock_dispatch.call_args[0]
        # Check payload
        payload = call_kwargs.payload if hasattr(call_kwargs, "payload") else mock_dispatch.call_args.kwargs.get("payload") or mock_dispatch.call_args[0][2]
        assert payload.json_body["model"] == "gpt-5.6-luna"
        assert payload.json_body["reasoning_effort"] == "low"
        assert payload.json_body["max_completion_tokens"] == 120

        assert len(res.ranked_synonyms) == 12
        words = [s.word for s in res.ranked_synonyms]
        assert "documented" in words
        assert "noted" in words
        assert "observed" not in words  # Target word must be excluded

    @patch("lexical_synonyms.synonyms.dispatch_api_request")
    async def test_openai_fallback_on_quota_error(self, mock_dispatch):
        """Validates that when OpenAI returns HTTP 429 (quota exhausted), engine falls back gracefully."""
        mock_dispatch.return_value = ApiResponse(
            status_code=429,
            data={"error": {"code": "credit_balance_exhausted", "message": "No credits remaining"}},
            latency_ms=50.0,
            error="HTTP 429: credit_balance_exhausted",
        )

        engine = LexicalSynonymsEngine()
        res = await engine.find_contextual_synonyms(
            target_word="observed",
            sentence_context="Chen et al. observed this in a similar study",
            limit=5,
            use_llm=True,
        )

        # Must not raise error, must return valid synonyms via local fallback
        assert isinstance(res, SynonymGroupResult)
        assert len(res.ranked_synonyms) > 0


