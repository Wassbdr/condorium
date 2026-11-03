"""Web-search channel — the second mandatory channel for the Scientist.

Tavily when `TAVILY_API_KEY` is set (reliable, built for agents); otherwise
the keyless DuckDuckGo HTML endpoint, best-effort (it often answers with an
anti-bot page). Results carry their URL and feed the same citation gate as
the paper APIs. Failures degrade, but are reported through `status["web"]`:
"tavily:ok:N" | "ddg:ok:N" | "ddg:blocked" | "<provider>:error:<reason>" | ...
"""

from __future__ import annotations

import html
import logging
import os
import re
from urllib.parse import parse_qs, urlparse

import httpx

_TAVILY_URL = "https://api.tavily.com/search"
_DDG_URL = "https://html.duckduckgo.com/html/"
_RESULT_RE = re.compile(r'<a(?P<attrs>[^>]*class="result__a"[^>]*)>(?P<title>.*?)</a>', re.DOTALL)
_HREF_RE = re.compile(r'href="(?P<url>[^"]+)"')
_TAG_RE = re.compile(r"<[^>]+>")

log = logging.getLogger("condorium.sources")


def _set(status: dict | None, value: str) -> None:
    if status is not None:
        status["web"] = value


def _error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"error:HTTP {exc.response.status_code}"
    return f"error:{type(exc).__name__}"


def decode_ddg_url(href: str) -> str | None:
    """DDG wraps results as //duckduckgo.com/l/?uddg=<encoded target>; ads go
    through y.js. Returns the real target URL, or None."""
    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com"):
        if parsed.path.startswith("/y.js"):
            return None  # sponsored result
        target = parse_qs(parsed.query).get("uddg", [None])[0]
        return target if target and target.startswith("http") else None
    return href if href.startswith("http") else None


def parse_ddg_html(page: str, max_results: int) -> list[dict]:
    results = []
    for m in _RESULT_RE.finditer(page):
        href = _HREF_RE.search(m.group("attrs"))
        url = decode_ddg_url(href.group("url")) if href else None
        title = html.unescape(_TAG_RE.sub("", m.group("title"))).strip()
        if title and url:
            results.append({"title": title, "url": url, "source": "web"})
        if len(results) >= max_results:
            break
    return results


def _search_tavily(query: str, max_results: int, key: str) -> list[dict]:
    resp = httpx.post(
        _TAVILY_URL,
        json={"query": query, "max_results": max_results, "search_depth": "basic"},
        headers={"Authorization": f"Bearer {key}"},
        timeout=20.0,
    )
    resp.raise_for_status()
    return [
        {"title": r["title"], "url": r["url"], "source": "web",
         "snippet": (r.get("content") or "")[:400]}
        for r in resp.json().get("results", []) or []
        if r.get("title") and str(r.get("url", "")).startswith("http")
    ][:max_results]


def _search_ddg(query: str, max_results: int, status: dict | None) -> list[dict]:
    resp = httpx.post(
        _DDG_URL,
        data={"q": query},
        timeout=20.0,
        follow_redirects=True,
        headers={"User-Agent": "condorium/0.1 (idea committee; research lookup)"},
    )
    resp.raise_for_status()
    if resp.status_code == 202 or "anomaly" in resp.text[:5000].lower():
        _set(status, "ddg:blocked")
        log.warning("web channel: DuckDuckGo returned an anti-bot page "
                    "(set TAVILY_API_KEY for a reliable web channel)")
        return []
    results = parse_ddg_html(resp.text, max_results)
    _set(status, f"ddg:ok:{len(results)}" if results else "ddg:empty")
    return results


def search_web(query: str, max_results: int = 6, status: dict | None = None) -> list[dict]:
    if key := os.environ.get("TAVILY_API_KEY"):
        try:
            results = _search_tavily(query, max_results, key)
        except (httpx.HTTPError, ValueError) as exc:
            _set(status, f"tavily:{_error(exc)}")
            log.warning("web channel tavily failed: %s", _error(exc))
            return []
        _set(status, f"tavily:ok:{len(results)}" if results else "tavily:empty")
        return results
    try:
        return _search_ddg(query, max_results, status)
    except httpx.HTTPError as exc:
        _set(status, f"ddg:{_error(exc)}")
        log.warning("web channel ddg failed: %s", _error(exc))
        return []
