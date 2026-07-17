"""Web-search channel (DuckDuckGo HTML endpoint — keyless, best-effort).

The second mandatory channel for the Scientist. Results carry their URL and
feed the same citation gate as the paper APIs. Failures degrade silently:
the paper channel alone still satisfies the run, the web channel is
complementary context.
"""

from __future__ import annotations

import re

import httpx

_SEARCH_URL = "https://html.duckduckgo.com/html/"
_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


def search_web(query: str, max_results: int = 6) -> list[dict]:
    try:
        resp = httpx.post(
            _SEARCH_URL,
            data={"q": query},
            timeout=20.0,
            headers={"User-Agent": "condorium/0.1 (idea committee; research lookup)"},
        )
        resp.raise_for_status()
    except Exception:
        return []
    results = []
    for m in _RESULT_RE.finditer(resp.text):
        title = _TAG_RE.sub("", m.group("title")).strip()
        url = m.group("url")
        if title and url.startswith("http"):
            results.append({"title": title, "url": url, "source": "web"})
        if len(results) >= max_results:
            break
    return results
