"""Evidence Engine offline tests (no network required).

Covers query building, normalizers, dedup, disk cache, cool-down,
section extraction, sentence splitting, and pipeline with monkeypatched
adapters.
"""

import asyncio
import sqlite3
import time

import pytest

import evidence_engine.evidence_pipeline as ep
from evidence_engine.models import PaperRef


# ---------------------------------------------------------------- queries

class TestBuildQueries:
    def test_two_variants(self):
        qs = ep.build_queries(
            "Multilayer perceptron is the dominant choice of learning "
            "based solutions for inverse kinematics"
        )
        assert len(qs) == 2
        kw, nat = qs
        assert "the" not in kw.split() and "is" not in kw.split()
        assert nat.startswith("Multilayer")

    def test_dedup_when_already_keywords(self):
        assert ep.build_queries("perceptron kinematics") == ["perceptron kinematics"]

    def test_cap_at_eight_terms(self):
        qs = ep.build_queries(" ".join(f"w{i}" for i in range(20)))
        assert len(qs[0].split()) == 8


# ------------------------------------------------------------ normalizers

class TestNormalizers:
    def test_doi_extraction(self):
        assert ep._doi("https://doi.org/10.1234/abc.x") == "10.1234/abc.x"
        assert ep._doi("10.1234/plain") == "10.1234/plain"
        assert ep._doi(None) is None
        assert ep._doi("nope") is None

    def test_first_author_et_al(self):
        assert ep._first_author_et_al([]) == "Unknown"
        assert ep._first_author_et_al(["A"]) == "A"
        assert ep._first_author_et_al(["A", "B", "C"]) == "A et al."

    def test_reconstruct_abstract(self):
        inv = {"Hello": [0], "world": [1], "again": [2]}
        assert ep._reconstruct_abstract(inv) == "Hello world again"
        assert ep._reconstruct_abstract(None) == ""
        assert ep._reconstruct_abstract({}) == ""

    def test_keyword_terms(self):
        terms = ep._keyword_terms("the neural network is fast", cap=3)
        assert "the" not in terms
        assert "neural" in terms
        assert len(terms) == 3


# ---------------------------------------------------------------- dedup

def _ref(title="T", doi=None, year=2020, source="s"):
    return PaperRef(
        title=title, authors="A", year=year, doi=doi,
        url=None, abstract="x", source=source,
    )


class TestDedupe:
    def test_doi_wins(self):
        out = ep.dedupe_papers([
            _ref("Alpha", doi="10.1/a", source="epmc"),
            _ref("Alpha v2", doi="10.1/a", source="s2"),
        ])
        assert len(out) == 1 and out[0].source == "epmc"

    def test_title_year_fallback(self):
        out = ep.dedupe_papers([
            _ref("Beta Study!", year=2019, source="oa"),
            _ref("beta  study", year=2019, source="s2"),
            _ref("beta  study", year=2021, source="s2"),
        ])
        assert len(out) == 2

    def test_no_doi_no_title_dropped(self):
        out = ep.dedupe_papers([_ref("", doi=None), _ref("Keep", doi=None)])
        assert [p.title for p in out] == ["Keep"]


# ------------------------------------------------------------- disk cache

class TestCache:
    def setup_method(self):
        con = sqlite3.connect(ep.CACHE_PATH)
        con.execute("DELETE FROM cache")
        con.commit()
        con.close()

    def test_put_get_roundtrip(self):
        ep._cache_put(ep._cache_key("s", "q", 10), [{"title": "A"}])
        assert ep._cache_get(ep._cache_key("s", "q", 10)) == [{"title": "A"}]

    def test_empty_never_cached(self):
        ep._cache_put(ep._cache_key("s", "q", 10), [])
        assert ep._cache_get(ep._cache_key("s", "q", 10)) is None

    def test_ttl_expiry(self):
        key = ep._cache_key("s", "old", 10)
        ep._cache_put(key, [{"title": "A"}])
        con = sqlite3.connect(ep.CACHE_PATH)
        con.execute("UPDATE cache SET ts=? WHERE k=?", (time.time() - 7 * 3600, key))
        con.commit()
        con.close()
        assert ep._cache_get(key) is None

    def test_corrupt_row_is_miss(self):
        key = ep._cache_key("s", "bad", 10)
        ep._cache_put(key, [{"title": "A"}])
        con = sqlite3.connect(ep.CACHE_PATH)
        con.execute("UPDATE cache SET payload='{broken' WHERE k=?", (key,))
        con.commit()
        con.close()
        assert ep._cache_get(key) is None


# ------------------------------------------------------------- cool-down

class TestCoolDown:
    def setup_method(self):
        ep._COOL.clear()

    def test_failure_then_success_resets(self):
        ep._mark_failure("x")
        assert ep._cooling_down("x")
        ep._mark_success("x")
        assert not ep._cooling_down("x")

    def test_tiered_window(self):
        ep._mark_failure("x")
        ep._COOL["x"][0] -= 61
        assert not ep._cooling_down("x")
        ep._mark_failure("x")
        ep._mark_failure("x")
        ep._COOL["x"][0] -= 61
        assert ep._cooling_down("x")


# --------------------------------------------------------- section extraction

class TestSectionExtraction:
    def test_extracts_discussion(self):
        xml = '<body><sec><title>Discussion</title><p>Some detailed analysis of results.</p></sec></body>'
        sections = ep._extract_sections(xml)
        assert "disc" in sections
        assert "analysis" in sections["disc"]

    def test_extracts_conclusion(self):
        xml = '<body><sec><title>Conclusions</title><p>We conclude that the method works well.</p></sec></body>'
        sections = ep._extract_sections(xml)
        assert "conc" in sections

    def test_strips_xml_tags(self):
        xml = '<body><sec><title>Discussion</title><p><bold>Bold</bold> text here now.</p></sec></body>'
        sections = ep._extract_sections(xml)
        assert "<" not in sections.get("disc", "")


class TestSentenceSplitting:
    def test_splits_on_period(self):
        sents = ep._split_sentences(
            "The first sentence has enough words to pass the filter. "
            "The second sentence also has enough words here."
        )
        assert len(sents) >= 2

    def test_filters_short(self):
        sents = ep._split_sentences("Hi. Go. Run.")
        assert len(sents) == 0


# --------------------------------------------------------- per-source runner

async def _ok_adapter(client, query, limit):
    return [{"title": f"P for {query}", "authors": "A", "year": 2024,
             "doi": None, "url": None, "venue": None, "citation_count": 1,
             "abstract": "s", "open_access": True}]


async def _fail_adapter(client, query, limit):
    raise RuntimeError("boom")


class TestRunSource:
    def setup_method(self):
        ep._COOL.clear()
        con = sqlite3.connect(ep.CACHE_PATH)
        con.execute("DELETE FROM cache")
        con.commit()
        con.close()

    def test_success(self):
        loop = asyncio.new_event_loop()
        refs, report, raw = loop.run_until_complete(
            ep._run_source("t", _ok_adapter, "q1", 10, loop.time() + 5, loop)
        )
        loop.close()
        assert report["status"] == "ok" and report["papers"] == 1
        assert refs[0].source == "t"

    def test_network_failure(self):
        loop = asyncio.new_event_loop()
        refs, report, raw = loop.run_until_complete(
            ep._run_source("t", _fail_adapter, "q1", 10, loop.time() + 5, loop)
        )
        loop.close()
        assert refs == []
        assert "degraded" in report["status"]

    def test_cache_hit(self):
        key = ep._cache_key("t", "q1", 10)
        ep._cache_put(key, [{"title": "cached", "authors": "A", "year": 1,
                             "doi": None, "url": None, "abstract": "s",
                             "open_access": False}])
        loop = asyncio.new_event_loop()
        refs, report, raw = loop.run_until_complete(
            ep._run_source("t", _fail_adapter, "q1", 10, loop.time() + 5, loop)
        )
        loop.close()
        assert [r.title for r in refs] == ["cached"]

    def test_cool_down_skips_network(self):
        ep._mark_failure("t")
        loop = asyncio.new_event_loop()
        refs, report, raw = loop.run_until_complete(
            ep._run_source("t", _ok_adapter, "q1", 10, loop.time() + 5, loop)
        )
        loop.close()
        assert refs == []
        assert "cool-down" in report["status"]


# ------------------------------------------------------------- end-to-end

class TestRetrievePapers:
    def setup_method(self):
        ep._COOL.clear()
        con = sqlite3.connect(ep.CACHE_PATH)
        con.execute("DELETE FROM cache")
        con.commit()
        con.close()

    def test_fanout_merges_and_dedupes(self, monkeypatch):
        async def epmc(client, q, limit):
            return [{"title": "Shared", "authors": "A", "year": 2020,
                     "doi": "10.1/shared", "url": None, "venue": None,
                     "citation_count": 5, "abstract": "a", "open_access": True}]

        async def oa(client, q, limit):
            return [{"title": "Shared (OA form)", "authors": "B", "year": 2020,
                     "doi": "10.1/shared", "url": None, "venue": None,
                     "citation_count": 7, "abstract": "a", "open_access": False},
                    {"title": "OA only", "authors": "B", "year": 2021,
                     "doi": "10.2/x", "url": None, "venue": None,
                     "citation_count": 0, "abstract": "a", "open_access": False}]

        async def core(client, q, limit):
            raise RuntimeError("budget exhausted")

        monkeypatch.setattr(ep, "_fetch_europepmc", epmc)
        monkeypatch.setattr(ep, "_fetch_openalex", oa)
        monkeypatch.setattr(ep, "_fetch_core", core)
        ep._COOL.clear()

        res = asyncio.run(ep.retrieve_papers("claim about things", deadline_s=5))
        assert len(res.papers) == 2
        assert res.sources["core"]["status"].startswith("degraded")
        assert res.sources["europepmc"]["status"] == "ok"
        assert res.wall_ms > 0
        assert "2 unique papers" in res.summary()

    def test_never_raises(self, monkeypatch):
        async def fail(client, q, limit):
            raise RuntimeError("boom")

        monkeypatch.setattr(ep, "_fetch_europepmc", fail)
        monkeypatch.setattr(ep, "_fetch_openalex", fail)
        monkeypatch.setattr(ep, "_fetch_core", fail)
        ep._COOL.clear()
        res = asyncio.run(ep.retrieve_papers("some claim text here"))
        assert res.papers == []
        assert set(res.sources) == {"europepmc", "openalex", "core"}
