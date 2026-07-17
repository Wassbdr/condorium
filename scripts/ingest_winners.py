#!/usr/bin/env python3
"""Ingest one hackathon winner from a URL or a text file.

    python scripts/ingest_winners.py <url-or-file>

URL/text -> LLM extraction to the winners schema -> winners.json + summary md
+ knowledge-graph update. Designed to be called by an EXTERNAL weekly job
(cron / Scheduled Task) — no scheduling implemented here, on purpose.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from condorium.knowledge import kgraph, store  # noqa: E402
from condorium.llm import complete_json  # noqa: E402
from condorium.prompts import load_prompt, render  # noqa: E402


def fetch_source(target: str) -> str:
    if target.startswith(("http://", "https://")):
        import httpx

        resp = httpx.get(target, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
        return resp.text[:40000]
    return Path(target).read_text(encoding="utf-8")[:40000]


def ingest(target: str) -> dict:
    source = fetch_source(target)
    prompt = load_prompt("system/ingest.md")
    entry = complete_json(prompt.body.split("SOURCE:")[0], render(prompt.body, source=source))
    if not isinstance(entry, dict) or not entry.get("id"):
        raise SystemExit("extraction failed: no id in extracted entry")
    if target.startswith("http") and not entry.get("source_url"):
        entry["source_url"] = target
    store.save_winner(entry)
    kgraph.ingest_entry(entry)
    return entry


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    e = ingest(sys.argv[1])
    print(f"ingested: {e['id']} ({e.get('winning_project')})")
