"""Evidence Engine — Part 1: federated paper extraction from peer-reviewed sources.

Goal: given a claim (any text), pull the papers potentially associated with it
from three peer-reviewed literature APIs, in parallel, under a hard deadline:

  * Europe PMC        — Lucene BODY: search over open-access FULL TEXTS
                        (finds papers whose body — not just abstract — matches)
  * OpenAlex          — 240M+ works; `search` spans title+abstract+fulltext
  * Semantic Scholar  — 200M+ papers, best metadata quality (citations, DOIs);
                        anonymous pool is bursty, so requests carry a retry ladder

Design contracts (each live-verified in earlier iterations of this module):

  * Never raise: every failure degrades to a per-source status string in the
    report; other sources are unaffected.
  * Disk cache: every successful per-variant fetch is persisted (6 h TTL) and
    served on later runs even while the network or the source is down. The
    cache is the resilience mechanism, not an optimization.
  * Cool-down: a source that just failed stops hitting the network for a
    short tiered window; cached results still serve.
  * Dedup: cross-source and cross-variant duplicates collapse (DOI first,
    normalized title+year fallback).
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
from typing import Callable, Dict, List, Optional

import httpx

from evidence_engine.models import PaperRef, RetrievalResult

log = logging.getLogger("evidence_engine.sources")

# ---------------------------------------------------------------- config

SOURCE_TIMEOUT_S = 10.0     # per-request ceiling; the stage deadline clamps it
USER_AGENT = "evidence-engine/2.0 (academic evidence retrieval)"
CACHE_TTL_S = 6 * 3600      # retrieval cache lifetime
CACHE_PATH = pathlib.Path(__file__).parent / ".retrieval_cache.db"

_S2_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
_OPENALEX_KEY = os.environ.get("OPENALEX_API_KEY", "")

# ------------------------------------------------------- disk cache

_SQLITE_READY = False


def _cache_conn() -> sqlite3.Connection:
    global _SQLITE_READY
    con = sqlite3.connect(CACHE_PATH)
    if not _SQLITE_READY:
        con.execute("CREATE TABLE IF NOT EXISTS cache("
                    "k TEXT PRIMARY KEY, ts REAL, payload TEXT)")
        con.commit()
        _SQLITE_READY = True
    return con


def _cache_get(key: str) -> Optional[List[dict]]:
    try:
        row = _cache_conn().execute(
            "SELECT ts, payload FROM cache WHERE k=?", (key,)).fetchone()
    except sqlite3.Error:
        return None
    if row is None or (time.time() - row[0]) > CACHE_TTL_S:
        return None
    try:
        return json.loads(row[1])
    except Exception:  # noqa: BLE001 — corrupt row == miss
        return None


def _cache_put(key: str, rows: List[dict]) -> None:
    if not rows:
        return  # never cache empty results: a throttled fetch must not poison a query
    try:
        con = _cache_conn()
        con.execute("INSERT OR REPLACE INTO cache(k, ts, payload) VALUES(?,?,?)",
                    (key, time.time(), json.dumps(rows)))
        con.commit()
    except sqlite3.Error as exc:  # cache is best-effort
        log.info("cache put failed: %s", exc)


def _ckey(source: str, variant: str, limit: int) -> str:
    return hashlib.sha1(f"{source}|{variant}|{limit}".encode()).hexdigest()


# ------------------------------------------------------- cool-down

_COOL: Dict[str, List] = {}  # name -> [last_fail_ts, consecutive_failures]


def _cooling_down(name: str) -> bool:
    if name not in _COOL:
        return False
    last_fail, fails = _COOL[name]
    window = 60 if fails <= 2 else 300  # tiered: brief breather, then longer
    return (time.time() - last_fail) < window


def _mark_failure(name: str) -> None:
    if name not in _COOL:
        _COOL[name] = [time.time(), 1]
    else:
        _COOL[name][0] = time.time()
        _COOL[name][1] += 1


def _mark_success(name: str) -> None:
    _COOL.pop(name, None)


# ------------------------------------------------------- normalizers

def _doi(raw: Optional[str]) -> Optional[str]:
    """Extract a bare DOI from the many shapes APIs return."""
    if not raw:
        return None
    m = re.search(r"10\.\d{4,9}/\S+", raw)
    return m.group(0).rstrip(".") if m else None


def _first_author_et_al(names: List[str]) -> str:
    if not names:
        return "Unknown"
    return names[0] + (" et al." if len(names) > 1 else "")


def reconstruct_abstract(inverted_index: Optional[dict]) -> str:
    """OpenAlex abstracts arrive as {word: [positions]}; rebuild the sentence."""
    if not inverted_index:
        return ""
    positions: List[tuple] = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions)


# ------------------------------------------------------- adapters
# Contract: (client, query, limit) -> list[row-dict]; raises on failure.
# Row-dicts are source-agnostic: title/authors/year/doi/url/venue/
# citation_count/abstract/open_access.

_STOP = set("""a an and are as at be by for from has have in is it its of on or
that the this to with which into their than thus we our using used""".split())


def _keyword_terms(query: str, cap: int = 8) -> List[str]:
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z-]+|\d+", query.lower())
             if w not in _STOP]
    return list(dict.fromkeys(words))[:cap]


async def fetch_europepmc(client: httpx.AsyncClient, query: str,
                          limit: int) -> List[dict]:
    """Europe PMC: strict AND of quoted content words inside BODY (full text),
    open-access subset (their OA corpus carries the machine-readable bodies).
    Lucene wants quoted phrases; a bare natural-language string hits nothing."""
    terms = _keyword_terms(query, cap=4)
    expr = " AND ".join(f'"{t}"' for t in terms) if terms else f'"{query}"'
    resp = await client.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={"query": f"BODY:({expr}) AND OPEN_ACCESS:Y", "format": "json",
                "pageSize": min(limit, 25), "resultType": "core"},
    )
    resp.raise_for_status()
    arts = (resp.json().get("resultList", {}) or {}).get("result", []) or []
    out = []
    for a in arts:
        astr = a.get("authorString", "") or ""
        names = [n.strip() for n in astr.split(",") if n.strip()]
        out.append({
            "title": re.sub(r"\s+", " ", a.get("title", "") or "").strip(),
            "authors": _first_author_et_al(names),
            "year": int(a["pubYear"]) if str(a.get("pubYear", "")).isdigit() else None,
            "doi": _doi(a.get("doi")),
            "url": (f"https://europepmc.org/article/{a.get('source', 'MED')}/"
                    f"{a.get('id', '')}"),
            "venue": a.get("journalTitle", "") or None,
            "citation_count": (int(a["citedByCount"])
                               if str(a.get("citedByCount", "")).isdigit() else None),
            "abstract": re.sub(r"<[^>]+>", " ", a.get("abstractText", "") or "").strip(),
            "open_access": a.get("isOpenAccess") == "Y",
        })
    return out


async def fetch_openalex(client: httpx.AsyncClient, query: str,
                         limit: int) -> List[dict]:
    """OpenAlex: default `search` (relevance over title+abstract+fulltext).
    One call per query — the anonymous daily budget is the scarce resource."""
    select = ("id,doi,display_name,authorships,publication_year,"
              "primary_location,cited_by_count,abstract_inverted_index,open_access")
    params = {"search": query, "per-page": min(limit, 100), "select": select}
    if _OPENALEX_KEY:
        params["api_key"] = _OPENALEX_KEY
    resp = await client.get("https://api.openalex.org/works", params=params)
    resp.raise_for_status()
    out = []
    for w in resp.json().get("results", []) or []:
        loc = w.get("primary_location") or {}
        src = (loc.get("source") or {}) or {}
        oa = w.get("open_access") or {}
        names = [a.get("author", {}).get("display_name") or ""
                 for a in (w.get("authorships") or [])]
        out.append({
            "title": (w.get("display_name") or "").strip(),
            "authors": _first_author_et_al([n for n in names if n]),
            "year": w.get("publication_year"),
            "doi": _doi(w.get("doi")),
            "url": w.get("id"),
            "venue": src.get("display_name"),
            "citation_count": w.get("cited_by_count"),
            "abstract": reconstruct_abstract(w.get("abstract_inverted_index")),
            "open_access": bool(oa.get("is_oa")),
        })
    return out


async def fetch_semanticscholar(client: httpx.AsyncClient, query: str,
                                limit: int) -> List[dict]:
    """Semantic Scholar: relevance search with a retry ladder (0.5/2/6 s) —
    the anonymous shared pool 429s in bursts, and patience wins (live-verified:
    attempt 3 succeeds where attempt 1 fails)."""
    params = {
        "query": query,
        "limit": min(limit, 100),
        "fields": "title,authors,year,abstract,externalIds,venue,citationCount,isOpenAccess",
    }
    headers = {"x-api-key": _S2_KEY} if _S2_KEY else None
    resp = None
    for backoff in (0.0, 0.5, 2.0, 6.0):
        if backoff:
            await asyncio.sleep(backoff)
        try:
            r = await client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params=params, headers=headers)
            r.raise_for_status()
            resp = r
            break
        except Exception:  # noqa: BLE001 — retry then degrade
            resp = None
    if resp is None:
        raise RuntimeError("semanticscholar: all retry attempts failed")
    out = []
    for p in resp.json().get("data", []) or []:
        names = [a.get("name") or "" for a in (p.get("authors") or [])]
        out.append({
            "title": (p.get("title") or "").strip(),
            "authors": _first_author_et_al([n for n in names if n]),
            "year": p.get("year"),
            "doi": _doi((p.get("externalIds") or {}).get("DOI")),
            "url": p.get("url"),
            "venue": p.get("venue") or None,
            "citation_count": p.get("citationCount"),
            "abstract": p.get("abstract") or "",
            "open_access": bool(p.get("isOpenAccess")),
        })
    return out


# ------------------------------------------------------- per-source runner

def _mk_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=SOURCE_TIMEOUT_S,
                             headers={"User-Agent": USER_AGENT},
                             follow_redirects=True)


async def _run_source(name: str,
                      fn: Callable[[httpx.AsyncClient, str, int], List[dict]],
                      variants: List[str], limit: int, deadline: float,
                      loop, sequential: bool = False) -> tuple[List[PaperRef], dict]:
    """Run one source over its variants: cache-first, deadline-bounded, never
    raises. `sequential=True` for sources whose throttling is concurrency-
    sensitive (EPMC). Every variant success is cached immediately, so a later
    variant's failure cannot cost an earlier one's results."""
    report = {"papers": 0, "status": "ok"}
    try:
        keys = [_ckey(name, v, limit) for v in variants]
        cached = [_cache_get(k) for k in keys]
        misses = [v for v, c in zip(variants, cached) if c is None]

        fetched: List = []
        if misses and _cooling_down(name):
            # Cool-down blocks only the network path; cached rows still serve.
            fetched = [Exception(f"{name}: skipped network (cool-down)")] * len(misses)
        elif misses:
            try:
                async with _mk_client() as client:
                    remaining = max(0.5, deadline - loop.time())
                    client.timeout = httpx.Timeout(min(SOURCE_TIMEOUT_S, remaining))
                    if sequential:
                        fetched = []
                        for v in misses:
                            try:
                                fetched.append(await fn(client, v, limit))
                            except Exception as exc:  # noqa: BLE001
                                fetched.append(exc)
                    else:
                        fetched = await asyncio.wait_for(
                            asyncio.gather(*(fn(client, v, limit) for v in misses),
                                           return_exceptions=True),
                            timeout=max(0.5, deadline - loop.time()))
            except Exception as net_exc:  # noqa: BLE001
                _mark_failure(name)
                served = sum(len(c) for c in cached if c)
                report.update(papers=served,
                              status=f"degraded: network ({type(net_exc).__name__})"
                                     + (f"; {served} cached rows" if served else ""))
                return _refs_from_cache(cached, name), report

        rows_by_variant: Dict[str, List[dict]] = {}
        errors = 0
        miss_iter = iter(fetched)
        for v, c, k in zip(variants, cached, keys):
            if c is not None:
                rows_by_variant[v] = c
            else:
                r = next(miss_iter)
                if isinstance(r, Exception):
                    errors += 1
                    log.info("%s variant failed: %s", name, r)
                else:
                    rows_by_variant[v] = r
                    _cache_put(k, r)

        rows: List[dict] = []
        for v in variants:
            rows.extend(rows_by_variant.get(v, []))
        papers = [_to_ref(r, name) for r in rows]

        if errors and not papers:
            _mark_failure(name)
            report.update(papers=0,
                          status=f"degraded: {errors}/{len(variants)} variants failed")
        else:
            _mark_success(name)
            report.update(papers=len(papers),
                          status="ok" if not errors else
                          f"ok ({errors}/{len(variants)} variants failed)")
        return papers, report
    except Exception as exc:  # noqa: BLE001 — degradation is the contract
        _mark_failure(name)
        log.info("source %s degraded: %s", name, exc)
        report.update(papers=0, status=f"degraded: {type(exc).__name__}")
        return [], report


def _refs_from_cache(cached: List[Optional[List[dict]]], name: str) -> List[PaperRef]:
    rows: List[dict] = []
    for c in cached:
        if c:
            rows.extend(c)
    return [_to_ref(r, name) for r in rows]


def _to_ref(row: dict, name: str) -> PaperRef:
    return PaperRef(
        title=row.get("title") or "",
        authors=row.get("authors") or "Unknown",
        year=row.get("year"),
        doi=row.get("doi"),
        url=row.get("url"),
        venue=row.get("venue"),
        citation_count=row.get("citation_count"),
        abstract=row.get("abstract") or "",
        open_access=bool(row.get("open_access")),
        source=name,
    )


# ------------------------------------------------------- dedup

def dedupe_papers(papers: List[PaperRef]) -> List[PaperRef]:
    """Collapse duplicates: DOI key first, normalized title+year fallback.
    First occurrence wins."""
    seen: set = set()
    out: List[PaperRef] = []
    for p in papers:
        tnorm = re.sub(r"\W+", " ", p.title.lower()).strip()
        key = ("doi", p.doi) if p.doi else ("title", tnorm, p.year)
        if key in seen or (not p.doi and not tnorm):
            continue
        seen.add(key)
        out.append(p)
    return out


# ------------------------------------------------------- public API

def build_queries(claim: str) -> List[str]:
    """Two complementary query shapes: a keyword variant (content words,
    stopword-free — best for exact-match backends like EPMC) and the
    natural-language claim itself (best for relevance-ranked backends
    like OpenAlex/S2)."""
    kw = " ".join(_keyword_terms(claim))
    nat = re.sub(r"\s+", " ", claim).strip()
    return list(dict.fromkeys(q for q in (kw, nat) if q))


async def extract_papers(claim: str, per_source_limit: int = 100,
                         deadline_s: float = 8.0) -> RetrievalResult:
    """Fan out over the three peer-reviewed sources in parallel; return a
    deduplicated paper set plus a per-source report. Never raises."""
    variants = build_queries(claim)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadline_s

    jobs = [
        # EPMC throttles concurrent core requests -> sequential variants.
        ("europepmc", fetch_europepmc, variants, per_source_limit, True),
        ("openalex", fetch_openalex, variants, per_source_limit, False),
        ("semanticscholar", fetch_semanticscholar, variants, per_source_limit, False),
    ]
    started = time.perf_counter()
    results = await asyncio.gather(*(
        _run_source(name, fn, vs, lim, deadline, loop, seq)
        for name, fn, vs, lim, seq in jobs))
    papers: List[PaperRef] = []
    sources: Dict[str, dict] = {}
    for (name, *_), (refs, report) in zip(jobs, results):
        papers.extend(refs)
        sources[name] = report
    unique = dedupe_papers(papers)
    wall = (time.perf_counter() - started) * 1000
    return RetrievalResult(papers=unique, sources=sources, wall_ms=wall)


def extract_papers_sync(claim: str, **kw) -> RetrievalResult:
    """Synchronous convenience wrapper (the hotkey app is sync)."""
    return asyncio.run(extract_papers(claim, **kw))
