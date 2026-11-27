"""Small web UI: watch the committee deliberate, live or from a recorded run.

`panel ui` (needs the `ui` extra). Live mode streams LangGraph node updates
as they land; replay mode re-plays a recorded trace and needs no API key.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path

from .comparison import (
    Rubric,
    compare,
    comparison_error,
    comparison_model,
    default_rubric_path,
    format_comparison,
)
from .config import SETTINGS
from .display import believer_cap, format_score

REPLAY_NOTE = ("> **Replay of a recorded run** — no LLM is called, no API key is needed. "
               "The opinions below were recorded from a past live run.")
LIVE_NOTE = "> **Live run** — every opinion below is being generated now by `{model}`."
ORDER = ("judge", "believer", "scientist_eval", "skeptic", "investor", "strategist", "jury")


def render(record: dict, note: str, status: str = "") -> str:
    """Markdown view of a (possibly partial) evaluation record."""
    idea = record.get("idea") or {}
    r1, r2 = record.get("round1") or {}, record.get("round2") or {}
    out = [note, "", f"## {idea.get('title') or 'Idea'}", "", idea.get("text", "")]
    if status:
        out += ["", f"*{status}*"]
    names = [n for n in ORDER if n in r1 or n in r2] + sorted(set(r1) | set(r2) - set(ORDER))
    if names:
        out += ["", "| agent | round 1 (blind) | round 2 (after deliberation) | view |",
                "|---|---|---|---|"]
        for n in names:
            o1, o2 = r1.get(n) or {}, r2.get(n) or {}
            s1 = format_score(o1.get("score")) if o1 else "…"
            s2 = format_score(o2.get("score")) if o2 else "…"
            if o2.get("capped"):
                s2 = f"**{o2['score']}** (capped from {o2.get('uncapped_score')})"
            view = (o2.get("verdict") or o1.get("verdict") or "").replace("|", "/")[:140]
            out.append(f"| {n} | {s1} | {s2} | {view} |")
    limit = believer_cap(record) if "believer" in r2 else None
    if limit is not None:
        b = r2["believer"]
        state = (f"asked {b.get('uncapped_score')} → **capped to {b['score']}**"
                 if b.get("capped") else f"{b.get('score')} is within the cap")
        out += ["", f"**Anti-sycophancy cap (code):** believer ≤ median(others' blind "
                    f"scores) + 3 = **{limit:g}** — {state}"]
    syn = record.get("synthesis") or {}
    if syn:
        out += ["", f"### Verdict: {syn.get('verdict', '?')}", "", syn.get("consensus", ""),
                "", "*No average is computed: disagreements are shown instead.*"]
        for d in syn.get("disagreements") or []:
            crit = " — **critical**" if d.get("critical") else ""
            out.append(f"- **{d.get('topic', '')}** (gap {d.get('gap', '?')}: "
                       f"{', '.join(d.get('agents', []))}){crit}: {d.get('positions', '')}")
        if syn.get("debate_outcome"):
            out.append(f"\n**Targeted debate:** {syn['debate_outcome']} — "
                       f"{syn.get('debate_conclusion', '')}")
        out += ["", f"**Next action:** {syn.get('action', '')}"]
    return "\n".join(out)


def recorded_traces() -> dict[str, Path]:
    return {p.stem: p for p in sorted(SETTINGS.demo_dir.glob("*.json"))}


def replay(trace: Path, pause: float = 0.6) -> Iterator[str]:
    """Re-play a recorded evaluation in the order the graph produced it."""
    full = json.loads(Path(trace).read_text(encoding="utf-8"))
    rec: dict = {"idea": full.get("idea", {}), "round1": {}, "round2": {}}
    yield render(rec, REPLAY_NOTE, "intake…")
    for stage in ("round1", "round2"):
        for name in [n for n in ORDER if n in full.get(stage, {})]:
            time.sleep(pause)
            rec[stage][name] = full[stage][name]
            yield render(rec, REPLAY_NOTE, f"{stage.replace('round', 'round ')}: {name}")
    time.sleep(pause)
    rec["synthesis"] = full.get("synthesis") or {}
    yield render(rec, REPLAY_NOTE, "replay finished")


def live(title: str, text: str, mode: str = "general") -> Iterator[str]:
    """Run the evaluation subgraph and yield a view after every node."""
    from .graph.evaluation import compile_evaluation_graph

    rec: dict = {"idea": {"title": title, "text": text}, "round1": {}, "round2": {}}
    note = LIVE_NOTE.format(model=SETTINGS.model)
    yield render(rec, note, "intake…")
    app = compile_evaluation_graph(mode)
    initial = {"idea": {"id": "ui", "title": title, "text": text, "provenance": "user"},
               "mode": mode, "interactive": False, "no_persist": True}
    for update in app.stream(initial, stream_mode="updates"):
        for node, delta in update.items():
            for key, value in (delta or {}).items():
                if key in ("round1", "round2"):
                    rec[key].update(value)
                elif key in ("synthesis", "debate", "intake"):
                    rec[key] = value
            yield render(rec, note, f"{node} done")
    yield render(rec, note, "evaluation finished")


def run_comparison(a: str, b: str, rubric_text: str) -> str:
    model = comparison_model()
    try:
        criteria = Rubric.from_yaml(rubric_text)
        return format_comparison(compare(a, b, criteria, model=model))
    except Exception as exc:
        error = comparison_error(exc, model)
        if error is None:
            raise
        return f"Error: {error}"


def build_app():
    import gradio as gr

    traces = recorded_traces()
    with gr.Blocks(title="Condorium — idea committee") as app:
        gr.Markdown("# Condorium\nA committee of LLM agents judges an idea in two rounds "
                    "(blind, then after deliberation). Guardrails are enforced in code.")
        with gr.Tab("Replay (no key)"):
            choice = gr.Dropdown(list(traces), value=next(iter(traces), None),
                                 label="Recorded run")
            play = gr.Button("Replay deliberation", variant="primary")
            replay_out = gr.Markdown(REPLAY_NOTE)
            play.click(lambda name: (yield from replay(traces[name])), choice, replay_out)
        with gr.Tab("Live"):
            gr.Markdown(f"Model: `{SETTINGS.model}` (set `CONDORIUM_MODEL` and the provider "
                        "key, e.g. `ANTHROPIC_API_KEY` or `NVIDIA_NIM_API_KEY`).")
            title = gr.Textbox(label="Title", value="Compost Courier")
            text = gr.Textbox(label="Idea", lines=4, value=(
                "Restaurants hand food scraps to community gardens; a driver app batches "
                "pickups by street and gardens confirm each delivery with a photo."))
            mode = gr.Radio(["general", "hackathon"], value="general", label="Mode")
            go = gr.Button("Evaluate live", variant="primary")
            live_out = gr.Markdown()

            def run_live(t, x, m):
                try:
                    yield from live(t, x, m)
                except Exception as exc:  # surface provider/key errors in the page
                    yield f"**Live run failed:** `{type(exc).__name__}: {str(exc)[:300]}`"

            go.click(run_live, [title, text, mode], live_out)
        with gr.Tab("Compare"):
            first = gr.Textbox(label="Proposal A", lines=5)
            second = gr.Textbox(label="Proposal B", lines=5)
            rubric = gr.Code(label="Rubric", language="yaml", interactive=True,
                             value=default_rubric_path().read_text(encoding="utf-8"))
            compare_button = gr.Button("Compare proposals", variant="primary")
            result = gr.Textbox(label="Comparison result", lines=12, interactive=False)
            compare_button.click(run_comparison, [first, second, rubric], result)
    return app
