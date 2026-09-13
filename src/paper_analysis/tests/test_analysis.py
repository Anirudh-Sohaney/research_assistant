import asyncio
import os
import sys
from unittest.mock import patch

import pytest

_src = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _src not in sys.path: sys.path.insert(0, _src)

from api_gateway.models import ApiResponse
from paper_analysis.analysis import JUDGE_RUBRICS, _run_judge, analyze_paper


def _response(name: str, score: int = 84):
    return ApiResponse(200, {"choices": [{"message": {"content": '{"score":%d,"findings":[{"excerpt":"sample phrase","issue":"%s issue","fix":"Rewrite this phrase precisely."},{"excerpt":"another phrase","issue":"Needs support","fix":"Add the missing explanation."},{"excerpt":"the conclusion","issue":"Too broad","fix":"Limit the claim to the evidence."}]}' % (score, name)}}]}, 1.0, tokens_consumed=11)


@pytest.mark.asyncio
async def test_eight_full_text_judges_run_and_return_curved_scores():
    paper = "The study evaluates a reproducible method on a carefully described benchmark dataset."
    with patch("paper_analysis.analysis.dispatch_api_request", side_effect=[_response(name) for name in JUDGE_RUBRICS]):
        result = await analyze_paper(paper)
    assert len(result.judges) == 8
    assert result.overall_score == 87
    assert all(j.score == 87 and len(j.findings) == 3 for j in result.judges)


@pytest.mark.asyncio
async def test_each_judge_payload_contains_complete_selected_text():
    calls = []
    async def dispatch(*args):
        calls.append(args[2].json_body)
        return _response("dimension")
    paper = "A long selected paper section with methods, results, limitations, and conclusions."
    with patch("paper_analysis.analysis.dispatch_api_request", side_effect=dispatch):
        await analyze_paper(paper)
    assert len(calls) == 8
    assert all(p["messages"][1]["content"].endswith(paper) for p in calls)
    assert {p["messages"][0]["content"].split("Your assigned dimension is ", 1)[1].split(":", 1)[0] for p in calls} == set(JUDGE_RUBRICS)


@pytest.mark.asyncio
async def test_failed_judge_is_visible_without_fabricating_findings():
    responses = [_response("ok") for _ in range(7)] + [ApiResponse(503, None, 1.0, error="offline")]
    with patch("paper_analysis.analysis.dispatch_api_request", side_effect=responses):
        result = await analyze_paper("A paper paragraph.")
    assert sum(j.score is not None for j in result.judges) == 7
    assert result.judges[-1].score is None
    assert result.judges[-1].findings == []


@pytest.mark.asyncio
async def test_judges_are_published_as_they_complete():
    completed = []

    async def dispatch(*args):
        return _response("stream")

    with patch("paper_analysis.analysis.dispatch_api_request", side_effect=dispatch):
        await analyze_paper("A paper paragraph.", on_judge=lambda judge: completed.append(judge.name))
    assert len(completed) == 8
    assert set(completed) == set(JUDGE_RUBRICS)


@pytest.mark.asyncio
async def test_judge_uses_up_to_three_retries_for_invalid_output():
    invalid = ApiResponse(200, {"choices": [{"message": {"content": "not json"}}]}, 1.0, tokens_consumed=2)
    with patch("paper_analysis.analysis.dispatch_api_request", side_effect=[invalid, invalid, invalid, _response("retry")]) as dispatch:
        result = await _run_judge("Grammar", JUDGE_RUBRICS["Grammar"], "A paper paragraph.")
    assert result.score is not None
    assert len(result.findings) == 3
    assert dispatch.call_count == 4
