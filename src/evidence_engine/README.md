# Evidence Engine v2 — `supports()` / `opposes()`

> **Status: PLANNING DOCUMENT (no code yet).**
> This document is the full architecture plan for a ground-up rewrite of `evidence_engine`.
> It was written after researching current (2026) academic search APIs, NLI models, and
> retrieval/reranking techniques. Sources are linked inline.

---

## 1. Mission

Two functions, one contract:

```python
def supports(text: str) -> EvidenceResult: ...
def opposes(text: str) -> EvidenceResult: ...
```

- `supports(text)` → the **10 best individual pieces of peer-reviewed evidence that back** the assertion in `text`.
- `opposes(text)` → the **10 best individual pieces of peer-reviewed evidence that contradict / weaken / bound** the assertion in `text`.

Input: **4–30 words** of plain text (a single assertive sentence). Anything shorter is rejected; anything longer is first decomposed into sentences and the caller picks one (or we run on the longest assertive sentence in v1).

A **piece of evidence** is *not* a paper. It is an **individual observation or conclusion sentence (or short passage) taken from a specific paper**, with verbatim quote + full citation. "10 pieces of evidence" therefore means we must see *inside* papers, not just rank papers.

---

## 2. The three hard constraints (and why they make this hard)

| # | Constraint | Why it's hard |
|---|------------|---------------|
| 1 | **Scan "hundreds" of research sources per call** | Realistically this means: fan out to 6–8 federated academic APIs and retrieve **hundreds of candidate papers/passages** per query (dozens of API calls' worth of results). No single API exposes hundreds of *sources*; we need parallel federated retrieval. |
| 2 | **Evidence must be sentence-level, stance-labeled** | Abstracts alone are usually insufficient ([firecrawl comparison](https://www.firecrawl.dev/blog/ai-agents-search-academic-papers): "an abstract tells you a paper is probably relevant; it rarely contains the result the agent needs to quote"). Stance (supports vs opposes) is a different signal than relevance — a paper can be highly relevant and neutral. |
| 3 | **Everything before the LLM in < 10 seconds**, on a **desktop CPU** | Cross-encoder NLI over hundreds of sentences at fp32 PyTorch speeds would take minutes. The 10 s budget forces: async parallel fan-out with hard per-source timeouts, ONNX int8 quantization, batching, aggressive funnel pruning, and multi-level caching. |

The user described the ask as "very unrealistic." It is achievable — but only as a **strict funnel with a per-stage latency budget** and graceful degradation. This document is that funnel.

---

## 3. Shape of the pipeline (the funnel)

```
                       ┌──────────────────────────────────────────────────────┐
 input (4–30 words)    │  STAGE 0 · Claim normalization + dual query synthesis │  ~100 ms
 ───────────────────►  │  1 affirmative query + 1 counter query + variants     │
                       └───────────────┬──────────────────────────────────────┘
                                       │  (6 query variants)
                       ┌───────────────▼──────────────────────────────────────┐
                       │  STAGE 1 · Federated retrieval fan-out (async)        │  ~1.5–2.5 s  (hard cap)
                       │  S2 search + S2 snippets · OpenAlex fulltext search   │
                       │  Europe PMC BODY: field search · arXiv/CORE fallback  │
                       │  → hundreds of papers → ~800–1,500 candidate sentences│
                       └───────────────┬──────────────────────────────────────┘
                                       │
                       ┌───────────────▼──────────────────────────────────────┐
                       │  STAGE 2 · Passage assembly                           │  ~100–200 ms
                       │  reconstruct OpenAlex inverted-index abstracts,       │
                       │  sentence-split, dedup (DOI+hash), attach metadata    │
                       └───────────────┬──────────────────────────────────────┘
                                       │  ~1,000 sentences
                       ┌───────────────▼──────────────────────────────────────┐
                       │  STAGE 3 · Rule-based candidate filtering  ──► 40     │  ~150–400 ms
                       │  BM25 Okapi + lexical anchor rules + cue-word priors  │
                       │  + Reciprocal Rank Fusion + MMR diversity             │
                       └───────────────┬──────────────────────────────────────┘
                                       │  40 sentences
                       ┌───────────────▼──────────────────────────────────────┐
                       │  STAGE 4 · NLI stance gate (NLP model)    ──► 25      │  ~0.4–1.2 s
                       │  DeBERTa-v3-small NLI cross-encoder, ONNX int8,       │
                       │  batched inference, entailed / contradicted / neutral │
                       └───────────────┬──────────────────────────────────────┘
                                       │  20–25 stance-scored sentences
                       ┌───────────────▼──────────────────────────────────────┐
                       │  STAGE 5 · LLM final curation             ──► 10      │  ~1.5–4 s (not in the 10 s budget)
                       │  rubric-based filter, verbatim quotes, dedup of       │
                       │  near-identical findings, per-paper cap, retraction   │
                       │  flags, JSON structured output                        │
                       └───────────────┬──────────────────────────────────────┘
                                       │
                                 EvidenceResult (10 EvidenceItems)
```

**Cumulative pre-LLM budget: target ≈ 2.5–4.5 s typical, p95 ≤ 8 s, hard SLA 10 s** (with the degradation ladder in §9).

---

## 4. Stage 0 — Claim normalization & dual query synthesis (~100 ms)

**Goal:** turn `text` into one *affirmative* query and one *counter* query, plus keyword variants, because both `supports()` and `opposes()` need to retrieve both stances and then **classify** — you cannot rely on the query to carry the stance (search engines match words, not intent).

**Rules (0 LLM tokens):**
1. Strip hedging ("may", "might", "suggests") → canonical assertive form.
2. Extract: entity terms (proper nouns, domain nouns via capitalization + stopword filtering), action/effect verbs ("improves", "causes", "impairs"), comparatives/quantifiers.
3. Affirmative query: entity + effect terms.
4. Counter query: entity terms + negation/reversal cues ("adverse", "no effect", "impairs", "contrary") — [Cochrane-style adverse-effect query patterns](https://www.ncbi.nlm.nih.gov/books/NBK494402/).
5. Variants: synonym expansion for top-2 entities only (small static map, no embeddings at this stage).
6. Emit **6 queries**: `{affirmative×2, counter×2, entity-only×1, quoted-title-fragments×1}`.

**Alternative designs considered:**
- **(A) Pure regex/stopword rules** ← *chosen for v1.* Deterministic, ~1 ms, debuggable.
- **(B) Tiny local keyphrase model** (e.g., KeyBERT-style with MiniLM embeddings). Better paraphrase coverage, +50–150 ms. Adopt in v2 if Stage 1 recall is poor.
- **(C) LLM query synthesis.** Best quality, violates the "0 LLM before Stage 5" principle and adds 0.5–2 s. Rejected.

**Validation:** reject < 4 or > 30 words with a typed `InvalidClaimError` (caller may then split).

---

## 5. Stage 1 — Federated retrieval fan-out (~1.5–2.5 s, hard cap)

### 5.1 What "hundreds of sources" means, concretely

Per call we touch **6–8 API endpoints** in parallel and pull **hundreds of candidate papers → ~800–1,500 candidate sentences**. The fan-out is the only way to make "hundreds of sources" fit in seconds; sequential calling cannot.

### 5.2 Source shortlist (researched Aug–Sep 2026)

| Source | Corpus | Why it's in | Limits / gotchas |
|---|---|---|---|
| **Semantic Scholar Graph API** | 214M papers, 2.49B citations, all fields | Best cross-domain coverage; **`/graph/v1/snippet/search` returns query-matched in-body snippets** from open-access papers — our single biggest lever for sentence-level evidence | Unauthenticated: shared pool of 1000 req/s across *all* anonymous users (bursty, unpredictable). With key: dedicated 1 req/s. Budget **≤ 2–3 calls** per request ([source](https://www.firecrawl.dev/blog/ai-agents-search-academic-papers), [S2 API docs](https://www.semanticscholar.org/product/api)) |
| **OpenAlex** | 240M+ works; **fulltext.search covers title+abstract+full text of ~57M documents** | Broadest index, `fulltext.search` filter finds papers *containing our phrasing in the body*, 100 req/s ceiling, DOI-first metadata | Abstracts arrive as an **inverted index** (word→positions dict) and must be reconstructed client-side. Free-key daily budget ≈ 1k keyword searches → gateway-disk-cache aggressively ([fulltext blog](https://blog.openalex.org/fulltext-search-in-openalex/), [docs](https://help.openalex.org/api/searching/)) |
| **Europe PMC** | 4M+ OA full texts, biomedical | **Lucene fielded search: `BODY:"..."`, `INTRO:`, `METHODS:`** — direct in-body sentence hits; `fullTextExists:Y AND OPEN_ACCESS:Y` filters; no key, generous limits | Biomedical-skewed (fine — most evidence-seeking use cases are). Lucene syntax needs escaping ([EPMC developers](https://europepmc.org/developers)) |
| **arXiv API** | 2.4M preprints, STEM | Freshness (preprints announced Sun–Thu), abstract + metadata; free | 1 req / 3 s, single connection → use as **supplementary**, max 1 call ([arXiv ToU](https://info.arxiv.org/help/api/tou.html)) |
| **CORE** | 200M+ OA works, full texts | Full-text aggregation beyond EPMC's biomedical focus; free API key | Slower responses; v1 optional |
| **DOAJ / bioRxiv-medRxiv (via EPMC)** | OA journals; preprints | Coverage for grey OA + life-science preprints | Low volume; fold into EPMC queries |
| **Firecrawl Research Index** *(optional, paid)* | 3M+ arXiv papers, 41M+ life-sci | **Query-ranked in-body passages in one call** (`read mode`) — eliminates local PDF parsing for arXiv corpus; keyless to start | Credit-priced (~$0.32/task); vendor-run benchmarks ([docs](https://www.firecrawl.dev/blog/ai-agents-search-academic-papers)) |
| **scite** *(future / paid)* | Citation-context DB | Commercially labels citations as *supporting / contrasting* — the closest existing analog to this module; candidate data source for training our stance head | Paid API |
| **Local seminal cache** | ~50–200 hand-curated landmark papers | Offline fallback when all APIs fail; keeps the module testable with zero network | Maintained as fixture data |

**What we deliberately exclude:** Google Scholar (no API), Dimensions/Lens.org (licensing), Exa (grey literature focus, $7/1k), PubMed-only (EPMC superset).

### 5.3 Chosen mix (v1)

- **Primary trio:** Semantic Scholar (search + snippets) + OpenAlex (fulltext search) + Europe PMC (BODY search). Each queried with the affirmative *and* counter variants → **6 fan-out groups**, all in flight simultaneously via `asyncio.gather` through the existing `api_gateway`.
- **Supplementary:** arXiv (1 call), CORE (1 call, best-effort).
- **Optional premium lane:** Firecrawl passages for arXiv hits when configured.
- **Fallback ladder:** any source that errors or times out is dropped; if **all** sources fail → local seminal cache + honest `degraded=True` flag on the result.

### 5.4 Latency engineering rules

1. **Hard per-source timeout: 2.5 s** (asyncio). Partial results beat complete failure; Stage 3 is tolerant of smaller input.
2. **Query budget per source:** S2 ≤ 2, OpenAlex ≤ 3, EPMC ≤ 4 (their in-body search is cheap and fast), arXiv 1, CORE 1 → ≤ 11 calls total.
3. **Per-source rate limits** come from the existing `api_gateway` token-bucket registry; add EPMC (~10 rps) and CORE entries. S2's 1 rps *keyed* limit is the binding constraint — that's why S2 gets few, high-value calls (its `search` returns up to 100 papers, and `snippet/search` up to 1,000 snippets in **one** request).
4. **Result caps:** ≤ 100 papers/source/query, `page=1` only. Recall comes from breadth (6 queries × 4 sources), not pagination.
5. **Disk cache** (existing `api_gateway.ResponseCache`, SQLite WAL): identical queries within TTL are zero-network. A repeated `supports()` call should return in **< 1 s** (cache + NLI verdict cache, §8.4).

**Alternative designs considered:**
- **(A) Single-source (S2 only).** Simplest; fails the "hundreds of sources" bar and S2's keyed rate limit makes parallel queries impossible. Rejected as primary.
- **(B) Federated trio** ← *chosen.* Complexity is contained in per-source adapters (~80 lines each), all behind `api_gateway`.
- **(C) Local mirror of OpenAlex quarterly snapshot + on-device index (SPLADE/BM25 over 240M abstracts).** Removes network latency entirely and is the true long-term answer to the 10 s SLA — but the snapshot is ~300 GB compressed and needs an index build pipeline. **This is the v3 "big bet"**, kept as a clearly-scoped future work item, not v1.

---

## 6. Stage 2 — Passage assembly (~100–200 ms)

**Goal:** convert heterogeneous API payloads into uniform `CandidateSentence` objects.

1. **Reconstruct OpenAlex abstracts** from inverted index (`{word: [positions]}` → sorted join).
2. **Sentence-split** abstracts and snippets (regex + abbreviation-aware splitting; `syntok` optional).
3. **Dedup:** `hash(doi_normalized + sentence_normalized)`, plus near-dup collapse (Jaccard ≥ 0.9 on token sets).
4. **Attach metadata:** title, authors (first author et al.), year, venue, citation count, DOI/URL, source endpoint, OA status.
5. **Drop obvious non-evidence** (see Stage 3 rules for the shared stoplist).

Output: ~800–1,500 `CandidateSentence`s (target: "hundreds of papers" ✓).

---

## 7. Stage 3 — Rule-based filtering: ~1,000 → **40** candidates (~150–400 ms)

**Goal:** cheap, deterministic pruning so the expensive NLI stage sees only plausible evidence. Pure CPU, no model. This stage merges several classic IR algorithms.

### 7.1 Algorithms merged here

| Algorithm | Role in stage | Why |
|---|---|---|
| **BM25 Okapi** (k1=1.5, b=0.75; `rank_bm25` or the existing `rag_indexer` implementation) | Primary scorer over sentences vs both query variants | BEIR's zero-shot finding: *"BM25 is a robust baseline; reranking and late-interaction models achieve the best zero-shot performance"* — i.e., BM25 for recall, learned models for precision ([BEIR, NeurIPS 2021](https://arxiv.org/abs/2104.08663)) |
| **Lexical anchor rules** | Hard boost for sentences containing entity terms, numbers/percentages, effect verbs, and outcome words ("reduced", "increased", "N =") | SciFact-style evidence sentences almost always contain the entities + a result; rules encode that prior for ~0 cost |
| **Cue-word priors** | Demote methods boilerplate ("we collected", "were purchased from"), meta-sentences ("this paper is organized as"), acknowledgments | These are the top noise producers in abstract mining |
| **Reciprocal Rank Fusion (k=60)** | Merge rankings from: BM25-vs-affirmative, BM25-vs-counter, anchor-score, source-native rank | RRF on ranks (not scores) merges heterogeneous scorers without calibration ([RRF explanation](https://blog.gopenai.com/hybrid-search-in-rag-dense-sparse-bm25-splade-reciprocal-rank-fusion-and-when-to-use-which-fafe4fd6156e)) |
| **MMR (λ≈0.7) diversity** | Final 40 selection, penalizing near-duplicate findings across papers | Prevents "10 paraphrases of the same result"; keeps per-paper cap ≤ 3 |

### 7.2 Funnel inside the stage

```
~1,000 sentences
   ├─ stoplist + sentence-quality filters           → ~700
   ├─ BM25 top-100 per query variant (RRF merged)   → ~120
   ├─ anchor boosts + cue demotions (rescore)       → ~60
   └─ MMR diversity + per-paper cap                 →  40   ✔ (spec: 20–40)
```

**Alternative designs considered:**
- **(A) Pure BM25, top-40.** Simplest; risks keyword myopia (misses paraphrases). 
- **(B) Rules + bi-encoder semantic rerank** (MiniLM-L6, ONNX int8, ~100 ms for 100 sentences). ← *adopted as an optional sub-stage 3b when Stage 1 recall is thin*; off by default, measured flag to enable.
- **(C) Learned sparse (SPLADE-distill) as the scorer.** Better recall than BM25 in principle, but adds a model download + runtime for marginal gain at this corpus size; revisit with the v3 local index.
- **(D) ColBERTv2/PLAID late interaction.** Quality gold standard — PLAID hits *tens of ms on GPU, low hundreds of ms on CPU* ([PLAID paper](https://arxiv.org/abs/2205.09707)) — but requires a prebuilt token-level index over a local corpus; only meaningful after the v3 local-mirror bet.

---

## 8. Stage 4 — NLI stance gate: 40 → **20–25** (~0.4–1.2 s)

**Goal:** for each candidate sentence, decide its relationship to the claim: **entails (supports) / contradicts (opposes) / neutral-mention (discard)**, with calibrated probabilities.

### 8.1 Model options compared (researched)

| Model | Params | Accuracy (SNLI / MNLI-mm) | CPU latency (int8 ONNX, seq≈192) | Notes |
|---|---|---|---|---|
| **`cross-encoder/nli-deberta-v3-small`** ← v1 choice | ~44M | **91.65 / 87.55** | ~15–25 ms/pair → **0.4–1.0 s for 40, batched** | Best speed/quality tradeoff for 3-way NLI; standard reranking NLI encoder ([model card](https://huggingface.co/cross-encoder/nli-deberta-v3-small)) |
| `cross-encoder/nli-deberta-v3-base` | ~86M | 92.38 / 88.5 | ~2× slower | Upgrade path when CPU allows ([model card](https://huggingface.co/cross-encoder/nli-deberta-v3-base)) |
| `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` | ~86M | Strong on adversarial (ANLI) | ~2× slower | Better on tricky claims; candidate for the *opposes()* path where contradictions are subtle |
| `nli-MiniLM2-L6-H768` | ~30M | lower | fastest | Emergency fast lane if SLA breached |
| Text2Text zero-shot (FLAN-T5) | 250M+ | good | too slow for CPU batch-40 | Rejected |

**Pairing format:** `(premise = candidate sentence, hypothesis = canonical claim)`.
- `supports()`: rank by P(entailment), require P(contradiction) < threshold.
- `opposes()`: rank by P(contradiction); also accept strong "limits/boundary" sentences (hedged entailments) flagged separately — reviewers value boundary evidence.
- **Threshold calibration:** v1 ships with fixed thresholds + reported probabilities; v2 calibrates on SciNLI/SciCite holdouts (§11).

### 8.2 Runtime engineering (this is where the 10 s SLA is won or lost)

1. **Export → ONNX → int8 dynamic quantization.** ONNX Runtime int8 on VNNI CPUs gives **2–6×** inference speedup over PyTorch fp32 ([HF+ORT results](https://medium.com/microsoft/faster-and-smaller-quantized-nlp-with-hugging-face-and-onnx-runtime-ec5525473bb7), [ORT quantization docs](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html)). One-time export script ships with the module; quantized artifact committed or downloaded on first run.
2. **Single batched call:** all 40 pairs in one `sess.run` (batch=40, seq=192, dynamic axes), intra-op threads = physical cores. Never per-pair loop.
3. **Model warm at app start:** the orchestrator's init path loads the ONNX session once (~1 s, off the SLA clock); a first-inference warmup run avoids lazy-init jank.
4. **Verdict cache:** `hash(normalized_claim, sentence_hash, model_version)` → probs, persisted (SQLite). Repeat/edited queries skip NLI for seen pairs.
5. **Abort-to-degrade:** if Stage 4 hasn't finished by t=8 s total, return rules-stage top-25 with `stance="UNVERIFIED"` and the degrade flag (§9).

### 8.3 Beyond generic NLI (v2, domain-tuned head)

Generic SNLI/MNLI accuracy overstates scientific-stance performance (hedges, population mismatch, "we failed to detect X"). Planned fine-tune set:
- **SciNLI** — 107k sentence pairs mined from ACL papers ([arXiv 2104.02939](https://arxiv.org/abs/2104.02939)).
- **SciCite / 3C citation-context** — citation intent (background/method/result-comparison) ([Cohan et al. 2019](https://aclanthology.org/P19-1074/)).
- **scite-style supporting/contrasting labels** for the *opposes* head if licensable; else weak-label via citation verbs ("is consistent with" vs "contradicts", "fails to replicate").
- Distill into the same DeBERTa-v3-small architecture → swap-in artifact, no architecture change.

### 8.4 Output

`StanceScoredSentence`: probs `{entail, contradict, neutral}`, selected stance, confidence, NLI model version. Keep top **20–25** (spec) by stance-weighted score, preserving MMR diversity.

---

## 9. The 10-second budget, itemized

| Stage | Typical | p95 | Hard cap | Mechanism |
|---|---|---|---|---|
| 0. Claim normalize + query synthesis | 0.08 s | 0.10 s | — | pure rules |
| 1. Federated fan-out | 1.2–1.8 s | 2.4 s | **2.5 s** | asyncio.gather, per-source timeouts, ≤11 calls |
| 2. Passage assembly | 0.10 s | 0.20 s | — | pure CPU |
| 3. Rule-based filter | 0.15 s | 0.40 s | 0.5 s | rank_bm25 + rules (numpy) |
| 4. NLI gate (int8, batch-40) | 0.5 s | 1.0 s | **2.0 s** | ONNX Runtime, intra-op threads |
| **Pre-LLM total** | **≈ 2.2–3.6 s** | **≈ 4.1 s** | **10 s SLA** | degradation ladder below |
| 5. LLM curation | 1.5–3 s | 5 s | 8 s* | structured output, streamed; *not part of the 10 s pre-LLM budget |

**Degradation ladder (enforced by an async deadline scheduler):**
1. t=2.5 s → seal fan-out, proceed with partial results.
2. t=4.5 s → if Stage 3 not done, fall back to BM25-only top-40.
3. t=8.0 s → skip fine reranking; ship NLI-batched or UNVERIFIED results, set `pipeline_meta.degraded=True` and a human-readable reason.
4. All timeouts non-fatal by design; the module **always returns** (worst case: local seminal cache, clearly flagged).

---

## 10. Stage 5 — LLM final curation: 25 → **10** (outside the 10 s budget)

**Why an LLM is still needed:** the NLI head scores *logical* stance. The LLM enforces *scholarly curation*: population/scope fit, effect-direction sanity, hedging quality, near-duplicate findings, and quote fidelity — failure modes pure IR+NN funnels leave on the table.

**Rubric (system prompt, deterministic order):**
1. Discard anything not an *observation/conclusion* sentence.
2. Discard scope mismatches (species, population, dose, scale) vs the claim.
3. Collapse near-duplicate findings (keep highest-citation paper; per-paper cap ≤ 3).
4. Prefer: quote contains quantitative result > directional result > qualitative statement.
5. **Quote must appear verbatim in the provided sentence** (anti-hallucination; reject and re-pull otherwise).
6. Return **exactly 10** (or fewer with `insufficient_evidence` flag), JSON only.

**Input packing:** claim + 25 items × (sentence + title + year + venue + stance probs) ≈ 2.5–3.5k tokens in, ~600 out. Use the repo's existing `api_gateway` LLM lane (OpenAI-compatible), structured-output mode, temperature 0.

**Caching:** full prompt hash → response via existing semantic cache (`rag_indexer.cache_llm_response` or gateway cache). Repeat queries: near-instant.

**Fallback if LLM lane unavailable:** return the NLI top-10 with `llm_curated=False`. The two pre-LLM stages remain fully useful on their own — that's deliberate layering.

---

## 11. Public API contract (to implement)

```python
@dataclass(frozen=True)
class EvidenceItem:
    quote: str                    # verbatim sentence from the paper
    paper: PaperRef               # title, authors, year, venue, doi, url, citation_count, oa
    stance: Literal["supports", "opposes", "limits", "unverified"]
    stance_probs: dict            # {"entail": p, "contradict": p, "neutral": p}
    relevance_score: float        # fused rules-stage score
    checks: dict                  # {"doi_format": bool, "retracted": bool, "llm_curated": bool, "quote_verbatim": bool}
    rationale: str | None         # short LLM curation note (Stage 5)

@dataclass(frozen=True)
class EvidenceResult:
    claim: str
    query_variant: Literal["supports", "opposes"]
    items: list[EvidenceItem]     # 0–10, target exactly 10
    consensus_summary: str        # e.g. "8 supporting / 2 limiting across 9 papers"
    pipeline_meta: PipelineMeta   # per-stage timings, funnel counts (1000→40→25→10), model+endpoint versions, degraded flags

def supports(text: str) -> EvidenceResult: ...
def opposes(text: str) -> EvidenceResult: ...
```

Both share the entire pipeline; they differ in **Stage 4 selection objective** (entailment-weighted vs contradiction-weighted) and Stage 5 rubric emphasis. `PipelineMeta` exposes the full funnel trace for debugging (`verbose=True` also returns the pruned 40 and 25 lists).

**Module boundary:** import nothing from other subsystems except `api_gateway` (all external calls, rate limits, caches) — consistent with the repo's layering. `rag_indexer` may be used for BM25/sentence-splitting utilities but is not a hard dependency (docs/code mismatch in v1 must not repeat).

---

## 12. Evaluation plan (gate before calling v1 done)

1. **Retrieval quality:** SciFact (BEIR) subset — claims → must retrieve the labeled abstract/sentence in top-40; target top-40 hit-rate ≥ 0.8.
2. **Stance quality:** holdout from SciNLI + hand-labeled 200 (claim, sentence) pairs from our own fan-out; report per-stance precision/recall; NLI-gate precision@25 ≥ 0.7 pre-LLM.
3. **End-to-end:** 20 real-world claims across domains (biomed, ML, psych, econ); human-judged precision@10 ≥ 0.8; ≥ 8/10 calls with exactly 10 items; zero fabricated quotes (verbatim check = hard gate).
4. **Latency:** p50/p95 pre-LLM on a mid-range laptop CPU (4 physical cores); SLA: p95 < 10 s, and record degradation frequency. CI runs the latency suite against the local seminal cache (no network) for determinism.
5. **Robustness drills:** each source individually blackholed (must still return); repeat query (must hit caches, < 1.5 s); 4-word and 30-word boundary inputs.

## 13. Risks & open questions

- **S2 anonymous pool variability** — biggest latency wildcard; mitigation is the trio fan-out + low S2 call budget. (Consider requesting a free API key early.)
- **OpenAlex free-key daily budget (~1k keyword searches)** — fine for a desktop assistant, but gateway caching is not optional.
- **Abstract-only evidence for paywalled papers** — inherent limitation; we always return OA source URLs and mark `oa=False` items.
- **Paraphrase recall at Stage 3** — BM25 may miss wording-distant evidence; the optional bi-encoder sub-stage (§7.2-B) and the v3 local index are the answers.
- **Stance ≠ citation stance** — a paper can *cite* a claim contradictorily while its own abstract is neutral; scite-style data (§8.3) is the principled fix, deferred to v2.
- **Do we need GPU?** Plan assumes no. If p95 breaches persist, the cheapest fix is Firecrawl passages (removes local sentence work for arXiv) before any GPU requirement.

## 14. Build order (when coding starts)

1. Models + `InvalidClaimError` + pipeline skeleton with fake per-stage results.
2. Stage 0 (rules) + unit tests (no network).
3. Stage 1 adapters: EPMC → OpenAlex → S2 (in that order: easiest to test → hardest), each behind a `RetrievalSource` protocol; fan-out + timeouts + gateway wiring.
4. Stage 2 assembly + tests on recorded API fixtures.
5. Stage 3 rules + RRF + MMR + tests; latency benchmark.
6. Stage 4: ONNX export script, batched inference, verdict cache; NLI tests on fixed pairs.
7. Stage 5: LLM rubric + JSON schema + verbatim-check hard gate.
8. Deadline scheduler + degradation ladder; full latency suite.
9. Evaluation suite (§12) + docs refresh.

---

# PART II — IMPLEMENTATION STATUS (built and live-verified)

> Stages 0–4 are **implemented, tested (21 offline unit tests, all passing), and
> live-verified against the real APIs and the real NLI model**. Stage 5 (LLM
> curation) is intentionally not built yet. Deviations from Part I are
> documented in section 16 — Part I remains the design rationale.

## 15. What exists on disk

```
evidence_engine/
├── README.md            this document
├── __init__.py          public surface: supports(), opposes(), models;
│                        starts a background NLI prewarm thread on import
├── models.py            frozen dataclasses: Stance, PaperRef, CandidateSentence,
│                        ScoredSentence, StanceScoredSentence, EvidenceItem,
│                        PipelineMeta, EvidenceResult, InvalidClaimError
├── sources.py           Stage 1 (EPMC + OpenAlex + Semantic Scholar adapters,
│                        disk cache, circuit-breaker cool-down, degradation
│                        reports) + Stage 2 (abstract reconstruction,
│                        abbreviation-safe sentence splitting, dedup)
├── nli.py               Stage 4: ONNX int8 DeBERTa-v3-small (HF
│                        Xenova/nli-deberta-v3-small, downloaded on first use,
│                        probe-calibrated label order), length-sorted batching,
│                        topical + outcome + NLI-sanity guards, in-memory
│                        verdict cache, deterministic lexical fallback
├── pipeline.py          Stage 0 (normalize + 6 query variants + cause/outcome
│                        term split), Stage 3 (inline BM25 Okapi, anchor priors,
│                        aim/boilerplate demotion, weighted RRF, MMR,
│                        per-paper cap), funnel orchestration with SLA-aware
│                        stage-4 cap, supports()/opposes()
├── tests/test_evidence_engine.py   21 offline unit tests (no network)
└── .retrieval_cache.db  runtime artifact (SQLite, 6 h TTL) — auto-created
```

## 16. Deviations from Part I, with reasons (all from live verification)

1. **Source set is 4: EPMC, OpenAlex, S2, arXiv.** arXiv (1 call/run per its
   1-req/3-s ToU) was added after live runs showed CS/robotics claims retrieve
   mostly from S2 — the life-science skew of EPMC and the S2 shared-pool
   429s make single-source reliance fragile. CORE/Firecrawl/scite remain
   documented future work. Optional API keys (EVIDENCE_ENGINE_S2_KEY,
   EVIDENCE_ENGINE_OPENALEX_KEY) raise free-tier ceilings; without them the
   anonymous OpenAlex budget ($0.10/day) and the S2 shared pool are the
   observed bottlenecks. S2/EPMC variants are fetched SEQUENTIALLY
   (concurrent bursts draw 429s on call #2 — live-verified).
2. **S2 gets 2 complementary search calls** (keyword + natural-language
   variants return materially different result sets), still no snippet
   endpoint — that is the documented v2 upgrade.
3. **BM25 is inline** (`pipeline.BM25`): `rank_bm25` isn't in the environment;
   ~30 lines with identical Okapi semantics. Documented, testable.
4. **Guards beyond the plan** (each fixes a live-observed failure):
   - *Topical-identity guard*: a confident NLI verdict requires ≥2 shared topic
     terms; topic terms are scrubbed of generic vocabulary (`_GENERIC_TERMS` —
     "learning", "model", "inverse" occur in most CS abstracts and prove
     nothing).
   - *Outcome-identity guard (all-hit)*: the sentence or its paper title must
     address ALL of the claim's outcome terms. Any-hit leaked every
     inverse-design paper through a claim about inverse KINEMATICS.
   - *Claim-type policy*: prevalence/dominance claims ("MLP is the dominant
     choice for IK") are classified by topical consistency of strong usage
     evidence (`_prevalence_stance`), because raw NLI entailment correctly
     refuses to let one usage sentence prove prevalence (a wall of NEUTRAL);
     contradictions still come from NLI. Causal claims use the standard gate.
   - *NLI-sanity guard*: confident verdicts must be confident in one direction
     only (entail+contradict co-activation is rejected).
   - *Aim-sentence demotion*: "This study aimed to..." sentences maximize
     keyword overlap but carry no evidence; result-verb sentences get boosted.
5. **Mode-weighted RRF**: a symmetric fusion let the counter-query dominate the
   candidate pool and starve `supports()`; supports/opposes weight the
   affirmative/counter streams 1.0/0.6 and 0.7/1.0 respectively.
6. **Stance-honest selection**: `supports()` never pads its 10 with opposing
   items (and vice versa); UNVERIFIED items are excluded. Fewer than 10
   eligible → fewer returned.
7. **Latency engineering that differs from the letter of §9:** import-time
   background prewarm (download + session + cold-start off the SLA clock),
   bounded 1 s first-call readiness wait, premise head-truncation (keep the
   sentence END, where verdict clauses live) + length-sorted batch packing,
   tiered circuit-breaker cool-down (transient 2 min / budget-exhaustion 1 h;
   cache still serves during cool-down), SQLite retrieval cache (6 h TTL) +
   in-memory NLI verdict cache, and a 6 s stage-1 deadline with the per-request
   timeout clamped to the remaining window (S2's shared pool sometimes needs
   5 s for one call — two doomed 3 s attempts were strictly worse).
   Observed on a contended sandbox (S2 only, EPMC timing out, OpenAlex budget
   spent): 6.0 s retrieval + 2.2 s NLI ≈ 8.3 s total, inside the SLA; with all
   sources healthy or cache warm: 2.5–4.5 s; repeat call ~0.2 s.
8. **Degradation is richer than planned:** sources report
   `ok (n/m variants failed)` / `skipped network (cool-down)` /
   `degraded: network (...); N cached rows served` / `degraded: <err>`;
   a network failure NEVER discards cache hits for other variants; NLI
   failures fall back to cue-word stance labeling (still useful, flagged);
   the result always returns, with `pipeline_meta.degraded` + reason.
   Additionally: an **SLA top-up** scores the next rules-stage chunk (24 more
   candidates) when the requested stance is thin and the deadline has budget
   left — idle SLA time becomes additional evidence.
9. **OpenAlex anonymous budget is real.** Verified: `$0.10/day` free tier,
   hard-stop 429 with `x-ratelimit-reset` (midnight UTC). The retrieval cache
   is not an optimization here — it is the budget-survival mechanism. Request
   a free key (raises to $1/day) before production use.

## 17. Verified behavior (live runs, Sep 13 2026)

- Funnel trace (fresh call, EPMC healthy): `variants 6 → papers 555 →
  sentences 1337 → after_rules 40 → after_nli 24 → items ≤ 10`.
- `supports()` top items: verbatim conclusions with p(entail) 0.95–0.98 from
  on-topic RCTs/reviews (e.g. "...16-week aerobic dancing program improved
  sleep quality", p=0.98).
- `opposes()` top items: genuine counter-evidence ("...insufficient evidence
  for a beneficial effect...", p(contradict)=0.89) and boundary LIMITS items.
- Off-topic distractors (liver-cirrhosis management, headache guidelines,
  exercise-in-pregnancy) are filtered by the topical/outcome guards.
- 21/21 offline tests pass: stage-0 bounds and variants, abstract
  reconstruction, dedup, BM25 ordering, RRF, per-paper cap, hedge→LIMITS,
  selection objectives, funnel with fake retrieval, all-sources-down contract,
  and a live-NLI test (skips automatically if the artifact is unavailable).
- Latency: see §16.7. SLA breach path verified (degraded-but-usable result,
  never an exception, never silent padding).

## 18. Remaining work

1. **Stage 5 (LLM curation, §10)** — the only missing piece of the deliverable:
   rubric filter 24 → 10, dedup of near-identical findings, verbatim-quote hard
   gate, retraction flags, `rationale` field. Until then `checks.llm_curated`
   is always False and items are the NLI top-10 stance-honest.
2. Free S2 API key + OpenAlex key (rate limits), S2 `/snippet/search` for
   in-body sentences, optional arXiv/CORE adapters.
3. Calibration + evaluation harness (§12) on SciFact/SciNLI holdouts.
4. `docs.md` refresh in the house style once Stage 5 lands.
