"""Academic Text Rewording Engine with Entity Shielding and Token-Budgeted Generation."""

from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional, Tuple

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

# Regex patterns for shielding citations and formulas
CITATION_PATTERN = re.compile(
    r"\([A-Z][a-zA-Z\s]+(?:et al\.)?,?\s*\d{4}[a-z]?\)|\b[A-Z][a-zA-Z]+\s+et\s+al\.\s+\(\d{4}\)|\[\d+(?:,\s*\d+)*\]"
)
MATH_PATTERN = re.compile(r"\$\$.*?\$\$|\$[^\$]+?\$")

# Offline rule-based academic replacements
ACADEMIC_SUBSTITUTIONS: Dict[str, str] = {
    r"\blook into\b": "investigate",
    r"\ba lot of\b": "substantial",
    r"\bmake sure\b": "ensure",
    r"\bget rid of\b": "eliminate",
    r"\bturns out\b": "demonstrates",
    r"\bcomes from\b": "originates from",
    r"\bfind out\b": "determine",
    r"\bshows that\b": "demonstrates that",
    r"\bdeal with\b": "address",
    r"\bput together\b": "synthesize",
    r"\bgood\b": "rigorous",
    r"\bbad\b": "suboptimal",
}


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

    def _offline_rule_reword(self, masked_text: str, style: RewordStyle) -> Tuple[str, List[str]]:
        """Fallback rule-based transformation when LLM is unconfigured or offline."""
        transformed = masked_text
        for pattern, replacement in ACADEMIC_SUBSTITUTIONS.items():
            transformed = re.sub(pattern, replacement, transformed, flags=re.IGNORECASE)

        if style == RewordStyle.CONCISE_FLOW:
            transformed = re.sub(r"\bin order to\b", "to", transformed, flags=re.IGNORECASE)
            transformed = re.sub(r"\bdue to the fact that\b", "because", transformed, flags=re.IGNORECASE)

        # Capitalize first letter
        if transformed:
            transformed = transformed[0].upper() + transformed[1:]

        variant1 = f"Specifically, {transformed.lower()}" if not transformed.startswith("Specifically") else transformed
        variant2 = transformed.replace("demonstrates", "indicates")

        return transformed, [variant1, variant2]

    async def reword_text_segment(
        self,
        selected_text: str,
        context: Optional[SurroundingContext] = None,
        style: RewordStyle = RewordStyle.ACADEMIC_FORMAL,
    ) -> RewordResult:
        """Executes entity shielding, token-budgeted prompt dispatch, and unmasking."""
        ctx = context or SurroundingContext()
        shield = mask_scholarly_entities(selected_text)
        cache_key = f"{shield.masked_text}:{style.value}"

        # 1. Probe semantic prompt cache
        cached = query_semantic_cache(cache_key)
        if cached:
            try:
                data = json.loads(cached.cached_response)
                primary = restore_scholarly_entities(data["primary"], shield.mask_map)
                variants = [restore_scholarly_entities(v, shield.mask_map) for v in data.get("variants", [])]
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
        max_tokens = 350 if is_paragraph else 180

        system_instruction = (
            f"You are an expert academic editor. Reword the input text for {style.value}. "
            "Preserve all __CITE_x__ and __MATH_x__ placeholders exactly verbatim. "
            'Return strict JSON format: {"primary": "...", "variants": ["...", "..."]}'
        )

        user_content = f"Context: {ctx.preceding_sentence} [TARGET: {shield.masked_text}] {ctx.following_sentence}"

        payload = RequestPayload(
            method="POST",
            json_body={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.4,
            },
            max_tokens=max_tokens,
        )

        resp = await dispatch_api_request(ExternalService.LLM_SERVICE, "/chat/completions", payload)

        # 3. Process response or fallback
        if resp.is_success and isinstance(resp.data, dict):
            try:
                content = resp.data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                primary = restore_scholarly_entities(parsed.get("primary", ""), shield.mask_map)
                variants = [
                    restore_scholarly_entities(v, shield.mask_map)
                    for v in parsed.get("variants", [])
                ]
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

        # 4. Fallback execution
        primary_raw, variants_raw = self._offline_rule_reword(shield.masked_text, style)
        primary = restore_scholarly_entities(primary_raw, shield.mask_map)
        variants = [restore_scholarly_entities(v, shield.mask_map) for v in variants_raw]

        return RewordResult(
            primary_replacement=primary,
            alternative_variants=variants,
            tokens_used=0,
            style_applied=style.value,
            cached=False,
        )


_global_reword_engine = TextRewordEngine()


async def reword_text_segment(
    selected_text: str,
    context: Optional[SurroundingContext] = None,
    style: RewordStyle = RewordStyle.ACADEMIC_FORMAL,
) -> RewordResult:
    return await _global_reword_engine.reword_text_segment(selected_text, context, style)
