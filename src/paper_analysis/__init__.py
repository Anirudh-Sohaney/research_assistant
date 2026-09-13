"""Multi-judge academic paper analysis."""

from paper_analysis.analysis import (
    JUDGE_RUBRICS,
    JudgeResult,
    PaperAnalysisResult,
    analyze_paper,
)

__all__ = ["JUDGE_RUBRICS", "JudgeResult", "PaperAnalysisResult", "analyze_paper"]
