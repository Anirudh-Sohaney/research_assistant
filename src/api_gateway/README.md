# API Gateway Subsystem

## 1. Final Deliverable
A centralized egress communications and token-efficiency gateway (`api_gateway`) providing:
- Asynchronous API request dispatching (`dispatch_api_request()`) to external services: Datamuse, FreeDictionary, Semantic Scholar, OpenAlex, arXiv, and authenticated LLM endpoints.
- Event-loop-safe async client lifecycle for desktop worker requests, allowing repeated popup generations without reusing an `httpx.AsyncClient` across closed asyncio loops.
- Per-service asynchronous Token Bucket rate limiting.
- Three-state Circuit Breaker (`CLOSED`, `OPEN`, `HALF_OPEN`) with fast-fail capability during outages.
- Persistent SQLite disk caching for idempotent GET requests with TTL eviction.
- Token accounting telemetry (`get_token_usage_report()`) and prompt/completion tracking.
- Credential management (`configure_credentials()`) with automatic API key masking in logs.
- **OpenRouter & OpenAI Provider Integration** (`oauth.py`, `gateway.py`, `auth_cli.py`):
  - Routes `ExternalService.LLM_SERVICE` to OpenRouter (`https://openrouter.ai/api/v1`) by default with environment override (`LLM_BASE_URL`).
  - Auto-loads OpenRouter API key from environment (`OPENROUTER_API_KEY`) or local file (`~/.research_aid/openrouter_credentials.json`), falling back to OpenAI credentials.
  - Automatically injects required `HTTP-Referer` and `X-Title` headers for OpenRouter requests.
  - Real OpenAI API Key extraction, live validation against `api.openai.com/v1/models`, organization & project resolution, and secure persistence (`verify_real_openai_api_key()`, `verify_and_save_real_openai_credentials()`).
  - Interactive CLI management tool (`python -m api_gateway.auth_cli`) for checking status, interactive masked authentication, environment variable ingestion, and clearing credentials.
  - **OpenAI OAuth 2.0 Device Code Flow (RFC 8628)** (`OpenAIOAuthClient`, `oauth.py`):
    - Device code grant initiation (`request_device_code()`) requesting user code and verification URL.
    - Interactive terminal instruction banner and browser launch (`login()`, `start_openai_device_flow()`).
    - RFC 8628 polling loop (`poll_for_token()`) with backoff for `authorization_pending` and `slow_down`.
    - Secure credential extraction and persistence (`save_oauth_credentials()`, `load_oauth_credentials()`, `clear_oauth_credentials()`) with user-only permissions (`0o600`).
    - Automatic token expiration detection and refresh token grant exchange (`refresh_token()`, `get_valid_openai_token()`).
    - Gateway integration helper (`apply_oauth_credentials_to_gateway()`).

## 2. Algorithm Used
1. **Token Bucket Rate Limiter**: Accumulates floating tokens based on elapsed monotonic time ($\text{rate} \times \Delta t$), capping at bucket capacity. Requests wait on `asyncio.sleep` only if tokens are insufficient.
2. **Circuit Breaker Pattern**:
   - Counts consecutive HTTP 5xx / connection failures.
   - Trips to `OPEN` when threshold is exceeded (default: 5 failures), fast-failing subsequent calls within $<1\text{ms}$.
   - Automatically transitions to `HALF_OPEN` after a recovery cooldown (30s) to probe upstream service health.
3. **Deterministic SQLite Caching**:
   - Computes deterministic SHA-256 cache keys: `hash(service + endpoint + sorted_params)`.
   - Returns cached payloads with `cache_hit=True`, bypassing network calls and saving token/rate budgets.
4. **RFC 8628 Device Authorization Grant Algorithm**:
   - **Step 1 (Device Auth)**: Client sends POST to `https://auth.openai.com/oauth/device/code` with `client_id`, `scope`, and `audience`. Receives `device_code`, `user_code`, `verification_uri`, and polling `interval`.
   - **Step 2 (User Interaction)**: Displays `user_code` and opens `verification_uri` in the browser for user confirmation.
   - **Step 3 (Polling)**: Client polls `https://auth.openai.com/oauth/token` with `grant_type=urn:ietf:params:oauth:grant-type:device_code` every `interval` seconds.
     - Handles `authorization_pending` by sleeping `interval`.
     - Handles `slow_down` by increasing `interval += 5`.
     - Catches `expired_token` and `access_denied` with explicit custom exceptions.
   - **Step 4 (Credential Persistence)**: Upon HTTP 200, extracts `access_token`, `refresh_token`, `expires_at`, `token_type`, and writes to `~/.research_aid/openai_oauth.json` with user-restricted permissions.
5. **Token Economics & Guardrails**:
   - Enforces hard `max_tokens` boundaries on LLM payloads.
   - Injects polite headers (`User-Agent` with `mailto`) for high-throughput academic pools.

## 3. Description
The `api_gateway` subsystem acts as the single egress controller for the Research Aid Desktop Assistant. It protects user API budgets, prevents HTTP 429 rate-limit bans, enables Tier 1 non-LLM feature modules (synonyms, definitions, paper discovery) to query free academic and lexical web services reliably, and provides native RFC 8628 OAuth 2.0 Device Code authorization for OpenAI credentials without requiring hardcoded API secrets. *(Note: OpenAI LLM inference usage is decoupled and will be implemented in subsequent phases).*
