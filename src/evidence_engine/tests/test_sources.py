"""Evidence Engine — Part 1 offline tests (no network required).

Covers query building, normalizers, dedup, the disk cache (TTL, empty-
protection, corruption), the cool-down state machine, the per-source runner
(success isolation, cache-rescue on network failure, cool-down cache serving),
and end-to-end extract_papers with monkeypatched adapters.
"""

import asyncio
import time

import pytest

import evidence_engine.sources as sources
from evidence_engine import models as m


# ---------------------------------------------------------------- queries

class TestBuildQueries:
    def test_two_variants_keyword_and_natural(self):
        qs = sources.build_queries(
            "Multilayer perceptron is the dominant choice of learning "
            "based solutions for inverse kinematics")
        assert len(qs) == 2
        kw, nat = qs
        assert "the" not in kw.split() and "is" not in kw.split()
        assert nat.startswith("Multilayer")

    def test_dedup_when_claim_is_already_keywords(self):
        assert sources.build_queries("perceptron kinematics") == \
            ["perceptron kinematics"]

    def test_cap_at_eight_terms(self):
        qs = sources.build_queries(" ".join(f"w{i}" for i in range(20)))
        assert len(qs[0].split()) == 8


# ------------------------------------------------------------ normalizers

class TestNormalizers:
    def test_doi_extraction_shapes(self):
        assert sources._doi("https://doi.org/10.1234/abc.x") == "10.1234/abc.x"
        assert sources._doi("10.1234/plain") == "10.1234/plain"
        assert sources._doi(None) is None
        assert sources._doi("nope") is None

    def test_first_author_et_al(self):
        assert sources._first_author_et_al([]) == "Unknown"
        assert sources._first_author_et_al(["A"]) == "A"
        assert sources._first_author_et_al(["A", "B", "C"]) == "A et al."

    def test_reconstruct_abstract(self):
        inv = {"Hello": [0], "world": [1], "again": [2]}
        assert sources.reconstruct_abstract(inv) == "Hello world again"
        assert sources.reconstruct_abstract(None) == ""
        assert sources.reconstruct_abstract({}) == ""


# ---------------------------------------------------------------- dedup

def _ref(title="T", doi=None, year=2020, source="s"):
    return m.PaperRef(title=title, authors="A", year=year, doi=doi,
                      url=None, abstract="x", source=source)


class TestDedupe:
    def test_doi_wins_over_title(self):
        out = sources.dedupe_papers([
            _ref("Alpha", doi="10.1/a", source="epmc"),
            _ref("Alpha v2 title drift", doi="10.1/a", source="s2"),
        ])
        assert len(out) == 1 and out[0].source == "epmc"

    def test_title_year_fallback(self):
        out = sources.dedupe_papers([
            _ref("Beta Study!", year=2019, source="openalex"),
            _ref("beta  study", year=2019, source="s2"),
            _ref("beta  study", year=2021, source="s2"),
        ])
        assert len(out) == 2  # same title+year collapse; different year kept

    def test_no_doi_no_title_dropped(self):
        out = sources.dedupe_papers([_ref("", doi=None), _ref("Keep", doi=None)])
        assert [p.title for p in out] == ["Keep"]


# ------------------------------------------------------------- disk cache

class TestCache:
    def setup_method(self):
        sources._CACHE_TESTING = True
        import sqlite3
        con = sqlite3.connect(sources.CACHE_PATH)
        con.execute("DELETE FROM cache")
        con.commit()
        con.close()

    def test_put_get_roundtrip(self):
        sources._cache_put(sources._ckey("s", "q", 10), [{"title": "A"}])
        assert sources._cache_get(sources._ckey("s", "q", 10)) == [{"title": "A"}]

    def test_empty_never_cached(self):
        sources._cache_put(sources._ckey("s", "q", 10), [])
        assert sources._cache_get(sources._ckey("s", "q", 10)) is None

    def test_ttl_expiry(self):
        key = sources._ckey("s", "old", 10)
        sources._cache_put(key, [{"title": "A"}])
        import sqlite3
        con = sqlite3.connect(sources.CACHE_PATH)
        con.execute("UPDATE cache SET ts=? WHERE k=?", (time.time() - 7 * 3600, key))
        con.commit()
        con.close()
        assert sources._cache_get(key) is None

    def test_corrupt_row_is_a_miss(self):
        key = sources._ckey("s", "bad", 10)
        import sqlite3
        sources._cache_put(key, [{"title": "A"}])
        con = sqlite3.connect(sources.CACHE_PATH)
        con.execute("UPDATE cache SET payload='{broken' WHERE k=?", (key,))
        con.commit()
        con.close()
        assert sources._cache_get(key) is None


# ------------------------------------------------------------- cool-down

class TestCoolDown:
    def setup_method(self):
        sources._COOL.clear()

    def test_failure_then_success_resets(self):
        sources._mark_failure("x")
        assert sources._cooling_down("x")
        sources._mark_success("x")
        assert not sources._cooling_down("x")

    def test_tiered_window(self):
        sources._mark_failure("x")
        sources._COOL["x"][0] -= 61  # past the one-failure window
        assert not sources._cooling_down("x")
        sources._mark_failure("x")
        sources._mark_failure("x")  # 3 consecutive
        sources._COOL["x"][0] -= 61  # inside the 300 s tier
        assert sources._cooling_down("x")


# --------------------------------------------------------- per-source runner

def _ok_adapter(client, query, limit):
    return [{"title": f"P for {query}", "authors": "A", "year": 2024,
             "doi": None, "url": None, "venue": None, "citation_count": 1,
             "abstract": "s", "open_access": True}]


def _fail_adapter(client, query, limit):
    raise RuntimeError("boom")


class TestRunSource:
    def test_success_reports_and_yields_refs(self):
        loop = asyncio.new_event_loop()
        refs, report = loop.run_until_complete(sources._run_source(
            "t", _ok_adapter, ["q1", "q2"], 10, loop.time() + 5, loop))
        loop.close()
        assert report["status"] == "ok" and report["papers"] == 2
        assert all(r.source == "t" for r in refs)

    def test_variant_failure_isolated(self):
        def half(client, q, limit):
            if q == "bad":
                raise RuntimeError("boom")
            return [{"title": "ok", "authors": "A", "year": 1, "doi": None,
                     "url": None, "abstract": "s", "open_access": False}]

        loop = asyncio.new_event_loop()
        refs, report = loop.run_until_complete(sources._run_source(
            "t", half, ["good", "bad"], 10, loop.time() + 5, loop))
        loop.close()
        assert report["status"].startswith("ok (1/2")
        assert len(refs) == 1

    def test_network_failure_serves_cache(self):
        # prime cache, then make the adapter raise on the network path
        key = sources._ckey("t", "q1", 10)
        sources._cache_put(key, [{"title": "cached", "authors": "A", "year": 1,
                                  "doi": None, "url": None, "abstract": "s",
                                  "open_access": False}])
        loop = asyncio.new_event_loop()
        refs, report = loop.run_until_complete(sources._run_source(
            "t", _fail_adapter, ["q1"], 10, loop.time() + 5, loop))
        loop.close()
        assert [r.title for r in refs] == ["cached"]
        assert "degraded" in report["status"]

    def test_cool_down_still_serves_cache(self):
        sources._mark_failure("t")
        key = sources._ckey("t", "q1", 10)
        sources._cache_put(key, [{"title": "cached", "authors": "A", "year": 1,
                                  "doi": None, "url": None, "abstract": "s",
                                  "open_access": False}])
        loop = asyncio.new_event_loop()
        refs, report = loop.run_until_complete(sources._run_source(
            "t", _ok_adapter, ["q1"], 10, loop.time() + 5, loop))
        loop.close()
        assert [r.title for r in refs] == ["cached"]
        assert report["status"] == "ok"

    def test_all_fail_degrades_without_raising(self):
        loop = asyncio.new_event_loop()
        refs, report = loop.run_until_complete(sources._run_source(
            "t", _fail_adapter, ["q1"], 10, loop.time() + 5, loop))
        loop.close()
        assert refs == []
        assert report["status"].startswith("degraded")


# ------------------------------------------------------------- end-to-end

class TestExtractPapers:
    def test_fanout_merges_and_dedupes(self, monkeypatch):
        def epmc(client, q, limit):
            return [{"title": "Shared", "authors": "A", "year": 2020,
                     "doi": "10.1/shared", "url": None, "venue": None,
                     "citation_count": 5, "abstract": "a", "open_access": True}]

        def s2(client, q, limit):
            return [{"title": "Shared (S2 form)", "authors": "B", "year": 2020,
                     "doi": "10.1/shared", "url": None, "venue": None,
                     "citation_count": 7, "abstract": "a", "open_access": False},
                    {"title": "S2 only", "authors": "B", "year": 2021,
                     "doi": "10.2/x", "url": None, "venue": None,
                     "citation_count": 0, "abstract": "a", "open_access": False}]

        def oa(client, q, limit):
            raise RuntimeError("budget exhausted")

        monkeypatch.setattr(sources, "fetch_europepmc", epmc)
        monkeypatch.setattr(sources, "fetch_semanticscholar", s2)
        monkeypatch.setattr(sources, "fetch_openalex", oa)
        sources._COOL.clear()

        res = asyncio.run(sources.extract_papers("claim about things", deadline_s=5))
        assert len(res.papers) == 2  # DOI dedupe collapsed the shared one
        assert res.sources["openalex"]["status"].startswith("degraded")
        assert res.sources["europepmc"]["status"] == "ok"
        assert res.wall_ms > 0
        assert "2 unique papers" in res.summary()

    def test_never_raises_when_everything_fails(self, monkeypatch):
        monkeypatch.setattr(sources, "fetch_europepmc", _fail_adapter)
        monkeypatch.setattr(sources, "fetch_openalex", _fail_adapter)
        monkeypatch.setattr(sources, "fetch_semanticscholar", _fail_adapter)
        sources._COOL.clear()
        res = asyncio.run(sources.extract_papers("some claim text here"))
        assert res.papers == []
        assert set(res.sources) == {"europepmc", "openalex", "semanticscholar"}
