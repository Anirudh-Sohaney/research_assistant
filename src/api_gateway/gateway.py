"""Centralized API Gateway implementation with rate-limiting, circuit-breaking, and disk caching."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from typing import Any, Dict, Optional, Tuple

import httpx

from api_gateway.models import (
    ApiResponse,
    AuthConfig,
    ExternalService,
    RequestPayload,
    TokenUsageReport,
)

log = logging.getLogger("api_gateway")

# Default Base URLs
SERVICE_BASE_URLS: Dict[ExternalService, str] = {
    ExternalService.DATAMUSE: "https://api.datamuse.com",
    ExternalService.FREEDICTIONARY: "https://api.dictionaryapi.dev/api/v2/entries/en",
    ExternalService.SEMANTIC_SCHOLAR: "https://api.semanticscholar.org/graph/v1",
    ExternalService.OPENALEX: "https://api.openalex.org",
    ExternalService.ARXIV: "http://export.arxiv.org/api",
    ExternalService.LLM_SERVICE: os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
}

# Rate limits (requests per second)
SERVICE_RATE_LIMITS: Dict[ExternalService, float] = {
    ExternalService.DATAMUSE: 15.0,
    ExternalService.FREEDICTIONARY: 15.0,
    ExternalService.SEMANTIC_SCHOLAR: 1.0,
    ExternalService.OPENALEX: 10.0,
    ExternalService.ARXIV: 0.33,  # 1 req / 3 sec
    ExternalService.LLM_SERVICE: 5.0,
}


class TokenBucket:
    """Async token bucket rate limiter."""

    def __init__(self, rate_per_sec: float, capacity: Optional[float] = None):
        self.rate = rate_per_sec
        self.capacity = capacity if capacity is not None else max(1.0, rate_per_sec)
        self.tokens = self.capacity
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.last_update = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

            if self.tokens < 1.0:
                needed = 1.0 - self.tokens
                wait_time = needed / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0.0
                self.last_update = time.monotonic()
            else:
                self.tokens -= 1.0


class CircuitBreaker:
    """Three-state circuit breaker pattern (CLOSED, OPEN, HALF_OPEN)."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = "CLOSED"
        self.consecutive_failures = 0
        self.last_failure_time = 0.0

    def can_execute(self) -> bool:
        if self.state == "CLOSED":
            return True
        now = time.monotonic()
        if self.state == "OPEN":
            if now - self.last_failure_time >= self.recovery_timeout:
                self.state = "HALF_OPEN"
                return True
            return False
        return True  # HALF_OPEN allows probe

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.state = "CLOSED"

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        self.last_failure_time = time.monotonic()
        if self.consecutive_failures >= self.failure_threshold:
            self.state = "OPEN"


class ResponseCache:
    """SQLite-backed persistent cache for idempotent GET requests."""

    def __init__(self, db_path: Optional[str] = None):
        if not db_path:
            import tempfile
            db_path = os.path.join(tempfile.gettempdir(), "research_aid_gateway_cache.db")
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        try:
            conn = self._get_conn()
            try:
                with conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS http_cache (
                            cache_key TEXT PRIMARY KEY,
                            service TEXT,
                            status_code INTEGER,
                            response_json TEXT,
                            created_at REAL,
                            ttl_sec REAL
                        )
                        """
                    )
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_created ON http_cache(created_at)")
            finally:
                conn.close()
        except Exception as exc:
            log.warning("Cache init warning: %s", exc)

    @staticmethod
    def _compute_key(service: str, endpoint: str, params: Optional[Dict[str, Any]]) -> str:
        param_str = json.dumps(params or {}, sort_keys=True)
        raw = f"{service}:{endpoint}:{param_str}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, service: str, endpoint: str, params: Optional[Dict[str, Any]]) -> Optional[Tuple[int, Any]]:
        key = self._compute_key(service, endpoint, params)
        now = time.time()
        try:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "SELECT status_code, response_json, created_at, ttl_sec FROM http_cache WHERE cache_key = ?",
                    (key,),
                )
                row = cursor.fetchone()
                if row:
                    status_code, response_json, created_at, ttl_sec = row
                    if now - created_at <= ttl_sec:
                        return status_code, json.loads(response_json)
                    with conn:
                        conn.execute("DELETE FROM http_cache WHERE cache_key = ?", (key,))
            finally:
                conn.close()
        except Exception as exc:
            log.warning("Cache read error: %s", exc)
        return None

    def set(
        self,
        service: str,
        endpoint: str,
        params: Optional[Dict[str, Any]],
        status_code: int,
        data: Any,
        ttl_sec: float = 86400.0,
    ) -> None:
        key = self._compute_key(service, endpoint, params)
        now = time.time()
        try:
            conn = self._get_conn()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO http_cache (cache_key, service, status_code, response_json, created_at, ttl_sec)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (key, service, status_code, json.dumps(data), now, ttl_sec),
                    )
            finally:
                conn.close()
        except Exception as exc:
            log.warning("Cache write error: %s", exc)


class ApiGateway:
    """Master API Gateway coordinating routing, token accounting, and resilience."""

    def __init__(self, cache_db_path: Optional[str] = None):
        self.credentials: Dict[ExternalService, AuthConfig] = {}
        self.limiters: Dict[ExternalService, TokenBucket] = {
            svc: TokenBucket(rate) for svc, rate in SERVICE_RATE_LIMITS.items()
        }
        self.breakers: Dict[ExternalService, CircuitBreaker] = {
            svc: CircuitBreaker() for svc in ExternalService
        }
        self.cache = ResponseCache(cache_db_path)
        self.telemetry = TokenUsageReport()
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(15.0, connect=5.0),
                follow_redirects=True,
                headers={"User-Agent": "ResearchAid-DesktopAssistant/1.0 (mailto:research-aid@local.dev)"},
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @staticmethod
    def redact_key(text: str) -> str:
        """Redact API keys like sk-... or Authorization headers."""
        return re.sub(r"(sk-[a-zA-Z0-9_\-]{6})[a-zA-Z0-9_\-]+", r"\1[REDACTED]", text)

    def configure_credentials(self, service: ExternalService, credentials: AuthConfig) -> bool:
        """Register credentials and update rate limits accordingly."""
        self.credentials[service] = credentials
        if service == ExternalService.SEMANTIC_SCHOLAR and credentials.api_key:
            self.limiters[service] = TokenBucket(10.0)
        return True

    def get_token_usage_report(self) -> TokenUsageReport:
        """Return the current token consumption telemetry."""
        return self.telemetry

    async def dispatch_api_request(
        self,
        service: ExternalService,
        endpoint: str,
        payload: Optional[RequestPayload] = None,
    ) -> ApiResponse:
        """Dispatches an HTTP request with rate-limiting, circuit-breaking, and token tracking."""
        payload = payload or RequestPayload()
        start_time = time.monotonic()

        # Check circuit breaker
        breaker = self.breakers.get(service)
        if breaker and not breaker.can_execute():
            return ApiResponse(
                status_code=503,
                data=None,
                latency_ms=(time.monotonic() - start_time) * 1000,
                error="Circuit breaker is OPEN. Service unavailable.",
            )

        # Probe cache for GET requests
        if payload.method.upper() == "GET":
            cached = self.cache.get(service.value, endpoint, payload.params)
            if cached is not None:
                status, data = cached
                self.telemetry.cached_tokens_saved += 50
                return ApiResponse(
                    status_code=status,
                    data=data,
                    latency_ms=(time.monotonic() - start_time) * 1000,
                    cache_hit=True,
                    tokens_consumed=0,
                )

        # Rate limiting acquisition
        limiter = self.limiters.get(service)
        if limiter:
            await limiter.acquire()

        # Resolve URL and headers
        base_url = (
            self.credentials.get(service, AuthConfig()).base_url
            or SERVICE_BASE_URLS.get(service, "")
        )
        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}" if endpoint else base_url

        headers = dict(payload.headers or {})
        auth = self.credentials.get(service)

        if auth and auth.api_key:
            if service == ExternalService.LLM_SERVICE:
                headers["Authorization"] = f"Bearer {auth.api_key}"
            elif service == ExternalService.SEMANTIC_SCHOLAR:
                headers["x-api-key"] = auth.api_key

        if "openrouter.ai" in url:
            headers.setdefault("HTTP-Referer", "https://github.com/Anirudh-Sohaney/research_assistant")
            headers.setdefault("X-Title", "Research Aid")

        if service == ExternalService.LLM_SERVICE and (not auth or not auth.api_key):
            # Attempt auto-loading persisted OpenRouter or OpenAI token from disk
            try:
                from api_gateway.oauth import get_valid_openrouter_token, get_valid_openai_token
                auto_token = get_valid_openrouter_token() or get_valid_openai_token()
                if auto_token:
                    self.credentials[ExternalService.LLM_SERVICE] = AuthConfig(api_key=auto_token)
                    auth = self.credentials[ExternalService.LLM_SERVICE]
                    headers["Authorization"] = f"Bearer {auto_token}"
            except Exception as exc:
                log.debug("Notice auto-loading LLM token: %s", exc)

        if service == ExternalService.LLM_SERVICE and (not auth or not auth.api_key):
            # Graceful unconfigured LLM notice
            return ApiResponse(
                status_code=400,
                data=None,
                latency_ms=(time.monotonic() - start_time) * 1000,
                error="LLM_SERVICE is UNCONFIGURED. No API key provided.",
            )

        # Handle LLM Token Caps
        body = payload.json_body
        if service == ExternalService.LLM_SERVICE and body and payload.max_tokens:
            body["max_tokens"] = payload.max_tokens

        client = self._get_client()

        try:
            resp = await client.request(
                method=payload.method.upper(),
                url=url,
                params=payload.params,
                json=body,
                headers=headers,
                timeout=payload.timeout,
            )
            latency_ms = (time.monotonic() - start_time) * 1000

            try:
                data = resp.json()
            except Exception:
                data = resp.text

            tokens_consumed = 0
            if service == ExternalService.LLM_SERVICE and isinstance(data, dict):
                usage = data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                tokens_consumed = prompt_tokens + completion_tokens
                self.telemetry.total_prompt_tokens += prompt_tokens
                self.telemetry.total_completion_tokens += completion_tokens
                svc_key = service.value
                self.telemetry.service_breakdown[svc_key] = (
                    self.telemetry.service_breakdown.get(svc_key, 0) + tokens_consumed
                )

            if resp.status_code >= 500:
                if breaker:
                    breaker.record_failure()
            elif resp.is_success:
                if breaker:
                    breaker.record_success()
                if payload.method.upper() == "GET" and resp.status_code == 200:
                    self.cache.set(service.value, endpoint, payload.params, resp.status_code, data)

            return ApiResponse(
                status_code=resp.status_code,
                data=data,
                latency_ms=latency_ms,
                tokens_consumed=tokens_consumed,
                error=None if resp.is_success else f"HTTP {resp.status_code}: {str(data)[:200]}",
            )

        except httpx.RequestError as exc:
            if breaker:
                breaker.record_failure()
            latency_ms = (time.monotonic() - start_time) * 1000
            safe_err = self.redact_key(str(exc))
            return ApiResponse(
                status_code=500,
                data=None,
                latency_ms=latency_ms,
                error=f"Request failed: {safe_err}",
            )


# Global Default Gateway Instance
_global_gateway = ApiGateway()


async def dispatch_api_request(
    service: ExternalService,
    endpoint: str,
    payload: Optional[RequestPayload] = None,
) -> ApiResponse:
    """Module-level dispatch helper."""
    return await _global_gateway.dispatch_api_request(service, endpoint, payload)


def configure_credentials(service: ExternalService, credentials: AuthConfig) -> bool:
    """Module-level credentials configurator."""
    return _global_gateway.configure_credentials(service, credentials)


def get_token_usage_report() -> TokenUsageReport:
    """Module-level telemetry report."""
    return _global_gateway.get_token_usage_report()
