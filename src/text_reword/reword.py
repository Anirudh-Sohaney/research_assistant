"""Academic Text Rewording Engine with Entity Shielding and Token-Budgeted Generation."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, List, Optional

from api_gateway.models import ExternalService, RequestPayload
from api_gateway.gateway import dispatch_api_request
from rag_indexer.indexer import query_semantic_cache, cache_llm_response
from text_reword.models import (
    EntityMaskReport,
    RewordResult,
    RewordStyle,
    SurroundingContext,
)

log = logging.getLogger("text_reword")

DEFAULT_REWORD_MODEL = os.getenv(
    "OPENROUTER_REWORD_MODEL",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
)

# Regex patterns for shielding citations and formulas
CITATION_PATTERN = re.compile(
    r"\([A-Z][a-zA-Z\s]+(?:et al\.)?,?\s*\d{4}[a-z]?\)|\b[A-Z][a-zA-Z]+\s+et\s+al\.\s+\(\d{4}\)|\[\d+(?:,\s*\d+)*\]"
)
MATH_PATTERN = re.compile(r"\$\$.*?\$\$|\$[^\$]+?\$")

def mask_scholarly_entities(raw_text: str) -> EntityMaskReport:
    """Replaces citations and LaTeX math with atomic placeholders to shield tokens."""
    mask_map: Dict[str, str] = {}
    counter = 0

    def math_repl(match: re.Match) -> str:
        nonlocal counter
        ph = f"__MATH_{counter}__"
        mask_map[ph] = match.group(0)
        counter += 1
        return ph

    def cite_repl(match: re.Match) -> str:
        nonlocal counter
        ph = f"__CITE_{counter}__"
        mask_map[ph] = match.group(0)
        counter += 1
        return ph

    # Mask math first then citations
    masked = MATH_PATTERN.sub(math_repl, raw_text)
    masked = CITATION_PATTERN.sub(cite_repl, masked)

    return EntityMaskReport(masked_text=masked, mask_map=mask_map)


def restore_scholarly_entities(masked_text: str, mask_map: Dict[str, str]) -> str:
    """Restores shielded citations and formulas into the reworded text."""
    restored = masked_text
    for placeholder, original in mask_map.items():
        if placeholder in restored:
            restored = restored.replace(placeholder, original)
        else:
            # Fallback if model omitted placeholder: append to end
            restored += f" {original}"
    return restored


class TextRewordEngine:
    """Rewords sentences/paragraphs for academic style with strict token limits."""

    async def reword_text_segment(
        self,
        selected_text: str,
        context: Optional[SurroundingContext] = None,
        style: RewordStyle = RewordStyle.ACADEMIC_FORMAL,
        bypass_cache: bool = False,
    ) -> RewordResult:
        """Executes entity shielding, token-budgeted prompt dispatch, and unmasking."""
        ctx = context or SurroundingContext()
        shield = mask_scholarly_entities(selected_text)
        # Version the key so cached output from the pre-Ling implementation cannot leak into
        # the interactive popup, and include adjacent context in the cache identity.
        cache_key = (
            f"reword_v2:{shield.masked_text}:{style.value}:"
            f"{ctx.preceding_sentence}:{ctx.following_sentence}"
        )

        # 1. Probe semantic prompt cache
        cached = query_semantic_cache(cache_key)
        if cached and not bypass_cache:
            try:
                data = json.loads(cached.cached_response)
                primary_raw = str(data["primary"]).strip()
                quality_text = re.sub(r"__(?:CITE|MATH)_\d+__", "", primary_raw).strip()
                if not quality_text or not re.search(r"[A-Za-z]{2,}", quality_text) or re.fullmatch(r"[.\s,;:!?()\[\]_-]+", quality_text):
                    raise ValueError("Cached replacement is unusable")
                primary = restore_scholarly_entities(primary_raw, shield.mask_map)
                variants = [restore_scholarly_entities(v, shield.mask_map) for v in data.get("variants", [])]
                if primary.strip() == selected_text.strip():
                    raise ValueError("Cached replacement is unchanged")
                return RewordResult(
                    primary_replacement=primary,
                    alternative_variants=variants,
                    tokens_used=0,
                    style_applied=style.value,
                    cached=True,
                )
            except Exception:
                pass

        # 2. Prepare compact prompt
        is_paragraph = len(selected_text.split()) > 40
        # Ling may spend completion tokens on an internal reasoning trace before emitting
        # JSON. Leave enough room for both reasoning and the full rewritten passage.
        max_tokens = 900 if is_paragraph else 700

        style_instruction = {
            RewordStyle.ACADEMIC_FORMAL: (
                "Fully rewrite and restructure the selected text while preserving the exact idea and factual content. "
                "The user expressed an idea but wants a substantially better formulation: repair grammar and English conventions, "
                "improve vocabulary, vary syntax, and use a natural new sentence structure. Combine some conservative edits with "
                "stronger structural and lexical improvements; do not merely delete filler words or lightly proofread. "
                "Do not add a preface, self-introduction, conclusion, or any information not present in the source."
            ),
            RewordStyle.EXPANDED_ARGUMENT: (
                "Keep the original sentence structure and progression recognizable, but add useful detail, specificity, "
                "explanation, and connective context. Preserve the original claim and do not invent citations, measurements, "
                "or unsupported facts."
            ),
            RewordStyle.SIMPLIFIED_CLARITY: (
                "Preserve the essential ideas and their order, but express them with simpler words, shorter constructions, "
                "and clearer explanations. Reduce unnecessary complexity without losing important meaning or factual content."
            ),
        }.get(style, "Improve the wording while preserving the original meaning.")

        system_instruction = (
            f"You are an expert academic editor. {style_instruction} "
            "Think internally but emit the JSON answer immediately after your analysis; do not expose a reasoning trace. "
            "Return a genuinely revised version of the selected text; do not copy it unchanged "
            "unless no grammatical, clarity, or convention improvement is possible. "
            "Preserve all __CITE_x__ and __MATH_x__ placeholders exactly verbatim. "
            'Return strict JSON format: {"primary": "...", "variants": ["...", "..."]}'
        )

        user_content = (
            f"PRECEDING CONTEXT: {ctx.preceding_sentence}\n"
            f"SELECTED TEXT TO TRANSFORM: {shield.masked_text}\n"
            f"FOLLOWING CONTEXT: {ctx.following_sentence}\n"
            "Only transform the selected text; use context to resolve meaning."
        )

        payload = RequestPayload(
            method="POST",
            json_body={
                "model": DEFAULT_REWORD_MODEL,
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.4,
                "reasoning": {"effort": "low", "exclude": True},
            },
            max_tokens=max_tokens,
        )

        resp = await dispatch_api_request(ExternalService.LLM_SERVICE, "/chat/completions", payload)

        # 3. Process the OpenRouter response. Rewording is intentionally LLM-only;
        # there is no local text substitution fallback.
        if resp.is_success and isinstance(resp.data, dict):
            try:
                message = resp.data["choices"][0].get("message", {})
                content = message.get("content") or message.get("reasoning") or ""
                parsed = self._parse_structured_response(content)
                primary_raw = str(parsed.get("primary", "")).strip()
                primary = restore_scholarly_entities(primary_raw, shield.mask_map)
                variants = [
                    restore_scholarly_entities(str(v).strip(), shield.mask_map)
                    for v in parsed.get("variants", [])
                    if str(v).strip()
                ]
                quality_text = re.sub(r"__(?:CITE|MATH)_\d+__", "", primary_raw).strip()
                if not quality_text or not re.search(r"[A-Za-z]{2,}", quality_text) or re.fullmatch(r"[.\s,;:!?()\[\]_-]+", quality_text):
                    raise ValueError("LLM returned an unusable primary replacement")
                if primary.strip() == selected_text.strip():
                    alternate = next((v for v in variants if v.strip() != selected_text.strip()), "")
                    if alternate:
                        primary = alternate
                    else:
                        # Never cache or report an unchanged LLM response as a successful rewrite.
                        raise ValueError("LLM returned unchanged text")
                cache_llm_response(cache_key, json.dumps({"primary": parsed.get("primary", ""), "variants": parsed.get("variants", [])}))
                return RewordResult(
                    primary_replacement=primary,
                    alternative_variants=variants,
                    tokens_used=resp.tokens_consumed,
                    style_applied=style.value,
                    cached=False,
                )
            except Exception as exc:
                log.warning("LLM response parse error: %s", exc)

        error = resp.error or "OpenRouter did not return a usable rewording."
        return RewordResult(
            primary_replacement="",
            alternative_variants=[],
            tokens_used=0,
            style_applied=style.value,
            cached=False,
            error=error,
        )

    @staticmethod
    def _parse_structured_response(content: str) -> Dict[str, object]:
        """Parses strict, fenced, or prose-wrapped JSON returned by chat models."""
        text = str(content or "").strip()
        if not text:
            raise ValueError("LLM response was empty")
        candidates = [text]
        fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.IGNORECASE | re.DOTALL)
        candidates.extend(fenced)
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            candidates.append(text[start : end + 1])
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except (TypeError, json.JSONDecodeError):
                continue
        raise ValueError("LLM response did not contain valid reword JSON")


_global_reword_engine = TextRewordEngine()


async def reword_text_segment(
    selected_text: str,
    context: Optional[SurroundingContext] = None,
    style: RewordStyle = RewordStyle.ACADEMIC_FORMAL,
    bypass_cache: bool = False,
) -> RewordResult:
    return await _global_reword_engine.reword_text_segment(selected_text, context, style, bypass_cache=bypass_cache)
