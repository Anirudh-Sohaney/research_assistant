# Screen Capture Module

The `screen_capture` module provides the foundation layer for the Research Aid Desktop Assistant: detecting text selection, capturing screenshots, reading text via OCR, identifying the active window, and optionally parsing UI layout.

## Main Function Signature

```python
def capture_and_read_screen(
    region: tuple[int, int, int, int] | None = None,
    detect_selection: bool = True,
    detect_window: bool = True,
    ocr_engine: str = "paddleocr",
    language: str = "en",
    confidence_threshold: float = 0.7,
    include_layout: bool = False,
    clipboard_polling: bool = True,
    polling_interval_ms: int = 100,
    screenshot_format: str = "png",
    screenshot_quality: int = 95,
    return_screenshot_bytes: bool = False,
    fallback_engines: list[str] | None = None,
    timeout_ms: int = 500,
    app_filter: list[str] | None = None,
) -> dict:
    """
    Returns dict with keys:
        selected_text, selected_coords, screen_text, screen_text_blocks,
        window_info, layout_info, screenshot_path, screenshot_bytes,
        engine_used, latency_ms, errors
    """
```

## Text Selection Detection

| Solution | License | Pros | Cons | When to Use |
|----------|---------|------|------|-------------|
| **selection-hook** | MIT | Only library detecting selection in ANY app without clipboard hijack. Returns text, coordinates, source app. | Partial Wayland support. May need OS permissions. | Primary choice. Essential for "select → trigger" paradigm. |
| **radical-selection-hook** | MIT | Multiple fallback methods (UI Automation, Accessibility API, AXAPI, clipboard). | Less maintained than selection-hook. | Backup for edge cases. |
| **Clipboard polling (pyperclip)** | PSF | Zero OS dependencies. Simple. | Requires explicit Ctrl+C — cannot detect selections. | Last resort when selection APIs unavailable. |

**Platform notes:** Windows uses UI Automation + Accessibility APIs. macOS uses AXAPI (requires permissions). Linux X11 uses PRIMARY selection atom. Linux Wayland uses wlr-data-control (partial, compositor-dependent).

## Screen Capture

| Solution | License | Pros | Cons | When to Use |
|----------|---------|------|------|-------------|
| **XCap** | Apache-2.0 | High performance. Window-level capture. Raw pixel output. | No Wayland on Linux yet. | Primary choice when window-level capture needed. |
| **python-mss** | MIT | No dependencies. Thread-safe. Extremely fast. NumPy/OpenCV compatible. | Full monitors only — no window capture. | High-frequency polling. Lightweight deployments. |
| **node-screenshots** | Apache-2.0 | Zero-dependency native Node.js. Async. | Requires Node.js. | Tauri/Electron apps. |

## OCR Engines

| Solution | License | Stars | Pros | Cons | When to Use |
|----------|---------|-------|------|------|-------------|
| **PaddleOCR** | Apache-2.0 | ~88K | Best accuracy-to-speed. 80+ languages. Structured JSON output. PP-StructureV3 for documents. | PaddlePaddle dependency. Large models (~100MB). | Primary choice. Production-proven (Dify, RAGFlow). |
| **Tesseract** | Apache-2.0 | ~76K | Maximum portability. 100+ languages. Wrappers in every language. | Struggles with scene text. Needs preprocessing. | Portability across ecosystems. |
| **sceptre** | MIT | ~1.5K | ~2.8x faster than EasyOCR. Single binary. Ships as CLI and MCP server. | Smaller language coverage. | Rust-native assistants. |
| **light-ocr** | Apache-2.0 | Newer | Prebuilt binaries. Embedded in Tauri/Electron. No Python sidecar. | Limited to PP-OCRv6 Small. | Desktop apps without Python runtime. |
| **VLM-based** | Varies | Research | Semantic understanding beyond raw text. | Requires GPU. High latency. | When semantic understanding is needed. |

## Active Window Detection

| Solution | License | Pros | Cons | When to Use |
|----------|---------|------|------|-------------|
| **active-win / get-windows** | MIT | Returns title, bounds, owner, PID, browser URL. | No Wayland on Linux. | Primary choice. App-aware behavior switching. |
| **focus-tracker** | Apache-2.0 | Event-driven callbacks. Configurable polling. Ignore rules. | Rust-only. | Continuous monitoring with minimal CPU. |
| **PyWinCtl** | BSD-3-Clause | Built-in watchdog for focus changes. Window control included. | Python GIL affects high-frequency monitoring. | Python-first projects needing window control. |

## Screen Content Understanding

| Solution | License | Stars | Pros | Cons | When to Use |
|----------|---------|-------|------|------|-------------|
| **OmniParser** | CC-BY-4.0 | ~25K | Identifies icons, buttons, text fields. Bounding boxes + labels. GPT-4V plugin. | Web-focused. Requires GPU. | Understanding UI layout, not just text. |
| **ScreenVLM** | Apache-2.0 | HuggingFace | 55 UI element classes. Lightweight, on-device. | Smaller vocabulary than OmniParser. | Lightweight UI understanding. |
| **ScreenAI** | Research | Paper | State-of-the-art. 4.6B params. | Significant compute required. | Research baseline. Future upgrade. |

## Alternatives and Issues

**Wayland vs X11:** The biggest cross-platform challenge. Wayland restricts selection detection, screen capture (requires Portal D-Bus consent dialog), and window detection for security. Strategy: detect display server at startup, gracefully degrade on Wayland or prompt for XWayland session.

**Accessibility API limitations:** macOS requires manual permission grants. Windows UI Automation misses some Win32 apps. Linux AT-SPI2 is mature but not universal across toolkits.

**Performance targets:**
- Selection detection: < 50ms (event-driven)
- Screen capture: < 100ms (full screen)
- OCR: < 200ms (single region, CPU)
- Window detection: < 20ms
- Full pipeline: < 500ms

**Error handling:** Never crash the main app. All errors captured in the `errors` list. Fallback chains: selection-hook → clipboard polling, PaddleOCR → Tesseract, window detection → `None`. Timeout returns partial results.

## Codebase Structure

```
screen_capture/
├── __init__.py              # Public API: capture_and_read_screen()
├── selection_detector.py    # Text selection monitoring
├── screen_capturer.py       # Screenshot functionality
├── ocr_engine.py            # OCR processing with fallback chain
├── window_detector.py       # Active window detection
├── content_parser.py        # UI layout understanding
├── models.py                # Data models (SelectionInfo, ScreenContent, WindowInfo)
└── config.py                # Configuration and preferences
```

## Quick Start

```python
from screen_capture import capture_and_read_screen

result = capture_and_read_screen()
if result["selected_text"]:
    print(f"Selected: {result['selected_text']}")
    print(f"App: {result['window_info']['app_name']}")
```

```python
# Advanced: specific engine, layout parsing, Japanese
result = capture_and_read_screen(
    region=(100, 200, 800, 600),
    ocr_engine="tesseract",
    language="ja",
    include_layout=True,
    fallback_engines=["paddleocr"],
)
```

## Sources

- selection-hook: https://github.com/0xfullex/selection-hook
- radical-selection-hook: https://github.com/RaoHai/radical-selection-hook
- XCap: https://github.com/nashaofu/xcap
- python-mss: https://github.com/BoboTiG/python-mss
- node-screenshots: https://github.com/nashaofu/node-screenshots
- PaddleOCR: https://github.com/PaddlePaddle/PaddleOCR
- Tesseract: https://github.com/tesseract-ocr/tesseract
- sceptre: https://github.com/Goldziher/sceptre
- light-ocr: https://github.com/endlessc/light-ocr
- active-win: https://github.com/sindresorhus/active-win
- focus-tracker: https://crates.io/crates/focus-tracker
- PyWinCtl: https://github.com/Kalmat/PyWinCtl
- OmniParser: https://github.com/microsoft/OmniParser
- ScreenVLM: https://huggingface.co/docling-project/ScreenVLM
- ScreenAI: https://arxiv.org/abs/2402.04615
