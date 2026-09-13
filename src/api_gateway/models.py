"""Data models for the API Gateway."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class ExternalService(str, Enum):
    """External services managed by the gateway."""
    DATAMUSE = "DATAMUSE"
    FREEDICTIONARY = "FREEDICTIONARY"
    SEMANTIC_SCHOLAR = "SEMANTIC_SCHOLAR"
    OPENALEX = "OPENALEX"
    ARXIV = "ARXIV"
    LLM_SERVICE = "LLM_SERVICE"


@dataclass
class RequestPayload:
    """Outbound request specification."""
    method: str = "GET"
    params: Optional[Dict[str, Any]] = None
    json_body: Optional[Dict[str, Any]] = None
    headers: Optional[Dict[str, str]] = None
    timeout: float = 10.0
    max_tokens: Optional[int] = None


@dataclass
class ApiResponse:
    """Normalized response returned by the gateway."""
    status_code: int
    data: Any
    latency_ms: float
    cache_hit: bool = False
    tokens_consumed: int = 0
    error: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300 and self.error is None


@dataclass
class AuthConfig:
    """Credentials and host configuration for a service."""
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    org_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenUsageReport:
    """Aggregate token usage telemetry."""
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    cached_tokens_saved: int = 0
    estimated_cost_usd: float = 0.0
    service_breakdown: Dict[str, int] = field(default_factory=dict)
