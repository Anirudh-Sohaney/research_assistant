# Agent Module

Central LLM orchestration layer for the Research Aid Desktop Assistant. Provides unified inference, prompt engineering, structured output, and streaming across local (Ollama) and remote (OpenAI, Anthropic, Google) models.

## Overview

The agent module abstracts LLM interactions behind a stable API so other modules (writing assistance, RAG, codebase analysis) can use LLM capabilities without coupling to a specific provider. It handles multi-provider inference, prompt management, structured output validation, context window management, and streaming.

## Installation

```bash
pip install -e ".[agent]"
```

Core dependencies: `httpx>=0.27`, `pydantic>=2.0`, `tiktoken>=0.7`

Optional: `ollama>=0.3`, `openai>=1.0`, `anthropic>=0.30`, `google-generativeai>=0.5`

## API Reference

### `generate`

```python
def generate(
    prompt: str,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    top_p: float = 0.9,
    top_k: int | None = None,
    frequency_penalty: float = 0.0,
    presence_penalty: float = 0.0,
    stop: list[str] | None = None,
    stream: bool = False,
    system_prompt: str | None = None,
    context: list[dict] | None = None,
    timeout: int = 30,
    retry_count: int = 2,
    provider: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """
    Returns: {
        "response", "model_used", "tokens_used", "tokens_prompt",
        "tokens_completion", "tokens_remaining", "latency_ms",
        "finish_reason", "error_message", "provider", "metadata", "cached"
    }
    """
```

### `generate_structured`

```python
def generate_structured(
    prompt: str,
    output_schema: dict | type[BaseModel],
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    retries: int = 3,
    system_prompt: str | None = None,
    context: list[dict] | None = None,
    provider: str | None = None,
    strict: bool = True,
    timeout: int = 30,
) -> dict:
    """
    Returns: {
        "parsed_output", "raw_response", "schema_valid", "validation_errors",
        "model_used", "attempts", "total_latency_ms"
    }
    """
```

### `batch_generate`

```python
async def batch_generate(
    prompts: list[str | dict],
    model: str | None = None,
    max_concurrent: int = 3,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """
    Returns: [{
        "response", "index", "success", "error_message",
        "latency_ms", "tokens_used", "model_used"
    }]
    """
```

### `classify_text`

```python
def classify_text(
    text: str,
    categories: list[str],
    model: str | None = None,
    temperature: float = 0.1,
    multi_label: bool = False,
) -> dict:
    """
    Returns: {
        "classification", "confidence", "all_scores",
        "model_used", "latency_ms"
    }
    """
```

### `extract_information`

```python
def extract_information(
    text: str,
    extraction_prompt: str,
    output_format: str = "json",
    model: str | None = None,
    schema: dict | type[BaseModel] | None = None,
) -> dict:
    """
    Returns: {
        "extracted_data", "raw_response", "format_valid",
        "parsing_error", "model_used", "latency_ms", "tokens_used"
    }
    """
```

### Streaming

All functions support `stream=True`, returning an async generator yielding chunks:

```python
async for chunk in generate(prompt="...", stream=True):
    print(chunk["token"], end="", flush=True)
```

## Potential Solutions

### Local LLM Backends

| Solution | License | Pros | Cons |
|----------|---------|------|------|
| **Ollama** | MIT | One-command setup, GPU auto-detect, OpenAI-compatible API | Limited fine-tuning, single-node |
| **llama.cpp** | MIT | Smallest memory footprint, CPU+GPU hybrid, quantization | Manual model management |
| **vLLM** | Apache-2.0 | PagedAttention, continuous batching, tensor parallel | High VRAM requirements |

### API Providers

| Provider | Key Models | Pros | Cons |
|----------|-----------|------|------|
| **OpenAI** | GPT-4o, GPT-4o-mini | Best general quality, function calling | Rate limits, cost at scale |
| **Anthropic** | Claude 3.5 Sonnet/Haiku | 200K context, strong reasoning | Strict rate limits |
| **Google** | Gemini 1.5 Pro/Flash | 1M context, multimodal, free tier | Inconsistent JSON mode |
| **Mistral** | Mistral Large/Small | Open-weight available, EU data residency | Smaller ecosystem |

### Orchestration & Structured Output

| Library | License | Best For |
|---------|---------|----------|
| **LangChain** | MIT | Complex chains, agents, tool orchestration |
| **LlamaIndex** | MIT | RAG pipelines, document retrieval |
| **Instructor** | MIT | Pydantic-validated structured output with retries |
| **Outlines** | Apache-2.0 | Constrained decoding, guaranteed valid output |

## Design Decisions

### Latency Targets

| Task | Target | Approach |
|------|--------|----------|
| Writing assistance | <500ms | Local Ollama (phi3, qwen2) |
| Evidence synthesis | <5s | API (GPT-4o/Claude) |
| Codebase analysis | <10s | API with streaming |

### Model Selection Tiers

```
Tier 1 (Local, <500ms): phi3:mini, qwen2:1.5b
  → Synonyms, definitions, classification

Tier 2 (Local, <2s): llama3.2:8b, mistral:7b
  → Rewording, context-aware suggestions

Tier 3 (API, <5s): GPT-4o-mini, Claude 3.5 Haiku
  → Structured extraction, complex reasoning

Tier 4 (API, <10s): GPT-4o, Claude 3.5 Sonnet
  → Evidence synthesis, research QA
```

### Error Handling

- **Transient errors** (5xx, timeout, rate limit): exponential backoff, max 3 retries, fallback to next provider
- **Permanent errors** (4xx, invalid key): immediate `ProviderError`
- **Structured output failures**: repair prompt with schema error details, up to 3 attempts

### Context Window Management

`context_manager.py` provides token budgeting via `tiktoken`/`AutoTokenizer`, sliding window truncation, turn summarization when full, and priority-based retention (system prompts and recent messages always kept).

## Codebase Structure

```
agent/
├── __init__.py              # Public API exports
├── llm_client.py            # Multi-provider HTTP client
├── prompt_manager.py        # Templates, versioning, interpolation
├── response_parser.py       # JSON extraction, format validation
├── context_manager.py       # Token counting, sliding window
├── model_selector.py        # Model selection, fallback chains
├── streaming.py             # SSE/WebSocket chunked responses
├── structured_output.py     # Schema validation, repair logic
├── models.py                # Pydantic data models
├── config.py                # Provider config, API keys
├── exceptions.py            # Custom exception hierarchy
└── tests/
```

## Sources

- Ollama: https://github.com/ollama/ollama
- llama.cpp: https://github.com/ggerganov/llama.cpp
- vLLM: https://github.com/vllm-project/vllm
- OpenAI API: https://platform.openai.com/docs
- Anthropic API: https://docs.anthropic.com
- Google Gemini: https://ai.google.dev/docs
- LangChain: https://github.com/langchain-ai/langchain
- LlamaIndex: https://github.com/run-llama/llama_index
- Instructor: https://github.com/jxnl/instructor
- Outlines: https://github.com/dottxt-ai/outlines
- tiktoken: https://github.com/openai/tiktoken

## Usage

```python
from agent import generate, generate_structured, classify_text

# Reword sentence
result = generate(
    prompt=f"Reword for clarity: {sentence}",
    system_prompt=f"Before: {before}\nAfter: {after}",
    temperature=0.5,
)

# Classify paper abstract
cls = classify_text(
    text=abstract,
    categories=["supports", "opposes", "neutral"],
)

# Extract methodology
methodology = generate_structured(
    prompt=f"Extract methodology from:\n{code}",
    output_schema=MethodologySchema,
    temperature=0.2,
)
```
