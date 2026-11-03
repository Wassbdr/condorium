"""arXiv + Semantic Scholar clients.

Every returned paper carries the verifiable URL the API itself provided —
these URLs are the only ones the Scientist (generator or evaluator) may cite,
and the orchestrator gate (`filter_cited_references`) enforces it.

A failing provider degrades, it never blocks the run — but it never fails
silently either: pass a `status` dict and each channel reports
"ok:N" | "empty" | "error:<reason>".
"""

from __future__ import annotations

import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass

import httpx

ARXIV_API = "https://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"
_TIMEOUT = 30.0
_MAX_RETRY_AFTER = 5.0

log = logging.getLogger("condorium.sources")

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "your", "their", "our",
    "app", "using", "use", "uses", "which", "who", "what", "when", "where", "how", "are",
    "was", "were", "will", "can", "could", "would", "should", "has", "have", "had", "not",
    "but", "all", "any", "each", "they", "them", "its", "via", "per", "than", "then",
    "idea", "title", "about", "make", "makes", "helps", "help", "people", "users",
}


@dataclass
class Paper:
    title: str
    url: str
    abstract: str
    year: str | None = None
    source: str = "arxiv"

    def as_dict(self) -> dict:
        return asdict(self)


def clean_query(text: str, max_terms: int = 8) -> list[str]:
    """Keywords only: no punctuation, no stopwords, no duplicates."""
    terms: list[str] = []
    for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]+", text or ""):
        w = word.lower().strip("-")
        if len(w) >= 3 and w not in _STOPWORDS and w not in terms:
            terms.append(w)
        if len(terms) >= max_terms:
            break
    return terms


def _arxiv_query(terms: list[str], max_results: int, joiner: str) -> list[Paper]:
    params = {
        "search_query": f" {joiner} ".join(f"all:{t}" for t in terms),
        "max_results": max_results,
        "sortBy": "relevance",
    }
    resp = httpx.get(ARXIV_API, params=params, timeout=_TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    ns = {"a": "http://www.w3.org/2005/Atom"}
    papers = []
    for entry in ET.fromstring(resp.text).findall("a:entry", ns):
        title = " ".join((entry.findtext("a:title", "", ns) or "").split())
        url = (entry.findtext("a:id", "", ns) or "").strip()
        abstract = (entry.findtext("a:summary", "", ns) or "").strip()
        published = entry.findtext("a:published", "", ns) or ""
        if title and url:
            papers.append(Paper(title, url, abstract[:800], published[:4] or None, "arxiv"))
    return papers


def search_arxiv(query: str, max_results: int = 8) -> list[Paper]:
    """AND of the keywords first (precise); OR if that finds nothing."""
    terms = clean_query(query)[:5]
    if not terms:
        return []
    papers = _arxiv_query(terms, max_results, "AND")
    if not papers and len(terms) > 1:
        papers = _arxiv_query(terms, max_results, "OR")
    return papers


def _s2_get(params: dict) -> httpx.Response:
    headers = {}
    if key := os.environ.get("S2_API_KEY"):
        headers["x-api-key"] = key
    resp = httpx.get(S2_API, params=params, headers=headers, timeout=_TIMEOUT,
                     follow_redirects=True)
    if resp.status_code == 429:
        try:
            wait = float(resp.headers.get("Retry-After", "1"))
        except ValueError:
            wait = 1.0
        time.sleep(min(max(wait, 0.0), _MAX_RETRY_AFTER))
        resp = httpx.get(S2_API, params=params, headers=headers, timeout=_TIMEOUT,
                         follow_redirects=True)
    return resp


def search_semantic_scholar(query: str, max_results: int = 8) -> list[Paper]:
    terms = clean_query(query)
    if not terms:
        return []
    resp = _s2_get({"query": " ".join(terms), "limit": max_results,
                    "fields": "title,url,abstract,year"})
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


def _describe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"error:HTTP {exc.response.status_code}"
    return f"error:{type(exc).__name__}"


def search_papers(query: str, max_results: int = 8, status: dict | None = None) -> list[Paper]:
    """Dual API channel; a failing provider degrades, it never blocks the run."""
    papers: list[Paper] = []
    for name, fn in (("arxiv", search_arxiv), ("semantic_scholar", search_semantic_scholar)):
        try:
            found = fn(query, max_results)
        except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
            reason = _describe_error(exc)
            log.warning("paper channel %s failed: %s", name, reason)
            if status is not None:
                status[name] = reason
            continue
        if status is not None:
            status[name] = f"ok:{len(found)}" if found else "empty"
        papers.extend(found)
    seen: set[str] = set()
    unique = []
    for p in papers:
        key = p.title.lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def filter_cited_references(references: list, retrieved: list[dict]) -> list[dict]:
    """Orchestrator gate: keep only references whose URL was actually retrieved.

    The kept reference carries the RETRIEVED title, so a model cannot attach a
    real URL to an invented title."""
    by_url = {r["url"]: r for r in retrieved if isinstance(r, dict) and r.get("url")}
    kept = []
    for ref in references if isinstance(references, list) else []:
        if not isinstance(ref, dict) or ref.get("url") not in by_url:
            continue
        kept.append({**ref, "title": by_url[ref["url"]].get("title", ref.get("title", ""))})
    return kept
