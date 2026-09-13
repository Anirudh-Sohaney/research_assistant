# API Gateway Documentation

## Module Overview
`api_gateway` manages all outbound HTTP requests to academic, lexical, and LLM APIs, handling rate limiting, fault tolerance, caching, and token telemetry.

## File Structure
- `models.py`: Data classes (`ExternalService`, `RequestPayload`, `ApiResponse`, `AuthConfig`, `TokenUsageReport`).
- `gateway.py`: Core gateway implementation containing `TokenBucket`, `CircuitBreaker`, `ResponseCache`, and `ApiGateway`.
- `oauth.py`: RFC 8628 OAuth 2.0 Device Authorization Grant implementation for OpenAI (`OpenAIOAuthClient`, `OAuthCredentials`, `DeviceCodeResponse`).
- `tests/test_api_gateway.py`: Pytest suite covering token buckets, circuit breaking, caching, token accounting, and key redaction.
- `tests/test_openai_oauth.py`: Pytest suite validating device code issuance, polling with pending/slow-down backoffs, credential extraction, file persistence, and automatic token refresh.

## API Reference

### `dispatch_api_request(service: ExternalService, endpoint: str, payload: Optional[RequestPayload]) -> ApiResponse`
Dispatches an asynchronous HTTP request through rate limiters, circuit breakers, and caches.
- **`service`**: `ExternalService` enum (`DATAMUSE`, `FREEDICTIONARY`, `SEMANTIC_SCHOLAR`, `OPENALEX`, `ARXIV`, `LLM_SERVICE`).
- **`endpoint`**: Sub-path relative to service base URL (e.g. `"/words"`, `"/v1/chat/completions"`).
- **`payload`**: `RequestPayload(method, params, json_body, headers, timeout, max_tokens)`.
- **Returns**: `ApiResponse(status_code, data, latency_ms, cache_hit, tokens_consumed, error)`.

### `configure_credentials(service: ExternalService, credentials: AuthConfig) -> bool`
Registers authentication keys or custom base URLs for external services.
- **`credentials`**: `AuthConfig(api_key, base_url, org_id)`.

### `get_token_usage_report() -> TokenUsageReport`
Returns telemetry on prompt tokens, completion tokens, cached token savings, and service breakdowns.

### `start_openai_device_flow(client_id: Optional[str] = None, open_browser: bool = True, save_path: Optional[Path] = None) -> OAuthCredentials`
Initiates the interactive RFC 8628 Device Authorization Grant for OpenAI, displays the verification code and URL, opens the browser, polls until confirmed, and saves credentials to disk.

### `save_oauth_credentials(credentials: OAuthCredentials, file_path: Optional[Path] = None) -> Path`
Persists extracted OAuth credentials to `~/.research_aid/openai_oauth.json` with user-restricted permissions (`0o600`).

### `load_oauth_credentials(file_path: Optional[Path] = None) -> Optional[OAuthCredentials]`
Loads stored credentials from disk.

### `get_valid_openrouter_token() -> Optional[str]`
Returns a valid OpenRouter API key from environment (`OPENROUTER_API_KEY`) or persisted credentials file (`~/.research_aid/openrouter_credentials.json`).

### `get_valid_openai_token(file_path: Optional[Path] = None, auto_refresh: bool = True) -> Optional[str]`
Returns a valid OpenAI access token. If expired and a refresh token is present, automatically performs a refresh grant and saves the rotated tokens.

### `verify_real_openai_api_key(api_key: str, organization: Optional[str], project: Optional[str]) -> Dict[str, Any]`
Validates a real OpenAI API key live against `https://api.openai.com/v1/models`, retrieving organization name, project ID, and list of available models.

### `verify_and_save_real_openai_credentials(api_key: str, ...) -> Tuple[OAuthCredentials, Dict[str, Any]]`
Validates a real OpenAI API key against the official API, writes the token to `~/.research_aid/openai_oauth.json` for the gateway, and saves rich account metadata to `~/.research_aid/openai_credentials.json`.

### `apply_oauth_credentials_to_gateway(gateway: ApiGateway, credentials: OAuthCredentials) -> None`
Wires the extracted OAuth access token or verified API key into the `ApiGateway` for `LLM_SERVICE`.

### CLI Tool: `python -m api_gateway.auth_cli`
Interactive command-line tool for managing OpenAI credentials:
- `python -m api_gateway.auth_cli`: Interactive masked prompt for entering and validating OpenAI API keys.
- `python -m api_gateway.auth_cli --status`: Displays current credential status, organization, and model count.
- `python -m api_gateway.auth_cli --key <KEY>`: Direct validation and persistence of a provided key.
- `python -m api_gateway.auth_cli --from-env`: Validates and saves credentials from the `OPENAI_API_KEY` environment variable.
- `python -m api_gateway.auth_cli --clear`: Deletes saved credentials.
- `python -m api_gateway.auth_cli --device-flow`: Initiates RFC 8628 Device Code flow for bridge/enterprise IdPs.

## Usage Example

```python
import asyncio
from api_gateway import (
    ExternalService,
    RequestPayload,
    dispatch_api_request,
    load_oauth_credentials,
    start_openai_device_flow,
)

# 1. Authorize via OAuth 2.0 Device Code Flow
# creds = start_openai_device_flow()

# 2. Or retrieve stored credentials and verify access token
creds = load_oauth_credentials()
if creds and not creds.is_expired():
    print(f"Authenticated with OpenAI via OAuth! Token expires in {creds.expires_at - time.time():.0f}s")
```

## Running Tests
```bash
python -m pytest api_gateway/tests/test_api_gateway.py api_gateway/tests/test_openai_oauth.py -v
```
