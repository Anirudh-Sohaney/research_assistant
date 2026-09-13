"""Evidence Engine — federated retrieval + LLM judging pipeline.

Retrieves papers from three academic sources (Europe PMC, OpenAlex, CORE),
extracts discussion/conclusion sections, and uses an LLM (via OpenRouter)
to classify which sentences support a given claim.

Sources:
  - Europe PMC: full-text BODY: search, open-access subset
  - OpenAlex: 240M+ works, title+abstract+fulltext search
  - CORE: 200M+ open-access works, full-text aggregation

Design contracts:
  - Never raises: every failure degrades gracefully
  - Disk cache (SQLite, 6h TTL) serves results when network is down
  - Cool-down prevents hammering failed sources
  - Hard deadline with per-source timeout clamping
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
from typing import Optional

import httpx

from evidence_engine.models import (
    EvidenceItem,
    EvidenceResult,
    PaperRef,
    RetrievalResult,
)

log = logging.getLogger("evidence_engine")

# ---------------------------------------------------------------- config

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
CORE_API_KEY = os.environ.get("CORE_API_KEY", "")
OPENALEX_API_KEY = os.environ.get("OPENALEX_API_KEY", "")

LLM_MODEL = "openai/gpt-4o-mini"
LLM_BATCH_SIZE = 8
LLM_RETRIES = 3
LLM_TIMEOUT_S = 30.0

SOURCE_TIMEOUT_S = 10.0
USER_AGENT = "evidence-engine/2.0 (academic evidence retrieval)"
CACHE_TTL_S = 6 * 3600
CACHE_PATH = pathlib.Path(__file__).parent / ".retrieval_cache.db"

# CORE uses a hardcoded query for the domain
CORE_QUERY = '"inverse kinematics" AND ("neural network" OR "MLP")'

# Section patterns for full-text XML extraction
_SECTION_PATTERNS = [
    (r"<title>\d*\.?\s*Discussion[s]?\s*</title>", "disc"),
    (r"<title>\d*\.?\s*Results and Discussion\s*</title>", "disc"),
    (r"<title>\d*\.?\s*Conclusions?\s*</title>", "conc"),
    (r"<title>\d*\.?\s*Concluding Remarks\s*</title>", "conc"),
]

# Stopwords for keyword extraction
_STOP = frozenset(
    "a an and are as at be by for from has have in is it its of on or "
    "that the this to with which into their than thus we our using used".split()
)

# ------------------------------------------------------- disk cache

_SQLITE_READY = False


def _cache_conn() -> sqlite3.Connection:
    global _SQLITE_READY
    con = sqlite3.connect(CACHE_PATH)
    if not _SQLITE_READY:
        con.execute(
            "CREATE TABLE IF NOT EXISTS cache(k TEXT PRIMARY KEY, ts REAL, payload TEXT)"
        )
        con.commit()
        _SQLITE_READY = True
    return con


def _cache_get(key: str) -> Optional[list[dict]]:
    try:
        row = _cache_conn().execute(
            "SELECT ts, payload FROM cache WHERE k=?", (key,)
        ).fetchone()
    except sqlite3.Error:
        return None
    if row is None or (time.time() - row[0]) > CACHE_TTL_S:
        return None
    try:
        return json.loads(row[1])
    except Exception:
        return None


def _cache_put(key: str, rows: list[dict]) -> None:
    if not rows:
        return
    try:
        con = _cache_conn()
        con.execute(
            "INSERT OR REPLACE INTO cache(k, ts, payload) VALUES(?,?,?)",
            (key, time.time(), json.dumps(rows)),
        )
        con.commit()
    except sqlite3.Error as exc:
        log.info("cache put failed: %s", exc)


def _cache_key(source: str, query: str, limit: int) -> str:
    return hashlib.sha1(f"{source}|{query}|{limit}".encode()).hexdigest()


# ------------------------------------------------------- cool-down

_COOL: dict[str, list] = {}


def _cooling_down(name: str) -> bool:
    if name not in _COOL:
        return False
    last_fail, fails = _COOL[name]
    window = 60 if fails <= 2 else 300
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
    if not raw:
        return None
    m = re.search(r"10\.\d{4,9}/\S+", raw)
    return m.group(0).rstrip(".") if m else None


def _first_author_et_al(names: list[str]) -> str:
    if not names:
        return "Unknown"
    return names[0] + (" et al." if len(names) > 1 else "")


def _reconstruct_abstract(inverted_index: Optional[dict]) -> str:
    if not inverted_index:
        return ""
    positions = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions)


def _keyword_terms(query: str, cap: int = 8) -> list[str]:
    words = [
        w
        for w in re.findall(r"[A-Za-z][A-Za-z-]+|\d+", query.lower())
        if w not in _STOP
    ]
    return list(dict.fromkeys(words))[:cap]


# ------------------------------------------------------- source adapters


async def _fetch_openalex(
    client: httpx.AsyncClient, query: str, limit: int
) -> list[dict]:
    select = (
        "id,doi,display_name,authorships,publication_year,"
        "primary_location,cited_by_count,abstract_inverted_index,open_access"
    )
    params = {"search": query, "per-page": min(limit, 100), "select": select}
    if OPENALEX_API_KEY:
        params["api_key"] = OPENALEX_API_KEY
    resp = await client.get("https://api.openalex.org/works", params=params)
    resp.raise_for_status()
    out = []
    for w in resp.json().get("results", []) or []:
        loc = w.get("primary_location") or {}
        src = (loc.get("source") or {}) or {}
        oa = w.get("open_access") or {}
        names = [
            a.get("author", {}).get("display_name") or ""
            for a in (w.get("authorships") or [])
        ]
        out.append(
            {
                "title": (w.get("display_name") or "").strip(),
                "authors": _first_author_et_al([n for n in names if n]),
                "year": w.get("publication_year"),
                "doi": _doi(w.get("doi")),
                "url": w.get("id"),
                "venue": src.get("display_name"),
                "citation_count": w.get("cited_by_count"),
                "abstract": _reconstruct_abstract(w.get("abstract_inverted_index")),
                "open_access": bool(oa.get("is_oa")),
            }
        )
    return out


async def _fetch_europepmc(
    client: httpx.AsyncClient, query: str, limit: int
) -> list[dict]:
    terms = _keyword_terms(query, cap=4)
    expr = " AND ".join(f'"{t}"' for t in terms) if terms else f'"{query}"'
    resp = await client.get(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        params={
            "query": f"BODY:({expr}) AND OPEN_ACCESS:Y",
            "format": "json",
            "pageSize": min(limit, 25),
            "resultType": "core",
        },
    )
    resp.raise_for_status()
    arts = (resp.json().get("resultList", {}) or {}).get("result", []) or []
    out = []
    for a in arts:
        astr = a.get("authorString", "") or ""
        names = [n.strip() for n in astr.split(",") if n.strip()]
        out.append(
            {
                "title": re.sub(r"\s+", " ", a.get("title", "") or "").strip(),
                "authors": _first_author_et_al(names),
                "year": (
                    int(a["pubYear"])
                    if str(a.get("pubYear", "")).isdigit()
                    else None
                ),
                "doi": _doi(a.get("doi")),
                "url": (
                    f"https://europepmc.org/article/{a.get('source', 'MED')}/"
                    f"{a.get('id', '')}"
                ),
                "venue": a.get("journalTitle", "") or None,
                "citation_count": (
                    int(a["citedByCount"])
                    if str(a.get("citedByCount", "")).isdigit()
                    else None
                ),
                "abstract": re.sub(
                    r"<[^>]+>", " ", a.get("abstractText", "") or ""
                ).strip(),
                "open_access": a.get("isOpenAccess") == "Y",
                "_pmcid": a.get("pmcid") or "",
            }
        )
    return out


async def _fetch_core(
    client: httpx.AsyncClient, query: str, limit: int
) -> list[dict]:
    resp = await client.get(
        "https://api.core.ac.uk/v3/search/works/",
        params={"q": query, "limit": min(limit, 10)},
        headers={"Authorization": f"Bearer {CORE_API_KEY}"},
    )
    if resp.status_code != 200:
        return []
    out = []
    for r in resp.json().get("results", []) or []:
        out.append(
            {
                "title": (r.get("title") or "").strip(),
                "authors": _first_author_et_al(
                    [a.get("name", "") for a in (r.get("authors") or [])]
                ),
                "year": r.get("yearPublished"),
                "doi": _doi(r.get("doi")),
                "url": r.get("id"),
                "venue": None,
                "citation_count": r.get("citationCount"),
                "abstract": r.get("abstract") or "",
                "open_access": True,
                "_fulltext": r.get("fullText") or "",
            }
        )
    return out


# ------------------------------------------------------- full-text section extraction


def _extract_sections(xml: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for pat, cat in _SECTION_PATTERNS:
        m = re.search(
            pat + r"(.*?)(?=<sec[ >]|</body)", xml, re.DOTALL | re.IGNORECASE
        )
        if m:
            text = re.sub(r"<[^>]+>", " ", m.group(1))
            text = re.sub(r"\s+", " ", text).strip()
            if len(text.split()) > len(found.get(cat, "").split()):
                found[cat] = text
    return found


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) > 5]


# ------------------------------------------------------- LLM judging via OpenRouter


async def _llm_judge(claim: str, sentences: list[str]) -> list[tuple[int, float]]:
    """Send sentences to OpenRouter in batches; return (index, confidence) pairs."""
    results: list[tuple[int, float]] = []
    for start in range(0, len(sentences), LLM_BATCH_SIZE):
        batch = sentences[start : start + LLM_BATCH_SIZE]
        lines = "\n".join(f"{i}: {s[:250]}" for i, s in enumerate(batch))
        prompt = (
            f'Which sentences SUPPORT this claim: "{claim}"?\n'
            f'Return ONLY a JSON array: [{{"id": 0, "confidence": 0.9}}]\n'
            f'Only include supporting sentences. Empty [] if none.\n\n{lines}'
        )
        for attempt in range(LLM_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=LLM_TIMEOUT_S) as c:
                    r = await c.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": LLM_MODEL,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.0,
                            "max_tokens": 500,
                        },
                    )
                    if r.status_code != 200:
                        continue
                    content = (
                        r.json()
                        .get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                        or ""
                    )
                    match = re.search(r"\[.*\]", content, re.DOTALL)
                    if match:
                        for item in json.loads(match.group()):
                            if isinstance(item, dict) and "id" in item:
                                results.append(
                                    (
                                        item["id"] + start,
                                        item.get("confidence", 0.7),
                                    )
                                )
                        break
            except Exception:
                if attempt < LLM_RETRIES - 1:
                    await asyncio.sleep(1)
    return results


# ------------------------------------------------------- per-source runner


def _to_ref(row: dict, source: str) -> PaperRef:
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
        source=source,
    )


async def _run_source(
    name: str,
    fetch_fn,
    query: str,
    limit: int,
    deadline: float,
    loop,
) -> tuple[list[PaperRef], dict, list[dict]]:
    """Run one source: cache-first, deadline-bounded, never raises.

    Returns (papers, report, raw_dicts) where raw_dicts carry source-specific
    fields like _fulltext (CORE) and _pmcid (Europe PMC).
    """
    report: dict = {"papers": 0, "status": "ok"}
    key = _cache_key(name, query, limit)

    cached = _cache_get(key)
    if cached is not None:
        return [_to_ref(r, name) for r in cached], report, cached

    if _cooling_down(name):
        report["status"] = "skipped (cool-down)"
        return [], report, []

    try:
        remaining = max(0.5, deadline - loop.time())
        async with httpx.AsyncClient(
            timeout=min(SOURCE_TIMEOUT_S, remaining),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            rows = await asyncio.wait_for(
                fetch_fn(client, query, limit),
                timeout=remaining,
            )
            _cache_put(key, rows)
            _mark_success(name)
            papers = [_to_ref(r, name) for r in rows]
            report["papers"] = len(papers)
            return papers, report, rows
    except Exception as exc:
        _mark_failure(name)
        log.info("source %s failed: %s", name, exc)
        report["status"] = f"degraded: {type(exc).__name__}"
        return [], report, []


# ------------------------------------------------------- deduplication


def dedupe_papers(papers: list[PaperRef]) -> list[PaperRef]:
    seen: set = set()
    out: list[PaperRef] = []
    for p in papers:
        tnorm = re.sub(r"\W+", " ", p.title.lower()).strip()
        key = ("doi", p.doi) if p.doi else ("title", tnorm, p.year)
        if key in seen or (not p.doi and not tnorm):
            continue
        seen.add(key)
        out.append(p)
    return out


# ------------------------------------------------------- query building


def build_queries(claim: str) -> list[str]:
    kw = " ".join(_keyword_terms(claim))
    nat = re.sub(r"\s+", " ", claim).strip()
    return list(dict.fromkeys(q for q in (kw, nat) if q))


# ------------------------------------------------------- pipeline


async def retrieve_papers(
    claim: str, per_source_limit: int = 100, deadline_s: float = 8.0
) -> RetrievalResult:
    """Fan out to Europe PMC, OpenAlex, and CORE in parallel.

    Returns deduplicated papers with per-source status reports.
    Never raises.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadline_s
    queries = build_queries(claim)

    # EPMC needs sequential variants (concurrent bursts draw 429s)
    epmc_query = " AND ".join(f'"{q}"' for q in queries) if queries else f'"{claim}"'

    jobs = [
        ("europepmc", _fetch_europepmc, epmc_query),
        ("openalex", _fetch_openalex, " ".join(queries) if queries else claim),
        ("core", _fetch_core, CORE_QUERY),
    ]

    started = time.perf_counter()
    results = await asyncio.gather(
        *(_run_source(name, fn, q, per_source_limit, deadline, loop) for name, fn, q in jobs)
    )

    papers: list[PaperRef] = []
    sources: dict = {}
    raw_by_doi: dict[str, dict] = {}  # doi -> raw dict for fulltext access
    for (name, *_), (refs, report, raw_rows) in zip(jobs, results):
        papers.extend(refs)
        sources[name] = report
        for row in raw_rows:
            doi = row.get("doi") or row.get("title", "")
            raw_by_doi[doi] = row

    unique = dedupe_papers(papers)
    unique_raw = [raw_by_doi.get(p.doi or p.title, {}) for p in unique]
    wall = (time.perf_counter() - started) * 1000
    return RetrievalResult(papers=unique, sources=sources, wall_ms=wall, raw=unique_raw)


async def find_evidence(
    claim: str,
    per_source_limit: int = 100,
    retrieval_deadline_s: float = 8.0,
    top_n: int = 10,
) -> EvidenceResult:
    """Full pipeline: retrieve papers, extract sections, judge with LLM.

    Steps:
      1. Federated retrieval (EPMC + OpenAlex + CORE)
      2. Extract discussion/conclusion sentences from full-text XML
      3. LLM judge (OpenRouter) classifies supporting sentences
      4. Return top N evidence items ranked by confidence
    """
    t0 = time.perf_counter()

    # Step 1: retrieve
    retrieval = await retrieve_papers(claim, per_source_limit, retrieval_deadline_s)
    t1 = time.perf_counter()
    log.info(
        "retrieved %d papers in %.1fs [%s]",
        len(retrieval.papers),
        (t1 - t0),
        retrieval.summary(),
    )

    # Step 2: extract sentences from full-text sources
    sentences: list[str] = []
    meta: list[dict] = []

    # Extract from papers that have full-text data (CORE)
    for paper, raw in zip(retrieval.papers, retrieval.raw):
        fulltext = raw.get("_fulltext", "") or ""
        if len(fulltext) < 500:
            continue
        lower = fulltext.lower()
        for marker in ["discussion", "conclusion"]:
            pos = lower.find(marker)
            if pos >= 0:
                chunk = fulltext[pos : pos + 3000]
                for end in ["references", "acknowledgment"]:
                    ep = chunk.lower().find(end, 100)
                    if ep > 0:
                        chunk = chunk[:ep]
                        break
                for s in _split_sentences(chunk):
                    sentences.append(s)
                    meta.append(
                        {"title": paper.title, "url": paper.url, "section": marker[:4]}
                    )
                break

    # Fetch full-text XML from Europe PMC for papers with PMCIDs
    epmc_papers = [
        (p, r) for p, r in zip(retrieval.papers, retrieval.raw)
        if p.source == "europepmc"
    ]
    if epmc_papers:
        async with httpx.AsyncClient(timeout=SOURCE_TIMEOUT_S) as c:
            for paper, raw in epmc_papers[:20]:
                pmcid = raw.get("_pmcid", "")
                if not pmcid:
                    continue
                try:
                    r = await c.get(
                        f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML",
                        timeout=10.0,
                    )
                    if r.status_code == 200:
                        for cat, text in _extract_sections(r.text).items():
                            for s in _split_sentences(text):
                                sentences.append(s)
                                meta.append(
                                    {
                                        "title": paper.title,
                                        "url": paper.url,
                                        "section": cat,
                                    }
                                )
                except Exception:
                    continue

    t2 = time.perf_counter()
    log.info("extracted %d sentences in %.1fs", len(sentences), (t2 - t1))

    if not sentences:
        return EvidenceResult(
            claim=claim,
            items=[],
            total_papers=len(retrieval.papers),
            total_sentences=0,
            wall_ms=(time.perf_counter() - t0) * 1000,
        )

    # Step 3: LLM judge
    judgments = await _llm_judge(claim, sentences)
    judgments.sort(key=lambda x: x[1], reverse=True)
    t3 = time.perf_counter()
    log.info("LLM judged %d supporting sentences in %.1fs", len(judgments), (t3 - t2))

    # Step 4: build evidence items
    seen: set = set()
    items: list[EvidenceItem] = []
    for idx, conf in judgments:
        m = meta[idx]
        dedup_key = (m["title"], sentences[idx][:80])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        items.append(
            EvidenceItem(
                quote=sentences[idx],
                paper=PaperRef(
                    title=m["title"],
                    authors="",
                    year=None,
                    doi=None,
                    url=m.get("url"),
                    source="",
                ),
                confidence=conf,
                section=m.get("section", ""),
            )
        )
        if len(items) >= top_n:
            break

    total = time.perf_counter() - t0
    return EvidenceResult(
        claim=claim,
        items=items,
        total_papers=len(retrieval.papers),
        total_sentences=len(sentences),
        wall_ms=total * 1000,
    )


def find_evidence_sync(claim: str, **kwargs) -> EvidenceResult:
    """Synchronous wrapper."""
    return asyncio.run(find_evidence(claim, **kwargs))
