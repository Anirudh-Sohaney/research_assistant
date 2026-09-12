# Voice Control — Live Microphone Input and Voice Commands

## The Problem

The research aid needs voice control — the user should be able to speak commands and have them recognized in real-time. This is not just "record and transcribe" but "always listening, instantly responsive." The voice system needs to handle:
- Wake word detection ("Hey Research Aid")
- Voice commands ("find synonyms for selected word", "show supporting evidence")
- Live dictation (speak text directly into the editor)
- All with <500ms latency for "live" feel

---

## 1. Speech-to-Text (STT) Engines

### Recommended: Moonshine Voice

**GitHub:** https://github.com/moonshine-ai/moonshine  
**License:** MIT (English models)  
**Stars:** ~11k  
**Parameters:** 27M (tiny) to 245M (large)  
**WER:** 6.65% (large) — beats Whisper Large V3's 7.44% with 6x fewer parameters

**Why Moonshine is the breakthrough:**
- Designed specifically for live streaming
- Does compute while user is still talking
- Partial text updates supplied continuously
- CPU-only, no GPU dependency
- Platforms: Python, JavaScript/WASM, iOS, Android, macOS, Linux, Windows, Raspberry Pi
- Tiny footprint, lowest latency by design

**For the research aid:** Moonshine is the ideal primary STT engine. It's small enough to run always-on in the background, accurate enough for dictation, and fast enough for real-time voice commands.

### Alternative: faster-whisper

**GitHub:** https://github.com/SYSTRAN/faster-whisper  
**License:** MIT  
**Stars:** ~25k  
**Backend:** CTranslate2 with INT8 quantization

**Speed:** Up to 4x faster than original Whisper; large-v3 at ~12x real-time on RTX 4070  
**Latency:** 0.5-2 seconds for streaming with VAD pipeline

**When to use:** If GPU is available and maximum accuracy is needed. Built-in Silero VAD simplifies streaming.

**Limitation:** NVIDIA GPU only for speed advantage. No Metal/Apple Silicon support.

### Alternative: whisper.cpp

**GitHub:** https://github.com/ggml-org/whisper.cpp  
**License:** MIT  
**Stars:** ~40k+

C/C++ with zero Python dependencies. Platforms: macOS (Metal + Core ML), Linux, Windows, iOS, Android, WebAssembly, Raspberry Pi.

**Speed:** ~10x real-time on Apple M5 Pro with Metal  
**Latency:** 100-150ms mean latency for server-mode small model

**Key insight:** Must run in persistent server mode, NOT as CLI invocations — model load overhead dominates per-invocation latency.

**When to use:** Best choice for Mac users or when Python is not available.

### Alternative: Vosk

**GitHub:** https://github.com/alphacep/vosk-api  
**License:** Apache 2.0  
**Stars:** ~15k  
**Model sizes:** 40 MB - 1.8 GB

True real-time streaming with very low resource requirements. Closed grammars (keyword lists) are extremely accurate.

**Unique advantage:** For voice commands with limited vocabulary, Vosk's closed-grammar mode is faster and more accurate than any large language model approach.

**Hybrid approach:** Use Vosk for real-time preview (showing text as user speaks), then Whisper/Moonshine for final correction after sentence completion.

### Alternative: DeepSpeech (Mozilla)

**Status:** ARCHIVED (June 2025). Do not use for new projects.

---

## 2. Voice Command Systems

### Recommended: Talon Voice (Reference)

**Website:** https://talonvoice.com  
**Community repo:** https://github.com/talonhub/community (866 stars, MIT)

The de facto standard for power-user voice control. Uses custom Python scripting language (`.talon` files) for command definitions.

**Features:**
- Mouse control via voice (mouse grid, cursor)
- Dictation + command mode
- Noise-based commands (finger snaps, hisses)
- Programming language support
- Large community with commands for VS Code, browser, terminal, vim

**Limitation:** Proprietary binary (free to use, but not open-source). Steep learning curve.

**For the research aid:** Study Talon's architecture for command parsing patterns, but build open-source equivalent.

### Alternative: OpenDex

**GitHub:** https://github.com/wassgha/opendex

Voice-first agentic desktop assistant with J.A.R.V.I.S. theme:
- Wake word or hotkey activation
- Pluggable voice I/O (Vosk/Whisper/Web Speech for STT)
- Computer use (screen capture + mouse/keyboard via nut.js)
- Skills system with permission gates
- Multiple LLM support

**Use case:** Complete voice-first assistant framework. Could serve as UI shell.

### Alternative: CODEC

**GitHub:** https://github.com/AVADSA25/codec  
**License:** MIT

Most ambitious voice-controlled desktop system:
- "Hey CODEC" wake word
- F13/F18/F16 activation keys
- Voice-to-click on any UI element via vision model
- Live typing at cursor (F5)
- 89 skills, MCP server/client
- Real-time voice calls with interrupt detection

**Key insight:** Vision-based clicking means it works with any application without accessibility API support.

### Alternative: EasySpeak

**GitHub:** https://github.com/ctsdownloads/easyspeak  
**License:** GPL-3.0  
**Stars:** 156

Linux desktop voice control, Wayland-native, fully local:
- pyopen-wakeword + Whisper + Piper TTS
- Mouse grid, head tracking, browser control, dictation
- Simple plugin system (drop a Python file in `plugins/`)

---

## 3. Live Microphone Access

### Recommended: cpal (Rust)

**GitHub:** https://github.com/RustAudio/cpal  
**License:** Apache 2.0  
**Stars:** ~3.9k  
**Downloads:** 16.8M on crates.io

Cross-platform audio I/O: Linux (ALSA, JACK, PipeWire, PulseAudio), macOS (CoreAudio), Windows (WASAPI, ASIO, JACK), iOS, Android, WebAssembly.

**Features:** Enumerate audio devices, build input/output streams, real-time priority thread promotion.

**For the research aid:** Best Rust option for microphone capture. Used by Handy (the most popular open-source dictation tool).

### Alternative: PyAudio (Python)

**License:** MIT  
**Version:** 0.2.14

Python bindings for PortAudio. Simple API:
```python
p = pyaudio.PyAudio()
stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True)
data = stream.read(CHUNK)
```

**For the research aid:** Standard Python microphone library. Used by AURA and many voice assistant projects.

### Voice Activity Detection (VAD)

**Silero VAD** (MIT): Modern ML-based VAD. More accurate than WebRTC, especially in noisy environments. Used by faster-whisper (built-in), openWakeWord, and EasySpeak.

**WebRTC VAD** (`webrtcvad` Python): Google's VAD. Processes 30ms frames at 16kHz with aggressiveness levels 0-3. Simpler but less accurate.

**For the research aid:** Use Silero VAD to detect when user is speaking vs. silence. Essential for avoiding transcription of silence and for wake word detection.

---

## 4. Wake Word Detection

### Recommended: openWakeWord

**GitHub:** https://github.com/dscripka/openWakeWord  
**License:** Apache 2.0 (code), CC-BY-NC-SA 4.0 (pretrained models)  
**Stars:** ~2.7k

Open-source wake word framework. Uses streaming classifier on Google speech embeddings. 80ms audio frames via ONNX Runtime.

**Pretrained models:** "alexa", "hey mycroft", "hey jarvis", "hey rhasspy", "timers", "weather"  
**Custom training:** ~1 hour on Google Colab using synthetic Piper-TTS speech  
**Performance:** False-accept <0.5/hr, false-reject <5%

**Platforms:** Windows, macOS, Linux, Raspberry Pi

**Caveat:** Pretrained models are non-commercial (CC-BY-NC-SA). Must retrain for commercial use.

### Alternative: ViolaWake

**GitHub:** https://github.com/GeeIHadAGoodTime/ViolaWake  
**License:** Apache 2.0  
**Status:** Active (2026)

Most feature-rich open-source wake word SDK:
- TemporalCNN model, 8-phase training pipeline
- ONNX inference
- Integrated VAD + STT + TTS
- Speaker verification gate
- Noise-adaptive threshold
- Power management

**Performance:** EER 5.49% vs openWakeWord's 8.24%

### Alternative: Picovoice Porcupine (Proprietary)

**GitHub:** https://github.com/Picovoice/Porcupine  
**Stars:** ~4.9k

Best accuracy (97.3% detection at 1 false alarm per 10 hours). Self-service console for custom keywords.

**Limitation:** Free plan is evaluation-only. Commercial deployment requires paid subscription. Not truly open-source.

---

## 5. Complete Voice Stack Recommendations

### Option A: Full Offline, Low Latency (Recommended)

| Component | Tool | Why |
|-----------|------|-----|
| Wake word | openWakeWord | Open source, CPU, proven |
| Microphone | cpal (Rust) or PyAudio | Cross-platform |
| VAD | Silero VAD | ML-based, accurate |
| STT | Moonshine (245M) | CPU-only, lowest latency, beats Whisper |
| Command parser | Custom grammar (Vosk) or LLM intent | Commands vs dictation |
| TTS | Kokoro-82M or Piper | Local, lightweight |

### Option B: Maximum Accuracy, GPU Available

| Component | Tool | Why |
|-----------|------|-----|
| Wake word | openWakeWord | Same |
| Microphone | PyAudio | Simpler Python integration |
| VAD | Silero VAD | Same |
| STT | faster-whisper (INT8, large-v3) | Best accuracy on GPU |
| Correction | WhisperX post-pass | Word-level timestamps |
| TTS | Kokoro-82M | Same |

### Option C: Minimal, Cross-Platform

| Component | Tool | Why |
|-----------|------|-----|
| All-in-one | Handy | Already works, 30k+ stars, MIT, Tauri-based |
| Custom commands | Whisper + custom intent layer | Build on top of Handy |

---

## Key Insights

1. **The "live feel" requires <500ms** — Users perceive voice systems as responsive when latency is under 500ms. Moonshine and Vosk achieve this; Whisper variants need streaming forks.

2. **Hybrid STT is the practical approach** — Use Vosk/Moonshine for real-time preview (showing text as user speaks), then Whisper for final correction after sentence completion.

3. **No single project does it all well** — Talon is closest for voice coding but proprietary. CODEC is most ambitious but macOS-only. Handy is most popular but dictation-only. The ideal solution combines Handy's simplicity, Talon's command richness, and Moonshine's STT.

4. **Wake word + keybind is better than wake word alone** — For a writing assistant, keybinds are more reliable than wake words. Voice should supplement keybinds, not replace them. Use wake word for hands-free moments (hands on keyboard, can't reach mouse).

5. **Vosk's closed-grammar mode is underrated** — For fixed command vocabularies ("find synonyms", "show evidence", "reword this"), Vosk's grammar-based recognition is faster and more accurate than LLM-based intent classification.
