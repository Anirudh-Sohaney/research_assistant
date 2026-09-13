# API Gateway

The gateway centralizes outbound requests, rate limiting, circuit breaking, response caching, and token telemetry.

## Services

Supported services include Datamuse, Free Dictionary, Semantic Scholar, OpenAlex, arXiv, and the OpenRouter-compatible LLM endpoint.

## Authentication

Set `OPENROUTER_API_KEY` in the process environment for LLM requests. Optional source credentials are read from `OPENALEX_API_KEY`, `CORE_API_KEY`, and `SEMANTIC_SCHOLAR_API_KEY` where the corresponding source supports them. No credentials are stored by this package.

`configure_credentials(service, AuthConfig(...))` can also provide runtime credentials or a custom base URL.
