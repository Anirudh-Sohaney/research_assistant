# Voice Module

Real-time voice input pipeline for the Research Aid Desktop Assistant. Handles microphone capture, wake word detection, speech-to-text transcription, voice activity detection, and voice command parsing.

## Function Signature

```python
def process_voice_input(
    audio_stream,
    mode: str = "dictation",
    wake_word: str = "hey research",
    stt_engine: str = "moonshine",
    model_size: str = "245M",
    language: str = "en",
    enable_vad: bool = True,
    vad_threshold: float = 0.5,
    command_grammar: dict | None = None,
    partial_results: bool = True,
    sample_rate: int = 16000,
    chunk_duration_ms: int = 30,
    max_silence_duration_ms: int = 800,
    energy_threshold: float = 0.01,
    confidence_threshold: float = 0.3,
    device: str = "cpu",
    cache_models: bool = True,
    log_transcriptions: bool = False,
) -> dict:
    """
    Process audio stream and return structured voice input result.

    Returns:
        dict with keys:
            - transcription (str): Final transcribed text
            - confidence (float): 0.0-1.0 transcription confidence
            - is_command (bool): True if input matches a voice command
            - command_type (str | None): Matched command category
            - command_args (dict | None): Parsed command arguments
            - partial_text (str | None): Streaming partial transcription
            - language_detected (str): ISO 639-1 language code
            - processing_time_ms (float): Total pipeline latency
            - vad_active (bool): Voice activity state at endpoint
            - wake_word_detected (bool): Whether wake word triggered processing
            - audio_duration_ms (float): Duration of processed audio
            - segments (list[dict]): Word-level timestamp segments
    """
```

## Architecture

```
Audio Stream
    │
    ▼
┌─────────────┐
│ Microphone   │  cpal / PyAudio capture
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ VAD         │  Silero / WebRTC voice activity
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Wake Word   │  openWakeWord detection
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Audio Proc  │  Noise reduction, normalization
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ STT Engine  │  Moonshine / faster-whisper / Vosk
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Commands    │  Grammar matching, intent parsing
└──────┬──────┘
       │
       ▼
    Result dict
```

## File Structure

```
voice/
├── __init__.py
├── stt_engine.py          # Speech-to-text transcription
├── wake_word_detector.py  # Wake word detection
├── voice_commands.py      # Command parsing and routing
├── microphone.py          # Audio capture
├── vad.py                 # Voice activity detection
├── audio_processor.py     # Audio preprocessing
├── models.py              # Data models (VoiceInput, Command, etc.)
└── config.py              # Configuration
```

## Component Solutions

### Speech-to-Text Engines

| Engine | License | Stars | Size | Latency | Notes |
|--------|---------|-------|------|---------|-------|
| **Moonshine** | MIT | 3K+ | 245M params | <200ms | Purpose-built for real-time. Outperforms Whisper-small on speed. |
| **faster-whisper** | MIT | 25K+ | Various | 500ms-2s | CTranslate2 backend. Best accuracy. GPU preferred. |
| **whisper.cpp** | MIT | 40K+ | Various | 300ms-1.5s | Metal acceleration on macOS. C++ native. |
| **Vosk** | Apache-2.0 | 15K+ | Small | <100ms | Closed-grammar. Fastest for constrained vocabularies. |

**Recommendation:** Use Moonshine as default for real-time dictation. Offer faster-whisper as accuracy-focused alternative. Vosk for command-mode with fixed grammar.

### Wake Word Detection

| Engine | License | Stars | Notes |
|--------|---------|-------|-------|
| **openWakeWord** | Apache-2.0 | 2.7K+ | Custom wake words via retraining. On-device. |
| **ViolaWake** | Apache-2.0 | - | Lightweight, customizable. |
| **Picovoice Porcupine** | Proprietary | 3K+ | Best accuracy. Free tier limited. |

**Recommendation:** openWakeWord for open-source compliance and custom wake word support.

### Microphone Capture

| Library | License | Stars | Notes |
|---------|---------|-------|-------|
| **cpal** | Apache-2.0 | 3.9K+ | Cross-platform. Low-level control. |
| **PyAudio** | MIT | 2K+ | Python wrapper around PortAudio. Widely used. |

**Recommendation:** PyAudio for Python-native projects. Consider cpal via PyO3 if low-latency is critical.

### Voice Activity Detection

| Engine | License | Notes |
|--------|---------|-------|
| **Silero VAD** | MIT | Neural network. More accurate. 1-2ms per chunk. |
| **WebRTC VAD** | MIT | Google's C-based VAD. Very fast. 3 aggressiveness modes. |

**Recommendation:** Silero VAD for accuracy. WebRTC VAD for minimal resource usage.

### Voice Command Systems

Reference implementations for grammar-based command parsing:

- **Talon Voice** ([github.com/saxophone-vad](https://github.com/saxophone-saxophone/talon-vad)) - Full voice coding environment
- **OpenDex** - Open voice control framework
- **CODEC** - Command-oriented dictation engine
- **EasySpeak** - Lightweight command parser

## Usage Examples

### Basic Dictation

```python
from voice import process_voice_input

result = process_voice_input(
    audio_stream=mic_stream,
    mode="dictation",
    stt_engine="moonshine",
    enable_vad=True,
)

print(result["transcription"])
# > "define machine learning in the context of neural networks"
```

### Command Mode with Custom Grammar

```python
grammar = {
    "search": {"patterns": ["search for {query}", "look up {query}"], "args": ["query"]},
    "navigate": {"patterns": ["go to {page}", "open {page}"], "args": ["page"]},
    "summarize": {"patterns": ["summarize {topic}", "tldr {topic}"], "args": ["topic"]},
}

result = process_voice_input(
    audio_stream=mic_stream,
    mode="command",
    command_grammar=grammar,
    stt_engine="vosk",
    wake_word="hey research",
)

if result["is_command"]:
    print(f"Command: {result['command_type']}")
    print(f"Args: {result['command_args']}")
```

### Hybrid STT (Preview + Final)

```python
from voice.stt_engine import HybridSTT

stt = HybridSTT(
    preview_engine="vosk",      # Fast, low-latency preview
    final_engine="moonshine",   # Accurate final pass
    preview_threshold=0.6,      # Switch to final when confidence < this
)

result = process_voice_input(
    audio_stream=mic_stream,
    stt_engine=stt,
    partial_results=True,       # Stream Vosk partials, finalize with Moonshine
)
```

## Latency Budget

Target: <500ms total pipeline for live conversational feel.

| Stage | Target | Strategy |
|-------|--------|----------|
| VAD | <5ms | WebRTC or Silero on small chunks |
| Wake Word | <30ms | openWakeWord with quantized model |
| Audio Prep | <10ms | Normalization, resampling |
| STT | <200ms | Moonshine 245M on CPU |
| Command Parse | <5ms | Regex/grammar match |
| **Total** | **<250ms** | **Typical on modern CPU** |

## Considerations

- **CPU vs GPU:** Moonshine and Silero VAD run efficiently on CPU. faster-whisper benefits significantly from CUDA. Detect device at runtime.
- **Platform Differences:** Windows/macOS require different audio backends. Use `platform.system()` to select. Linux ALSA vs PulseAudio.
- **Background Noise:** Apply noise gate via energy_threshold. Consider RNNoise for real-time denoising before STT.
- **Languages:** Moonshine supports multilingual. Set `language` parameter. Auto-detect available via Whisper-based engines.
- **Memory:** Cache loaded models in `config.py` to avoid reload per call. Moonshine 245M ~500MB RAM.
- **Offline Operation:** All recommended engines run fully offline. No network required after model download.

## Sources

- Moonshine: https://github.com/saxophone-saxophone/moonshine
- faster-whisper: https://github.com/SYSTRAN/faster-whisper
- whisper.cpp: https://github.com/ggerganov/whisper.cpp
- Vosk: https://alphacephei.com/vosk/
- openWakeWord: https://github.com/dscripka/openWakeWord
- Silero VAD: https://github.com/snakers4/silero-vad
- WebRTC VAD: https://github.com/wiseman/py-webrtcvad
- cpal: https://github.com/RustAudio/cpal
- PyAudio: https://people.csail.mit.edu/hubert/pyaudio/
