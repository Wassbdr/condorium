"""arXiv + Semantic Scholar clients.

Every returned paper carries the verifiable URL the API itself provided —
these URLs are the only ones the Scientist (generator or evaluator) may cite,
and the orchestrator gate (`filter_cited_references`) enforces it.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass

import httpx

ARXIV_API = "http://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"
_TIMEOUT = 30.0


@dataclass
class Paper:
    title: str
    url: str
    abstract: str
    year: str | None = None
    source: str = "arxiv"

    def as_dict(self) -> dict:
        return asdict(self)


def search_arxiv(query: str, max_results: int = 8) -> list[Paper]:
    params = {
        "search_query": f"all:{query}",
        "max_results": max_results,
        "sortBy": "relevance",
    }
    resp = httpx.get(ARXIV_API, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    ns = {"a": "http://www.w3.org/2005/Atom"}
    papers = []
    for entry in ET.fromstring(resp.text).findall("a:entry", ns):
        title = (entry.findtext("a:title", "", ns) or "").strip().replace("\n", " ")
        url = (entry.findtext("a:id", "", ns) or "").strip()
        abstract = (entry.findtext("a:summary", "", ns) or "").strip()
        published = entry.findtext("a:published", "", ns) or ""
        if title and url:
            papers.append(Paper(title, url, abstract[:800], published[:4] or None, "arxiv"))
    return papers


def search_semantic_scholar(query: str, max_results: int = 8) -> list[Paper]:
    params = {"query": query, "limit": max_results, "fields": "title,url,abstract,year"}
    resp = httpx.get(S2_API, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    papers = []
    for item in resp.json().get("data", []) or []:
        if item.get("title") and item.get("url"):
            papers.append(
                Paper(
                    item["title"],
                    item["url"],
                    (item.get("abstract") or "")[:800],
                    str(item["year"]) if item.get("year") else None,
                    "semantic_scholar",
                )
            )
    return papers


def search_papers(query: str, max_results: int = 8) -> list[Paper]:
    """Dual API channel; a failing provider degrades, it never blocks the run."""
    papers: list[Paper] = []
    for fn in (search_arxiv, search_semantic_scholar):
        try:
            papers.extend(fn(query, max_results))
        except Exception:
            continue
    seen: set[str] = set()
    unique = []
    for p in papers:
        key = p.title.lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def filter_cited_references(references: list[dict], retrieved: list[dict]) -> list[dict]:
    """Orchestrator gate: keep only references whose URL was actually retrieved."""
    allowed = {r["url"] for r in retrieved if r.get("url")}
    return [r for r in references or [] if r.get("url") in allowed]
