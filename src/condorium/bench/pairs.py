"""Build (winner, non-winner) pairs from a Devpost-style dataset — outcome masked."""

from __future__ import annotations

import csv
import json
import random
from collections import defaultdict
from pathlib import Path

from .antileak import strip_victory_clues

_ALIASES = {
    "title": ["title", "name", "project", "project_name"],
    "hackathon": ["hackathon", "hackathon_name", "event", "submission_hackathon"],
    "description": ["description", "about", "story", "text", "tagline"],
    "prizes": ["prizes", "prize", "winner", "awards", "submission_prizes", "is_winner"],
}


def _pick(row: dict, field: str) -> str:
    lower = {k.lower(): v for k, v in row.items()}
    for alias in _ALIASES[field]:
        v = lower.get(alias)
        if v not in (None, "", [], "[]"):
            return v if isinstance(v, str) else json.dumps(v)
    return ""


def _is_winner(row: dict) -> bool:
    prizes = _pick(row, "prizes").strip().lower()
    return prizes not in ("", "0", "[]", "false", "none", "null")


def load_rows(path: Path) -> list[dict]:
    if path.suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("data", [])


def build_pairs(dataset: Path, n: int, seed: int) -> list[dict]:
    """n pairs, each a winner + a non-winner from the SAME hackathon,
    descriptions cleaned of victory clues, real outcome kept aside (masked)."""
    rows = load_rows(dataset)
    by_hackathon: dict[str, dict[str, list[dict]]] = defaultdict(lambda: {"win": [], "lose": []})
    for row in rows:
        hackathon = _pick(row, "hackathon")
        desc = _pick(row, "description")
        if not hackathon or not desc:
            continue
        bucket = "win" if _is_winner(row) else "lose"
        by_hackathon[hackathon][bucket].append(row)

    rng = random.Random(seed)
    candidates = [h for h, b in by_hackathon.items() if b["win"] and b["lose"]]
    rng.shuffle(candidates)
    pairs = []
    for i, hackathon in enumerate(candidates[:n]):
        b = by_hackathon[hackathon]
        winner, loser = rng.choice(b["win"]), rng.choice(b["lose"])
        entries = [
            {"role": "winner", "title": _pick(winner, "title"),
             "text": strip_victory_clues(_pick(winner, "description"))[:2500]},
            {"role": "loser", "title": _pick(loser, "title"),
             "text": strip_victory_clues(_pick(loser, "description"))[:2500]},
        ]
        rng.shuffle(entries)  # the committee never sees which is which
        pairs.append({"pair_id": f"pair-{i}", "hackathon": hackathon, "entries": entries})
    return pairs
