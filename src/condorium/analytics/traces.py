"""Full-trace persistence: every JSON of every round, for every run.

Layout: evaluations/<eval_id>/trace.json         (one idea, full detail)
        evaluations/<run_id>/run.json            (tournament/run level)
Everything downstream (stats, reports, pitch, bench, coach) reads these files.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ..config import SETTINGS


def new_id(prefix: str, label: str = "") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")[:40]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return "-".join(p for p in (prefix, slug, stamp) if p)


def eval_dir(eval_id: str) -> Path:
    d = SETTINGS.evaluations_dir / eval_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_eval(record: dict) -> Path:
    path = eval_dir(record["eval_id"]) / "trace.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_run(run: dict) -> Path:
    path = eval_dir(run["run_id"]) / "run.json"
    path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_eval(eval_id: str) -> dict:
    return json.loads((SETTINGS.evaluations_dir / eval_id / "trace.json").read_text(encoding="utf-8"))


def list_evals() -> list[dict]:
    out: list[dict] = []
    root = SETTINGS.evaluations_dir
    if not root.is_dir():
        return out
    for trace in sorted(root.glob("*/trace.json")):
        try:
            out.append(json.loads(trace.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def load_outcome(eval_id: str) -> dict | None:
    f = SETTINGS.evaluations_dir / eval_id / "outcome.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return None


def save_outcome(eval_id: str, outcome: dict) -> Path:
    path = eval_dir(eval_id) / "outcome.json"
    path.write_text(json.dumps(outcome, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
