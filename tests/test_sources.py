"""Research channels: they degrade, but never silently. HTTP is faked at the
httpx level with recorded responses (tests/data/) — no network."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from condorium.sources import papers, web

DATA = Path(__file__).parent / "data"


def _resp(status: int, url: str, *, text: str = "", json: dict | None = None,
          headers: dict | None = None) -> httpx.Response:
    req = httpx.Request("GET", url)
    if json is not None:
        return httpx.Response(status, json=json, request=req, headers=headers)
    return httpx.Response(status, text=text, request=req, headers=headers)


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(papers.time, "sleep", lambda s: None)


def test_clean_query_keeps_keywords_only():
    terms = papers.clean_query("An app that helps: plant-disease detection, with the phone!")
    assert terms == ["plant-disease", "detection", "phone"]


def test_arxiv_https_atom_parsed_and_redirects_followed(monkeypatch):
    seen = {}

    def fake_get(url, **kw):
        seen.update(url=url, follow=kw.get("follow_redirects"), q=kw["params"]["search_query"])
        return _resp(200, url, text=(DATA / "arxiv_atom.xml").read_text())

    monkeypatch.setattr(papers.httpx, "get", fake_get)
    found = papers.search_arxiv("plant disease detection")
    assert seen["url"].startswith("https://")
    assert seen["follow"] is True
    assert seen["q"] == "all:plant AND all:disease AND all:detection"
    assert [p.title for p in found] == ["Leaf Disease Detection on Smartphones",
                                        "Lightweight CNNs for Crop Health"]
    assert found[0].year == "2021"


def test_arxiv_falls_back_to_or_when_and_finds_nothing(monkeypatch):
    queries = []
    empty = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'

    def fake_get(url, **kw):
        q = kw["params"]["search_query"]
        queries.append(q)
        body = empty if " AND " in q else (DATA / "arxiv_atom.xml").read_text()
        return _resp(200, url, text=body)

    monkeypatch.setattr(papers.httpx, "get", fake_get)
    assert len(papers.search_arxiv("plant disease")) == 2
    assert [" AND " in q for q in queries] == [True, False]


def test_s2_429_reports_error_without_raising(monkeypatch, no_sleep):
    def fake_get(url, **kw):
        if "arxiv" in url:
            return _resp(200, url, text=(DATA / "arxiv_atom.xml").read_text())
        return _resp(429, url, json={"message": "Too Many Requests"})

    monkeypatch.setattr(papers.httpx, "get", fake_get)
    status: dict = {}
    found = papers.search_papers("plant disease", status=status)
    assert len(found) == 2  # arXiv alone still serves the run
    assert status == {"arxiv": "ok:2", "semantic_scholar": "error:HTTP 429"}


def test_s2_retries_once_on_429_and_sends_key(monkeypatch, no_sleep):
    monkeypatch.setenv("S2_API_KEY", "k-123")
    calls = []

    def fake_get(url, **kw):
        calls.append(kw.get("headers") or {})
        if len(calls) == 1:
            return _resp(429, url, json={}, headers={"Retry-After": "2"})
        return _resp(200, url, json={"data": [
            {"title": "S2 paper", "url": "https://www.semanticscholar.org/paper/x", "year": 2020}]})

    monkeypatch.setattr(papers.httpx, "get", fake_get)
    found = papers.search_semantic_scholar("plant disease")
    assert [p.title for p in found] == ["S2 paper"]
    assert len(calls) == 2
    assert all(h.get("x-api-key") == "k-123" for h in calls)


def test_network_error_is_reported(monkeypatch):
    def boom(url, **kw):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(papers.httpx, "get", boom)
    status: dict = {}
    assert papers.search_papers("plant disease", status=status) == []
    assert status == {"arxiv": "error:ConnectError", "semantic_scholar": "error:ConnectError"}


def test_ddg_redirect_links_decoded_titles_unescaped_ads_skipped(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(web.httpx, "post", lambda url, **kw: _resp(
        200, url, text=(DATA / "ddg_results.html").read_text()))
    status: dict = {}
    results = web.search_web("plant doctor", status=status)
    assert results == [
        {"title": "Plant & Leaf Doctor", "url": "https://example.org/plant-doctor", "source": "web"},
        {"title": "Direct link", "url": "https://direct.example.com/page", "source": "web"},
    ]
    assert status == {"web": "ddg:ok:2"}


def test_ddg_antibot_page_reported_as_blocked(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(web.httpx, "post", lambda url, **kw: _resp(202, url, text="<html></html>"))
    status: dict = {}
    assert web.search_web("plant doctor", status=status) == []
    assert status == {"web": "ddg:blocked"}


def test_tavily_used_when_key_set(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tv-1")
    seen = {}

    def fake_post(url, **kw):
        seen.update(url=url, auth=kw["headers"]["Authorization"])
        return _resp(200, url, json={"results": [
            {"title": "T", "url": "https://t.example/a", "content": "snippet"},
            {"title": "no url", "url": ""}]})

    monkeypatch.setattr(web.httpx, "post", fake_post)
    status: dict = {}
    results = web.search_web("plant doctor", status=status)
    assert seen == {"url": "https://api.tavily.com/search", "auth": "Bearer tv-1"}
    assert [r["url"] for r in results] == ["https://t.example/a"]
    assert status == {"web": "tavily:ok:1"}


def test_citation_gate_ignores_non_dicts_and_restores_real_title():
    retrieved = [{"title": "Real title", "url": "https://arxiv.org/abs/1"}]
    refs = ["https://arxiv.org/abs/1",
            {"title": "Invented title", "url": "https://arxiv.org/abs/1"},
            {"title": "x", "url": "https://fake.example"}]
    kept = papers.filter_cited_references(refs, retrieved)
    assert kept == [{"title": "Real title", "url": "https://arxiv.org/abs/1"}]
    assert papers.filter_cited_references("not a list", retrieved) == []


def test_scientist_generator_without_sources_warns(mock_llm, monkeypatch):
    from condorium.graph import cohort
    from condorium.graph.build import compile_main_graph

    def no_papers(q, max_results=8, status=None):
        status.update({"arxiv": "error:HTTP 301", "semantic_scholar": "error:HTTP 429"})
        return []

    def no_web(q, max_results=6, status=None):
        status["web"] = "ddg:blocked"
        return []

    monkeypatch.setattr(cohort, "search_papers", no_papers)
    monkeypatch.setattr(cohort, "search_web", no_web)
    result = compile_main_graph().invoke({
        "command": "generate", "sources": ["scientist"], "mode": "hackathon",
        "theme": "health", "top": 1, "lang": "en", "run_id": "run-nosrc"})
    assert result["warnings"] == [
        "scientist: no source retrieved (arxiv: error:HTTP 301, "
        "semantic_scholar: error:HTTP 429, web: ddg:blocked)"]
    assert result.get("evaluations", []) == []
