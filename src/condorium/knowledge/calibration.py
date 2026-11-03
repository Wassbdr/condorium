"""Calibration: inject the 5 graph-nearest past winners into Judge/Jury prompts."""

from __future__ import annotations

import json

from . import kgraph, store


def nearest_winners_block(theme: str, techs: list[str] | None = None, k: int = 5, *,
                          idea_text: str = "", exclude: dict | None = None) -> str:
    """Human-readable block for the {nearest_winners} placeholder.

    Context = the session theme + the idea's declared techs + known techs
    named in its text. Only winners sharing something with it are shown."""
    g = kgraph.load_graph()
    if g.number_of_nodes() == 0:
        return "(knowledge base is empty — no calibration available)"
    all_techs = sorted(set(techs or []) | set(kgraph.techs_mentioned(g, idea_text)))
    nearest = kgraph.nearest_projects_to_context(
        g, all_techs, [theme] if theme else [], k, min_overlap=1, exclude=exclude)
    winners = {w["id"]: w for w in store.load_winners()}
    lines = []
    for item in nearest:
        w = winners.get(item.get("entry_id") or "", {})
        lines.append(
            f"- {item['label']}: {item.get('pitch') or w.get('one_sentence_pitch', '')} "
            f"(won {w.get('hackathon', '?')}, theme {w.get('theme', '?')}; "
            f"why it won: {w.get('why_it_won', 'n/a')})"
        )
    return "\n".join(lines) if lines else "(no comparable winners found)"


def historian_context_block(theme: str, techs: list[str] | None = None) -> str:
    """JSON block for the Historian's {graph_context} placeholder."""
    ctx = kgraph.historian_context(theme, techs)
    return json.dumps(ctx, indent=2, ensure_ascii=False)
