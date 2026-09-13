# Source Summary Subsystem

## 1. Final Deliverable
A zero-token codebase and empirical dataset methodology profiler with localized RAG Q&A (`source_summary`) providing:
- Structural AST codebase profiling (`profile_external_source()`) extracting classes, functions, lines of code, and dependencies while ignoring tests/build dirs.
- Tabular dataset statistical profiling analyzing sample sizes ($N$), feature counts ($D$), numerical/categorical types, and missingness metrics.
- Ready-to-cite methodology bullet point synthesis for research papers.
- Localized RAG Q&A (`query_source_context()`) over indexed codebases and dataset schemas citing exact files or columns.
- Persistent floating inspector handle generation (`render_floating_inspector()`).

## 2. Algorithm Used
**Algorithmic Structural AST Topology & Statistical Profiling with Local RAG**:
1. **Codebase AST Parsing (0 LLM Tokens)**: Traverses directory trees with exclusion heuristics (`.git`, `tests`, `build`, `__pycache__`). Parses Python AST syntax trees to extract `ast.ClassDef`, `ast.FunctionDef`, and `ast.Import` nodes, calculating total LoC.
2. **Tabular Dataset Profiling (0 LLM Tokens)**: Evaluates row counts, feature types, missing value percentages, and numeric distributions across CSV/TSV datasets.
3. **Automated Methodology Bullet Synthesis**: Formats standard empirical and computational methodology paragraphs ($N = \text{observations}$, features, primary classes, core dependencies).
4. **Focused Local RAG Q&A**: Chunks and indexes structural profiles into `src/rag_indexer/` under collection `source_{source_id}`, resolving author questions within strict token limits.

## 3. Description
The `source_summary` subsystem eliminates cognitive fatigue by profiling large codebases and multi-megabyte datasets on-device, providing researchers with ready-to-cite methodology summaries and instant answers without dumping entire repositories into an LLM context.
