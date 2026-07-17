"""Winners base: knowledge/winners.json + one readable summary per entry."""

from __future__ import annotations

import json
from pathlib import Path

from ..config import SETTINGS

ENTRY_FIELDS = [
    "id", "hackathon", "date", "theme", "duration", "winning_project",
    "one_sentence_pitch", "stack", "official_criteria", "why_it_won", "source_url",
]


def _winners_file() -> Path:
    return SETTINGS.knowledge_dir / "winners.json"


def load_winners() -> list[dict]:
    f = _winners_file()
    if not f.exists():
        return []
    return json.loads(f.read_text(encoding="utf-8"))


def save_winner(entry: dict) -> None:
    winners = [w for w in load_winners() if w.get("id") != entry.get("id")]
    winners.append({k: entry.get(k) for k in ENTRY_FIELDS} | {"entities": entry.get("entities", {})})
    f = _winners_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(winners, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_summary(entry)


def _write_summary(entry: dict) -> None:
    d = SETTINGS.knowledge_dir / "summaries"
    d.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {entry.get('winning_project', entry.get('id'))}",
        "",
        f"**Hackathon**: {entry.get('hackathon', '?')} ({entry.get('date', '?')}) — "
        f"theme: {entry.get('theme', '?')}, duration: {entry.get('duration', '?')}",
        "",
        f"**Pitch**: {entry.get('one_sentence_pitch', '')}",
        "",
        f"**Stack**: {', '.join(entry.get('stack') or [])}",
        "",
        f"**Official criteria**: {', '.join(entry.get('official_criteria') or [])}",
        "",
        f"**Why it won**: {entry.get('why_it_won', '')}",
        "",
        f"Source: {entry.get('source_url', '')}",
    ]
    (d / f"{entry['id']}.md").write_text("\n".join(lines), encoding="utf-8")
