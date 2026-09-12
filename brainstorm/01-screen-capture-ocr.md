# Screen Capture, OCR, and Screen Content Reading

## The Problem

The research aid needs to "see" the user's screen — read what text is displayed, understand the layout, detect highlighted/selected text, and identify the active application. This is the foundation layer: without reliable screen reading, nothing else works.

## Components Needed

1. **Text selection detection** — know what the user has highlighted
2. **Screen capture** — capture the screen or a region for OCR
3. **OCR** — read text from captured regions
4. **Active window detection** — know which application is focused
5. **Screen content understanding** — interpret UI elements beyond raw text

---

## 1. Text Selection Detection

### The Killer Tool: selection-hook

**GitHub:** https://github.com/0xfullex/selection-hook  
**License:** MIT  
**Stars:** ~2.4K weekly npm downloads, actively maintained

This is the most critical component for the entire project. selection-hook is the **first and only open-source cross-platform text selection monitoring library**. It detects when users select text in ANY application and returns:
- The selected text
- Screen coordinates (where the selection is on screen)
- Source program name (which application the selection is in)

**How it works:**
- **Windows:** UI Automation API (modern apps) + Accessibility API (legacy)
- **macOS:** AXAPI (Apple's Accessibility API)
- **Linux:** X11 PRIMARY selection + clipboard fallback
- **Linux Wayland:** wlr-data-control protocol (partial)

**Key methods:**
- `start()` — begin monitoring
- `getCurrentSelection()` — poll for current selection
- Events: `text-selection`, `mouse-*`, `key-*`
- Configurable clipboard fallback, per-app filtering

**Why this matters:** Without selection-hook, the entire "select text → trigger action" paradigm breaks. The alternative (clipboard hijacking) is invasive and breaks user workflows.

### Alternative: radical-selection-hook

**GitHub:** https://github.com/RaoHai/radical-selection-hook  
**License:** MIT

Similar to selection-hook but with multiple extraction methods as fallbacks:
- UI Automation (Windows modern apps)
- Accessibility API (Windows legacy)
- AXAPI (macOS)
- Clipboard fallback

**Use case:** Backup for edge cases where selection-hook's primary method fails.

### Alternative: Clipboard Polling (Last Resort)

If selection-hook fails on a particular application, fall back to clipboard polling:
- Monitor clipboard for changes at 100ms intervals
- When user copies text, capture it
- **Limitation:** User must explicitly copy (Ctrl+C), not just select
- Libraries: `pyperclip` (Python), `clipboard-monitor` (Python)

**Implementation pattern:**
```python
import pyperclip
import time

prev = pyperclip.paste()
while True:
    current = pyperclip.paste()
    if current != prev:
        handle_selection(current)
        prev = current
    time.sleep(0.1)
```

---

## 2. Screen Capture

### Recommended: XCap (Rust)

**GitHub:** https://github.com/nashaofu/xcap  
**License:** Apache-2.0  
**Capabilities:** Cross-platform screen and window capture (Linux X11, macOS, Windows)

- Can capture full screen or individual windows
- Returns raw pixel data compatible with image processing
- Used by multiple production tools (SnapX, node-screenshots)

**Limitation:** No Wayland screen capture yet on Linux.

### Alternative: python-mss (Python)

**GitHub:** https://github.com/BoboTiG/python-mss  
**License:** MIT  
**Stars:** ~1,267

Ultra-fast cross-platform screenshot module. No dependencies. Thread-safe. Returns raw pixel data compatible with NumPy/OpenCV.

**Best for:** High-frequency screen polling (capture region every N seconds for continuous OCR). Extremely lightweight.

**Limitation:** Full monitors only — no window-level capture.

### Alternative: node-screenshots (Node.js)

**GitHub:** https://github.com/nashaofu/node-screenshots  
**License:** Apache-2.0

Zero-dependency native Node.js screenshot library wrapping XCap. If building a Tauri/Node.js app, this avoids Python dependencies.

---

## 3. OCR (Optical Character Recognition)

### Recommended: PaddleOCR

**GitHub:** https://github.com/PaddlePaddle/PaddleOCR  
**License:** Apache-2.0  
**Stars:** ~88,000

Industry-grade OCR from Baidu. PP-OCRv5 model handles 80+ languages with excellent accuracy.

**Key advantages:**
- Best accuracy-to-speed ratio
- Structured output (JSON/Markdown) — not just raw text
- PP-StructureV3 for document layout parsing (tables, forms, formulas)
- Used in production by Dify, RAGFlow, and Cherry Studio

**Limitation:** Built on PaddlePaddle (not PyTorch). Large model files.

### Alternative: Tesseract OCR

**GitHub:** https://github.com/tesseract-ocr/tesseract  
**License:** Apache-2.0  
**Stars:** ~76,000

The most widely-used open-source OCR engine. 100+ languages. LSTM-based neural recognition.

**When to use:** When you need maximum portability (wrappers in every language). Works with pytesseract (Python) or tesseract.js (Node.js).

**Limitation:** Struggles with scene text and complex layouts. Needs preprocessing for best results.

### Alternative: sceptre (Rust)

**GitHub:** https://github.com/Goldziher/sceptre  
**Capabilities:** Rust reimplementation of EasyOCR's pipeline. Runs ~2.8x faster than EasyOCR warm, ~4.4x faster cold. Single binary, no Python.

**When to use:** If building a Rust-native assistant. Ships as library, CLI, and MCP server.

### Alternative: light-ocr (C++/Node.js)

**GitHub:** https://github.com/endlessc/light-ocr  
**License:** Apache-2.0  
**Capabilities:** C++17 PP-OCRv6 Small with async Node-API. Prebuilt binaries for macOS/Linux/Windows.

**When to use:** Embedding OCR directly in a Tauri/Electron desktop app without a Python sidecar.

### VLM-Based OCR (Advanced)

**HunyuanOCR-1.5 (Tencent):** Lightweight end-to-end OCR using vision-language models. Unifies document parsing, text spotting, information extraction. Can run on consumer hardware via llama.cpp.

**When to use:** When you need semantic understanding beyond raw text extraction (e.g., "what does this form field say?").

---

## 4. Active Window Detection

### Recommended: active-win / get-windows

**GitHub:** https://github.com/sindresorhus/active-win (renamed to get-windows)  
**License:** MIT  
**Stars:** ~906

Cross-platform (macOS 10.14+, Linux X11, Windows 7+) active window detection. Returns:
- Window title
- Window ID and bounds
- Owner (name, processId, bundleId, path)
- Browser URL (Chrome, Edge, Brave, Firefox, Safari on macOS)

**Key methods:**
- `activeWindow()` — get currently focused window
- `getOpenWindows()` — list all open windows

**Why this matters:** Knowing which application is focused lets the assistant switch behavior (e.g., "writing mode" when a text editor is focused, "research mode" when a browser is focused).

**Limitation:** No Wayland support on Linux (security restriction).

### Alternative: focus-tracker (Rust)

**crates.io:** https://crates.io/crates/focus-tracker  
**License:** Apache-2.0

Real-time focus tracking with automatic deduplication. Returns window title, process name, PID, and icon. Configurable polling, ignore rules.

**Better for:** Continuous monitoring (event-driven callbacks when user switches apps).

### Alternative: PyWinCtl (Python)

**GitHub:** https://github.com/Kalmat/PyWinCtl  
**License:** BSD-3-Clause

Cross-platform window management with built-in watchdog for monitoring focus changes. Can also move, resize, activate, minimize windows.

**Best feature:** Watchdog fires callbacks when user switches to a writing application, automatically triggering the assistant's context-gathering.

---

## 5. Screen Content Understanding

### Recommended: OmniParser (Microsoft)

**GitHub:** https://github.com/microsoft/OmniParser  
**License:** CC-BY-4.0  
**Stars:** ~25,300

Parses UI screenshots into structured elements:
- Fine-tuned detection model identifies interactable icons, buttons, text fields
- Caption model generates functional descriptions
- Output: bounding boxes, semantic labels, descriptions
- Works as plugin for GPT-4V, Phi-3.5-V, Llama-3.2-V

**Use case:** When the assistant needs to understand what's on screen beyond raw text — "what application is this?", "where is the text field?", "what button should I click?"

**Limitation:** Designed for web UIs; desktop may vary. Requires GPU.

### Alternative: ScreenVLM (Docling Project)

**HuggingFace:** https://huggingface.co/docling-project/ScreenVLM

Compact VLM for screen parsing. Detects, classifies, localizes, and transcribes 55 UI element classes. Based on Idefics3 + Granite 165M LLM.

**Advantage:** Lightweight enough for on-device use.

### Alternative: ScreenAI (Google Research)

**Paper:** https://arxiv.org/abs/2402.04615

4.6B parameter VLM specializing in UI understanding. SoTA on multiple benchmarks. The gold standard but requires significant compute.

---

## Integration Strategy

For the research aid, the screen reading pipeline should be:

1. **selection-hook** detects text selection → triggers feature pipeline
2. **active-win** identifies the focused application → adjusts behavior
3. **PaddleOCR** reads text from screen regions when selection-hook fails
4. **OmniParser** (optional, advanced) understands UI layout for complex interactions

The selection-hook + active-win combination is the minimum viable screen reading stack. OCR and UI understanding are fallbacks for when direct text access fails.
