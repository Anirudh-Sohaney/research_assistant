"""Minimal evidence RAG: find papers, extract D+C, LLM-classify supports, return top 10."""
import asyncio, httpx, re, time, json, sys, os

API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
CORE_KEY = os.environ.get("CORE_API_KEY", "")
LLM = "openai/gpt-4o-mini"

SEC_PATS = [
    r'<title>\d*\.?\s*Discussion[s]?\s*</title>',
    r'<title>\d*\.?\s*Results and Discussion\s*</title>',
    r'<title>\d*\.?\s*Conclusions?\s*</title>',
    r'<title>\d*\.?\s*Concluding Remarks\s*</title>',
]


def extract_sections(xml):
    found = {}
    for pat in SEC_PATS:
        m = re.search(pat + r'(.*?)(?=<sec[ >]|</body)', xml, re.DOTALL | re.IGNORECASE)
        if m:
            text = re.sub(r'<[^>]+>', ' ', m.group(1))
            text = re.sub(r'\s+', ' ', text).strip()
            cat = "disc" if "discuss" in pat.lower() else "conc"
            if len(text.split()) > len(found.get(cat, "").split()):
                found[cat] = text
    return found


def split_sents(text):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if len(s.split()) > 5]


async def llm_supports(claim, sentences):
    results = []
    for start in range(0, len(sentences), 8):
        batch = sentences[start:start + 8]
        lines = "\n".join(f"{i}: {s[:250]}" for i, s in enumerate(batch))
        prompt = (
            f'Which sentences SUPPORT this claim: "{claim}"?\n'
            f'Return ONLY a JSON array: [{{"id": 0, "confidence": 0.9}}]\n'
            f'Only include supporting sentences. Empty [] if none.\n\n{lines}'
        )
        for _ in range(3):
            try:
                async with httpx.AsyncClient(timeout=30.0) as c:
                    r = await c.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                        json={"model": LLM, "messages": [{"role": "user", "content": prompt}],
                              "temperature": 0.0, "max_tokens": 500},
                    )
                    if r.status_code != 200:
                        continue
                    content = r.json().get("choices", [{}])[0].get("message", {}).get("content", "") or ""
                    if not content:
                        continue
                    match = re.search(r'\[.*\]', content, re.DOTALL)
                    if match:
                        for item in json.loads(match.group()):
                            if isinstance(item, dict) and "id" in item:
                                results.append((item["id"] + start, item.get("confidence", 0.7)))
                        break
            except:
                await asyncio.sleep(1)
    return results


async def run(claim):
    t0 = time.perf_counter()

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
        q = '("MLP" OR "multilayer perceptron" OR "neural network" OR "deep learning") AND ("inverse kinematics" OR "kinematic") AND (OPEN_ACCESS:Y) AND (IN_EPMC:Y)'
        r = await c.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                         params={"query": q, "format": "json", "pageSize": 25, "resultType": "core"})
        arts = r.json().get("resultList", {}).get("result", [])

        async def fetch(pmcid, title):
            try:
                r2 = await c.get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML", timeout=10.0)
                return (pmcid, r2.text, title) if r2.status_code == 200 else None
            except:
                return None

        tasks = [fetch(a["pmcid"], a.get("title", "")) for a in arts if a.get("pmcid")]
        papers = [x for x in await asyncio.gather(*tasks) if x]

        r3 = await c.get("https://api.core.ac.uk/v3/search/works/",
                         params={"q": '"inverse kinematics" AND ("neural network" OR "MLP")', "limit": 10},
                         headers={"Authorization": f"Bearer {CORE_KEY}"})
        core = r3.json().get("results", []) if r3.status_code == 200 else []

    t1 = time.perf_counter()
    print(f"[1] Retrieved {len(papers)} EPMC + {len(core)} CORE papers ({t1-t0:.1f}s)")

    sents, meta = [], []
    for pmcid, xml, title in papers:
        for cat, text in extract_sections(xml).items():
            for s in split_sents(text):
                sents.append(s)
                meta.append({"title": title, "pmcid": pmcid, "section": cat})
    for r in core:
        ft = r.get("fullText") or ""
        if len(ft) > 500:
            lower = ft.lower()
            for marker in ["discussion", "conclusion"]:
                pos = lower.find(marker)
                if pos >= 0:
                    chunk = ft[pos:pos+3000]
                    for end in ["references", "acknowledgment"]:
                        ep = chunk.lower().find(end, 100)
                        if ep > 0:
                            chunk = chunk[:ep]
                            break
                    for s in split_sents(chunk):
                        sents.append(s)
                        meta.append({"title": r.get("title", ""), "pmcid": None, "section": marker[:4]})
                    break

    print(f"[2] Extracted {len(sents)} sentences ({time.perf_counter()-t1:.1f}s)")

    t2 = time.perf_counter()
    supports = await llm_supports(claim, sents)
    supports.sort(key=lambda x: x[1], reverse=True)
    top = supports[:10]

    print(f"[3] LLM classified ({time.perf_counter()-t2:.1f}s)")

    print(f"\n{'='*60}")
    print(f"EVIDENCE FOR: {claim}")
    print(f"{'='*60}")
    seen = set()
    count = 0
    for idx, conf in top:
        m = meta[idx]
        key = (m["title"], sents[idx][:80])
        if key in seen:
            continue
        seen.add(key)
        count += 1
        print(f"\n{count}. [SUPPORTS] conf={conf:.2f}")
        print(f"   Paper: {m['title']}")
        print(f"   {sents[idx][:200]}")
        if m.get("pmcid"):
            print(f"   https://europepmc.org/article/PMC/{m['pmcid']}")
        if count >= 10:
            break

    total = time.perf_counter() - t0
    print(f"\n{'='*60}")
    print(f"Total: {total:.1f}s | {count} evidence from {len(papers)+len(core)} papers")


if __name__ == "__main__":
    claim = sys.argv[1] if len(sys.argv) > 1 else "MLP is a strong choice for a learning based solution to IK"
    asyncio.run(run(claim))
