#!/usr/bin/env python3
"""Bootstrap the winners base from a public Devpost-style dataset.

    python scripts/bootstrap_from_dataset.py <path> [--format json|csv|parquet]
                                             [--limit N] [--no-llm]

Works with e.g. the Kaggle/HuggingFace Devpost hackathon-projects dumps
(`alvanlii/devpost-hackathon-projects` or equivalent): pass the downloaded
file's path. Filters winners, converts to the winners schema, populates
winners.json + summaries + graph. The base is useful from day 1.

Column names are matched loosely (case-insensitive, several aliases), since
these dumps vary. `--no-llm` skips LLM entity extraction and derives graph
entities from the structured columns only (fast, keyless).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from condorium.knowledge import kgraph, store

ALIASES = {
    "title": ["title", "name", "project", "project_name", "winning_project"],
    "hackathon": ["hackathon", "hackathon_name", "event", "submission_hackathon"],
    "tagline": ["tagline", "pitch", "one_sentence_pitch", "description_short", "subtitle"],
    "description": ["description", "about", "story", "text"],
    "built_with": ["built_with", "builtwith", "stack", "technologies", "tags"],
    "prizes": ["prizes", "prize", "winner", "awards", "submission_prizes", "is_winner"],
    "url": ["url", "link", "source_url", "devpost_url"],
    "theme": ["theme", "category", "themes"],
    "date": ["date", "created_at", "submission_date", "year"],
}


def pick(row: dict, field: str) -> str:
    lower = {k.lower(): v for k, v in row.items()}
    for alias in ALIASES[field]:
        v = lower.get(alias)
        if v not in (None, "", [], "[]"):
            return v if isinstance(v, str) else json.dumps(v)
    return ""


def is_winner(row: dict) -> bool:
    prizes = pick(row, "prizes").strip().lower()
    return prizes not in ("", "0", "[]", "false", "none", "null")


def to_list(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x) for x in parsed][:12]
    except json.JSONDecodeError:
        pass
    return [t.strip() for t in re.split(r"[,;|]", raw) if t.strip()][:12]


def load_rows(path: Path, fmt: str) -> list[dict]:
    if fmt == "csv":
        with path.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    if fmt == "parquet":
        try:
            import pandas as pd
        except ImportError:
            raise SystemExit("parquet format needs pandas: uv pip install pandas pyarrow") from None
        return pd.read_parquet(path).to_dict("records")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("data", [])


def convert(row: dict, idx: int) -> dict:
    title = pick(row, "title") or f"project-{idx}"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or f"project-{idx}"
    stack = to_list(pick(row, "built_with"))
    theme = pick(row, "theme")
    return {
        "id": slug,
        "hackathon": pick(row, "hackathon") or "unknown",
        "date": str(pick(row, "date"))[:7],
        "theme": theme,
        "duration": "",
        "winning_project": title,
        "one_sentence_pitch": pick(row, "tagline")[:300],
        "stack": stack,
        "official_criteria": [],
        "why_it_won": f"Won: {pick(row, 'prizes')[:200]}",
        "source_url": pick(row, "url"),
        "entities": {"techs": stack, "themes": [theme] if theme else [], "patterns": [], "papers": []},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--format", choices=["json", "csv", "parquet"], default=None)
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--no-llm", action="store_true", default=True,
                    help="kept for symmetry; bootstrap is structural, no LLM needed")
    args = ap.parse_args()
    fmt = args.format or args.path.suffix.lstrip(".").replace("jsonl", "json") or "json"

    rows = load_rows(args.path, fmt)
    winners = [r for r in rows if is_winner(r)][: args.limit]
    print(f"{len(rows)} rows, {len(winners)} winners kept (limit {args.limit})")
    g = kgraph.load_graph()
    for i, row in enumerate(winners):
        entry = convert(row, i)
        store.save_winner(entry)
        kgraph.add_winner(g, entry)
    kgraph.save_graph(g)
    print(f"graph: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")


if __name__ == "__main__":
    main()
