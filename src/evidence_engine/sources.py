"""Evidence Engine v2 — Stage 1 (federated retrieval) + Stage 2 (passage assembly).

Stage 1 fans out over academic APIs in parallel (asyncio), each adapter with a
hard per-source timeout. Sources are free/no-key services chosen for
sentence-bearing payloads and breadth:

  * Europe PMC  — Lucene fielded search (BODY:), 4M+ open-access full texts
  * OpenAlex    — 240M+ works; `search` covers title+abstract+fulltext (57M docs)
  * Semantic Scholar — 214M papers; graph /paper/search (2 complementary queries)
  * arXiv       — 2.4M STEM preprints; freshness for CS/robotics claims
    (1 request / 3 s per arXiv ToU, so a single supplementary call per run)

CORE / Firecrawl / scite are documented in README section 18 as future work.
Optional API keys: EVIDENCE_ENGINE_S2_KEY (dedicated 1 rps),
EVIDENCE_ENGINE_OPENALEX_KEY ($1/day free tier).

Stage 2 assembles raw payloads into deduplicated `CandidateSentence`s:
OpenAlex abstracts are stored as inverted indexes and must be reconstructed;
S2 returns abstracts; EPMC (resultType=core) returns abstractText. Sentences
are split, length/quality filtered, and deduplicated by (doi, text-hash).

Everything here degrades silently per source: one failing API never raises;
it is recorded in `sources_report` and the funnel continues.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import pathlib
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from typing import Callable, Dict, List, Optional

import httpx

from evidence_engine.models import CandidateSentence, PaperRef

log = logging.getLogger("evidence_engine.sources")

# Optional API keys (README section 16): raise Semantic Scholar from the
# shared anonymous pool to a dedicated 1 rps, and OpenAlex from $0.10/day to
# $1/day. Both engines work without them; they just degrade under load.
_S2_KEY = os.environ.get("EVIDENCE_ENGINE_S2_KEY") or ""
_OPENALEX_KEY = os.environ.get("EVIDENCE_ENGINE_OPENALEX_KEY") or ""

SOURCE_TIMEOUT_S = 8.0          # per-request ceiling. The STAGE deadline
                                # (pipeline.STAGE1_DEADLINE_S = 6 s) clamps this
                                # to the remaining window, so a slow shared-pool
                                # source (S2 needs up to ~5 s; live-verified)
                                # uses its whole budget on one attempt instead
                                # of two doomed 3 s attempts.
USER_AGENT = "evidence-engine/2.0 (desktop research assistant)"

# ---------------------------------------------------------------- Disk cache
# Free-tier budgets are finite (OpenAlex anonymous: $0.10/day; S2 anonymous:
# shared pool). Identical (source, query) pairs within TTL are served from a
# local SQLite cache: zero network, zero budget, ~0 latency (README section 9).
_CACHE_PATH = pathlib.Path(__file__).resolve().parent / ".retrieval_cache.db"
_CACHE_TTL_S = 6 * 3600


# Circuit-breaker cool-down: a source that just failed is skipped for a
# tiered cool-down instead of burning its timeout on every call (README
# section 9). Tiered because failures are not equal (live-verified):
#   * transient (timeout, 429/5xx from shared anonymous pools) -> 120 s
#   * hard budget exhaustion (OpenAlex daily credits) -> 1 h, retrying sooner
#     is pointless — the quota only resets at midnight UTC
_COOLDOWN_TRANSIENT_S = 120.0
_COOLDOWN_BUDGET_S = 3600.0
_source_cooldown: Dict[str, float] = {}


def _cooling_down(name: str) -> bool:
    until = _source_cooldown.get(name, 0.0)
    if time.time() < until:
        return True
    return False


def _mark_failure(name: str, exc: object = None) -> None:
    budget = False
    try:
        import httpx as _httpx

        if isinstance(exc, _httpx.HTTPStatusError) and exc.response.status_code == 429:
            body = (exc.response.text or "")[:300].lower()
            budget = "budget" in body or "rate limit" in body
    except Exception:
        pass
    ttl = _COOLDOWN_BUDGET_S if budget else _COOLDOWN_TRANSIENT_S
    _source_cooldown[name] = time.time() + ttl


def _mark_success(name: str) -> None:
    _source_cooldown.pop(name, None)


def _cache_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_CACHE_PATH), timeout=5.0)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cache ("
        "k TEXT PRIMARY KEY, ts REAL, payload TEXT)"
    )
    return conn


def _cache_get(key: str) -> Optional[List[dict]]:
    try:
        conn = _cache_conn()
        try:
            row = conn.execute(
                "SELECT payload FROM cache WHERE k = ? AND ts > ?",
                (key, time.time() - _CACHE_TTL_S),
            ).fetchone()
        finally:
            conn.close()
        return json.loads(row[0]) if row else None
    except Exception:  # cache must never break retrieval
        return None


def _cache_put(key: str, rows: List[dict]) -> None:
    try:
        conn = _cache_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO cache (k, ts, payload) VALUES (?, ?, ?)",
                (key, time.time(), json.dumps(rows)),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass

# ---------------------------------------------------------------- Sentence utils

# Common abbreviations that must not terminate a sentence.
_ABBREV = (
    ("e.g.", "eg"), ("i.e.", "ie"), ("et al.", "et al"),
    ("vs.", "vs"), ("cf.", "cf"), ("ca.", "ca"),
    ("Fig.", "Fig"), ("Eq.", "Eq"), ("No.", "No"), ("Dr.", "Dr"),
    ("approx.", "approx"), ("resp.", "resp"),
)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])")
_GOOD_CHARS = re.compile(r"[A-Za-z]")


def _mask_abbrevs(text: str) -> str:
    """Mask abbreviations so the sentence splitter won't cut on them."""
    for orig, _repl in _ABBREV:
        text = re.sub(re.escape(orig) + r"(?=\W|$)", _repl, text)
    return text


def _unmask_abbrevs(text: str) -> str:
    """Restore abbreviations, word-boundary-safe (won't touch 'Regular')."""
    for orig, repl in _ABBREV:
        text = re.sub(r"\b" + re.escape(repl) + r"\b", orig, text)
    return text


def split_sentences(text: str) -> List[str]:
    """Sentence-split with abbreviation guarding (mask, split, unmask)."""
    if not text:
        return []
    parts = [p.strip() for p in _SENT_SPLIT.split(_mask_abbrevs(text)) if p.strip()]
    return [_unmask_abbrevs(p) for p in parts]


def reconstruct_abstract(inv_index: Optional[dict]) -> str:
    """Rebuild abstract text from OpenAlex's {word: [positions]} inverted index."""
    if not inv_index:
        return ""
    positions: List[tuple] = []
    for word, idxs in inv_index.items():
        positions.extend((int(i), word) for i in idxs)
    positions.sort()
    return " ".join(w for _, w in positions)


def _is_plausible_evidence(s: str) -> bool:
    """Stage-2 quality gate: cheap sentence-level heuristics.

    Keeps sentences that look like reportable observations/conclusions; drops
    fragments, questions, keyword lists, and boilerplate.
    """
    t = s.strip()
    if not (40 <= len(t) <= 450):
        return False
    if not _GOOD_CHARS.search(t):
        return False
    if t.endswith("?"):
        return False
    lower = t.lower()
    bad_starts = ("keywords", "copyright", "issn", "doi:", "©")
    if lower.startswith(bad_starts):
        return False
    digit_ratio = sum(c.isdigit() for c in t) / len(t)
    if digit_ratio > 0.25:
        return False
    letters = sum(c.isalpha() for c in t)
    if letters / len(t) < 0.6:
        return False
    return True


# ---------------------------------------------------------------- Adapters

def _mk_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=SOURCE_TIMEOUT_S, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    )


def _doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    return doi.replace("https://doi.org/", "").strip() or None


def _fmt_authors(authorships: list) -> str:
    names = [
        (a.get("author") or {}).get("display_name", "") for a in (authorships or [])[:6]
    ]
    names = [n for n in names if n]
    if not names:
        return "Unknown"
    return names[0] + (" et al." if len(names) > 1 else "")


async def _fetch_epmc_seq(client: httpx.AsyncClient, variants: List[str], limit: int) -> List[dict]:
    """Sequential variant fetching for EPMC: their throttling is concurrency-
    sensitive (parallel core requests intermittently 403/timeout), while the
    same requests one at a time succeed."""
    rows: List[dict] = []
    for v in variants:
        try:
            rows.extend(await _fetch_epmc(client, v, limit))
        except Exception as exc:  # noqa: BLE001
            log.info("epmc variant degraded: %s", exc)
    return rows


async def _fetch_epmc(client: httpx.AsyncClient, expr: str, limit: int) -> List[dict]:
    """Europe PMC: BODY field search over open-access full texts (resultType=core
    returns abstractText used for sentence extraction). Core payloads are heavy,
    so pageSize is capped at 15 to stay inside the fan-out deadline."""
    query = f'BODY:({expr}) AND OPEN_ACCESS:Y'
    resp = await client.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": query, "format": "json", "pageSize": min(limit, 15),
                "resultType": "core"},
    )
    resp.raise_for_status()
    articles = (resp.json().get("resultList", {}) or {}).get("result", []) or []
    out = []
    for a in articles:
        out.append({
            "title": a.get("title", ""),
            "authors": a.get("authorString", "") or "Unknown",
            "year": int(a["pubYear"]) if a.get("pubYear", "").isdigit() else None,
            "doi": _doi(a.get("doi")),
            "url": a.get("doi") or (f"https://europepmc.org/article/{a.get('source', 'MED')}/{a.get('id', '')}"),
            "venue": a.get("journalTitle", "") or None,
            "citation_count": a.get("citedByCount"),
            "open_access": a.get("isOpenAccess") == "Y",
            "abstract": a.get("abstractText", "") or "",
        })
    return out


async def _fetch_openalex(client: httpx.AsyncClient, expr: str, limit: int) -> List[dict]:
    """OpenAlex: two complementary searches per variant — fulltext.search (hits
    inside 57M indexed full texts) and default search (title+abstract)."""
    select = ("id,doi,display_name,authorships,publication_year,primary_location,"
              "cited_by_count,abstract_inverted_index,open_access,type")
    async def one(params: dict) -> List[dict]:
        if _OPENALEX_KEY:
            params = {**params, "api_key": _OPENALEX_KEY}
        resp = await client.get("https://api.openalex.org/works",
                                params={**params, "per-page": min(limit, 100), "select": select})
        resp.raise_for_status()
        return resp.json().get("results", []) or []

    # Errors (429 budget exhaustion, timeouts) must propagate so _fetch_source
    # can count them — swallowing them here produced a misleading "ok, 0 papers"
    # status (live-verified bug).
    results = await asyncio.gather(
        one({"search": expr}), one({"filter": f"fulltext.search:{expr}"}),
    )
    works: List[dict] = []
    for r in results:
        works.extend(r)
    out = []
    for w in works:
        loc = w.get("primary_location") or {}
        src = (loc.get("source") or {}) or {}
        oa = w.get("open_access") or {}
        out.append({
            "title": w.get("display_name", "") or "",
            "authors": _fmt_authors(w.get("authorships")),
            "year": w.get("publication_year"),
            "doi": _doi(w.get("doi")),
            "url": w.get("id"),
            "venue": src.get("display_name"),
            "citation_count": w.get("cited_by_count"),
            "open_access": bool(oa.get("is_oa")),
            "abstract": reconstruct_abstract(w.get("abstract_inverted_index")),
        })
    return out


async def _fetch_s2(client: httpx.AsyncClient, expr: str, limit: int) -> List[dict]:
    """Semantic Scholar: single /paper/search call (keyed limit is 1 rps, so the
    engine gives it one high-value shot). The anonymous pool 429s are
    transient — one short-backoff retry before degrading (live-verified)."""
    params = {
        "query": expr,
        "limit": min(limit, 100),
        "fields": "title,authors,year,abstract,externalIds,venue,citationCount,isOpenAccess",
    }
    headers = {"x-api-key": _S2_KEY} if _S2_KEY else None
    try:
        resp = await client.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params=params, headers=headers)
        resp.raise_for_status()
    except Exception:
        await asyncio.sleep(0.4)
        resp = await client.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params=params, headers=headers)
    resp.raise_for_status()
    data = resp.json().get("data", []) or []
    out = []
    for p in data:
        out.append({
            "title": p.get("title") or "",
            "authors": _fmt_authors(p.get("authors")),
            "year": p.get("year"),
            "doi": (p.get("externalIds") or {}).get("DOI"),
            "url": p.get("url") or (f"https://www.semanticscholar.org/paper/{p.get('paperId')}" if p.get("paperId") else None),
            "venue": p.get("venue") or None,
            "citation_count": p.get("citationCount"),
            "open_access": bool(p.get("isOpenAccess")),
            "abstract": p.get("abstract") or "",
        })
    return out


def _arxiv_text(entry) -> str:
    """Concatenate arXiv <summary> (abstract) — the only sentence-bearing field."""
    node = entry.find("{http://www.w3.org/2005/Atom}summary")
    return (node.text or "").strip() if node is not None else ""


async def _fetch_arxiv(client: httpx.AsyncClient, expr: str, limit: int) -> List[dict]:
    """arXiv API (Atom XML): supplementary STEM/preprint coverage. The ToU caps
    us at 1 request / 3 s and a single connection, so federated_retrieval gives
    arXiv ONE call per run (the keyword variant — arXiv relevance ranking
    handles natural phrasing poorly)."""
    q = re.sub(r"[^A-Za-z0-9 ]", " ", expr).strip()
    resp = await client.get(
        "https://export.arxiv.org/api/query",
        params={
            "search_query": f"all:{q}",
            "start": 0,
            "max_results": min(limit, 30),
            "sortBy": "relevance",
        },
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    ns = "http://www.w3.org/2005/Atom"
    out = []
    for entry in root.findall(f"{{{ns}}}entry"):
        title = (entry.findtext(f"{{{ns}}}title") or "").strip()
        summary = _arxiv_text(entry)
        authors = [a.findtext(f"{{{ns}}}name") or "" for a in entry.findall(f"{{{ns}}}author")]
        authors = [a for a in authors if a]
        arxiv_id = (entry.findtext(f"{{{ns}}}id") or "").rsplit("/", 1)[-1]
        published = entry.findtext(f"{{{ns}}}published") or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        doi = entry.findtext("{http://arxiv.org/schemas/atom}doi")
        out.append({
            "title": re.sub(r"\s+", " ", title),
            "authors": (authors[0] + (" et al." if len(authors) > 1 else "")) if authors else "Unknown",
            "year": year,
            "doi": _doi(doi) or (f"10.48550/arXiv.{arxiv_id}" if arxiv_id else None),
            "url": entry.findtext(f"{{{ns}}}id"),
            "venue": "arXiv",
            "citation_count": None,
            "open_access": True,
            "abstract": re.sub(r"\s+", " ", summary),
        })
    return out


async def _fetch_source(
    name: str,
    fn: Callable[[httpx.AsyncClient, str, int], List[dict]],
    variants: List[str],
    limit: int,
    deadline: float,
    report: Dict,
) -> List[dict]:
    """Run one source across query variants under a shared deadline, with a
    per-variant disk cache (hits skip the network entirely) and a cool-down
    for sources that just failed."""
    loop = asyncio.get_running_loop()
    try:
        keys = [hashlib.sha1(f"{name}|{v}|{limit}".encode()).hexdigest()
                for v in variants]
        cached = [_cache_get(k) for k in keys]
        misses = [v for v, c in zip(variants, cached) if c is None]
        fetched: List[List[dict]] = []
        if misses and _cooling_down(name):
            # Cool-down only blocks the NETWORK path: cached results still
            # serve while a source is cooling down (the cache is the
            # resilience mechanism, not an optimization).
            report[name] = {"papers": 0,
                            "status": "skipped network (cool-down after failure)"}
            rows: List[dict] = []
            for c in cached:
                if c:
                    for row in c:
                        row["source_name"] = name
                    rows.extend(c)
            return rows
        if misses:
            try:
                async with _mk_client() as client:
                    remaining = max(0.1, deadline - loop.time())
                    client.timeout = httpx.Timeout(min(SOURCE_TIMEOUT_S, remaining))
                    fetched = await asyncio.wait_for(
                        asyncio.gather(*(fn(client, v, limit) for v in misses),
                                       return_exceptions=True),
                        timeout=max(0.1, deadline - loop.time()),
                    )
            except Exception as net_exc:
                # Network path failed entirely (deadline/timeout). Cached
                # variants must still serve — the cache is the resilience
                # mechanism, so never let a network failure discard hits.
                rows_c: List[dict] = []
                for c in cached:
                    if c:
                        for row in c:
                            row["source_name"] = name
                        rows_c.extend(c)
                _mark_failure(name, net_exc)
                report[name] = {
                    "papers": len(rows_c),
                    "status": (f"degraded: network ({type(net_exc).__name__}); "
                               f"{len(rows_c)} cached rows served"),
                }
                return rows_c
        # stitch results back in variant order, caching successes
        by_variant: Dict[str, List[dict]] = {}
        miss_iter = iter(fetched)
        errors = 0
        for v, c, k in zip(variants, cached, keys):
            if c is not None:
                by_variant[v] = c
            else:
                r = next(miss_iter)
                if isinstance(r, Exception):
                    errors += 1
                else:
                    by_variant[v] = r
                    _cache_put(k, r)
        rows: List[dict] = []
        for v in variants:
            for row in by_variant.get(v, []):
                row["source_name"] = name
                rows.append(row)
        if errors and not rows:
            first_err = next((r for r in fetched if isinstance(r, Exception)), None)
            _mark_failure(name, first_err)
            report[name] = {
                "papers": 0,
                "status": f"degraded: {errors}/{len(variants)} variants failed",
            }
        else:
            _mark_success(name)
            status = "ok"
            if errors:
                status = f"ok ({errors}/{len(variants)} variants failed)"
            report[name] = {"papers": len(rows), "status": status}
        return rows
    except Exception as exc:  # noqa: BLE001 — degradation is the contract
        _mark_failure(name, exc)
        report[name] = {"papers": 0, "status": f"degraded: {type(exc).__name__}"}
        log.info("source %s degraded: %s", name, exc)
        return []


def _dedupe_keep_order(items: List[str]) -> List[str]:
    return list(dict.fromkeys(items))


async def _fetch_s2_seq(client: httpx.AsyncClient, variants: List[str], limit: int) -> List[dict]:
    """Sequential variant fetching for S2: concurrent bursts to the anonymous
    shared pool draw 429s on the second call (live-verified); the same calls
    one at a time pass. The stage deadline bounds total exposure."""
    rows: List[dict] = []
    for v in variants:
        try:
            rows.extend(await _fetch_s2(client, v, limit))
        except Exception as exc:  # noqa: BLE001
            log.info("s2 variant degraded: %s", exc)
    return rows


async def federated_retrieval(
    variants: List[str], per_source_limit: int, deadline_s: float
) -> tuple[List[dict], Dict]:
    """Stage 1 entry point: fire all sources x variants in parallel.

    EPMC/OpenAlex get the deduplicated variant set; S2 gets one call (keyed
    limit is 1 rps). Returns (paper_rows, sources_report). Never raises.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadline_s
    report: Dict = {}
    uniq = _dedupe_keep_order(variants)
    jobs = [
        # EPMC throttles concurrent core requests: 3 highest-value variants,
        # fetched sequentially (live-verification fix).
        ("europepmc", _fetch_epmc_seq, uniq[:3], per_source_limit, deadline, report),
        ("openalex", _fetch_openalex, uniq, per_source_limit, deadline, report),
        # S2: the keyword and natural-language variants return materially
        # different result sets; both run sequentially (bursts draw 429s).
        ("semanticscholar", _fetch_s2_seq, uniq[:2], per_source_limit, deadline, report),
        # arXiv ToU: 1 request / 3 s, single connection -> one supplementary
        # call with the keyword variant.
        ("arxiv", _fetch_arxiv, uniq[:1], 30, deadline, report),
    ]
    results = await asyncio.gather(*(
        _fetch_source(n, fn, vs, lim, dl, report) for n, fn, vs, lim, dl, _ in jobs
    ))
    papers: List[dict] = []
    for rows in results:
        papers.extend(rows)
    return papers, report


# ---------------------------------------------------------------- Stage 2

class _Deduper:
    """(doi, normalized-text) dedup across sources; first occurrence wins."""

    def __init__(self) -> None:
        self._seen: set = set()

    def add_paper(self, doi: Optional[str]) -> bool:
        key = ("p", doi or "")
        if doi and key in self._seen:
            return False
        self._seen.add(key)
        return True

    def add_sentence(self, doi: Optional[str], text: str) -> bool:
        norm = re.sub(r"\W+", " ", text.lower()).strip()
        key = ("s", doi or "", norm)
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


def assemble_sentences(
    papers: List[dict], max_sentences: int = 1600
) -> List[CandidateSentence]:
    """Stage 2: payloads -> deduplicated, quality-gated CandidateSentences."""
    out: List[CandidateSentence] = []
    deduper = _Deduper()
    rank = 0
    for p in papers:
        if not p.get("abstract"):
            continue
        if not deduper.add_paper(p.get("doi")):
            continue
        ref = PaperRef(
            title=(p.get("title") or "").strip(),
            authors=p.get("authors") or "Unknown",
            year=p.get("year"),
            doi=p.get("doi"),
            url=p.get("url"),
            venue=p.get("venue"),
            citation_count=p.get("citation_count"),
            source=str(p.get("source_name", "")),
            open_access=bool(p.get("open_access")),
        )
        for sent in split_sentences(p["abstract"]):
            if not _is_plausible_evidence(sent):
                continue
            if not deduper.add_sentence(ref.doi, sent):
                continue
            out.append(
                CandidateSentence(text=sent, paper=ref, source=ref.source,
                                  source_rank=rank, in_body=False)
            )
            rank += 1
            if len(out) >= max_sentences:
                return out
    return out
