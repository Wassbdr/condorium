"""The Cohort: idea generators (upstream layer).

Interviewer (human idea, refined via interrupt dialogue), Hackathon
Generator, Scientist Generator (dual research channel + citation gate),
Historian (knowledge-graph driven, abstains on an empty base).
"""

from __future__ import annotations

import json
import re

from langgraph.types import interrupt

from ..knowledge.calibration import historian_context_block
from ..llm import safe_complete_json
from ..prompts import generator_prompt, render
from ..sources.papers import filter_cited_references, search_papers
from ..sources.web import search_web
from ..state import Idea, PanelState

MAX_INTERVIEW_TURNS = 12  # 5 questions + tradeoff + margin for malformed turns


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [t.strip() for t in re.split(r"[,/+]", str(value or "")) if t.strip()]


def _raw_ideas(result) -> list[dict]:
    ideas = result.get("ideas") if isinstance(result, dict) else None
    return [r for r in ideas if isinstance(r, dict)] if isinstance(ideas, list) else []


def _mk_idea(raw: dict, provenance: str, index: int) -> Idea:
    text_bits = [raw.get("pitch") or raw.get("text") or ""]
    for key, label in (("tech", "Tech"), ("wow_moment", "Wow moment"), ("audience", "Audience")):
        if raw.get(key):
            text_bits.append(f"{label}: {raw[key]}")
    return {
        "id": f"{provenance}-{index}",
        "title": raw.get("title", f"idea {index}"),
        "text": ". ".join(b for b in text_bits if b),
        "provenance": provenance,
        "tech": _as_list(raw.get("tech")),
        "references": raw.get("references", []),
        "inspired_by": raw.get("inspired_by", []),
    }


# The Interviewer dialogue is a GRAPH CYCLE, not an in-node loop: each LLM
# call sits in its own completed node (checkpointed, never re-paid on resume)
# and the interrupt() lives in a gate node that makes no LLM call at all.
#   interviewer_step (LLM) -> route -> interviewer_gate (interrupt) -> step...
#                                   -> interviewer_done -> collect

def interviewer_step(state: PanelState) -> dict:
    """One LLM turn of the refinement dialogue."""
    prompt = generator_prompt("interviewer", state.get("lang"))
    iv = state.get("interview") or {
        "transcript": [{"role": "user_idea", "content": state.get("raw_input", "")}],
        "questions": 0, "turns": 0,
    }
    system = render(prompt.body,
                    transcript=json.dumps(iv["transcript"], ensure_ascii=False, indent=2))
    step, error = safe_complete_json(system, "Next step.")
    out: dict = {"interview": {**iv, "turns": iv.get("turns", 0) + 1,
                               "step": step if isinstance(step, dict) else {}}}
    if error:  # an empty step routes to interviewer_done: the raw idea goes on
        out["warnings"] = [f"interviewer: {error}"]
    return out


def interviewer_route(state: PanelState) -> str:
    iv = state.get("interview") or {}
    step = iv.get("step") or {}
    action = step.get("action")
    if iv.get("turns", 0) >= MAX_INTERVIEW_TURNS:
        return "interviewer_done"
    if action == "ask" and iv.get("questions", 0) < 5:
        return "interviewer_gate"
    if action == "tradeoff" and not iv.get("tradeoff_done"):
        return "interviewer_gate"
    return "interviewer_done"


def interviewer_gate(state: PanelState) -> dict:
    """The user answers through interrupt(); no LLM call in this node."""
    iv = dict(state.get("interview") or {})
    step = iv.get("step") or {}
    transcript = list(iv.get("transcript", []))
    if step.get("action") == "ask":
        answer = interrupt({"type": "interview_question", "question": step.get("question", "")})
        transcript += [{"role": "interviewer", "content": step.get("question", "")},
                       {"role": "user", "content": str(answer)}]
        iv["questions"] = iv.get("questions", 0) + 1
    else:  # tradeoff — THE USER decides
        choice = interrupt({"type": "tech_tradeoff",
                            "wow_option": step.get("wow_option"),
                            "mastered_option": step.get("mastered_option")})
        transcript += [{"role": "interviewer", "content": json.dumps(step, ensure_ascii=False)},
                       {"role": "user", "content": f"chosen: {choice}"}]
        iv["tradeoff_done"] = True
    iv["transcript"] = transcript
    iv.pop("step", None)
    return {"interview": iv}


def interviewer_done(state: PanelState) -> dict:
    step = (state.get("interview") or {}).get("step") or {}
    idea_raw = step.get("idea") or {"title": "user idea", "text": state.get("raw_input", "")}
    idea = _mk_idea(idea_raw, "user", 0)
    idea["text"] = idea_raw.get("text", idea["text"])
    return {"ideas": [idea]}


def passthrough_idea_node(state: PanelState) -> dict:
    """`--no-interview`: the raw user idea goes straight to intake."""
    return {"ideas": [{
        "id": "user-0", "title": (state.get("raw_input", "").split("\n")[0])[:80] or "user idea",
        "text": state.get("raw_input", ""), "provenance": "user",
    }]}


def hackathon_generator_node(state: PanelState) -> dict:
    prompt = generator_prompt("hackathon", state.get("lang"))
    n = state.get("n_ideas") or 5
    system = render(
        prompt.body, n=n,
        official_criteria=state.get("official_criteria") or "(none announced)",
        theme=state.get("theme") or "(open)",
        duration=state.get("duration") or "(unspecified)",
        context=state.get("context") or state.get("constraints") or "(none)",
    )
    result, error = safe_complete_json(system, "Generate the ideas now.")
    if error:
        return {"ideas": [], "warnings": [f"hackathon generator: {error}"]}
    return {"ideas": [_mk_idea(r, "hackathon", i)
                      for i, r in enumerate(_raw_ideas(result)[: n])]}


def scientist_generator_node(state: PanelState) -> dict:
    """Dual mandatory channel (paper APIs + web) + orchestrator citation gate:
    an idea whose references are not API-retrieved URLs is rejected."""
    prompt = generator_prompt("scientist", state.get("lang"))
    n = state.get("n_ideas") or 5
    query = " ".join(f"{state.get('theme', '')} {state.get('context', '')}".split()[:14]) or "emerging research"
    channels: dict = {}
    papers = [p.as_dict() for p in search_papers(query, status=channels)]
    web = search_web(query, status=channels)
    sources = papers + web
    if not sources:
        detail = ", ".join(f"{k}: {v}" for k, v in channels.items())
        return {"ideas": [], "warnings": [f"scientist: no source retrieved ({detail})"]}
    system = render(
        prompt.body, n=n,
        retrieved_sources=json.dumps(sources, indent=2, ensure_ascii=False),
        theme=state.get("theme") or "(open)",
        duration=state.get("duration") or "(unspecified)",
        context=state.get("context") or "(none)",
    )
    result, error = safe_complete_json(system, "Generate the ideas now.", timeout=prompt.timeout)
    if error:
        return {"ideas": [], "warnings": [f"scientist generator: {error}"]}
    kept: list[Idea] = []
    for i, raw in enumerate(_raw_ideas(result)[: n]):
        valid_refs = filter_cited_references(raw.get("references", []), sources)
        if not valid_refs:
            continue  # ABSOLUTE RULE: no verifiable API-retrieved source, no idea
        raw["references"] = valid_refs
        kept.append(_mk_idea(raw, "scientist", i))
    return {"ideas": kept}


def historian_node(state: PanelState) -> dict:
    """Knowledge-graph-driven ideas; says so and abstains on an empty base."""
    graph_context = historian_context_block(state.get("theme", ""), [])
    if '"empty": true' in graph_context:
        return {"ideas": []}
    prompt = generator_prompt("historian", state.get("lang"))
    system = render(
        prompt.body,
        graph_context=graph_context,
        theme=state.get("theme") or "(open)",
        context=state.get("context") or "(none)",
    )
    result, error = safe_complete_json(system, "Generate the ideas now.")
    if error:
        return {"ideas": [], "warnings": [f"historian: {error}"]}
    if not isinstance(result, dict) or result.get("abstained"):
        return {"ideas": []}
    return {"ideas": [_mk_idea(r, "historian", i) for i, r in enumerate(_raw_ideas(result))]}


GENERATOR_NODES = {
    "hackathon": hackathon_generator_node,
    "scientist": scientist_generator_node,
    "historian": historian_node,
}
