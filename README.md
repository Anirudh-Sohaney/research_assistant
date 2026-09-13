# Research Aid

Video : https://drive.google.com/file/d/1qmhpDipuHXex4TidjSD7ebJUN36HmsSh/view?usp=sharing

## Summary

Research Aid is a desktop writing assistant for academic papers. It reads highlighted text, retrieves contextual synonyms and definitions, rewrites prose, analyzes papers with independent LLM judges, finds citations, verifies claims, summarizes sources, and turns selected tables into charts. Results appear in keyboard-driven popups and can be inserted back into the active editor.

## External tools and services

- OpenRouter: language-model generation for rewording, contextual synonym selection, paper analysis, and evidence judging. The default models are configurable through environment variables.
- Google Docs and Chrome: selection reading and text insertion use the active editor's clipboard/accessibility behavior; no Google Docs API key is required.
- Datamuse and Free Dictionary API: dictionary and synonym candidate retrieval.
- OpenAlex, Semantic Scholar, arXiv, Europe PMC, and CORE: academic discovery and evidence retrieval. CORE requires an API key; OpenAlex and Semantic Scholar keys are optional where supported.
- Crossref and OpenLibrary: DOI, book, and publication metadata resolution.
- Page metadata/headless browser extraction: citation resolution for web pages when static metadata is insufficient.
- Hugging Face model downloads: optional local Qwen, sentence-transformer, and related NLP models used by local ranking and chart/table assistance. These are model downloads, not credential stores.

The application also uses standard local libraries and operating-system clipboard, keyboard, OCR, and accessibility facilities. No API keys or personal credentials are committed to this repository.

## How it works

The global hotkey listener captures a selection from the active editor. The orchestrator routes it to a focused subsystem: local processing handles lightweight lexical and formatting work, while the API gateway sends only the required task to external services. Results are validated, ranked or formatted, shown in a popup, and optionally inserted through the editor clipboard path. Paper analysis fans the full selection out to eight independent review prompts and streams valid judge results as they arrive.

## Setup

1. Install Python 3.11+ and the project dependencies used by the modules in `src` (PyQt6, httpx, pytest, and the NLP/chart packages required by the features you use).
2. Set credentials in the environment of the process that starts the app. Do not put them in source files:

   - Required for LLM features: `OPENROUTER_API_KEY`.
   - Required for the full evidence pipeline: `CORE_API_KEY`.
   - Optional: `OPENALEX_API_KEY` and `SEMANTIC_SCHOLAR_API_KEY` for higher source limits or authenticated retrieval.

   On PowerShell:

   ```powershell
   $env:OPENROUTER_API_KEY = "your-openrouter-key"
   $env:CORE_API_KEY = "your-core-key"
   $env:OPENALEX_API_KEY = "your-openalex-key"
   $env:SEMANTIC_SCHOLAR_API_KEY = "your-semantic-scholar-key"
   ```

   On macOS/Linux, use `export NAME="value"` equivalents.

3. Optional model and endpoint overrides include `LLM_BASE_URL`, `OPENROUTER_REWORD_MODEL`, `OPENROUTER_SYNONYM_MODEL`, `PAPER_ANALYSIS_MODEL`, and their timeout variables.
4. Start the application with:

   ```text
   python src/main.py
   ```

Datamuse, Free Dictionary, Crossref, OpenLibrary, arXiv, and Europe PMC can be used without application keys, subject to their public rate limits. Never commit `.env` files, credential JSON, bearer tokens, or API keys.
