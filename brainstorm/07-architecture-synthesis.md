# Architecture Synthesis — How to Combine Everything

## The Big Picture

The research aid is a desktop application that combines screen reading, voice control, writing assistance, and academic research into one unified tool. This document synthesizes all research findings into a coherent architecture.

---

## 1. Proposed Architecture

### Layer 1: Desktop Shell (Tauri v2)

**Technology:** Tauri v2 (Rust backend + React/Svelte frontend)  
**Bundle size:** ~5-10MB  
**Responsibilities:**
- System tray icon with status indicators
- Global shortcut registration (Ctrl+Shift+R, etc.)
- Transparent always-on-top overlay window
- Window positioning near cursor
- Click-through when not interacting

**Why Tauri over Electron:** 15-30x smaller bundle, lower memory usage, built-in global shortcuts, native Rust performance for backend processing.

### Layer 2: Input Processing

**Text Selection Detection:**
- Primary: selection-hook (MIT, cross-platform)
- Fallback: clipboard polling at 100ms intervals
- Returns: selected text, screen coordinates, source application

**Voice Input:**
- Wake word: openWakeWord (Apache-2.0)
- Microphone: cpal (Rust) or PyAudio (Python)
- VAD: Silero VAD (MIT)
- STT: Moonshine 245M (MIT, CPU-only, beats Whisper)
- Command parsing: Vosk closed-grammar for fixed commands

**Global Hotkeys:**
- Primary: Tauri global shortcuts plugin
- Fallback: pynput GlobalHotKeys

**Active Window Detection:**
- active-win / get-windows (MIT)
- Returns: window title, process name, path, bounds
- Used for: app-type detection, paste chord selection

### Layer 3: Algorithmic Processing

**Feature A — Synonyms:**
- Online: Datamuse API (free, no key)
- Offline: NLTK WordNet (Apache-2.0)
- Enhancement: LLM filters contextually appropriate synonyms

**Feature B — Definition:**
- Online: FreeDictionary API (MIT, based on Wiktionary)
- Offline: NLTK WordNet synsets
- Enhancement: LLM provides expanded explanation

**Feature C — Supporting/Opposing Evidence:**
- Framework: LlamaIndex (MIT)
- Vector DB: Qdrant (Apache-2.0)
- Embeddings: BGE-M3 (MIT)
- Sources: Semantic Scholar API + OpenAlex + PubMed
- Classification: LLM classifies retrieved papers as supporting/opposing
- Verification: ValiRef or BibSleuth (citation verification)

**Feature D — Reword:**
- Model: T5_Paraphrase_Paws (MIT, ~500MB)
- Input: selected sentence + surrounding context
- Output: N paraphrased variants (beam search)
- Enhancement: LLM filters for context consistency

**Feature E — Table to Graph:**
- Table parser: custom regex/HTML parser
- Chart renderer: matplotlib (Python) or Vega-Lite (JS)
- Injection: render chart to image, paste into editor

**Feature F — Codebase to Methodology:**
- Code reader: GitHub API + local filesystem
- Analysis: LLM reads code structure, extracts methodology
- Output: structured bullet points

**Feature G — Similar Papers:**
- Primary: Semantic Scholar Recommendations API
- Secondary: BGE-M3 embedding similarity via Qdrant
- Enhancement: LLM synthesizes similarity reasoning

### Layer 4: Output / Injection

**Text Injection Fallback Chain:**
1. Accessibility API insertion (when available)
2. Clipboard + paste chord (Ctrl+V or Ctrl+Shift+V per app)
3. Direct keyboard simulation (pynput/xdotool)
4. Clipboard-only (user pastes manually)

**App Detection:**
- active-win identifies focused application
- Heuristic map determines paste chord
- Terminal = Ctrl+Shift+V, everything else = Ctrl+V

**Overlay Display:**
- Tauri transparent window
- Positioned near cursor/selection coordinates
- Stays within screen bounds
- Click-through when not interacting

---

## 2. Data Flow Diagrams

### Flow: Synonym Lookup

```
User selects word "ubiquitous" in Google Docs
       |
       v
selection-hook fires "text-selection" event
  {text: "ubiquitous", coords: {x: 450, y: 320}, app: "Google Chrome"}
       |
       v
active-win confirms Google Chrome is focused
       |
       v
Global hotkey Ctrl+Shift+S pressed (pynput)
       |
       v
Synonym pipeline triggers:
  1. Query Datamuse API: rel_syn=ubiquitous
  2. Query WordNet: wn.synsets('ubiquitous')
  3. Merge + deduplicate results
  4. (Optional) LLM filters for writing context
       |
       v
Tauri overlay positions at (460, 330)
  Shows list:
    [1] omnipresent
    [2] pervasive
    [3] universal
    [4] widespread
    [5] prevalent
       |
       v
User presses "1" to select "omnipresent"
       |
       v
Text injection:
  1. Save clipboard
  2. Copy "omnipresent" to clipboard
  3. Simulate Ctrl+V (detected: browser = Ctrl+V)
  4. Restore clipboard
       |
       v
Word replaced in Google Docs
```

### Flow: Supporting Evidence

```
User selects paragraph about "quantum entanglement" in Word
       |
       v
selection-hook fires with text + coordinates
       |
       v
Global hotkey Ctrl+Shift+E pressed
       |
       v
Evidence pipeline triggers:
  1. LlamaIndex decomposes claim into sub-queries
  2. Semantic Scholar API retrieves top-20 papers
  3. BGE-M3 embedding similarity filters to top-10
  4. LLM classifies each paper: supporting / opposing / neutral
  5. ValiRef verifies citations exist
       |
       v
Tauri overlay shows:
  ┌─────────────────────────────────────────┐
  │ Supporting Evidence (3 papers)           │
  │  • Smith et al. 2023 - "Quantum..."     │
  │    "Confirms entanglement durability..." │
  │  • Chen et al. 2024 - "Novel..."        │
  │    "Demonstrates room-temp..."           │
  │  • ...                                   │
  │─────────────────────────────────────────│
  │ Opposing Evidence (1 paper)              │
  │  • Jones et al. 2022 - "Limits..."      │
  │    "Challenges decoherence models..."    │
  │─────────────────────────────────────────│
  │ [Insert citation] [Copy] [Dismiss]      │
  └─────────────────────────────────────────┘
       |
       v
User clicks "Insert citation"
       |
       v
Citation text injected into Word document
```

### Flow: Voice Dictation

```
User presses push-to-talk button (or says wake word)
       |
       v
cpal captures microphone audio stream
       |
       v
Silero VAD detects speech start
       |
       v
Moonshine streams partial transcriptions
  "The quick brown" -> "The quick brown fox" -> "The quick brown fox jumps"
       |
       v
Speech end detected (VAD silence > 500ms)
       |
       v
Final transcription: "The quick brown fox jumps over the lazy dog."
       |
       v
Text injection into active application
  (detected: VS Code = Ctrl+V)
```

---

## 3. Event Bus Architecture

The system should use an event-driven architecture to decouple components:

```
Events:
  text-selected {text, coords, app, window_id}
  hotkey-pressed {shortcut_id}
  voice-command {command_text}
  voice-dictation {full_text}
  window-changed {new_window_info}
  overlay-request {content, position}
  text-inject {text, target_app}

Handlers:
  on_text_selected -> store selection context
  on_hotkey_synonym -> trigger synonym pipeline
  on_hotkey_evidence -> trigger evidence pipeline
  on_hotkey_reword -> trigger reword pipeline
  on_hotkey_voice -> toggle voice mode
  on_overlay_request -> render overlay at position
  on_text_inject -> execute injection fallback chain
```

**Implementation:** Use Tauri's event system (Rust events + JS listeners) or a lightweight pub/sub library.

---

## 4. Configuration and Preferences

```json
{
  "hotkeys": {
    "synonym": "Ctrl+Shift+S",
    "definition": "Ctrl+Shift+D",
    "evidence": "Ctrl+Shift+E",
    "reword": "Ctrl+Shift+R",
    "similar_papers": "Ctrl+Shift+P",
    "voice_toggle": "Ctrl+Shift+V"
  },
  "llm": {
    "provider": "ollama",
    "model": "llama3.2",
    "api_url": "http://localhost:11434"
  },
  "voice": {
    "engine": "moonshine",
    "model_size": "245M",
    "language": "en"
  },
  "rag": {
    "vector_db": "qdrant",
    "qdrant_url": "http://localhost:6333",
    "embedding_model": "BAAI/bge-m3",
    "academic_sources": ["semantic_scholar", "openalex"]
  },
  "injection": {
    "strategy": "clipboard_paste",
    "restore_clipboard": true,
    "terminal_detection": true
  },
  "overlay": {
    "position": "near_cursor",
    "max_width": 400,
    "max_height": 300,
    "auto_dismiss_ms": 5000
  }
}
```

---

## 5. Performance Requirements

| Feature | Target Latency | Strategy |
|---------|---------------|----------|
| Synonym lookup | <500ms | Datamuse API + local WordNet cache |
| Definition lookup | <500ms | FreeDictionary API + local cache |
| Supporting evidence | <5s | Semantic Scholar API + pre-computed embeddings |
| Reword | <2s | Local T5 model (no API call) |
| Table to graph | <3s | Local matplotlib rendering |
| Similar papers | <5s | Semantic Scholar API + Qdrant |
| Voice dictation | <500ms | Moonshine streaming (CPU) |
| Text injection | <200ms | Clipboard + paste |

---

## 6. Dependency Tree

```
research-aid (Tauri app)
├── frontend (React/Svelte)
│   ├── overlay-ui
│   ├── settings-panel
│   └── hotkey-display
├── backend (Rust)
│   ├── tauri-plugin-global-shortcut
│   ├── selection-hook (npm/native)
│   ├── active-win (npm/native)
│   └── event-bus
├── python-sidecar
│   ├── moonshine (STT)
│   ├── silero-vad
│   ├── paddleocr
│   ├── t5-paraphrase
│   ├── llamaindex (RAG)
│   ├── qdrant-client
│   ├── pynput (hotkeys + typing)
│   ├── pyperclip
│   └── nltk (WordNet)
└── external-services
    ├── datamuse-api
    ├── freedictionary-api
    ├── semantic-scholar-api
    └── openalex-api
```

**Note:** The Python sidecar could be avoided by rewriting key components in Rust (Moonshine has whisper.cpp equivalent, PaddleOCR has sceptre, T5 could use candle). But Python gives faster prototyping and broader library access.

---

## 7. Build Phases

### Phase 1: Core Shell (Week 1-2)
- Tauri project scaffold
- System tray + global shortcuts
- Transparent overlay window
- selection-hook integration
- Basic text injection (clipboard + paste)

### Phase 2: Writing Features (Week 3-4)
- Synonym lookup (Datamuse + WordNet)
- Definition lookup (FreeDictionary)
- Reword (T5 paraphrase)
- Overlay positioning near cursor

### Phase 3: Research Features (Week 5-8)
- Semantic Scholar API integration
- Qdrant vector DB setup
- BGE-M3 embedding pipeline
- Supporting/opposing evidence pipeline
- Similar papers discovery

### Phase 4: Voice (Week 9-10)
- cpal microphone capture
- Silero VAD integration
- Moonshine STT pipeline
- Voice command parsing
- Push-to-talk and wake word

### Phase 5: Polish (Week 11-12)
- App-type detection + paste chord switching
- Error handling + fallback chains
- Settings UI
- Performance optimization
- Cross-platform testing
