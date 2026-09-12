# Research Aid Desktop Assistant — Project Overview

## The Vision

A research aid that lives on your screen — a desktop agent that sees your screen, listens to your voice, and acts on any text editor. Not a single-purpose tool, but a multi-algorithm system combining screen reading, voice control, RAG pipelines, LLM reasoning, and direct keyboard injection. Compatible with Google Docs, Notepad, VS Code, Word, any text editor.

**Core philosophy:** This is not an LLM wrapper. It is a system of specialized tools orchestrated together: OCR for reading, embedding models for retrieval, grammar engines for correction, paraphrase models for rewording, citation databases for evidence, and accessibility APIs for universal text injection.

## Design Principles

1. **Universal compatibility** — must work across all text editors (Google Docs, Notepad, Word, VS Code, etc.)
2. **Multi-algorithm** — not just one LLM call per feature; combine specialized algorithms
3. **Keybind-driven** — user triggers actions via keyboard shortcuts, not chat interfaces
4. **Non-intrusive** — popups appear near cursor/screen edge, not blocking the workspace
5. **Offline-capable** — core features should work without internet (voice, OCR, paraphrasing, synonyms)
6. **Open-source stack** — every component should be replaceable with open-source alternatives

## Feature Matrix

| Feature | Trigger | Primary Algorithm | Secondary Algorithm | Data Source |
|---------|---------|-------------------|---------------------|-------------|
| a) Synonyms | Select word → keybind | WordNet / Datamuse API | LLM contextual refinement | Local dictionary or API |
| b) Definition | Select word → keybind | FreeDictionary API / WordNet | LLM explanation | API or local |
| c) Supporting evidence | Select text → keybind | RAG retrieval (Semantic Scholar) | LLM reasoning + citation classification | Academic paper corpus |
| d) Opposing evidence | Select text → keybind | RAG retrieval (Semantic Scholar) | LLM reasoning + citation classification | Academic paper corpus |
| e) Reword | Select sentence → keybind | T5/Pegasus paraphrase model | Context window (before/after text) | Local model |
| f) Table → Graph | Select table → keybind | Table parser | Chart renderer (matplotlib/vega) | Local |
| g) Codebase → Methodology | Provide repo → prompt | Code summarizer LLM | Structured extraction | GitHub/local filesystem |
| h) Similar papers | Full paper → keybind | Semantic Scholar recommendations | Embedding similarity search | Academic API + vector DB |

## Architecture Layers

```
┌─────────────────────────────────────────────────────┐
│                   USER INTERFACE                     │
│  Tauri overlay (always-on-top, transparent popup)   │
│  System tray icon with status                       │
│  Global shortcuts (Ctrl+Shift+R for main actions)   │
├─────────────────────────────────────────────────────┤
│                INPUT PROCESSING                      │
│  selection-hook (text selection detection)           │
│  pynput (global hotkeys)                            │
│  cpal/PyAudio (microphone capture)                  │
│  active-win (window detection)                      │
├─────────────────────────────────────────────────────┤
│               ALGORITHMIC LAYER                      │
│  OCR: PaddleOCR / Tesseract                         │
│  STT: Moonshine / faster-whisper / Vosk             │
│  RAG: LlamaIndex + Qdrant + BGE-M3                  │
│  Paraphrase: T5_Paraphrase_Paws / PEGASUS           │
│  Grammar: LanguageTool                               │
│  Synonyms: WordNet + Datamuse                        │
│  Similarity: Semantic Scholar API + embeddings       │
│  Code analysis: LLM + AST parsing                    │
├─────────────────────────────────────────────────────┤
│               DATA / STORAGE                         │
│  Qdrant (vector DB for paper embeddings)             │
│  SQLite (user preferences, history)                  │
│  Local model cache (Whisper, T5, etc.)               │
├─────────────────────────────────────────────────────┤
│              OUTPUT / INJECTION                       │
│  Text injection: clipboard+paste fallback chain      │
│  Keyboard simulation: pynput / xdotool               │
│  Overlay rendering: Tauri transparent window         │
└─────────────────────────────────────────────────────┘
```

## Technology Stack (Proposed)

| Layer | Technology | License | Why |
|-------|-----------|---------|-----|
| Desktop shell | Tauri v2 | MIT/Apache-2.0 | 5MB bundle, always-on-top, system tray, global shortcuts |
| Text selection | selection-hook | MIT | Only cross-app text selection monitor |
| Voice input | cpal + Moonshine | MIT | CPU-only, lowest latency, beats Whisper accuracy |
| Wake word | openWakeWord | Apache-2.0 | Open source, proven in Home Assistant |
| OCR | PaddleOCR | Apache-2.0 | Best accuracy-to-speed ratio |
| Paraphrase | T5_Paraphrase_Paws | MIT | Local inference, small model |
| Grammar | LanguageTool | LGPL-2.1 | Full grammar engine, 30+ languages |
| Synonyms | NLTK WordNet + Datamuse | Apache-2.0 / Free API | Offline + online fallback |
| RAG framework | LlamaIndex | MIT | Best document retrieval framework |
| Vector DB | Qdrant | Apache-2.0 | Production-ready, fast filtering |
| Embeddings | BGE-M3 | MIT | Multilingual, hybrid search |
| Academic API | Semantic Scholar | Free | 200M+ papers, citation graphs |
| LLM reasoning | Local (Ollama) or API | — | For complex evidence synthesis |
| Text injection | Clipboard + paste chain | — | 95% universal compatibility |

## Key Research Findings

1. **selection-hook is the linchpin** — the only open-source cross-application text selection monitor. Without this, the entire "select text → trigger action" paradigm breaks.
2. **Moonshine is a breakthrough** — 245M params beating Whisper Large V3 (1.55B) in accuracy, CPU-only, streaming support. Changes the calculus for voice input.
3. **Clipboard + paste is the 95% solution** for text injection. Every tool that works "everywhere" converges on this approach.
4. **No single "type into any app" API exists.** The practical approach is a tiered fallback chain: accessibility API → clipboard+paste → keyboard simulation.
5. **Tauri v2 is the ideal shell** — 5MB vs Electron's 150MB, built-in always-on-top, system tray, global shortcuts, transparent windows.
6. **Semantic Scholar + OpenScholar** provide the academic backbone for evidence finding.
7. **OpenScholar outperforms GPT-4o** by 6.1% on ScholarQABench with non-hallucinating citations.

## Next Steps (For `execute`)

- Scaffold Tauri project with Rust backend + React/Svelte frontend
- Implement selection-hook integration for text detection
- Build overlay popup system with cursor-aware positioning
- Integrate T5 paraphrase model via HuggingFace inference
- Set up Semantic Scholar API client for paper retrieval
- Build clipboard-based text injection with app-specific paste chord detection
- Add Moonshine for voice dictation via cpal
