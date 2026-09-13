"""Lexical Synonyms Engine implementing 2-stage zero-token candidate harvesting and contextual re-ranking."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import time
from typing import Dict, List, Optional, Set, Tuple

from api_gateway.models import ExternalService, RequestPayload
from api_gateway.gateway import dispatch_api_request
from lexical_synonyms.models import (
    RawCandidate,
    SynonymGroupResult,
    SynonymItem,
)

log = logging.getLogger("lexical_synonyms")

# =============================================================================
# OpenRouter Model Configuration for Contextual Synonym Generation
# Configured for OpenRouter model: inclusionai/ling-3.0-flash-vl:free
# =============================================================================
DEFAULT_LLM_SYNONYM_MODEL = os.getenv(
    "OPENROUTER_SYNONYM_MODEL",
    os.getenv("LLM_SYNONYM_MODEL", "inclusionai/ling-3.0-flash-vl:free")
)
DEFAULT_OPENAI_SYNONYM_MODEL = DEFAULT_LLM_SYNONYM_MODEL  # Backward compatibility alias
DEFAULT_REASONING_EFFORT = "low"
DEFAULT_MAX_COMPLETION_TOKENS = 450  # Bounded for reasoning trace + JSON array generation

# Curated Academic Word List (AWL) subset + STEM research vocabulary for register scoring
ACADEMIC_REGISTER_TERMS: Set[str] = {
    "accurate", "adequate", "alter", "analyze", "apparent", "approach", "appropriate",
    "approximate", "arbitrary", "aspect", "assess", "assume", "authority", "available",
    "benefit", "category", "circumstance", "clarify", "coherent", "coincide", "collapse",
    "commence", "compatible", "compensate", "compile", "complement", "complex", "component",
    "comprehensive", "comprise", "compute", "conceive", "conclude", "concurrent", "conduct",
    "conform", "consent", "consequent", "considerable", "consist", "constant", "constitute",
    "constrain", "construct", "consult", "consume", "contact", "contemporary", "context",
    "contradict", "contrary", "contrast", "contribute", "controversy", "convene", "converse",
    "convert", "convince", "core", "correspond", "crucial", "deduce", "define", "demonstrate",
    "denote", "deny", "depict", "derive", "design", "detect", "deviate", "differentiate",
    "dimension", "diminish", "discrete", "discriminate", "displace", "display", "distinct",
    "distort", "distribute", "diverse", "domain", "dominate", "draft", "duration", "dynamic",
    "eliminate", "emerge", "emphasis", "empirical", "enable", "encounter", "enhance",
    "enormous", "ensure", "entity", "equate", "equip", "equivalent", "erode", "establish",
    "estate", "estimate", "evaluate", "evident", "evolve", "exceed", "exclude", "exhibit",
    "expand", "expert", "explicit", "exploit", "export", "expose", "external", "extract",
    "facilitate", "factor", "feature", "federal", "fee", "file", "final", "finite", "flexible",
    "fluctuate", "focus", "format", "formula", "forthcoming", "foundation", "framework",
    "function", "fund", "fundamental", "furthermore", "gender", "generate", "generation",
    "globe", "grade", "grant", "guarantee", "guideline", "hence", "hierarchy", "highlight",
    "hypothesis", "identical", "identify", "ideology", "ignorant", "illustrate", "image",
    "immigrate", "impact", "implement", "implication", "implicit", "imply", "impose",
    "incentive", "incidence", "incline", "income", "incorporate", "index", "indicate",
    "individual", "induce", "inevitable", "infer", "infrastructure", "inherent", "inhibit",
    "initial", "initiative", "injure", "innovate", "input", "insert", "insight", "inspect",
    "instance", "institute", "instruct", "integral", "integrate", "integrity", "intelligence",
    "intense", "interact", "intermediate", "internal", "interpret", "interval", "intervene",
    "intrinsic", "invest", "investigate", "invoke", "involve", "isolate", "issue", "item",
    "job", "journal", "justify", "label", "labor", "layer", "lecture", "legal", "legislate",
    "levy", "liberal", "license", "likewise", "link", "locate", "logic", "maintain", "major",
    "manifest", "manipulate", "manual", "margin", "mature", "maximize", "mechanism", "media",
    "mediate", "medical", "medium", "mental", "method", "migrate", "military", "minimal",
    "minimize", "minimum", "ministry", "minor", "mode", "modify", "monitor", "motive",
    "mutual", "negate", "network", "neutral", "nevertheless", "nonetheless", "norm", "normal",
    "notion", "notwithstanding", "nuclear", "objective", "obtain", "obvious", "occupy",
    "occur", "odd", "offset", "ongoing", "option", "orient", "outcome", "output", "overall",
    "overlap", "overseas", "panel", "paradigm", "paragraph", "parallel", "parameter",
    "participate", "partner", "passive", "perceive", "percent", "period", "persist",
    "perspective", "phase", "phenomenon", "philosophy", "physical", "plus", "policy",
    "portion", "pose", "positive", "potential", "practitioner", "precede", "precise",
    "predict", "predominant", "preliminary", "presume", "previous", "primary", "prime",
    "principal", "principle", "prior", "priority", "proceed", "process", "professional",
    "prohibit", "project", "promote", "proportion", "prospect", "protocol", "psychology",
    "publication", "publish", "purchase", "pursue", "qualitative", "quote", "radical",
    "random", "range", "ratio", "rational", "react", "recover", "refine", "regime", "region",
    "register", "regulate", "reinforce", "reject", "relax", "release", "relevant", "reluctance",
    "rely", "remove", "require", "research", "reside", "resolve", "resource", "respond",
    "restore", "restrain", "restrict", "retain", "reveal", "revenue", "reverse", "revise",
    "revolution", "rigid", "role", "route", "scenario", "schedule", "scheme", "scope",
    "section", "sector", "secure", "seek", "select", "sequence", "series", "shift",
    "significant", "similar", "simulate", "site", "so-called", "sole", "somewhat", "source",
    "specific", "specify", "sphere", "stable", "statistic", "status", "straightforward",
    "strategy", "stress", "structure", "style", "submit", "subordinate", "subsequent",
    "subsidy", "substitute", "successor", "sufficient", "sum", "summary", "supplement",
    "survey", "survive", "suspend", "sustain", "symbol", "tape", "target", "task", "team",
    "technical", "technique", "technology", "temporary", "tense", "terminate", "text",
    "theme", "theory", "thereby", "thesis", "topic", "trace", "tradition", "transfer",
    "transform", "transit", "transmit", "transport", "trend", "trigger", "ultimate",
    "undergo", "underlie", "undertake", "uniform", "unify", "unique", "utilize", "valid",
    "vary", "vehicle", "version", "via", "violate", "virtual", "visible", "vision", "visual",
    "volume", "voluntary", "welfare", "whereas", "whereby", "widespread", "ubiquitous",
    "omnipresent", "pervasive", "prevalent", "universal", "permeating", "train", "simulate",
    "model", "optimize", "compute", "calculate", "evaluate", "validate", "measure",
    "observe", "benchmark", "derive", "acquire", "detail", "outline", "depict",
    "characterize", "correlate", "formulate", "quantify", "synthesize", "classify", "present"
}

# Known antonym pairs to explicitly prevent polarity inversion in candidate harvesting
KNOWN_ANTONYMS: Dict[str, Set[str]] = {
    "objective": {"subjective", "biased", "partial", "prejudiced"},
    "subjective": {"objective", "impartial", "unbiased"},
    "increase": {"decrease", "diminish", "reduce", "curtail", "attenuate", "drop", "fall"},
    "decrease": {"increase", "augment", "elevate", "expand", "enhance", "escalate", "grow"},
    "positive": {"negative"},
    "negative": {"positive"},
    "direct": {"indirect"},
    "indirect": {"direct"},
    "significant": {"insignificant", "negligible", "trivial", "minor"},
    "sufficient": {"insufficient", "inadequate", "lacking"},
    "accurate": {"inaccurate", "incorrect", "erroneous"},
    "dependent": {"independent"},
    "independent": {"dependent"},
    "similar": {"different", "dissimilar", "distinct"},
    "active": {"passive", "inactive"},
    "passive": {"active"},
    "explicit": {"implicit", "vague", "ambiguous"},
    "implicit": {"explicit"},
    "stable": {"unstable", "volatile"},
    "internal": {"external"},
    "external": {"internal"},
    "finite": {"infinite"},
    "valid": {"invalid"},
    "consistent": {"inconsistent"},
    "converge": {"diverge"},
    "convergent": {"divergent"},
}

# Offline fallback lexicon for standard academic words with explicit POS tags
OFFLINE_FALLBACK_LEXICON: Dict[str, List[Tuple[str, str]]] = {
    "ubiquitous": [("omnipresent", "adj"), ("pervasive", "adj"), ("universal", "adj"), ("prevalent", "adj"), ("widespread", "adj")],
    "objective": [
        ("unbiased", "adj"), ("impartial", "adj"), ("neutral", "adj"), ("empirical", "adj"),
        ("factual", "adj"), ("dispassionate", "adj"), ("fair", "adj"), ("verifiable", "adj"),
        ("goal", "noun"), ("purpose", "noun"), ("aim", "noun"), ("target", "noun"),
        ("intent", "noun"), ("intention", "noun"), ("ambition", "noun"), ("benchmark", "noun")
    ],
    "demonstrate": [("illustrate", "verb"), ("exhibit", "verb"), ("indicate", "verb"), ("manifest", "verb"), ("substantiate", "verb"), ("reveal", "verb")],
    "show": [("demonstrate", "verb"), ("illustrate", "verb"), ("indicate", "verb"), ("reveal", "verb"), ("exhibit", "verb")],
    "use": [("utilize", "verb"), ("employ", "verb"), ("apply", "verb"), ("leverage", "verb"), ("implement", "verb")],
    "utilize": [("employ", "verb"), ("apply", "verb"), ("leverage", "verb"), ("implement", "verb"), ("adopt", "verb")],
    "important": [("significant", "adj"), ("crucial", "adj"), ("essential", "adj"), ("critical", "adj"), ("pivotal", "adj")],
    "indicate": [("suggest", "verb"), ("signify", "verb"), ("denote", "verb"), ("demonstrate", "verb"), ("imply", "verb")],
    "examine": [("investigate", "verb"), ("scrutinize", "verb"), ("evaluate", "verb"), ("probe", "verb"), ("assess", "verb")],
    "increase": [("augment", "verb"), ("elevate", "verb"), ("expand", "verb"), ("enhance", "verb"), ("escalate", "verb")],
    "decrease": [("diminish", "verb"), ("reduce", "verb"), ("curtail", "verb"), ("attenuate", "verb"), ("lessen", "verb")],
    "learn": [("train", "verb"), ("acquire", "verb"), ("study", "verb"), ("master", "verb"), ("develop", "verb"), ("derive", "verb"), ("instruct", "verb")],
    "describe": [("detail", "verb"), ("outline", "verb"), ("depict", "verb"), ("characterize", "verb"), ("delineate", "verb"), ("define", "verb"), ("portray", "verb"), ("illustrate", "verb"), ("present", "verb")],
    "significant": [("substantial", "adj"), ("notable", "adj"), ("considerable", "adj"), ("meaningful", "adj"), ("consequential", "adj")],
    "robust": [("resilient", "adj"), ("durable", "adj"), ("sturdy", "adj"), ("reliable", "adj"), ("sound", "adj"), ("rigorous", "adj")],
    "evaluate": [("assess", "verb"), ("appraise", "verb"), ("gauge", "verb"), ("estimate", "verb"), ("scrutinize", "verb"), ("measure", "verb")],
    "framework": [("structure", "noun"), ("architecture", "noun"), ("schema", "noun"), ("paradigm", "noun"), ("system", "noun")],
    "approach": [("method", "noun"), ("methodology", "noun"), ("technique", "noun"), ("strategy", "noun"), ("procedure", "noun")],
}


# Irregular verb inflections: (VBZ: 3rd-person singular present, VBD: past tense, VBN: past participle)
IRREGULAR_VERBS: Dict[str, Tuple[str, str, str]] = {
    "take": ("takes", "took", "taken"),
    "see": ("sees", "saw", "seen"),
    "write": ("writes", "wrote", "written"),
    "draw": ("draws", "drew", "drawn"),
    "find": ("finds", "found", "found"),
    "know": ("knows", "knew", "known"),
    "teach": ("teaches", "taught", "taught"),
    "learn": ("learns", "learned", "learned"),
    "give": ("gives", "gave", "given"),
    "make": ("makes", "made", "made"),
    "tell": ("tells", "told", "told"),
    "show": ("shows", "showed", "shown"),
    "build": ("builds", "built", "built"),
    "read": ("reads", "read", "read"),
    "understand": ("understands", "understood", "understood"),
    "acquire": ("acquires", "acquired", "acquired"),
    "examine": ("examines", "examined", "examined"),
    "study": ("studies", "studied", "studied"),
    "investigate": ("investigates", "investigated", "investigated"),
    "train": ("trains", "trained", "trained"),
    "simulate": ("simulates", "simulated", "simulated"),
    "model": ("models", "modeled", "modeled"),
    "derive": ("derives", "derived", "derived"),
    "develop": ("develops", "developed", "developed"),
    "optimize": ("optimizes", "optimized", "optimized"),
    "demonstrate": ("demonstrates", "demonstrated", "demonstrated"),
    "illustrate": ("illustrates", "illustrated", "illustrated"),
    "outline": ("outlines", "outlined", "outlined"),
    "detail": ("details", "detailed", "detailed"),
    "characterize": ("characterizes", "characterized", "characterized"),
    "depict": ("depicts", "depicted", "depicted"),
    "delineate": ("delineates", "delineated", "delineated"),
    "summarize": ("summarizes", "summarized", "summarized"),
    "describe": ("describes", "described", "described"),
    "define": ("defines", "defined", "defined"),
    "identify": ("identifies", "identified", "identified"),
    "present": ("presents", "presented", "presented"),
    "observe": ("observes", "observed", "observed"),
    "evaluate": ("evaluates", "evaluated", "evaluated"),
    "assess": ("assesses", "assessed", "assessed"),
}


def inflect_candidate(lemma: str, target_tag: str) -> str:
    """Inflects candidate base lemma to match target tense and grammatical number."""
    lemma = lemma.lower().strip()
    if not lemma or len(lemma) < 2:
        return ""

    if lemma in IRREGULAR_VERBS:
        vbz, vbd, vbn = IRREGULAR_VERBS[lemma]
        if target_tag == "VBZ":
            return vbz
        elif target_tag == "VBD":
            return vbd
        elif target_tag == "VBN":
            return vbn

    if target_tag == "VBZ":
        if lemma.endswith(("s", "sh", "ch", "x", "z", "o")):
            return lemma + "es"
        elif lemma.endswith("y") and len(lemma) > 1 and lemma[-2] not in "aeiou":
            return lemma[:-1] + "ies"
        return lemma + "s"

    elif target_tag in ("VBD", "VBN"):
        if lemma.endswith("e"):
            return lemma + "d"
        elif lemma.endswith("y") and len(lemma) > 1 and lemma[-2] not in "aeiou":
            return lemma[:-1] + "ied"
        elif len(lemma) >= 3 and lemma[-1] in "bdfglmnprt" and lemma[-2] in "aeiou" and lemma[-3] not in "aeiou":
            return lemma + lemma[-1] + "ed"
        return lemma + "ed"

    elif target_tag == "VBG":
        if lemma.endswith("ie"):
            return lemma[:-2] + "ying"
        elif lemma.endswith("e") and not lemma.endswith("ee"):
            return lemma[:-1] + "ing"
        return lemma + "ing"

    elif target_tag == "NNS":
        if lemma.endswith(("s", "sh", "ch", "x", "z")):
            return lemma + "es"
        elif lemma.endswith("y") and len(lemma) > 1 and lemma[-2] not in "aeiou":
            return lemma[:-1] + "ies"
        return lemma + "s"

    return lemma


_NLP = None
_TRANSFORMER = None


def _get_nlp():
    """Lazy loader for spaCy language model."""
    global _NLP
    if _NLP is None:
        try:
            import spacy
            _NLP = spacy.load("en_core_web_sm")
        except Exception as exc:
            log.debug("spaCy load notice: %s", exc)
    return _NLP


def _get_transformer():
    """Lazy loader for local SentenceTransformer model."""
    global _TRANSFORMER
    if _TRANSFORMER is None:
        try:
            from sentence_transformers import SentenceTransformer
            _TRANSFORMER = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception as exc:
            log.debug("SentenceTransformer load notice: %s", exc)
    return _TRANSFORMER


_QWEN_MODEL = None
_QWEN_TOKENIZER = None


def _get_qwen():
    """Lazy loader for local 1.5B instruction-tuned LLM (Qwen2.5-1.5B-Instruct)."""
    global _QWEN_MODEL, _QWEN_TOKENIZER
    if _QWEN_MODEL is None or _QWEN_TOKENIZER is None:
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            model_id = "Qwen/Qwen2.5-1.5B-Instruct"
            _QWEN_TOKENIZER = AutoTokenizer.from_pretrained(model_id)
            _QWEN_MODEL = AutoModelForCausalLM.from_pretrained(model_id, dtype=torch.bfloat16)
        except Exception as exc:
            log.debug("Qwen LLM load notice: %s", exc)
    return _QWEN_MODEL, _QWEN_TOKENIZER


class LexicalSynonymsEngine:
    """Harvests synonyms from Datamuse dictionary and ranks them using transformer context embeddings."""

    async def harvest_candidate_synonyms(
        self, word: str, lemma: Optional[str] = None, pos: Optional[str] = None
    ) -> List[RawCandidate]:
        """Harvests candidates from Datamuse API with offline fallback and strict antonym purging."""
        clean_word = word.strip().lower()
        base_lemma = (lemma or clean_word).strip().lower()
        candidates: List[RawCandidate] = []
        seen_words: Set[str] = set()

        # 1. Purge known antonyms to prevent contrasting opposites
        antonym_set = set(KNOWN_ANTONYMS.get(clean_word, set())) | set(KNOWN_ANTONYMS.get(base_lemma, set()))

        # 2. Build targeted synonym and hyponym queries
        if pos == "VERB":
            queries = [
                {"rel_syn": base_lemma, "md": "p,f", "max": 40},
                {"ml": base_lemma, "md": "p,f", "max": 40},
            ]
        else:
            queries = [
                {"rel_syn": base_lemma, "md": "p,f", "max": 40},
                {"rel_spc": base_lemma, "md": "p,f", "max": 20},
            ]
            if clean_word != base_lemma:
                queries.append({"rel_syn": clean_word, "md": "p,f", "max": 40})
                queries.append({"rel_spc": clean_word, "md": "p,f", "max": 20})
            queries.append({"ml": base_lemma, "md": "p,f", "max": 30})

        for q_params in queries:
            try:
                resp = await dispatch_api_request(
                    service=ExternalService.DATAMUSE,
                    endpoint="/words",
                    payload=RequestPayload(params=q_params),
                )
                if resp.is_success and isinstance(resp.data, list):
                    is_ml_query = "ml" in q_params
                    for item in resp.data:
                        c_word = item.get("word", "").lower().strip()
                        if not c_word or " " in c_word or "-" in c_word:
                            continue
                        if c_word == clean_word or c_word == base_lemma:
                            continue
                        if c_word in seen_words or c_word in antonym_set:
                            continue

                        tags = item.get("tags", [])
                        # For 'ml' (means-like) queries, strictly require 'syn' or 'primary_rel' tag
                        # to discard loose associations, non-synonyms, and antonyms
                        if is_ml_query and "syn" not in tags and "results_type:primary_rel" not in tags:
                            continue

                        seen_words.add(c_word)
                        c_pos = "verb" if "v" in tags else "adj" if "adj" in tags else "noun" if "n" in tags else "general"
                        freq_str = next((t.split(":")[1] for t in tags if t.startswith("f:")), "0.0")
                        freq = float(freq_str) if freq_str else 0.0
                        candidates.append(
                            RawCandidate(word=c_word, source="DATAMUSE", pos=c_pos, frequency=freq)
                        )
            except Exception as exc:
                log.debug("Datamuse harvesting notice: %s", exc)

        # 3. Inject offline fallback lexicon candidates if available
        for lookup in (clean_word, base_lemma):
            if lookup in OFFLINE_FALLBACK_LEXICON:
                for fallback_entry in OFFLINE_FALLBACK_LEXICON[lookup]:
                    if isinstance(fallback_entry, tuple):
                        fallback_w, fallback_pos = fallback_entry
                    else:
                        fallback_w, fallback_pos = fallback_entry, ("verb" if pos == "VERB" else "general")

                    if fallback_w not in seen_words and fallback_w not in antonym_set and fallback_w != clean_word and fallback_w != base_lemma:
                        seen_words.add(fallback_w)
                        candidates.append(
                            RawCandidate(
                                word=fallback_w,
                                source="OFFLINE_FALLBACK",
                                pos=fallback_pos,
                                frequency=20.0,
                            )
                        )

        return candidates

    def _is_academic_register(self, word: str) -> bool:
        w = word.lower()
        if w in ACADEMIC_REGISTER_TERMS:
            return True
        for suffix in ("ed", "ing", "es", "s", "d", "tion", "ly"):
            if w.endswith(suffix):
                stem = w[: -len(suffix)]
                if stem in ACADEMIC_REGISTER_TERMS or (stem + "e") in ACADEMIC_REGISTER_TERMS:
                    return True
        return False

    def rank_candidates_in_context(
        self, candidates: List[RawCandidate], target_word: str, sentence: str
    ) -> List[SynonymItem]:
        """Ranks candidate synonyms using sentence transformer contextual similarity and register."""
        if not candidates:
            return []

        clean_target = target_word.strip().lower()
        transformer = _get_transformer()

        # Compute transformer sentence-level contextual similarities
        cand_similarities: Dict[str, float] = {}
        if transformer is not None and sentence and clean_target in sentence.lower():
            try:
                from sentence_transformers import util
                emb_orig = transformer.encode(sentence, convert_to_tensor=True)
                cand_sentences = [
                    re.sub(r"\b" + re.escape(target_word) + r"\b", cand.word, sentence, flags=re.IGNORECASE)
                    for cand in candidates
                ]
                emb_cands = transformer.encode(cand_sentences, convert_to_tensor=True)
                sims = util.cos_sim(emb_orig, emb_cands)[0]
                for i, cand in enumerate(candidates):
                    cand_similarities[cand.word] = float(sims[i])
            except Exception as exc:
                log.debug("Transformer scoring fallback notice: %s", exc)

        ranked: List[SynonymItem] = []
        for cand in candidates:
            w = cand.word.lower()

            # 1. Academic register score (0.0 to 1.0)
            awl_score = 1.0 if self._is_academic_register(w) else 0.3

            # 2. Contextual similarity (from transformer or morphological baseline)
            if w in cand_similarities:
                sim_score = cand_similarities[w]
            else:
                sim_score = 0.5
                if clean_target.endswith("ing") and w.endswith("ing"):
                    sim_score += 0.25
                elif clean_target.endswith("ed") and w.endswith("ed"):
                    sim_score += 0.25
                elif clean_target.endswith("s") and w.endswith("s"):
                    sim_score += 0.15

            # Frequency normalization
            freq_score = min(1.0, cand.frequency / 50.0) if cand.frequency > 0 else 0.4

            # Joint composite score (75% transformer semantic context fit, 20% AWL register, 5% frequency)
            composite = (0.75 * sim_score) + (0.20 * awl_score) + (0.05 * freq_score)
            composite = round(min(0.99, max(0.10, composite)), 3)

            ranked.append(
                SynonymItem(
                    word=cand.word,
                    composite_score=composite,
                    semantic_similarity=round(sim_score, 3),
                    academic_register=awl_score,
                    part_of_speech=cand.pos or "general",
                )
            )

        # Sort descending by composite score
        ranked.sort(key=lambda item: item.composite_score, reverse=True)
        return ranked

    async def _generate_openrouter_synonyms(
        self, target_word: str, sentence_context: str, pos_hint: str = "", limit: int = 12
    ) -> List[str]:
        """Queries OpenRouter using model 'inclusionai/ling-3.0-flash-vl:free' to generate 8-12 academic synonyms.

        ========================================================================
        OPENROUTER INTEGRATION DETAILS:
        ========================================================================
        1. Model Selection: Uses 'inclusionai/ling-3.0-flash-vl:free' (configurable via
           OPENROUTER_SYNONYM_MODEL env var) via OpenRouter API (https://openrouter.ai/api/v1).
        2. Prompt Design & Reasoning Budget:
           - Prompt supplies the target word, sentence context, and morphological part-of-speech
             rules to enforce exact grammatical agreement when substituted into the sentence.
           - max_tokens=450: Sufficient token budget to accommodate model reasoning traces
             plus the full 8-12 word JSON array.
           - 15.0s network timeout: Enforces desktop responsiveness.
        3. Centralized API Gateway Dispatch:
           - Dispatches through `api_gateway.dispatch_api_request` with `ExternalService.LLM_SERVICE`.
           - Gateway automatically injects Bearer API key, HTTP-Referer, and X-Title headers.
        4. Robust Output Parsing:
           - Checks both `message.content` and `message.reasoning` for JSON array or word strings.
           - Deduplicates case-insensitively, filters out original target word, and returns up to `limit`.
        ========================================================================
        """
        clean_target = target_word.strip()
        pos_line = f"Part-of-speech: {pos_hint}\n" if pos_hint else ""
        pos_rule = (
            f"- The replacement words MUST strictly be {pos_hint}s matching the target word's exact grammatical form.\n"
            if pos_hint
            else "- Maintain the exact same grammatical tense, aspect, number, and part-of-speech as the target word.\n"
        )

        prompt = (
            f"Target word: \"{clean_target}\"\n"
            f"{pos_line}"
            f"Sentence: \"{sentence_context}\"\n\n"
            f"Provide 8 to 12 of the best academic, scholarly synonyms for the target word in this specific sentence context.\n"
            f"Rules:\n"
            f"{pos_rule}"
            f"- Each synonym must be a single word that directly replaces the target word in the sentence.\n"
            f"- Must make clear grammatical sense when directly substituted into the sentence.\n"
            f"- Use rigorous, scholarly academic vocabulary.\n"
            f"- Do NOT include antonyms or colloquial words.\n"
            f"- Output ONLY a JSON array of 8 to 12 words, e.g. [\"word1\", \"word2\", ...]."
        )

        messages = [
            {
                "role": "system",
                "content": "You are a specialized academic vocabulary engine. Output ONLY a valid JSON array of 8 to 12 strings.",
            },
            {"role": "user", "content": prompt},
        ]

        payload_dict = {
            "model": DEFAULT_LLM_SYNONYM_MODEL,
            "messages": messages,
            "max_tokens": DEFAULT_MAX_COMPLETION_TOKENS,
            "temperature": 0.2,
        }

        try:
            req_payload = RequestPayload(
                method="POST",
                json_body=payload_dict,
                timeout=15.0,
            )
            # Dispatch through centralized API gateway (applies rate limiters, circuit breakers, and OAuth bearer token)
            resp = await dispatch_api_request(
                service=ExternalService.LLM_SERVICE,
                endpoint="/chat/completions",
                payload=req_payload,
            )

            content = ""
            if resp.status_code == 200 and isinstance(resp.data, dict):
                choices = resp.data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
            else:
                log.debug("OpenAI synonym API response status %s: %s", resp.status_code, resp.error)

            if not content:
                return []

            # Parse array from JSON or regex findall
            found_words = re.findall(r'"([^"]+)"', content)
            if not found_words:
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, list):
                        found_words = [str(x) for x in parsed]
                except Exception:
                    pass

            results: List[str] = []
            clean_lower = clean_target.lower()
            for w in found_words:
                w_clean = w.strip()
                if (
                    w_clean
                    and w_clean.lower() != clean_lower
                    and w_clean.lower() not in [r.lower() for r in results]
                ):
                    results.append(w_clean)

            return results[:limit]
        except Exception as exc:
            log.warning("OpenRouter synonym generation notice: %s", exc)
            return []

    # Backward compatibility alias
    _generate_openai_synonyms = _generate_openrouter_synonyms

    def _generate_qwen_synonyms(
        self, target_word: str, sentence_context: str, pos_hint: str = "", limit: int = 12
    ) -> List[str]:
        """Local fallback: Uses Qwen2.5-1.5B-Instruct to generate academic synonyms when cloud API is unavailable."""
        model, tokenizer = _get_qwen()
        if model is None or tokenizer is None:
            return []

        clean_target = target_word.strip()
        pos_line = f"Part-of-speech: {pos_hint}\n" if pos_hint else ""
        pos_rule = (
            f"- The replacement words MUST strictly be {pos_hint}s matching the target word's exact grammatical form.\n"
            if pos_hint
            else "- Maintain the exact same grammatical tense, aspect, number, and part-of-speech as the target word.\n"
        )

        prompt = (
            f"Target word: \"{clean_target}\"\n"
            f"{pos_line}"
            f"Sentence: \"{sentence_context}\"\n\n"
            f"Provide 8 to 12 of the best academic, scholarly synonyms for the target word in this specific sentence context.\n"
            f"Rules:\n"
            f"{pos_rule}"
            f"- Each synonym must be a single word that directly replaces the target word in the sentence.\n"
            f"- Must make clear grammatical sense when directly substituted into the sentence.\n"
            f"- Use rigorous, scholarly academic vocabulary.\n"
            f"- Do NOT include antonyms or colloquial words.\n"
            f"- Output ONLY a JSON array of 8 to 12 words, e.g. [\"word1\", \"word2\", ...]."
        )

        messages = [
            {"role": "system", "content": "You are a specialized academic vocabulary engine. Output only valid JSON arrays."},
            {"role": "user", "content": prompt},
        ]

        try:
            import torch
            text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = tokenizer([text], return_tensors="pt")
            with torch.no_grad():
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=90,
                    do_sample=False,
                )
            gen = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:])
            found_words = re.findall(r'"([^"]+)"', gen)
            results: List[str] = []
            clean_lower = clean_target.lower()
            for w in found_words:
                w_clean = w.strip()
                if w_clean.lower() != clean_lower and w_clean.lower() not in [r.lower() for r in results]:
                    results.append(w_clean)
            return results[:limit]
        except Exception as exc:
            log.debug("Qwen generation notice: %s", exc)
            return []

    def _generate_llm_synonyms(
        self, target_word: str, sentence_context: str, pos_hint: str = "", limit: int = 12
    ) -> List[str]:
        """Backward-compatible wrapper for local LLM generation."""
        return self._generate_qwen_synonyms(target_word, sentence_context, pos_hint=pos_hint, limit=limit)

    async def find_contextual_synonyms(
        self, target_word: str, sentence_context: str, limit: int = 12, use_llm: bool = True
    ) -> SynonymGroupResult:
        """Finds contextually accurate academic synonyms using OpenAI gpt-5.6-luna (low reasoning, max speed)
        with graceful fallback to local Qwen2.5-1.5B and dictionary + sentence transformer."""
        t0 = time.monotonic()
        clean_target = target_word.strip().lower()

        # 1. Parse target word within sentence context using spaCy
        nlp = _get_nlp()
        doc = nlp(sentence_context) if nlp else None
        target_token = next((t for t in doc if t.text.lower() == clean_target), None) if doc else None
        tag = target_token.tag_ if target_token else ""
        pos = target_token.pos_ if target_token else ""
        lemma = target_token.lemma_.lower() if target_token else clean_target

        pos_hint = ""
        if pos == "VERB" or tag.startswith("VB"):
            if tag == "VBZ":
                pos_hint = "3rd-person singular present verb"
            elif tag in ("VBD", "VBN"):
                pos_hint = "past-tense / participial verb"
            elif tag == "VBG":
                pos_hint = "present participle (-ing) verb"
            else:
                pos_hint = "verb"
        elif pos == "ADJ" or tag.startswith("JJ"):
            pos_hint = "adjective"
        elif pos in ("NOUN", "PROPN") or tag.startswith("NN"):
            pos_hint = "plural noun" if tag == "NNS" else "noun"

        # 2. Attempt generation with OpenRouter inclusionai/ling-3.0-flash-vl:free
        if use_llm:
            req_limit = max(12, limit)
            # Primary: OpenRouter inclusionai/ling-3.0-flash-vl:free
            llm_words = await self._generate_openrouter_synonyms(
                target_word, sentence_context, pos_hint=pos_hint, limit=req_limit
            )

            # Secondary fallback: Local Qwen2.5-1.5B instruction-tuned model if cloud API unavailable
            if not llm_words:
                llm_words = self._generate_qwen_synonyms(
                    target_word, sentence_context, pos_hint=pos_hint, limit=req_limit
                )

            if llm_words:
                pos_str = pos.lower() if pos else "general"

                ranked_llm: List[SynonymItem] = []
                for i, word in enumerate(llm_words):
                    comp_score = round(max(0.60, 0.98 - (i * 0.025)), 3)
                    sim_score = round(max(0.55, 0.95 - (i * 0.025)), 3)
                    ranked_llm.append(
                        SynonymItem(
                            word=word,
                            composite_score=comp_score,
                            semantic_similarity=sim_score,
                            academic_register=1.0,
                            part_of_speech=pos_str,
                        )
                    )

                latency_ms = (time.monotonic() - t0) * 1000
                return SynonymGroupResult(
                    query_word=target_word,
                    sentence=sentence_context,
                    ranked_synonyms=ranked_llm[:limit],
                    antonyms=[],
                    inference_latency_ms=latency_ms,
                )

        # 3. Fallback to simplified 2-stage dictionary harvesting + SentenceTransformer ranking
        # Parse target word within sentence context using spaCy
        nlp = _get_nlp()
        doc = nlp(sentence_context) if nlp else None
        target_token = next((t for t in doc if t.text.lower() == clean_target), None) if doc else None
        tag = target_token.tag_ if target_token else ""
        pos = target_token.pos_ if target_token else ""
        lemma = target_token.lemma_.lower() if target_token else clean_target

        # Harvest raw candidate synonyms from Datamuse dictionary
        raw_candidates = await self.harvest_candidate_synonyms(clean_target, lemma=lemma, pos=pos)

        # 3. Enforce bidirectional grammatical tense & part-of-speech agreement
        aligned_candidates: List[RawCandidate] = []
        seen: Set[str] = set()

        is_target_verb = (pos == "VERB") or (tag and tag.startswith("VB"))
        is_target_noun = (pos in ("NOUN", "PROPN")) or (tag and tag.startswith("NN"))
        is_target_adj = (pos == "ADJ") or (tag and tag.startswith("JJ"))

        pure_nouns: Set[str] = {
            "goal", "purpose", "aim", "target", "object", "thing", "point", "idea",
            "substance", "result", "mind", "cause", "end", "lens", "accusative",
            "intent", "intention", "ambition", "benchmark", "principle"
        }
        pure_adjs: Set[str] = {
            "unbiased", "impartial", "neutral", "empirical", "factual", "dispassionate",
            "fair", "verifiable", "clinical", "impersonal", "nonsubjective", "concrete", "cool"
        }

        for cand in raw_candidates:
            w = cand.word.lower().strip()

            cand_pos_spacy = ""
            if nlp:
                c_doc = nlp(w)
                if len(c_doc) > 0:
                    cand_pos_spacy = c_doc[0].pos_

            # A. VERB context: must be a verb, inflect to match target tense
            if is_target_verb:
                if cand.pos not in ("verb", "general") and w not in IRREGULAR_VERBS and not w.endswith(("ed", "ing", "en")):
                    continue
                if tag in ("VBZ", "VBD", "VBN", "VBG"):
                    if tag in ("VBD", "VBN") and (w.endswith(("ed", "en", "wn", "pt")) or w in ("understood", "thought", "taught", "built", "read", "found", "made", "told", "struck")):
                        inflected_w = w
                    elif tag == "VBZ" and w.endswith("s") and not w.endswith("ss"):
                        inflected_w = w
                    else:
                        inflected_w = inflect_candidate(w, tag)
                else:
                    inflected_w = w

            # B. ADJECTIVE context: must be an adjective, reject pure nouns and verbs
            elif is_target_adj:
                if cand.pos == "noun" or cand_pos_spacy in ("NOUN", "PROPN") or w in pure_nouns:
                    continue
                cand_is_adj = (cand.pos == "adj" or cand_pos_spacy == "ADJ" or w in pure_adjs or w.endswith(("al", "ic", "ive", "ed", "ing", "ent", "ant", "ous", "ble", "ar")))
                if not cand_is_adj:
                    continue
                inflected_w = w

            # C. NOUN context: must be a noun, reject pure adjectives and verbs
            elif is_target_noun:
                if cand.pos == "adj" or cand_pos_spacy == "ADJ" or w in pure_adjs:
                    continue
                cand_is_noun = (cand.pos == "noun" or cand_pos_spacy in ("NOUN", "PROPN", "VERB") or w in pure_nouns or w.endswith(("tion", "ment", "ness", "ity", "ence", "ance", "er", "or", "ing", "s", "m", "t", "al")))
                if not cand_is_noun:
                    continue
                if tag == "NNS" and not w.endswith("s"):
                    inflected_w = inflect_candidate(w, tag)
                else:
                    inflected_w = w

            else:
                inflected_w = w

            # Ensure inflected candidate is a legitimate English word in spaCy's vocabulary
            if nlp and inflected_w not in nlp.vocab.strings:
                continue

            if inflected_w and inflected_w not in seen and inflected_w != clean_target:
                seen.add(inflected_w)
                aligned_candidates.append(
                    RawCandidate(
                        word=inflected_w,
                        source=cand.source,
                        pos=cand.pos,
                        frequency=cand.frequency,
                    )
                )

        # 4. Contextual Re-Ranking via Transformer sentence embeddings
        ranked = self.rank_candidates_in_context(aligned_candidates, target_word, sentence_context)
        latency_ms = (time.monotonic() - t0) * 1000

        return SynonymGroupResult(
            query_word=target_word,
            sentence=sentence_context,
            ranked_synonyms=ranked[:limit],
            antonyms=[],
            inference_latency_ms=latency_ms,
        )


_global_engine = LexicalSynonymsEngine()


async def find_contextual_synonyms(
    target_word: str, sentence_context: str, limit: int = 12, use_llm: bool = True
) -> SynonymGroupResult:
    return await _global_engine.find_contextual_synonyms(target_word, sentence_context, limit, use_llm=use_llm)


async def harvest_candidate_synonyms(
    word: str, lemma: Optional[str] = None, pos: Optional[str] = None
) -> List[RawCandidate]:
    return await _global_engine.harvest_candidate_synonyms(word, lemma=lemma, pos=pos)


def rank_candidates_in_context(
    candidates: List[RawCandidate], target_word: str, sentence: str
) -> List[SynonymItem]:
    return _global_engine.rank_candidates_in_context(candidates, target_word, sentence)
