"""Unit tests for source_summary subsystem."""

import os
import sys
import tempfile

import pytest

_src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from source_summary.models import InspectorHandle, ScreenCorner, SourceAnswer, SourceSummaryReport, SourceType
from source_summary.profiler import (
    SourceProfilerEngine,
    profile_external_source,
    query_source_context,
    render_floating_inspector,
)


class TestSourceSummary:
    def test_codebase_ast_profiling(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create sample python files
            file_a = os.path.join(tmpdir, "network.py")
            with open(file_a, "w", encoding="utf-8") as f:
                f.write(
                    "import torch\nimport numpy as np\n\nclass TransformerLayer:\n    def forward(self, x):\n        return x\n"
                )

            file_b = os.path.join(tmpdir, "optimizer.py")
            with open(file_b, "w", encoding="utf-8") as f:
                f.write("def configure_adamw():\n    return 'AdamW'\n")

            report = profile_external_source(tmpdir)
            assert isinstance(report, SourceSummaryReport)
            assert report.source_type == SourceType.LOCAL_CODEBASE
            assert report.statistics["total_files"] == 2
            assert report.statistics["lines_of_code"] >= 8
            assert "TransformerLayer" in str(report.methodology_bullet_points)

    def test_tabular_dataset_profiling(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "patients.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("PatientID,Age,Condition,BloodPressure\nP1,45,Healthy,120\nP2,58,Diabetic,140\nP3,,Healthy,115\n")

            report = profile_external_source(csv_path)
            assert isinstance(report, SourceSummaryReport)
            assert report.source_type == SourceType.TABULAR_DATASET
            assert report.statistics["row_count"] == 3
            assert report.statistics["column_count"] == 4
            assert report.statistics["column_types"]["Age"] == "NUMERICAL"
            assert report.statistics["column_types"]["Condition"] == "CATEGORICAL"
            assert "N = 3" in report.methodology_bullet_points[0]

            # Test Q&A over dataset schema
            ans = query_source_context(report.source_id, "What variables are recorded?")
            assert isinstance(ans, SourceAnswer)
            assert len(ans.cited_files_or_columns) >= 1

    def test_inspector_handle_rendering(self):
        report = SourceSummaryReport(
            source_id="repo123",
            title="MyProject",
            source_type=SourceType.LOCAL_CODEBASE,
            executive_summary="Summary",
        )
        handle = render_floating_inspector(report, preferred_corner=ScreenCorner.BOTTOM_RIGHT)
        assert isinstance(handle, InspectorHandle)
        assert handle.window_id == "inspector_repo123"
        assert handle.corner == ScreenCorner.BOTTOM_RIGHT
        assert handle.is_pinned is True
