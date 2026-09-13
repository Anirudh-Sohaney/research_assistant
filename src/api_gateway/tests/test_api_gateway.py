"""Unit and integration tests for api_gateway subsystem."""

import asyncio
import os
import sys
import tempfile
import time
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest

_src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from api_gateway.models import (
    ExternalService,
    RequestPayload,
    ApiResponse,
    AuthConfig,
    TokenUsageReport,
)
from api_gateway.gateway import (
    ApiGateway,
    TokenBucket,
    CircuitBreaker,
    ResponseCache,
    dispatch_api_request,
    configure_credentials,
    get_token_usage_report,
)


@pytest.mark.asyncio
async def test_token_bucket_acquire():
    bucket = TokenBucket(rate_per_sec=20.0, capacity=2.0)
    t0 = time.monotonic()
    await bucket.acquire()
    await bucket.acquire()
    elapsed = time.monotonic() - t0
    assert elapsed < 0.2


def test_circuit_breaker_transitions():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.2)
    assert cb.can_execute() is True
    assert cb.state == "CLOSED"

    cb.record_failure()
    cb.record_failure()
    assert cb.can_execute() is True
    assert cb.state == "CLOSED"

    cb.record_failure()
    assert cb.state == "OPEN"
    assert cb.can_execute() is False

    # Wait for recovery timeout
    time.sleep(0.25)
    assert cb.can_execute() is True
    assert cb.state == "HALF_OPEN"

    cb.record_success()
    assert cb.state == "CLOSED"
    assert cb.consecutive_failures == 0


def test_cache_set_and_get():
    db_file = os.path.join(tempfile.gettempdir(), f"test_cache_{os.getpid()}_{time.time_ns()}.db")
    try:
        cache = ResponseCache(db_file)
        params = {"rel_syn": "test"}
        assert cache.get("DATAMUSE", "/words", params) is None

        cache.set("DATAMUSE", "/words", params, 200, [{"word": "trial"}], ttl_sec=10.0)
        hit = cache.get("DATAMUSE", "/words", params)
        assert hit is not None
        code, data = hit
        assert code == 200
        assert data == [{"word": "trial"}]
    finally:
        try:
            if os.path.exists(db_file):
                os.unlink(db_file)
            for ext in ("-wal", "-shm"):
                if os.path.exists(db_file + ext):
                    os.unlink(db_file + ext)
        except Exception:
            pass


@pytest.mark.asyncio
@patch("api_gateway.oauth.get_valid_openrouter_token", return_value=None)
@patch("api_gateway.oauth.get_valid_openai_token", return_value=None)
async def test_unconfigured_llm_fails_gracefully(mock_openai, mock_openrouter):
    gateway = ApiGateway()
    try:
        resp = await gateway.dispatch_api_request(
            ExternalService.LLM_SERVICE,
            "/chat/completions",
            RequestPayload(method="POST", json_body={"model": "gpt-4o"}),
        )
        assert resp.status_code == 400
        assert "UNCONFIGURED" in (resp.error or "")
    finally:
        await gateway.close()


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request")
async def test_mocked_datamuse_query(mock_req):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.is_success = True
    mock_response.json.return_value = [{"word": "omnipresent", "score": 1000}]
    mock_req.return_value = mock_response

    db_file = os.path.join(tempfile.gettempdir(), f"test_gw_{os.getpid()}_{time.time_ns()}.db")
    gw = ApiGateway(cache_db_path=db_file)
    try:
        resp = await gw.dispatch_api_request(
            ExternalService.DATAMUSE,
            "/words",
            RequestPayload(params={"rel_syn": "ubiquitous"}),
        )
        assert resp.status_code == 200
        assert resp.data == [{"word": "omnipresent", "score": 1000}]
        assert resp.cache_hit is False

        # Test cache hit on second call
        resp_cached = await gw.dispatch_api_request(
            ExternalService.DATAMUSE,
            "/words",
            RequestPayload(params={"rel_syn": "ubiquitous"}),
        )
        assert resp_cached.status_code == 200
        assert resp_cached.cache_hit is True
        assert resp_cached.tokens_consumed == 0
    finally:
        await gw.close()
        try:
            if os.path.exists(db_file):
                os.unlink(db_file)
            for ext in ("-wal", "-shm"):
                if os.path.exists(db_file + ext):
                    os.unlink(db_file + ext)
        except Exception:
            pass


@pytest.mark.asyncio
@patch("httpx.AsyncClient.request")
async def test_llm_token_accounting(mock_req):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.is_success = True
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Reworded sentence."}}],
        "usage": {"prompt_tokens": 40, "completion_tokens": 15},
    }
    mock_req.return_value = mock_response

    gw = ApiGateway()
    try:
        gw.configure_credentials(
            ExternalService.LLM_SERVICE,
            AuthConfig(api_key="sk-testsecretkey1234567890"),
        )

        resp = await gw.dispatch_api_request(
            ExternalService.LLM_SERVICE,
            "/chat/completions",
            RequestPayload(
                method="POST",
                json_body={"messages": [{"role": "user", "content": "Hi"}]},
                max_tokens=50,
            ),
        )
        assert resp.status_code == 200
        assert resp.tokens_consumed == 55

        report = gw.get_token_usage_report()
        assert report.total_prompt_tokens == 40
        assert report.total_completion_tokens == 15
    finally:
        await gw.close()


def test_key_redaction():
    raw = "Error sending to sk-proj123456789ABCDEF with key sk-1234567890abcdef"
    redacted = ApiGateway.redact_key(raw)
    assert "sk-123456[REDACTED]" in redacted
