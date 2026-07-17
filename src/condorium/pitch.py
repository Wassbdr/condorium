"""Pitch pack: assembled purely from the stored evaluation JSON.

Zero new LLM calls — the committee already produced every ingredient.
Output: evaluations/<id>/pitch.md, ready to rehearse before facing the jury.
"""

from __future__ import annotations

from pathlib import Path

from .analytics import traces


def _best(record: dict, agent: str) -> dict:
    return record.get("round2", {}).get(agent) or record.get("round1", {}).get(agent) or {}


def build_pitch(eval_id: str) -> Path:
    record = traces.load_eval(eval_id)
    idea = record.get("idea", {})
    intake = record.get("intake", {})
    syn = record.get("synthesis", {})
    jury = _best(record, "jury")
    strategist = _best(record, "strategist")
    skeptic = _best(record, "skeptic")
    scientist = _best(record, "scientist_eval")
    judge = _best(record, "judge")
    investor = _best(record, "investor")
    believer = _best(record, "believer")

    one_liner = jury.get("retained_sentence") or intake.get("restatement") or idea.get("text", "")[:180]

    lines = [f"# Pitch pack — {idea.get('title', eval_id)}", ""]
    lines += [f"**Verdict**: {syn.get('verdict', '?')} — {syn.get('action', '')}", ""]
    lines += ["## The one-sentence pitch", "", f"> {one_liner}", ""]

    lines += ["## The angle", "", strategist.get("verdict", "(no strategist opinion)")]
    if strategist.get("alternative_angle"):
        lines += ["", f"**Alternative angle to keep in your pocket**: {strategist['alternative_angle']}"]
    lines.append("")

    lines += ["## Likely objections — and your answers", ""]
    watchouts = skeptic.get("watchouts") or []
    tests = skeptic.get("proposed_tests") or []
    for i, w in enumerate(watchouts):
        answer = tests[i] if i < len(tests) else ""
        lines.append(f"- **{w}** — response/test: {answer}")
    if not watchouts:
        lines.append("(the skeptic raised no testable objection)")
    lines.append("")

    if scientist.get("scientific_verdict") == "grounded":
        lines += ["## Backed by science", ""]
        for ref in scientist.get("references", []):
            lines.append(f"- [{ref.get('title')}]({ref.get('url')})")
        lines.append("")

    if judge.get("viable_scope"):
        lines += ["## Minimal demonstrable scope", "", judge["viable_scope"], ""]

    lines += ["## Why now", "", investor.get("verdict", "(no investor opinion)"), ""]

    precedents = believer.get("precedents") or []
    if precedents:
        lines += ["## Comparable precedents", ""]
        for p in precedents:
            if isinstance(p, dict):
                lines.append(f"- **{p.get('name')}** — {p.get('why_comparable', '')}")
            else:
                lines.append(f"- {p}")
        lines.append("")

    path = traces.eval_dir(eval_id) / "pitch.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
