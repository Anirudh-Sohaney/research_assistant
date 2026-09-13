"""Parallel LLM judging for selected academic text."""

from __future__ import annotations

import asyncio
import ast
import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from api_gateway.gateway import dispatch_api_request
from api_gateway.models import ExternalService, RequestPayload


DEFAULT_MODEL = os.getenv("PAPER_ANALYSIS_MODEL", "inclusionai/ling-3.0-flash-fin:free")
DEFAULT_TIMEOUT = float(os.getenv("PAPER_ANALYSIS_TIMEOUT", "120"))

JUDGE_RUBRICS: Dict[str, str] = {
    "Consistency": "Check terminology, claims, tense, notation, numbers, and definitions for internal consistency.",
    "Grammar": "Check sentence construction, agreement, punctuation, articles, tense, and grammatical correctness.",
    "Clarity": "Check readability, ambiguity, overloaded sentences, vague references, and whether each claim is easy to understand.",
    "Organization": "Check logical order, transitions, paragraph purpose, argument progression, and information hierarchy.",
    "Evidence": "Check whether claims are supported, methods are sufficiently described, evidence matches conclusions, and unsupported overclaims appear.",
    "Academic Style": "Check formal scholarly register, precision, vocabulary, tone, unnecessary informality, and discipline-appropriate conventions.",
    "Methodology": "Check reproducibility, variables, data/sample descriptions, controls, evaluation design, and methodological omissions.",
    "Contribution": "Check novelty, significance, research question alignment, interpretation, limitations, and whether conclusions follow from the text.",
}


@dataclass
class Finding:
    excerpt: str
    issue: str
    fix: str


@dataclass
class JudgeResult:
    name: str
    score: Optional[int]
    findings: List[Finding] = field(default_factory=list)
    error: Optional[str] = None
    tokens_used: int = 0


@dataclass
class PaperAnalysisResult:
    judges: List[JudgeResult]
    overall_score: Optional[int]
    tokens_used: int


def _curved_score(raw_score: object) -> int:
    """Map the judge's quality estimate onto a forgiving 50-100 quality curve."""
    try:
        raw = max(1.0, min(100.0, float(raw_score)))
    except (TypeError, ValueError):
        raw = 1.0
    return max(50, min(100, int(round(50 + 50 * math.pow(raw / 100.0, 1.65)))))


def _parse_json(content: object) -> Dict[str, object]:
    text = str(content or "").strip()
    candidates = [text]
    candidates.extend(re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.I | re.S))
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except (TypeError, json.JSONDecodeError):
            try:
                value = ast.literal_eval(candidate)
                if isinstance(value, dict):
                    return value
            except (SyntaxError, ValueError):
                continue
    raise ValueError("judge response did not contain valid JSON")


def _judge_prompt(name: str, rubric: str, selected_text: str) -> List[Dict[str, str]]:
    system = (
        "You are one independent academic paper reviewer. Analyze only the supplied text, not hidden context. "
        f"Your assigned dimension is {name}: {rubric} "
        "Score quality from 1 to 100 using this raw scale: 1-30 fundamentally deficient, 31-49 many serious issues, "
        "50-69 multiple issues but salvageable, 70-89 strong with revisions, 90-99 publishable quality, 100 utterly perfect. "
        "Return exactly 3 to 6 concrete findings. Each finding must quote a short exact excerpt from the supplied text, "
        "identify the specific problem, and give a direct repair instruction. Do not praise generally, invent facts, or review other dimensions. "
        'Return strict JSON: {"score": 1-100, "findings": [{"excerpt":"...", "issue":"...", "fix":"..."}]}.'
    )
    user = f"FULL SELECTED PAPER TEXT:\n{selected_text}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def _run_judge(name: str, rubric: str, selected_text: str) -> JudgeResult:
    last_error = "judge request failed"
    total_tokens = 0
    for attempt in range(2):
        payload = RequestPayload(
            method="POST",
            json_body={
                "model": DEFAULT_MODEL,
                "messages": _judge_prompt(name, rubric, selected_text),
                "temperature": 0.2,
                "reasoning": {"effort": "low", "exclude": True},
            },
            timeout=DEFAULT_TIMEOUT,
            max_tokens=4000 if attempt == 0 else 5200,
        )
        try:
            response = await dispatch_api_request(ExternalService.LLM_SERVICE, "/chat/completions", payload)
        except Exception as exc:
            last_error = str(exc)
            continue
        total_tokens += response.tokens_consumed
        if not response.is_success or not isinstance(response.data, dict):
            last_error = response.error or last_error
            continue
        try:
            message = response.data["choices"][0].get("message", {})
            content = message.get("content") or message.get("reasoning") or ""
            parsed = _parse_json(content)
            findings = []
            for item in parsed.get("findings", []):
                if not isinstance(item, dict):
                    continue
                excerpt = str(item.get("excerpt", "")).strip()
                issue = str(item.get("issue", "")).strip()
                fix = str(item.get("fix", "")).strip()
                if excerpt and issue and fix:
                    findings.append(Finding(excerpt, issue, fix))
            if len(findings) < 3:
                raise ValueError("judge returned fewer than 3 actionable findings")
            return JudgeResult(name, _curved_score(parsed.get("score")), findings[:6], tokens_used=total_tokens)
        except Exception as exc:
            last_error = str(exc)
    return JudgeResult(name, None, error=last_error, tokens_used=total_tokens)


async def analyze_paper(selected_text: str) -> PaperAnalysisResult:
    """Run all independent judges concurrently, each receiving the full selection."""
    if not selected_text.strip():
        raise ValueError("selected paper text cannot be empty")
    results = await asyncio.gather(*(_run_judge(name, rubric, selected_text) for name, rubric in JUDGE_RUBRICS.items()))
    valid_scores = [judge.score for judge in results if judge.score is not None]
    return PaperAnalysisResult(
        judges=results,
        overall_score=round(sum(valid_scores) / len(valid_scores)) if valid_scores else None,
        tokens_used=sum(judge.tokens_used for judge in results),
    )
