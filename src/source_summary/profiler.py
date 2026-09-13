"""Codebase and Tabular Dataset Structural Profiling and Methodology Engine."""

from __future__ import annotations

import ast
import csv
import hashlib
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional, Set

from rag_indexer.indexer import index_document_corpus, filter_and_budget_context
from rag_indexer.models import DocumentPayload
from source_summary.models import (
    InspectorHandle,
    ScreenCorner,
    SourceAnswer,
    SourceSummaryReport,
    SourceType,
)

log = logging.getLogger("source_summary")

EXCLUDED_DIRS: Set[str] = {
    ".git", "__pycache__", "node_modules", "dist", "build", "venv", ".venv", "tests", "test", "docs"
}


class SourceProfilerEngine:
    """Extracts structural AST topology and tabular dataset statistics."""

    def __init__(self):
        self._reports: Dict[str, SourceSummaryReport] = {}

    def _profile_codebase(self, root_dir: str) -> SourceSummaryReport:
        """Parses Python AST across files, extracting classes, functions, and imports."""
        total_files = 0
        total_loc = 0
        classes: List[str] = []
        functions: List[str] = []
        imports: Set[str] = set()
        doc_payloads: List[DocumentPayload] = []

        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, root_dir)
                    total_files += 1
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        lines = content.splitlines()
                        total_loc += len(lines)
                        doc_payloads.append(DocumentPayload(doc_id=rel_path, content=content[:2000]))

                        tree = ast.parse(content, filename=file_path)
                        for node in ast.walk(tree):
                            if isinstance(node, ast.ClassDef):
                                classes.append(f"{node.name} ({rel_path})")
                            elif isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                                functions.append(f"{node.name}() in {rel_path}")
                            elif isinstance(node, ast.Import):
                                for alias in node.names:
                                    imports.add(alias.name.split(".")[0])
                            elif isinstance(node, ast.ImportFrom) and node.module:
                                imports.add(node.module.split(".")[0])
                    except Exception as exc:
                        log.debug("AST parsing skipped for %s: %s", rel_path, exc)

        source_id = str(uuid.uuid4())[:8]
        # Index for RAG Q&A
        if doc_payloads:
            index_document_corpus(doc_payloads, collection=f"source_{source_id}")

        bullets = [
            f"Software architecture comprised of {total_files} modules across {total_loc:,} lines of Python code.",
            f"Key dependencies and frameworks: {', '.join(sorted(list(imports)[:6])) or 'standard library'}.",
            f"Core architectural classes: {', '.join(classes[:4]) if classes else 'Functional/script structure'}.",
            f"Primary public interfaces: {', '.join(functions[:4]) if functions else 'Standard entry points'}.",
        ]

        report = SourceSummaryReport(
            source_id=source_id,
            title=os.path.basename(os.path.abspath(root_dir)),
            source_type=SourceType.LOCAL_CODEBASE,
            executive_summary=f"Python codebase with {total_files} files and {len(classes)} classes.",
            methodology_bullet_points=bullets,
            statistics={
                "total_files": total_files,
                "lines_of_code": total_loc,
                "classes_count": len(classes),
                "functions_count": len(functions),
                "dependencies": sorted(list(imports)),
            },
        )
        self._reports[source_id] = report
        return report

    def _profile_dataset(self, file_path: str) -> SourceSummaryReport:
        """Computes sample size, column types, and missingness metrics for tabular data."""
        rows: List[List[str]] = []
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            rows = [r for r in reader if r]

        if not rows:
            return SourceSummaryReport(
                source_id="empty",
                title=os.path.basename(file_path),
                source_type=SourceType.TABULAR_DATASET,
                executive_summary="Empty dataset.",
            )

        headers = rows[0]
        data = rows[1:]
        row_count = len(data)
        col_count = len(headers)
        source_id = str(uuid.uuid4())[:8]

        # Statistical analysis per column
        col_types: Dict[str, str] = {}
        missing_counts: Dict[str, int] = {}

        for col_idx, header in enumerate(headers):
            col_vals = [r[col_idx] for r in data if col_idx < len(r) and r[col_idx].strip() != ""]
            missing = row_count - len(col_vals)
            missing_counts[header] = missing

            num_count = 0
            for v in col_vals:
                try:
                    float(v)
                    num_count += 1
                except ValueError:
                    pass

            if col_vals and (num_count / len(col_vals)) >= 0.7:
                col_types[header] = "NUMERICAL"
            else:
                col_types[header] = "CATEGORICAL"

        bullets = [
            f"Empirical dataset consisting of N = {row_count:,} observations across {col_count} variables.",
            f"Numerical continuous features: {', '.join([c for c, t in col_types.items() if t == 'NUMERICAL'][:4]) or 'None'}.",
            f"Categorical features: {', '.join([c for c, t in col_types.items() if t == 'CATEGORICAL'][:4]) or 'None'}.",
            f"Data completeness: overall missing value rate of {(sum(missing_counts.values()) / max(1, row_count * col_count) * 100):.1f}%.",
        ]

        # Index schema and methodology text into RAG for robust Q&A
        schema_text = f"Dataset: {os.path.basename(file_path)}\nRows observations: {row_count}, Columns variables: {col_count}\n"
        for h in headers:
            schema_text += f"Column variable '{h}': type={col_types.get(h)}, missing={missing_counts.get(h, 0)}\n"
        full_rag_content = f"{schema_text}\nSummary Methodology:\n" + "\n".join(bullets)
        index_document_corpus(
            [DocumentPayload(doc_id=os.path.basename(file_path), content=full_rag_content)],
            collection=f"source_{source_id}",
        )

        report = SourceSummaryReport(
            source_id=source_id,
            title=os.path.basename(file_path),
            source_type=SourceType.TABULAR_DATASET,
            executive_summary=f"Tabular dataset with {row_count:,} observations and {col_count} columns.",
            methodology_bullet_points=bullets,
            statistics={
                "row_count": row_count,
                "column_count": col_count,
                "columns": headers,
                "column_types": col_types,
                "missing_counts": missing_counts,
            },
        )
        self._reports[source_id] = report
        return report

    def profile_external_source(
        self, target_path_or_url: str, source_type: Optional[SourceType] = None
    ) -> SourceSummaryReport:
        """Inspects directory path or dataset file and generates methodology summary."""
        target = os.path.abspath(target_path_or_url)
        if os.path.isdir(target):
            return self._profile_codebase(target)
        elif os.path.isfile(target) and any(target.endswith(ext) for ext in (".csv", ".tsv", ".txt")):
            return self._profile_dataset(target)
        else:
            return SourceSummaryReport(
                source_id="unknown",
                title=os.path.basename(target),
                source_type=source_type or SourceType.LOCAL_CODEBASE,
                executive_summary="Unsupported or unreadable target path.",
            )

    def query_source_context(self, source_id: str, user_question: str) -> SourceAnswer:
        """Answers author inquiries regarding the profiled artifact via localized RAG."""
        res = filter_and_budget_context(user_question, collection=f"source_{source_id}", token_budget=300)
        if not res.assembled_context:
            return SourceAnswer(
                markdown_answer="No relevant code or dataset schema found matching your question.",
                cited_files_or_columns=[],
                confidence=0.2,
            )

        cited = [p.doc_id for p in res.retrieved_passages]
        first_quote = res.retrieved_passages[0].text[:120]
        answer = f"Based on `{cited[0]}`: {first_quote}..."
        return SourceAnswer(
            markdown_answer=answer,
            cited_files_or_columns=list(set(cited)),
            confidence=0.88,
        )

    def render_floating_inspector(
        self, report: SourceSummaryReport, preferred_corner: ScreenCorner = ScreenCorner.TOP_RIGHT
    ) -> InspectorHandle:
        """Commands overlay window initialization for persistent sidebar viewing."""
        return InspectorHandle(
            window_id=f"inspector_{report.source_id}",
            corner=preferred_corner,
            is_pinned=True,
        )


_global_source_profiler = SourceProfilerEngine()


def profile_external_source(
    target_path_or_url: str, source_type: Optional[SourceType] = None
) -> SourceSummaryReport:
    return _global_source_profiler.profile_external_source(target_path_or_url, source_type)


def query_source_context(source_id: str, user_question: str) -> SourceAnswer:
    return _global_source_profiler.query_source_context(source_id, user_question)


def render_floating_inspector(
    report: SourceSummaryReport, preferred_corner: ScreenCorner = ScreenCorner.TOP_RIGHT
) -> InspectorHandle:
    return _global_source_profiler.render_floating_inspector(report, preferred_corner)
