"""Unit tests for text_reword subsystem."""

import os
import sys
from unittest.mock import patch

import pytest

_src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from api_gateway.models import ApiResponse
from text_reword.models import EntityMaskReport, RewordResult, RewordStyle, SurroundingContext
from text_reword.reword import (
    TextRewordEngine,
    mask_scholarly_entities,
    restore_scholarly_entities,
    reword_text_segment,
)


class TestEntityShielding:
    def test_citation_and_math_masking(self):
        raw = "Recent trials confirm quantum coherence (Bohr et al., 2020) when $\\mathcal{L} > 0.05$ holds."
        report = mask_scholarly_entities(raw)

        assert isinstance(report, EntityMaskReport)
        assert "(Bohr et al., 2020)" not in report.masked_text
        assert "$\\mathcal{L} > 0.05$" not in report.masked_text
        assert "__CITE_0__" in report.masked_text or "__CITE_1__" in report.masked_text
        assert "__MATH_0__" in report.masked_text or "__MATH_1__" in report.masked_text

    def test_entity_restoration(self):
        raw = "Coherence persists (Bohr et al., 2020) under $T < 10K$."
        report = mask_scholarly_entities(raw)
        # Simulate an LLM rewriting the masked text
        rewritten_by_llm = report.masked_text.replace("Coherence persists", "Quantum coherence remains stable")
        restored = restore_scholarly_entities(rewritten_by_llm, report.mask_map)

        assert "(Bohr et al., 2020)" in restored
        assert "$T < 10K$" in restored
        assert "__CITE" not in restored
        assert "__MATH" not in restored

    def test_structured_response_parser_accepts_fenced_json(self):
        parsed = TextRewordEngine._parse_structured_response(
            'Here is the result:\n```json\n{"primary":"The result was confirmed.","variants":[]}\n```'
        )
        assert parsed["primary"] == "The result was confirmed."


@pytest.mark.asyncio
class TestRewordExecution:
    @patch("text_reword.reword.query_semantic_cache", return_value=None)
    @patch("text_reword.reword.dispatch_api_request")
    async def test_llm_only_reports_unavailable_service(self, mock_dispatch, mock_cache):
        mock_dispatch.return_value = ApiResponse(status_code=503, data=None, latency_ms=0.0, error="offline")
        engine = TextRewordEngine()
        sentence = "We need to look into a lot of options (Smith, 2021) to make sure this works."
        result = await engine.reword_text_segment(sentence, style=RewordStyle.ACADEMIC_FORMAL)

        assert isinstance(result, RewordResult)
        assert result.primary_replacement == ""
        assert result.error == "OpenRouter did not return a usable rewording."

    @patch("text_reword.reword.query_semantic_cache", return_value=None)
    @patch("text_reword.reword.dispatch_api_request")
    async def test_mocked_llm_response(self, mock_dispatch, mock_cache):
        mock_dispatch.return_value = ApiResponse(
            status_code=200,
            data={
                "choices": [
                    {
                        "message": {
                            "content": '{"primary": "Empirical trials confirm coherence __CITE_0__.", "variants": ["Prior experiments substantiate coherence __CITE_0__.", "As demonstrated by __CITE_0__, coherence is preserved."]}'
                        }
                    }
                ],
                "usage": {"prompt_tokens": 50, "completion_tokens": 25},
            },
            latency_ms=45.0,
            tokens_consumed=75,
        )

        sentence = "Experiments show coherence (Smith et al., 2022)."
        result = await reword_text_segment(sentence, style=RewordStyle.ACADEMIC_FORMAL)

        assert isinstance(result, RewordResult)
        assert result.tokens_used == 75
        assert "(Smith et al., 2022)" in result.primary_replacement
        assert len(result.alternative_variants) == 2
        assert all("(Smith et al., 2022)" in v for v in result.alternative_variants)

    @patch("text_reword.reword.query_semantic_cache", return_value=None)
    @patch("text_reword.reword.dispatch_api_request")
    async def test_ling_model_and_explicit_mode_prompt(self, mock_dispatch, mock_cache):
        mock_dispatch.return_value = ApiResponse(
            status_code=200,
            data={"choices": [{"message": {"content": '{"primary":"The experiments demonstrate robust results.","variants":[]}'}}]},
            latency_ms=20.0,
            tokens_consumed=12,
        )
        await reword_text_segment(
            "The experiments show good results.",
            style=RewordStyle.EXPANDED_ARGUMENT,
        )
        payload = mock_dispatch.call_args.args[2]
        assert payload.json_body["model"] == "nvidia/nemotron-3-ultra-550b-a55b:free"
        assert "add useful detail" in payload.json_body["messages"][0]["content"]
