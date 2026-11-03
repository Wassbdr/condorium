"""Keyless network smoke test of the three research channels.

    python scripts/check_sources.py "plant disease detection smartphone"

Prints each channel's status (ok:N / empty / error / blocked). Not run in CI:
it hits the real arXiv, Semantic Scholar and web endpoints.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from condorium.sources.papers import search_papers
from condorium.sources.web import search_web


def main() -> int:
    query = " ".join(sys.argv[1:]) or "plant disease detection smartphone"
    status: dict = {}
    papers = search_papers(query, max_results=3, status=status)
    web = search_web(query, max_results=3, status=status)
    for channel, value in status.items():
        print(f"{channel:18} {value}")
    for item in [p.as_dict() for p in papers] + web:
        print(f"  - [{item.get('source')}] {item['title'][:70]} <{item['url']}>")
    return 0 if papers or web else 1


if __name__ == "__main__":
    raise SystemExit(main())
