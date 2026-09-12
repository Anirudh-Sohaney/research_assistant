# Config Module

Centralized configuration management for the Research Aid Desktop Assistant. Handles loading, validation, merging, and persistence of application settings, user preferences, hotkey bindings, model configurations, and environment-specific overrides.

## Function Signatures

### `load_config`

```python
def load_config(
    config_path: str | None = None,
    env: str = "default",
    validate: bool = True,
    merge_defaults: bool = True,
) -> dict:
    """
    Load configuration with environment overlay and validation.

    Search order (later overrides earlier):
      1. Built-in defaults (defaults.py)
      2. System config (/etc/research_aid/config.json)
      3. User config (~/.config/research_aid/config.json or AppData)
      4. Project config (./research_aid.json)
      5. Environment overlay (config.{env}.json)
      6. Environment variables (RESEARCH_AID__LLM__MODEL)

    Returns:
        dict with keys:
            - config (dict): Merged configuration dictionary.
            - validation_errors (list[dict]): [{key, message, severity}].
            - missing_keys (list[str]): Required keys absent from all sources.
            - environment (str): Active environment name.
            - config_path (str | None): Resolved primary config file path.
            - sources_loaded (list[str]): Ordered config source paths.
            - overrides_applied (int): Count of user/env overrides.
    """
```

### `get_setting`

```python
def get_setting(
    key_path: str,
    default: any = None,
    config: dict | None = None,
    required: bool = False,
) -> any:
    """
    Retrieve a nested config value using dot notation.
    Example: 'llm.model', 'hotkeys.synonym', 'voice.stt_engine'

    Raises ConfigKeyError if required=True and key is missing.
    """
```

### `update_setting`

```python
def update_setting(
    key_path: str,
    value: any,
    config: dict | None = None,
    persist: bool = True,
) -> dict:
    """
    Set a nested config value and optionally persist to disk.

    Returns:
        dict with keys: success, old_value, new_value, config_updated, persisted.
    """
```

### `validate_config`

```python
def validate_config(
    config: dict,
    schema: dict | None = None,
    strict: bool = False,
) -> dict:
    """
    Validate config against schema.

    Returns:
        dict with keys: is_valid, errors, warnings, missing_required,
        type_mismatches, unknown_keys.
    """
```

### `get_hotkey_config`

```python
def get_hotkey_config(platform: str | None = None) -> dict:
    """
    Retrieve hotkey configuration with platform-aware resolution.

    Returns:
        dict with keys: hotkeys, conflicts, platform_specific,
        custom_shortcuts, reserved, modifier_style.
    """
```

### `get_model_config`

```python
def get_model_config(category: str = "llm", provider: str | None = None) -> dict:
    """
    Retrieve model/provider configuration for a given category.

    Categories: "llm", "stt", "tts", "ocr", "embedding", "paraphrase".

    Returns:
        dict with keys: provider, model, api_url, api_key_set,
        parameters, fallback_models, timeout_seconds, device.
    """
```

---

## Potential Solutions

### Config Formats

| Format | Library | Pros | Cons |
|--------|---------|------|------|
| **JSON** | `json` (stdlib) | Universal, no deps, fast | No comments, verbose |
| **YAML** | PyYAML (pip) | Comments, human-friendly | Unsafe loader, indentation issues |
| **TOML** | `tomllib` (stdlib 3.11+) | Type-safe, PEP 680 | Verbose nested structures |
| **.env** | python-dotenv (pip) | Simple key=value | Flat only, no validation |

**Recommendation:** JSON as primary. YAML optional. .env for env var overrides.

### Config Libraries

| Library | License | Validation | Notes |
|---------|---------|-----------|-------|
| **pydantic-settings** | MIT | Built-in, typed | Best for Pydantic v2 projects |
| **dynaconf** | MIT | Schema-based | Excellent multi-source merging |
| **python-decouple** | Unlicense | None | Too minimal |
| **hydra** | MIT | OmegaConf | Overkill for desktop app |

**Recommendation:** Custom loader with Pydantic v2 models for validation.

### Storage

| Backend | Use Case | Notes |
|---------|----------|-------|
| **JSON files** | App config, preferences | Human-readable, versionable |
| **SQLite** | User history, search cache | ACID, queryable, stdlib |
| **Platform dirs** | User config storage | XDG (Linux), AppData (Win), ~/Library (macOS) |
| **OS Keychain** | API keys, tokens | Encrypted, biometric unlock |

### Validation

| Approach | Library | Pros | Cons |
|----------|---------|------|------|
| **Pydantic v2** | pydantic | Type coercion, JSON Schema export | Runtime overhead |
| **JSON Schema** | jsonschema | Standard, language-agnostic | Verbose schemas |
| **marshmallow** | marshmallow | Serialization + validation | Heavier than Pydantic |

### Hotkey Formats

| Format | Source | Notes |
|--------|--------|-------|
| **pynput** | pynput | `"ctrl+shift+s"` — simple, well-known |
| **Tauri plugin** | tauri-plugin-global-shortcut | Native Tauri integration |
| **Custom** | This project | `"CmdOrCtrl+Shift+S"` — platform-aware |

**Recommendation:** Custom format with platform-aware resolution. Support `"CmdOrCtrl"` modifier.

---

## Alternatives and Issues

### Config Migration

Schema changes between versions require migration. Version the config with `config_version`. On load, run migration functions in sequence (v1→v2→v3). Migrations are pure, tested, and idempotent.

### User Override vs. Defaults

Priority: `defaults < system < user < project < env < env_vars`. Deep merge for dicts, replace for scalars. Preserve explicit `null` values (user intentionally disables a default).

### Secure API Key Storage

Check OS keychain first, fall back to env vars, then encrypted config. Never log or return full keys; mask all values in output dicts (`"sk-...xxxx"`).

### Platform Config Paths

| OS | Path |
|----|------|
| Linux | `~/.config/research_aid/` (XDG_CONFIG_HOME) |
| macOS | `~/Library/Application Support/research_aid/` |
| Windows | `%APPDATA%\research_aid\` |

### Hotkey Conflicts

Detect conflicts at load time. Report colliding actions. Resolve by priority (user-defined > built-in).

---

## Codebase Structure

```
config/
├── __init__.py              # Public API exports
├── loader.py                # File discovery, loading, deep merge
├── validator.py             # Schema validation and type checking
├── hotkey_config.py         # Hotkey binding and conflict detection
├── model_config.py          # LLM/STT/TTS/embedding model config
├── preferences.py           # User preferences persistence
├── schemas.py               # Pydantic models and JSON Schema
├── models.py                # Data models (Config, HotkeyConfig, etc.)
├── defaults.py              # Built-in default configuration values
├── environment.py           # Environment detection and overlay loading
├── keychain.py              # OS keychain integration
├── migration.py             # Version migration functions
└── exceptions.py            # ConfigError, ConfigKeyError, etc.
```

---

## Usage Examples

```python
from config import load_config, get_setting, update_setting, get_model_config

# Load config for development
result = load_config(env="dev")
print(result["sources_loaded"])

# Query nested settings
model = get_setting("llm.model")           # "llama3.2"
hotkey = get_setting("hotkeys.synonym")    # "ctrl+shift+s"

# Update and persist
update_setting("llm.provider", "ollama", persist=True)

# Get model config
llm = get_model_config(category="llm")
print(llm["provider"], llm["model"])       # "ollama" "llama3.2"
```

---

## Sources

- pydantic-settings: https://github.com/pydantic/pydantic-settings
- pydantic: https://github.com/pydantic/pydantic
- dynaconf: https://github.com/dynaconf/dynaconf
- python-dotenv: https://github.com/theskumar/python-dotenv
- platformdirs: https://github.com/platformdirs/platformdirs
- keyring: https://github.com/jaraco/keyring
- JSON Schema: https://json-schema.org/
- XDG Base Directory: https://specifications.freedesktop.org/basedir-spec/latest/
