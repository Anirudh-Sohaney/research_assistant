"""Evidence Engine v2 — Stage 4: NLI stance gate.

Scores each candidate sentence against the claim with a Natural Language
Inference cross-encoder: (premise=sentence, hypothesis=claim) →
entailment / contradiction / neutral probabilities.

Backend selection at import time (graceful, documented in README section 16):

  1. ONNX int8  — HuggingFace `Xenova/nli-deberta-v3-small` (int8 artifact of
     cross-encoder/nli-deberta-v3-small, SNLI acc 91.65). Downloaded once to a
     module-local cache. Real NLI, ~15-25 ms/pair on CPU, batched.
  2. Lexical fallback — if onnxruntime, the tokenizer, or the network is
     unavailable: deterministic negation/cue-word scoring. Never raises; the
     pipeline marks results `degraded` and stance UNVERIFIED.

Label order for the Xenova/cross-encoder NLI exports is
[contradiction, entailment, neutral] (model config id2int under logits name
`logits`; see HF discussion for the checkpoint). We assert at load time via a
canonical probe (see `_calibrate_label_order`) so a mis-ordered export cannot
silently flip stances.
"""

from __future__ import annotations

import hashlib
import logging
import pathlib
import threading
from typing import List, Optional

import numpy as np

from evidence_engine.models import Stance

log = logging.getLogger("evidence_engine.nli")

NLI_MODEL_ID = "Xenova/nli-deberta-v3-small"
NLI_MODEL_OFFICIAL = "cross-encoder/nli-deberta-v3-small"
ONNX_FILE = "onnx/model_quantized.onnx"
CACHE_DIR = pathlib.Path(__file__).resolve().parent / ".model_cache"
MAX_SEQ = 192

# Lexical fallback cue sets (deterministic, offline).
_NEG_CUES = (
    "not ", "no evidence", "no significant", "did not", "does not", "do not",
    "failed to", "cannot", "can not", "unlikely", "no effect", "no difference",
    "reduced", "reduces", "decreased", "decreases", "impaired", "impairs",
    "inhibited", "inhibits", "lower", "lowered", "worse", "adverse", "negatively",
    "contrary", "contradict", "inconsistent with", "fails to",
)
_SUP_CUES = (
    "significantly increased", "significantly improved", "enhances", "enhanced",
    "improves", "improved", "promotes", "promoted", "effective", "beneficial",
    "consistent with", "supports", "supported by", "associated with",
    "positively", "greater", "higher", "accelerates", "strengthens",
)
_HEDGE_CUES = (
    "may", "might", "suggest", "suggests", "possible", "potentially", "appears",
    "in some", "under certain", "specific conditions", "modest", "limited to",
    "in mice", "in rats", "in vitro", "in older adults", "in patients with",
)

# Topical-overlap guard (added after live verification): NLI cross-encoders
# score *logical* relations, not *topic* identity — a sentence about exercise
# improving fitness in pregnancy reads as a strong contradiction of a claim
# about exercise and sleep. We require shared content words before any
# non-neutral verdict is trusted (README section 16, guardrails).
import re as _re

_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "in", "on", "for", "to", "with",
    "at", "by", "from", "is", "are", "was", "were", "be", "been", "this",
    "that", "these", "those", "it", "its", "their", "our", "we", "as", "than",
    "study", "studies", "trial", "trials", "participants", "results", "conclusion",
    "conclusions", "methods", "background", "objective", "context", "authors",
    "patients", "subjects", "group", "groups", "effect", "effects", "intervention",
    "treatment", "analysis", "data", "test", "tests", "using", "used", "between",
    "after", "before", "during", "may", "might", "can", "could", "also", "both",
    "such", "into", "over", "under", "more", "most", "less", "least", "new",
    "per", "via", "when", "while", "among", "across", "within", "without", "total",
    "change", "changes", "compared", "significant", "significantly", "versus",
}


def _content_words(text: str) -> set:
    return {
        w for w in _re.findall(r"[a-z][a-z-]{2,}", text.lower())
        if w not in _STOPWORDS
    }


def topical_overlap(sentence: str, claim: str) -> float:
    """Jaccard overlap of content words between sentence and claim (0-1)."""


class StanceGate:
    """Stage 4 scorer. Constructor is cheap; `ensure_loaded()` does I/O."""

    def __init__(self) -> None:
        self._sess = None
        self._tok = None
        self._backend = "unloaded"
        self._label_order = ("contradiction", "entailment", "neutral")
        self._lock = threading.Lock()
        # Verdict cache (README section 8.2 item 4): identical (claim, sentence)
        # pairs skip inference entirely. In-memory for v1; keyed on model too.
        self._verdict_cache: dict = {}

    # ------------------------------------------------------------ loading

    @property
    def backend(self) -> str:
        return self._backend

    def _try_load_onnx(self) -> bool:
        try:
            import onnxruntime as ort
            from huggingface_hub import hf_hub_download
        except ImportError:
            log.info("NLI: onnxruntime/huggingface_hub not installed; using lexical fallback")
            return False
        try:
            model_path = hf_hub_download(
                repo_id=NLI_MODEL_ID, filename=ONNX_FILE, cache_dir=str(CACHE_DIR)
            )
            from tokenizers import Tokenizer

            tok_url = f"https://huggingface.co/{NLI_MODEL_ID}/resolve/main/tokenizer.json"
            tok_path = CACHE_DIR / "tokenizer.json"
            if not tok_path.exists():
                import urllib.request

                urllib.request.urlretrieve(tok_url, tok_path)
            tok = Tokenizer.from_file(str(tok_path))
            tok.enable_truncation(max_length=MAX_SEQ)
            tok.enable_padding()
            sess = ort.InferenceSession(
                model_path, sess_options=None,
                providers=["CPUExecutionProvider"],
            )
            self._sess, self._tok = sess, tok
            self._backend = f"onnx-int8:{NLI_MODEL_ID}"
            return True
        except Exception as exc:  # noqa: BLE001 — fallback is the contract
            log.warning("NLI ONNX load failed (%s); using lexical fallback", exc)
            return False

    def ensure_loaded(self) -> str:
        """Load the real NLI model once; fall back lexically if impossible."""
        with self._lock:
            if self._backend != "unloaded":
                return self._backend
            if self._try_load_onnx():
                try:
                    self._calibrate_label_order()
                except Exception as exc:  # noqa: BLE001
                    log.warning("NLI calibration failed (%s); lexical fallback", exc)
                    self._sess, self._tok = None, None
                    self._backend = "unloaded"
            if self._backend == "unloaded":
                self._backend = "lexical-fallback"
            else:
                # Cold-start warmup: the first ORT inference allocates memory
                # arenas and spins up the thread pool (~2-3 s); doing it here
                # keeps the first real batch inside its SLA cap (live-fix).
                try:
                    self._score_batch(["Warmup sentence."], ["Warmup claim."])
                except Exception as exc:  # noqa: BLE001
                    log.warning("NLI warmup failed (%s); lexical fallback", exc)
                    self._sess, self._tok = None, None
                    self._backend = "lexical-fallback"
            return self._backend

    def _calibrate_label_order(self) -> None:
        """Probe the model once with a clear entailment and a clear contradiction
        to map logits positions -> labels robustly."""
        import numpy as _np

        p_yes = self._score_batch(["A man is eating food."], ["A man is eating a meal."])[0]
        p_no = self._score_batch(["A man is eating food."], ["A man is riding a horse."])[0]
        e_idx = int(_np.argmax(p_yes))
        c_idx = int(_np.argmax(p_no))
        if e_idx == c_idx:
            raise RuntimeError("NLI probe ambiguous (same argmax for entail/contradict)")
        n_idx = ({0, 1, 2} - {e_idx, c_idx}).pop()
        self._label_order = ("contradiction", "entailment", "neutral")  # semantic only
        self._idx = {"contradiction": c_idx, "entailment": e_idx, "neutral": n_idx}

    # ------------------------------------------------------------ scoring

    def _score_batch(self, premises: List[str], hypotheses: List[str]) -> "np.ndarray":
        """Run the ONNX model on a batch; returns (N, 3) softmax probabilities
        ordered by self._idx mapping. Empty input returns an empty array
        (ORT rejects rank-1 input tensors)."""
        if not premises:
            import numpy as _np

            return _np.zeros((0, 3))
        # Head-truncate premises (keep the END): S2 abstract sentences can be
        # 100+ tokens, pushing every pair to the 192 cap and doubling stage
        # latency (live-verified). Verdict clauses live at the END of evidence
        # sentences ("...has been considered the most appropriate"), so we
        # drop the beginning, never the conclusion.
        premises = [p[-350:] if len(p) > 350 else p for p in premises]
        # Length-sort before padding: batching sentences of similar length
        # avoids padding waste.
        order = sorted(range(len(premises)), key=lambda i: len(premises[i]))
        premises = [premises[i] for i in order]
        hypotheses = [hypotheses[i] for i in order]
        enc = self._tok.encode_batch(list(zip(premises, hypotheses)))
        input_ids = np.array([e.ids for e in enc], dtype=np.int64)
        attention = np.array([e.attention_mask for e in enc], dtype=np.int64)
        # token_type_ids: DeBERTa expects sequence ids; tokenizers gives them via
        # type_ids when pairing. Xenova export may not expose the input.
        input_names = {i.name for i in self._sess.get_inputs()}
        feeds = {"input_ids": input_ids, "attention_mask": attention}
        if "token_type_ids" in input_names:
            type_ids = np.array([e.type_ids for e in enc], dtype=np.int64)
            feeds["token_type_ids"] = type_ids
        logits = self._sess.run(None, feeds)[0]
        logits = logits - logits.max(axis=1, keepdims=True)
        probs = np.exp(logits)
        probs = probs / probs.sum(axis=1, keepdims=True)
        # restore caller order
        restored = np.empty_like(probs)
        for pos, orig_idx in enumerate(order):
            restored[orig_idx] = probs[pos]
        return restored

    def score(
        self, claim: str, sentences: List["object"], mode: str,
        topical_terms: Optional[List[str]] = None,
        outcome_terms: Optional[List[str]] = None,
        claim_type: str = "causal",
    ) -> List[tuple]:
        """Score (claim, sentence) pairs.

        Returns list of (p_entail, p_contradict, p_neutral, stance) aligned with
        `sentences`. `mode` is "supports" or "opposes". `topical_terms` are the
        Stage-0 topic words (population words excluded — see pipeline.py); a
        confident verdict requires >= 2 shared topic terms (1 for single-term
        claims) before it is trusted (live-verified failure mode: "exercise
        improves fitness in pregnancy" scoring as a contradiction of "exercise
        improves sleep in older adults").
        """
        backend = self.ensure_loaded()
        if backend == "lexical-fallback":
            return [
                self._lexical(s.candidate.text, claim, mode) for s in sentences
            ]
        topic = [t for t in (topical_terms or []) if t]
        outcomes = [t for t in (outcome_terms or []) if t]
        min_hits = 2 if len(topic) >= 2 else (1 if topic else 0)
        # Verdict-cache lookup: score only pairs not seen before.
        uncached_idx: List[int] = []
        cached_results: dict = {}
        for i, s_obj in enumerate(sentences):
            key = hashlib.sha1(
                f"{claim}\x00{s_obj.candidate.text}\x00{self._backend}".encode()
            ).hexdigest()
            hit = self._verdict_cache.get(key)
            if hit is not None:
                cached_results[i] = hit
            else:
                uncached_idx.append(i)
        if uncached_idx:
            fresh = self._raw_score(
                claim, [sentences[i] for i in uncached_idx],
                topic, outcomes, min_hits, mode, claim_type,
            )
            for i, verdict in zip(uncached_idx, fresh):
                cached_results[i] = verdict
                key = hashlib.sha1(
                    f"{claim}\x00{sentences[i].candidate.text}\x00{self._backend}".encode()
                ).hexdigest()
                self._verdict_cache[key] = verdict
        return [cached_results[i] for i in range(len(sentences))]

    def _raw_score(
        self, claim: str, sentences: List["object"], topic: List[str],
        outcomes: List[str], min_hits: int, mode: str, claim_type: str = "causal",
    ) -> List[tuple]:
        """Model inference + guards for a batch of (claim, sentence) pairs."""
        probs = self._score_batch(
            [s.candidate.text for s in sentences], [claim] * len(sentences)
        )
        out = []
        for s_obj, row in zip(sentences, probs):
            p_c = float(row[self._idx["contradiction"]])
            p_e = float(row[self._idx["entailment"]])
            p_n = float(row[self._idx["neutral"]])
            sent_words = _content_words(s_obj.candidate.text)
            # Guard 1 — topical identity: the sentence must mention at least
            # `min_hits` of the claim's topic terms. Topic terms are already
            # scrubbed of generic vocabulary (pipeline._GENERIC_TERMS), so a
            # hit means an approach- or problem-specific term ("perceptron",
            # "kinematics"), not filler like "learning" or "model".
            topic_hits = sum(1 for t in topic if t in sent_words)
            # Guard 1b — outcome identity: the sentence (or its paper title)
            # must address ALL of the claim's outcome terms. All-hit, not
            # any-hit: "inverse" alone matches every inverse-design paper,
            # which is exactly the leakage this guard exists to stop. The
            # title is included because one sentence may omit the domain word
            # the whole paper is about.
            out_scope = s_obj.candidate.text + " \n " + (
                s_obj.candidate.paper.title or "")
            out_words = _content_words(out_scope)
            outcomes_ok = (not outcomes) or all(t in out_words for t in outcomes)
            # Topical validity: gates the prevalence policy directly, and
            # gates NLI-confident verdicts for causal claims (Guard 2 below).
            topically_valid = topic_hits >= min_hits and outcomes_ok
            # Guard 2 — NLI sanity: a confident verdict must be confident in
            # exactly one direction; entail+contradict co-activation (common
            # when the model keys on surface overlap) is not a verdict.
            confident = (p_c > 0.5 or p_e > 0.5) and abs(p_c - p_e) > 0.35
            if claim_type == "prevalence":
                if not topically_valid:
                    out.append((p_e, p_c, p_n, Stance.UNVERIFIED))
                    continue
                out.append((p_e, p_c, p_n, self._prevalence_stance(
                    s_obj.candidate.text, out_scope, p_e, p_c, p_n,
                    topic, outcomes)))
            else:
                if confident and not topically_valid:
                    out.append((p_e, p_c, p_n, Stance.UNVERIFIED))
                    continue
                stance = self._stance_from_probs(p_e, p_c, p_n, mode)
                out.append((p_e, p_c, p_n, stance))
        return out

    @staticmethod
    def _prevalence_stance(sentence: str, out_scope: str, p_e: float,
                           p_c: float, p_n: float, topic: List[str],
                           outcomes: List[str]) -> Stance:
        """Stance policy for prevalence/dominance claims ("MLP is the dominant
        choice for IK"). Raw NLI entailment is the wrong instrument: a paper
        *using* MLP for IK does not *entail* that MLP dominates (hence a wall
        of NEUTRAL). Instead, topical consistency of strong usage evidence is
        the signal; contradictions still come from NLI. Classification:
          SUPPORTS — strong usage/finding sentence, topically on-target,
                     no contradiction signal
          OPPOSES  — NLI contradiction (confidence per guard rules)
          LIMITS   — usage evidence that is hedged or off-outcome
          UNVERIFIED — weak/topically-ambiguous sentences
        """
        sent_words = _content_words(sentence)
        out_words = _content_words(out_scope)
        topic_hits = sum(1 for t in topic if t in sent_words)
        outcome_ok = (not outcomes) or all(t in out_words for t in outcomes)
        # A genuine contradiction is still a genuine contradiction.
        if p_c >= 0.45 and p_c > p_e and topic_hits >= 1:
            return Stance.OPPOSES
        if topic_hits < 2 or not outcome_ok:
            return Stance.UNVERIFIED
        t = sentence.lower()
        usage = any(c in t for c in (
            "we use", "we employ", "we adopt", "we implement", "we propose",
            "we apply", "is used", "are used", "is employed", "is implemented",
            "is applied", "we model", "we solve", "is solved", "we train",
            "achieves", "achieve", "outperforms", "gives a minimum error",
            "yields", "obtained", "selected", "chosen",
        ))
        hedged = any(c in t for c in _HEDGE_CUES)
        if usage and not hedged and p_c < 0.4:
            return Stance.SUPPORTS
        if usage or p_e >= 0.34:
            return Stance.LIMITS
        return Stance.UNVERIFIED


    @staticmethod
    def _stance_from_probs(p_e: float, p_c: float, p_n: float, mode: str) -> Stance:
        # LIMITS: entailment wins but hedging present (checked by caller via text);
        # here: contradicted > entails > else neutral.
        if p_c >= 0.45 and p_c > p_e:
            return Stance.OPPOSES
        if p_e >= 0.34:
            return Stance.SUPPORTS
        return Stance.LIMITS if p_e >= 0.25 else Stance.UNVERIFIED

    # ------------------------------------------------------------ fallback

    def _lexical(self, sentence: str, claim: str, mode: str) -> tuple:
        """Deterministic cue-word stance scoring (documented degradation path)."""
        t = " " + sentence.lower() + " "
        neg = sum(1 for c in _NEG_CUES if c in t)
        sup = sum(1 for c in _SUP_CUES if c in t)
        if neg > sup:
            stance = Stance.OPPOSES
        elif sup > 0:
            stance = Stance.SUPPORTS
        else:
            stance = Stance.LIMITS if any(c in t for c in _HEDGE_CUES) else Stance.UNVERIFIED
        return (0.0, 0.0, 0.0, stance)

    def is_real_model(self) -> bool:
        return self._backend.startswith("onnx")


# Module-level singleton; threads load it once.
_gate = StanceGate()


def ensure_loaded() -> str:
    return _gate.ensure_loaded()


def wait_until_ready(timeout_s: float) -> bool:
    """Block up to `timeout_s` waiting for the backend to finish initializing
    (e.g. the import-time prewarm thread). Returns True once any backend —
    real or lexical — is ready."""
    import time as _time

    deadline = _time.monotonic() + timeout_s
    while _gate.backend == "unloaded" and _time.monotonic() < deadline:
        _time.sleep(0.05)
    return _gate.backend != "unloaded"


def backend_name() -> str:
    return _gate.backend


def score(claim: str, sentences: list, mode: str,
          topical_terms: Optional[List[str]] = None,
          outcome_terms: Optional[List[str]] = None,
          claim_type: str = "causal") -> List[tuple]:
    return _gate.score(claim, sentences, mode, topical_terms, outcome_terms,
                       claim_type)


def lexical_score(claim: str, sentences: list, mode: str) -> List[tuple]:
    """Public lexical scoring (used when the NLI stage fails or times out).
    Returns (0,0,0,stance) tuples: stance labels without calibrated probs."""
    return [_gate._lexical(s.candidate.text, claim, mode) for s in sentences]


def is_real_model() -> bool:
    return _gate.is_real_model()
