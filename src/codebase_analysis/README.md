# codebase_analysis — Code Repository Analysis

Analyzes code repositories to extract programming methodology, detect architectural patterns, map dependencies, and generate structured summaries. Provides the "Codebase → Methodology" feature for the Research Aid Desktop Assistant.

Part of the [Research Aid Desktop Assistant](../../brainstorm/00-project-overview.md).

## Quick Start

```python
from codebase_analysis import analyze_codebase, extract_methodology

report = analyze_codebase(
    source_path="https://github.com/user/repo",
    source_type="github",
    analysis_depth="deep",
)
print(report["methodology"]["methodology_summary"])

methodology = extract_methodology(code_content=open("main.py").read())
print(methodology["design_patterns"])
```

---

## API Reference

### `analyze_codebase`

```python
def analyze_codebase(
    source_path: str,                    # Local path or GitHub URL
    source_type: str = "auto",           # "auto", "local", "github", "gitlab"
    analysis_depth: str = "standard",    # "quick", "standard", "deep"
    extract_methodology: bool = True,
    include_dependencies: bool = True,
    include_patterns: bool = True,
    max_files: int = 100,
    file_extensions: list = None,        # e.g., [".py", ".js"]
    exclude_dirs: list = None,           # default: node_modules, .git, venv
    include_tests: bool = False,
    llm_provider: str = "ollama",
    llm_model: str = "llama3.2",
    timeout_ms: int = 30000,
) -> dict:
    """
    Returns dict with keys:
        methodology: {algorithms, data_structures, design_patterns, architectural_decisions,
                      testing_approach, key_functions, methodology_summary, confidence_score}
        architecture: {overview, layer_structure, entry_points, data_flow,
                       module_coupling, cohesion_scores}
        patterns: {design_patterns, anti_patterns, code_smells, suggestions, confidence_scores}
        dependencies: {external, internal, dependency_graph, circular_dependencies,
                       unused_imports, outdated_packages}
        file_count, total_lines, languages, languages_percentage,
        summary, detailed_report, analysis_time_ms, warnings, source_info
    """
```

### `extract_methodology`

```python
def extract_methodology(
    code_content: str,
    language: str = None,                 # Auto-detect if None
    context_files: list[dict] = None,     # [{"name": str, "content": str}]
    llm_provider: str = "ollama",
    llm_model: str = "llama3.2",
    temperature: float = 0.2,
    max_tokens: int = 4096,
    include_benchmarks: bool = False,
    include_security: bool = False,
) -> dict:
    """
    Returns dict with keys:
        algorithms: [{name, description, complexity, file, line_range, purpose}]
        data_structures: [{name, type, usage, file, complexity_notes}]
        design_patterns: [{pattern, category, location, description, purpose}]
        architectural_decisions: [{decision, rationale, alternatives_considered, trade_offs}]
        testing_approach: {framework, coverage_strategy, mocking_strategy, test_patterns, test_count}
        key_functions: [{name, signature, purpose, file, complexity, is_async}]
        methodology_summary, coding_style, performance_characteristics, confidence_score
    """
```

### `summarize_code_structure`

```python
def summarize_code_structure(
    source_path: str,
    max_depth: int = 3,
    include_imports: bool = True,
    include_call_graph: bool = False,
    include_type_hierarchy: bool = False,
    max_files: int = 100,
    file_extensions: list = None,
    exclude_dirs: list = None,
) -> dict:
    """
    Returns dict with keys:
        directory_tree, directory_tree_data,
        module_dependencies: [{module, depends_on, depended_by}],
        entry_points: [{name, type, file, line}],
        key_classes: [{name, file, line, methods, base_classes}],
        key_functions: [{name, file, line, signature, is_async}],
        imports_graph, statistics, languages
    """
```

### `detect_patterns`

```python
def detect_patterns(
    code_content: str,
    language: str = None,
    rules: list[str] = None,
    include_suggestions: bool = True,
    min_severity: str = "low",
    custom_rules: list[dict] = None,
) -> dict:
    """
    Returns dict with keys:
        design_patterns: [{pattern, confidence, locations, description, benefits}]
        anti_patterns: [{pattern, severity, locations, description, impact}]
        code_smells: [{smell, severity, category, location, description, suggestion, auto_fixable}]
        suggestions: [{category, priority, description, affected_files, estimated_effort, benefit}]
        confidence_scores, summary: {total_patterns, health_score, health_rating}
    """
```

---

## Component Solutions

### Code Parsing

| Library | License | Languages | Strengths | Weaknesses |
|---------|---------|-----------|-----------|------------|
| **tree-sitter** | MIT | 40+ | Incremental, 10x faster than AST | Large grammar downloads |
| **ast** (stdlib) | PSF | Python | Zero dependencies | Python only |
| **babel** | MIT | JS/TS | Full ECMAScript spec | JS-only, heavy |
| **Roslyn** | MIT | C# | Full .NET semantic analysis | Windows-centric |

**Recommendation:** `tree-sitter` for multi-language AST. `ast` as Python fallback.

### Code Metrics

| Library | License | Strengths | Weaknesses |
|---------|---------|-----------|------------|
| **radon** | MIT | CC, MI, Halstead for Python | Python only |
| **lizard** | MIT | CC for 20+ languages | Complexity metrics only |
| **semgrep** | MIT | Cross-language pattern matching | Pattern-based, not full analysis |
| **SonarQube** | LGPL-3 | Comprehensive, multi-language | Requires server |

**Recommendation:** `radon` + `lizard` for metrics. `semgrep` for cross-language patterns.

### LLM-Based Analysis

| Provider | Context | Strengths | Weaknesses |
|----------|---------|-----------|------------|
| **Ollama (local)** | Varies | Zero cost, full privacy | Smaller models less accurate |
| **GPT-4o** | 128K | Strong code understanding | API cost, external data |
| **Claude 3.5** | 200K | Largest context, careful analysis | Rate limits |
| **Gemini 1.5** | 1M | Massive context, free tier | Inconsistent JSON output |

**Recommendation:** Ollama with `deepseek-coder:33b` for privacy-first. GPT-4o for accuracy when permitted.

### Repository Access

| Tool | License | Strengths | Weaknesses |
|------|---------|-----------|------------|
| **GitPython** | BSD | Full Git API | Git binary required |
| **pydriller** | Apache-2.0 | Commit history analysis | Heavier for simple ops |
| **ghapi** | MIT | REST + GraphQL | GitHub-only |

**Recommendation:** `GitPython` for local repos. `ghapi` for GitHub features. `pydriller` for evolution analysis.

### Dependency Analysis

| Tool | License | Strengths | Weaknesses |
|------|---------|-----------|------------|
| **pipdeptree** | MIT | Tree visualization, conflicts | Python only |
| **pip-audit** | Apache-2.0 | Vulnerability scanning | Python only |
| **npm ls** | — | Built-in transitive view | Node only |

---

## Alternatives and Issues

### Large Repository Handling
- **File sampling:** Prioritize core modules, skip vendored/generated files
- **Chunked LLM analysis:** Split code into context-window-sized chunks
- **Incremental analysis:** Cache ASTs, only re-analyze changed files
- **Parallel processing:** `multiprocessing` for CPU-bound AST parsing

### Multi-Language Support
- **Grammar management:** tree-sitter grammars needed per-language (~10-50MB each)
- **Idiomatic patterns:** Design patterns differ across languages
- **Monorepos:** Handle 5+ languages with heterogeneous aggregation

### LLM Context Limitations
- **Hierarchical summarization:** Files → modules → layers → architecture
- **AST-driven extraction:** Parse full code, send only relevant nodes to LLM
- **Multi-pass:** Structure → key files → cross-references

### Privacy Concerns
- **Local-first:** Default to Ollama; API calls opt-in only
- **Secret scanning:** Run `detect-secrets` before external API calls
- **User consent:** Explicit prompt before sending code externally

### Accuracy
- **Confidence scoring:** Each extraction element includes confidence score
- **Cross-validation:** Compare LLM results against static analysis
- **Benchmarking:** Validate against well-documented open-source projects

### Generated Code
- **Detection:** Identify vendored dirs via config (`vendor/`, `node_modules/`)
- **Auto-skip:** Files with `Generated by` headers, `__pycache__`, `dist/`
- **Separation:** Clearly mark "authored" vs "vendored" in results

---

## Codebase Structure

```
codebase_analysis/
├── __init__.py                 # Public API exports
├── config.py                   # Configuration
├── models.py                   # Data models (CodebaseReport, Methodology, etc.)
├── repository_analyzer.py      # Repository-level orchestration
├── code_parser.py              # tree-sitter AST parsing
├── methodology_extractor.py    # LLM-based methodology extraction
├── pattern_detector.py         # Pattern and anti-pattern detection
├── dependency_analyzer.py      # Dependency graph and license analysis
├── summarizer.py               # Report generation
├── parsers/                    # Language-specific parsers
│   ├── python_parser.py
│   ├── javascript_parser.py
│   ├── rust_parser.py
│   └── generic_parser.py
├── detectors/                  # Detection rules
│   ├── design_patterns.py
│   ├── anti_patterns.py
│   ├── code_smells.py
│   └── security_patterns.py
├── llm/                        # LLM integration
│   ├── methodology_prompt.py
│   ├── architecture_prompt.py
│   └── code_reviewer.py
└── utils/                      # Utilities
    ├── git_utils.py
    ├── file_scanner.py
    ├── cache.py
    └── formatters.py
```

### Module Responsibilities

| Module | Responsibility | Key Dependencies |
|--------|---------------|-----------------|
| `repository_analyzer.py` | Orchestrates full pipeline | All modules |
| `code_parser.py` | AST parsing, function/class extraction | tree-sitter, ast |
| `methodology_extractor.py` | LLM methodology extraction | agent module |
| `pattern_detector.py` | Static pattern matching | ast, tree-sitter |
| `dependency_analyzer.py` | Dependency graphs, licenses | pipdeptree, pip-audit |
| `summarizer.py` | Markdown report generation | models, formatters |

---

## Sources

- tree-sitter: https://github.com/tree-sitter/tree-sitter
- radon: https://github.comrubik/radon
- lizard: https://github.com/terryyin/lizard
- semgrep: https://github.com/semgrep/semgrep
- GitPython: https://github.com/gitpython-developers/GitPython
- pydriller: https://github.com/ishepard/pydriller
- pipdeptree: https://github.com/tox-dev/pipdeptree
- pip-audit: https://github.com/pypa/pip-audit
- detect-secrets: https://github.com/Yelp/detect-secrets
- Ollama: https://github.com/ollama/ollama
