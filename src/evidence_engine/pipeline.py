"""Evidence Engine v2 — pipeline orchestration and public API.

Implements the funnel from README section 3:

  Stage 0  claim normalization + dual query synthesis      (~0.1 ms)
  Stage 1  federated retrieval fan-out (sources.py)        (≤2.5 s cap)
  Stage 2  passage assembly (sources.py)                   (~0.1 s)
  Stage 3  rule-based filtering: BM25 + anchors + RRF + MMR (~0.3 s) -> 40
  Stage 4  NLI stance gate (nli.py), batched               (≤2.0 s cap) -> 20-25
  ---- pre-LLM SLA: 10 s ----------------------------------------------
  Stage 5  LLM curation -> 10 (NOT implemented here; see README section 15.
           Until Stage 5 lands, supports()/opposes() return the NLI-curated
           top 10 with llm_curated=False, which is still fully useful.)

Public API: supports(text), opposes(text) -> EvidenceResult.
The deadline ladder (README section 9) guarantees a return: every stage has a
cap; the final answer falls back to rules-stage ranking, then lexical stance.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections import defaultdict
from typing import Dict, List, Optional

from evidence_engine import models as m
from evidence_engine import nli, sources

log = logging.getLogger("evidence_engine")

# ------------------------------------------------------------------ tuning
MIN_WORDS, MAX_WORDS = 4, 30
STAGE1_DEADLINE_S = 6.0      # federated fan-out hard cap (raised from 4.0:
                             # S2's shared anonymous pool sometimes needs 3-5 s
                             # per call; a tighter deadline cancelled the retry
                             # before it could fire. Worst case 6 + 0.1 + 2.5
                             # still fits the 10 s pre-LLM SLA)
STAGE4_CAP_S = 3.5           # NLI batch cap (premise head-truncation keeps
                             # sequences ~100 tokens; worst case 6.0 retrieval
                             # + 0.1 assembly + 3.5 NLI = 9.6 s still fits the
                             # 10 s pre-LLM SLA)
PRE_LLM_SLA_S = 10.0         # overall pre-LLM SLA
RULES_TARGET = 40            # Stage 3 output
NLI_TARGET = 24              # Stage 4 output (20-25 per spec)
FINAL_N = 10                 # delivered items
PER_PAPER_CAP = 3
RRF_K = 60
MMR_LAMBDA = 0.72

_HEDGES = re.compile(
    r"\b(may|might|could|suggest\w*|appear\w*|possible|potentially|preliminary|"
    r"under certain|in some contexts|modest|limited to|in mice|in rats|in vitro|"
    r"in older adults|in patients with|in subgroups?|at low doses?|at high doses?)\b",
    re.IGNORECASE,
)

# ------------------------------------------------------------------ Stage 0

_STOP = set(
    "a an and are as at be been by for from has have in into is it its of on or "
    "that the their this to was were which with without across between during "
    "than then these those there does do did not no can could may might will "
    "would should our we our you your they them he she his her".split()
)

_CUE_NEG = {
    "adverse", "impairs", "impaired", "reduces", "reduced", "inhibits",
    "inhibited", "worsens", "worsened", "toxic", "toxicity", "risk", "harmful",
    "negative", "decline", "declines", "deficit", "deficits", "ineffective",
}
_CUE_POS = {
    "improves", "improved", "enhances", "enhanced", "increases", "increased",
    "promotes", "promoted", "beneficial", "effective", "efficacy", "protective",
    "accelerates", "boosts", "strengthens", "positive",
}


class ClaimParts:
    """Stage 0 output: normalized claim + query variants.

    claim_type: "prevalence" claims assert dominance/ubiquity ("MLP is the
    dominant choice for IK") and are stance-classified by a consistency
    policy, not raw NLI entailment; "causal" claims ("X improves Y") use the
    standard NLI gate. Outcome vs cause terms: entities after the effect verb
    (causal) or after the dominance predicate (prevalence) are outcome terms;
    the rest are cause terms. Evidence for/against a claim must speak to its
    OUTCOME — a sentence about exercise improving walking speed is not
    counter-evidence for a sleep claim even though it shares cause terms
    (live-verified failure mode).
    """

    __slots__ = ("claim", "entities", "effect_terms", "cause_terms",
                 "outcome_terms", "claim_type", "affirmative", "counter")

    def __init__(self, claim: str, entities: List[str], effect_terms: List[str]) -> None:
        self.claim = claim
        self.entities = entities
        self.effect_terms = effect_terms
        low = claim.lower()
        self.claim_type = "prevalence" if _PREVALENCE_RX.search(claim) else "causal"
        if self.claim_type == "prevalence":
            # "APPROACH is the dominant choice FOR <problem domain>": outcome
            # terms come from the post-"for" phrase (the problem domain), not
            # from post-predicate position (which would sweep in approach
            # words like "learning" — live-verified pollution).
            for_pos = low.rfind(" for ")
            cut = for_pos if for_pos >= 0 else (
                (_PREVALENCE_RX.search(claim).end()))
        else:
            first_effect = min((low.find(e) for e in effect_terms if low.find(e) >= 0),
                               default=len(low))
            cut = first_effect
        before = [e for e in entities if low.find(e) < cut]
        after = [e for e in entities if low.find(e) >= cut]
        self.cause_terms = before
        self.outcome_terms = after
        self.affirmative = " ".join(entities + effect_terms) or claim
        self.counter = " ".join(entities + list(_CUE_NEG)[:4]) if entities else claim

    def variants(self) -> List[str]:
        """Six query variants: affirmative x2, counter x2, entity-only, quoted."""
        v = [self.affirmative, self.affirmative, self.counter, self.counter,
             " ".join(self.entities) or self.claim]
        v.append(self.claim)  # natural-language variant (OpenAlex `search` likes it)
        return v


def normalize_claim(text: str) -> ClaimParts:
    """Stage 0: validate 4-30 words, strip hedges, extract entities + effects."""
    text = (text or "").strip()
    words = text.split()
    if not (MIN_WORDS <= len(words) <= MAX_WORDS):
        raise m.InvalidClaimError(
            f"claim must be {MIN_WORDS}-{MAX_WORDS} words, got {len(words)}"
        )
    tokens = re.findall(r"[A-Za-z][A-Za-z-]*|\d+", text)
    content = [t for t in tokens if t.lower() not in _STOP]
    entities: List[str] = []
    effect_terms: List[str] = []
    for tok in content:
        low = tok.lower()
        if low in _GENERIC_TERMS or _PREVALENCE_RX.fullmatch(low):
            continue  # predicates and generic nouns are not approach/problem terms
        if low in _CUE_NEG:
            effect_terms.append(low)
        elif low in _CUE_POS:
            effect_terms.append(low)
        else:
            entities.append(low)

    # Entity priority: capitalized/numeric tokens first (proper nouns, doses,
    # genes), then by length. All content words are eligible — single-char
    # tokens like "D" (vitamin D) and mid-length words like "sleep" must not
    # be dropped, or topical-overlap guarding in Stage 4 breaks (fix from
    # live verification).
    def _prio(w: str) -> tuple:
        orig = next((t for t in content if t.lower() == w), w)
        return (0 if (orig[:1].isupper() or any(c.isdigit() for c in orig)) else 1,
                -len(w))

    entities = sorted(dict.fromkeys(entities), key=_prio)[:8]
    effect_terms = list(dict.fromkeys(effect_terms))[:4]
    if not entities:
        entities = content[:4]
    return ClaimParts(text, entities, effect_terms)


# ------------------------------------------------------------------ Stage 3

def _tokenize(s: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


class BM25:
    """BM25 Okapi (k1=1.5, b=0.75) over pre-tokenized docs — minimal inline
    implementation (rank_bm25 not in env; README section 16)."""

    def __init__(self, docs_tokens: List[List[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs = docs_tokens
        self.doc_len = [len(d) for d in docs_tokens]
        self.avgdl = (sum(self.doc_len) or 1) / max(1, len(docs_tokens))
        self.tf: List[Dict[str, int]] = []
        df: Dict[str, int] = defaultdict(int)
        for d in docs_tokens:
            counts: Dict[str, int] = defaultdict(int)
            for t in d:
                counts[t] += 1
            self.tf.append(counts)
            for t in counts:
                df[t] += 1
        n = len(docs_tokens)
        self.idf = {
            t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()
        }

    def scores(self, query_tokens: List[str]) -> List[float]:
        out = []
        for counts, dl in zip(self.tf, self.doc_len):
            s = 0.0
            for t in set(query_tokens):
                f = counts.get(t, 0)
                if not f:
                    continue
                idf = self.idf.get(t, 0.0)
                s += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            out.append(s)
        return out


def _topk(values: List[float], k: int) -> List[int]:
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=True)
    return [i for i in order if values[i] > 0][:k]


def _rrf(rankings: List[List[int]], k: int = RRF_K,
         weights: Optional[List[float]] = None) -> Dict[int, float]:
    """Reciprocal Rank Fusion over multiple ranked index lists (optionally
    weighted per ranking, e.g. to bias the candidate pool by stance mode)."""
    fused: Dict[int, float] = defaultdict(float)
    for i, ranking in enumerate(rankings):
        w = weights[i] if weights else 1.0
        for rank, idx in enumerate(ranking):
            fused[idx] += w / (k + rank + 1)
    return fused


def _anchor_score(sentence: str, parts: ClaimParts) -> tuple:
    """Lexical anchors: entity presence, numbers, effect verbs, result-verb
    boost, aim-sentence demotion (README 7.1)."""
    low = " " + sentence.lower() + " "
    matched = []
    score = 0.0
    for e in parts.entities:
        if e in low:
            matched.append(e)
            score += 1.0
    if re.search(r"\d", sentence):
        matched.append("has-number")
        score += 0.8
    for cue in parts.effect_terms:
        if cue in low:
            matched.append(cue)
            score += 0.6
    if _RESULT_RX.search(sentence):
        matched.append("result-verb")
        score += 0.6
    if _AIM_RX.search(sentence):
        matched.append("aim-demotion")
        score -= 1.2
    if _CUE_DEMOTE.search(sentence):
        matched.append("boilerplate")
        score -= 1.0
    return round(score, 3), tuple(matched)


_CUE_DEMOTE = re.compile(
    r"\b(we collected|were purchased|were obtained|ethical approval|"
    r"informed consent|acknowledg\w+|data availability|conflict of interest|"
    r"this (paper|study|article) (is|presents|describes) (organized|an overview))\b",
    re.IGNORECASE,
)

# Aim/objective sentences restate the claim's keywords (max BM25 overlap) but
# carry no evidence; result sentences state findings. Live verification showed
# aims crowding out conclusions from the 40-candidate pool, so Stage 3 demotes
# the former and boosts the latter (README section 7.1, cue-word priors).
_AIM_RX = re.compile(
    r"\b(this [a-z-]* ?(study|review|trial|paper|article|meta-analysis) (aimed|sought|was designed|examines|examined|summarizes|summarized|describes|presents|reviews|investigates)|"
    r"we (aimed|sought|hypothesized)|the (aim|purpose) of (this|the) (study|review|trial)|"
    r"(objective|objectives|aims?|purpose)\s*:|\b(aims?|aimed) to (determine|evaluate|assess|examine|investigate)\b)",
    re.IGNORECASE,
)
_RESULT_RX = re.compile(
    r"\b(improved|improves|reduced|reduces|increased|increases|decreased|decreases|"
    r"enhanced|enhances|attenuated|accelerated|lowered|outperformed|exceeded|"
    r"was associated with|were associated with|demonstrated|showed that|indicated that)\b",
    re.IGNORECASE,
)

# Prevalence/dominance claims ("X is the dominant choice for Y", "X is widely
# used for Y") are not causal claims: NLI entailment correctly refuses to let
# a single usage sentence prove prevalence, so the stance gate uses a
# claim-type-aware policy for them (see nli.py _prevalence_stance).
_PREVALENCE_RX = re.compile(
    r"\b(dominant|dominates|most (common|widely|popular|frequent|successful|suitable)|"
    r"widely (used|adopted|applied)|state-of-the-art|standard (choice|approach|method)|"
    r"preferred (choice|approach|method)|most prevalent|go-to|preeminent|prevalent)\b",
    re.IGNORECASE,
)

# Generic tokens that are neither approach nor problem terms; they pollute
# queries and topical guards. This list is deliberately broad for ML/engineering
# vocabulary (live-verified: "multilayer", "learning", "inverse" occur in most
# CS abstracts, so hitting them cannot establish topical identity — only
# approach-specific terms like "perceptron" or problem terms like
# "kinematics" can).
_GENERIC_TERMS = {
    "solutions", "solution", "choice", "approach", "approaches", "methods",
    "method", "based", "using", "domain", "problem", "field", "applications",
    "application", "systems", "system", "models", "model", "algorithms",
    "algorithm", "techniques", "technique", "strategies", "strategy",
    "learning", "neural", "network", "networks", "deep", "forward",
    "framework", "frameworks", "performance", "accuracy", "prediction",
    "predictions", "training", "design", "optimization", "regression",
    "error", "errors", "function", "functions", "results", "novel",
}


def rule_filter(sentences: List[m.CandidateSentence], parts: ClaimParts,
                mode: str = "supports") -> List[m.ScoredSentence]:
    """Stage 3: BM25 (both variants) + anchors -> weighted RRF -> MMR diversity.

    Mode-weighted fusion (live-verification fix): a symmetric fusion lets the
    counter query dominate the candidate pool, starving supports() of
    entailment candidates. Weights bias the pool toward the requested stance
    while keeping the other stream present for honest classification.
    """
    if not sentences:
        return []
    toks = [_tokenize(s.text) for s in sentences]
    bm25_aff = BM25(toks).scores(_tokenize(parts.affirmative))
    bm25_ctr = BM25(toks).scores(_tokenize(parts.counter))
    w_aff, w_ctr = (1.0, 0.6) if mode == "supports" else (0.7, 1.0)

    fused = _rrf([
        _topk(bm25_aff, 100), _topk(bm25_ctr, 100),
        # anchor prior as a ranking signal too
        _topk([_anchor_score(s.text, parts)[0] for s in sentences], 100),
    ], weights=(w_aff, w_ctr, 0.8))
    ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[: 3 * RULES_TARGET]

    # MMR: greedy diversity over token-set Jaccard, per-paper cap.
    chosen: List[int] = []
    chosen_sets: List[set] = []
    per_paper: Dict[str, int] = defaultdict(int)
    for idx, _score in ranked:
        s = sentences[idx]
        paper_key = s.paper.doi or s.paper.title
        if per_paper[paper_key] >= PER_PAPER_CAP:
            continue
        toks_set = set(toks[idx])
        if chosen_sets:
            max_sim = max(
                len(toks_set & c) / max(1, len(toks_set | c)) for c in chosen_sets
            )
            if max_sim > 1.0 - MMR_LAMBDA:  # too similar to something chosen
                continue
        chosen.append(idx)
        chosen_sets.append(toks_set)
        per_paper[paper_key] += 1
        if len(chosen) >= RULES_TARGET:
            break

    out = []
    for idx in chosen:
        a_score, anchors = _anchor_score(sentences[idx].text, parts)
        out.append(m.ScoredSentence(
            candidate=sentences[idx], rrf_score=round(fused[idx], 6),
            anchor_score=a_score, matched_anchors=anchors,
        ))
    return out


# ------------------------------------------------------------------ Stage 4

def _apply_hedge_limits(scored: List[m.StanceScoredSentence]) -> List[m.StanceScoredSentence]:
    """Re-tag heavy-hedged entailments as LIMITS (boundary evidence)."""
    out = []
    for s in scored:
        if s.stance is m.Stance.SUPPORTS and _HEDGES.search(s.scored.candidate.text):
            out.append(m.StanceScoredSentence(
                scored=s.scored, p_entail=s.p_entail, p_contradict=s.p_contradict,
                p_neutral=s.p_neutral, stance=m.Stance.LIMITS, nli_model=s.nli_model,
            ))
        else:
            out.append(s)
    return out


def nli_gate(parts: ClaimParts, scored: List[m.ScoredSentence], mode: str,
             cap_s: float) -> tuple[List[m.StanceScoredSentence], bool, Optional[str]]:
    """Stage 4: batched NLI stance scoring with a hard cap.

    Returns (items, used_real_nli, degraded_reason). Degraded reasons:
    backend still warming up, stage timeout, or permanent lexical fallback.
    """
    t0 = time.perf_counter()
    if not scored:
        return [], False, None
    # Bounded wait for the import-time prewarm (first call after app start).
    # Waiting the full load inside the SLA would blow the cap; a short wait
    # keeps first-call latency honest and degrades cleanly instead.
    if nli.backend_name() == "unloaded":
        nli.wait_until_ready(timeout_s=min(1.0, max(0.0, cap_s - 0.5)))
    real_model = nli.ensure_loaded() != "lexical-fallback"
    fail_reason: Optional[str] = None
    try:
        if real_model:
            verdicts = asyncio.run(
                asyncio.wait_for(
                    asyncio.to_thread(
                        nli.score, parts.claim, scored, mode,
                        topical_terms(parts), outcome_terms(parts),
                        parts.claim_type,
                    ),
                    timeout=cap_s,
                )
            )
        else:
            verdicts = None
            fail_reason = "NLI backend unavailable (lexical cues in use)"
    except Exception as exc:  # noqa: BLE001
        log.warning("NLI stage failed after %.2fs (cap %.2fs): %r",
                    time.perf_counter() - t0, cap_s, exc)
        verdicts = None
        fail_reason = f"NLI stage timeout/failure ({type(exc).__name__})"

    out: List[m.StanceScoredSentence] = []
    if verdicts is None:
        # Degraded path: cue-word stance labeling instead of flat UNVERIFIED so
        # the caller still receives usable (clearly-flagged) evidence.
        for s in scored:
            p_e, p_c, p_n, stance = nli.lexical_score(
                parts.claim, [s], mode)[0]
            out.append(m.StanceScoredSentence(
                scored=s, p_entail=p_e, p_contradict=p_c, p_neutral=p_n,
                stance=stance, nli_model="lexical-cues",
            ))
        return out, False, fail_reason

    for s, (p_e, p_c, p_n, stance) in zip(scored, verdicts):
        out.append(m.StanceScoredSentence(
            scored=s, p_entail=p_e, p_contradict=p_c, p_neutral=p_n,
            stance=stance, nli_model=nli.backend_name(),
        ))
    out = _apply_hedge_limits(out)

    # Selection objective differs by mode (README section 8.1).
    out.sort(key=_selection_key(mode))
    return out[:NLI_TARGET], True, None


def _selection_key(mode: str):
    """Stage-4 selection objective (README 8.1): rank stance buckets first,
    then NLI probability blended with the rules-stage fusion score."""
    if mode == "supports":
        return lambda x: (0 if x.stance is m.Stance.SUPPORTS else
                          1 if x.stance is m.Stance.LIMITS else
                          2 if x.stance is m.Stance.OPPOSES else 3,
                          -(x.p_entail + 0.3 * x.scored.rrf_score))
    # opposes: contradictions first, then limits/boundary evidence
    return lambda x: (0 if x.stance is m.Stance.OPPOSES else
                      1 if x.stance is m.Stance.LIMITS else
                      2 if x.stance is m.Stance.SUPPORTS else 3,
                      -(x.p_contradict + 0.3 * x.scored.rrf_score))


# ------------------------------------------------------------------ Assembly

# Population words are not topical: "older adults" appears in half the
# biomedical corpus, so overlap on them cannot establish topic identity.
_POPULATION_WORDS = {
    "older", "adults", "adult", "people", "patients", "men", "women",
    "children", "adolescents", "students", "individuals", "elderly",
    "participants", "persons", "youth",
}


def topical_terms(parts: "ClaimParts") -> List[str]:
    """Stage-0 cause+outcome terms that identify the claim's topic (population
    and generic words excluded; consumed by the Stage-4 topical guard)."""
    keep = [e for e in parts.entities
            if e not in _POPULATION_WORDS and e not in _GENERIC_TERMS]
    return keep


def outcome_terms(parts: "ClaimParts") -> List[str]:
    """Claim outcome terms (post-verb/post-predicate, population words and
    generic words excluded)."""
    return [e for e in parts.outcome_terms
            if e not in _POPULATION_WORDS and e not in _GENERIC_TERMS]


def _to_item(s: m.StanceScoredSentence, mode: str) -> m.EvidenceItem:
    paper = s.scored.candidate.paper
    return m.EvidenceItem(
        quote=s.scored.candidate.text,
        paper=paper,
        stance=s.stance,
        stance_probs={
            "entail": round(s.p_entail, 4), "contradict": round(s.p_contradict, 4),
            "neutral": round(s.p_neutral, 4),
        },
        relevance_score=round(s.scored.rrf_score, 6),
        nli_model=s.nli_model,
        in_body=s.scored.candidate.in_body,
        checks={
            "doi_format": bool(paper.doi and paper.doi.startswith("10.")),
            "retracted": False,   # Stage 5 / future: Retraction Watch lookup
            "llm_curated": False,  # Stage 5 pending (README section 15)
            "quote_verbatim": True,  # quotes are copied verbatim by construction
        },
        rationale=None,
    )


# ------------------------------------------------------------------ Orchestrator

def run_funnel(text: str, mode: str) -> m.EvidenceResult:
    """Execute the pre-LLM funnel. Synchronous public entrypoint."""
    t_start = time.perf_counter()
    timings: Dict[str, float] = {}
    funnel: Dict[str, int] = {}

    # Stage 0
    t0 = time.perf_counter()
    parts = normalize_claim(text)
    timings["stage0_normalize_ms"] = m._fmt_ms(t0)
    funnel["variants"] = len(parts.variants())

    # Stages 1+2 (async core)
    async def _async_core() -> tuple:
        papers, report = await sources.federated_retrieval(
            parts.variants(), per_source_limit=100, deadline_s=STAGE1_DEADLINE_S
        )
        funnel["papers_retrieved"] = len(papers)
        t1 = time.perf_counter()
        cands = sources.assemble_sentences(papers)
        timings["stage2_assemble_ms"] = m._fmt_ms(t1)
        return cands, report

    t1 = time.perf_counter()
    candidates, sources_report = asyncio.run(_async_core())
    timings["stage1_federated_ms"] = m._fmt_ms(t1)
    funnel["candidate_sentences"] = len(candidates)
    degraded = False
    degraded_reason = None
    ok_sources = [n for n, r in sources_report.items() if r["status"] == "ok"]
    if not ok_sources:
        degraded, degraded_reason = True, "all retrieval sources failed"

    # Stage 3
    t3 = time.perf_counter()
    scored = rule_filter(candidates, parts, mode=mode)
    timings["stage3_rules_ms"] = m._fmt_ms(t3)
    funnel["after_rules"] = len(scored)

    # Stage 4 (with global SLA awareness)
    t4 = time.perf_counter()
    elapsed = time.perf_counter() - t_start
    cap4 = min(STAGE4_CAP_S, max(0.2, PRE_LLM_SLA_S - elapsed))
    stance_scored, used_nli, nli_fail_reason = nli_gate(
        parts, scored, mode, cap_s=cap4)
    timings["stage4_nli_ms"] = m._fmt_ms(t4)
    funnel["after_nli"] = len(stance_scored)
    if not used_nli and not degraded:
        degraded = True
        degraded_reason = degraded_reason or nli_fail_reason

    wanted = (m.Stance.SUPPORTS, m.Stance.LIMITS) if mode == "supports" else (
        m.Stance.OPPOSES, m.Stance.LIMITS)

    def _eligible(lst: List[m.StanceScoredSentence]) -> List[m.StanceScoredSentence]:
        return [s for s in lst if s.stance in wanted]

    # SLA top-up (thin-pool fix): if the requested stance is thin and the SLA
    # has budget left, score the NEXT rules-stage chunk too — idle deadline
    # time becomes additional evidence instead of being wasted.
    if (used_nli and len(_eligible(stance_scored)) < FINAL_N
            and len(scored) > NLI_TARGET):
        remaining = PRE_LLM_SLA_S - (time.perf_counter() - t_start) - 0.6
        if remaining >= 1.2:
            extra, _, _ = nli_gate(
                parts, scored[NLI_TARGET:NLI_TARGET + 24], mode,
                cap_s=min(2.2, remaining))
            stance_scored = sorted(
                stance_scored + extra, key=_selection_key(mode)
            )[:NLI_TARGET + 12]
            funnel["after_nli_topup"] = len(stance_scored)

    # Interim selection (Stage 5 LLM pending). Stance-honest: supports() never
    # pads its 10 with contradictions (and vice versa) — if fewer than 10
    # eligible items exist, we return fewer. UNVERIFIED items (off-topic per
    # the nli.py guards) are excluded as well.
    eligible = _eligible(stance_scored)
    items = [_to_item(s, mode) for s in eligible[:FINAL_N]]

    total_ms = m._fmt_ms(t_start)
    meta = m.PipelineMeta(
        claim=parts.claim, mode=mode, query_variants=parts.variants(),
        funnel=funnel, stage_timings_ms=timings, sources_report=sources_report,
        nli_backend=nli.backend_name(), degraded=degraded,
        degraded_reason=degraded_reason, total_ms=total_ms,
    )
    return m.EvidenceResult(claim=parts.claim, mode=mode, items=items, pipeline_meta=meta)


# ------------------------------------------------------------------ Public API

def supports(text: str) -> m.EvidenceResult:
    """Return the 10 best pieces of peer-reviewed evidence SUPPORTING the claim.

    Input: 4-30 words. Raises InvalidClaimError outside that range.
    Pre-LLM SLA: 10 s (see README section 9). Stage 5 LLM curation pending.
    """
    return run_funnel(text, mode="supports")


def opposes(text: str) -> m.EvidenceResult:
    """Return the 10 best pieces of peer-reviewed evidence OPPOSING the claim."""
    return run_funnel(text, mode="opposes")
