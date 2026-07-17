"""The Cohort: idea generators (upstream layer).

Interviewer (human idea, refined via interrupt dialogue), Hackathon
Generator, Scientist Generator (dual research channel + citation gate),
Historian (knowledge-graph driven, abstains on an empty base).
"""

from __future__ import annotations

import json

from langgraph.types import interrupt

from ..knowledge.calibration import historian_context_block
from ..llm import complete_json
from ..prompts import generator_prompt, render
from ..sources.papers import filter_cited_references, search_papers
from ..sources.web import search_web
from ..state import Idea, PanelState

MAX_INTERVIEW_TURNS = 12  # 5 questions + tradeoff + margin for malformed turns


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
        "references": raw.get("references", []),
        "inspired_by": raw.get("inspired_by", []),
    }


def interviewer_node(state: PanelState) -> dict:
    """Short refinement dialogue: max 5 questions, one at a time, then the
    quantified tech trade-off. The user answers through interrupt()."""
    prompt = generator_prompt("interviewer", state.get("lang"))
    transcript: list[dict] = [{"role": "user_idea", "content": state.get("raw_input", "")}]
    questions_asked = 0
    for _ in range(MAX_INTERVIEW_TURNS):
        system = render(prompt.body, transcript=json.dumps(transcript, ensure_ascii=False, indent=2))
        step = complete_json(system, "Next step.")
        if not isinstance(step, dict):
            break
        action = step.get("action")
        if action == "ask" and questions_asked < 5:
            questions_asked += 1
            answer = interrupt({"type": "interview_question", "question": step.get("question", "")})
            transcript += [{"role": "interviewer", "content": step.get("question", "")},
                           {"role": "user", "content": str(answer)}]
        elif action == "tradeoff":
            choice = interrupt({"type": "tech_tradeoff",
                                "wow_option": step.get("wow_option"),
                                "mastered_option": step.get("mastered_option")})
            transcript += [{"role": "interviewer", "content": json.dumps(step)},
                           {"role": "user", "content": f"chosen: {choice}"}]
        else:  # "done", or question budget exhausted
            idea_raw = step.get("idea") or {"title": "user idea", "text": state.get("raw_input", "")}
            idea = _mk_idea(idea_raw, "user", 0)
            idea["text"] = idea_raw.get("text", idea["text"])
            return {"ideas": [idea]}
    return {"ideas": [_mk_idea({"title": "user idea", "text": state.get("raw_input", "")}, "user", 0)]}


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
    result = complete_json(system, "Generate the ideas now.")
    raw_ideas = (result or {}).get("ideas", []) if isinstance(result, dict) else []
    return {"ideas": [_mk_idea(r, "hackathon", i) for i, r in enumerate(raw_ideas[: n])]}


def scientist_generator_node(state: PanelState) -> dict:
    """Dual mandatory channel (paper APIs + web) + orchestrator citation gate:
    an idea whose references are not API-retrieved URLs is rejected."""
    prompt = generator_prompt("scientist", state.get("lang"))
    n = state.get("n_ideas") or 5
    query = " ".join(f"{state.get('theme', '')} {state.get('context', '')}".split()[:14]) or "emerging research"
    papers = [p.as_dict() for p in search_papers(query)]
    web = search_web(query)
    sources = papers + web
    system = render(
        prompt.body, n=n,
        retrieved_sources=json.dumps(sources, indent=2, ensure_ascii=False),
        theme=state.get("theme") or "(open)",
        duration=state.get("duration") or "(unspecified)",
        context=state.get("context") or "(none)",
    )
    result = complete_json(system, "Generate the ideas now.", timeout=prompt.timeout)
    raw_ideas = (result or {}).get("ideas", []) if isinstance(result, dict) else []
    kept: list[Idea] = []
    for i, raw in enumerate(raw_ideas[: n]):
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
    result = complete_json(system, "Generate the ideas now.")
    if not isinstance(result, dict) or result.get("abstained"):
        return {"ideas": []}
    return {"ideas": [_mk_idea(r, "historian", i) for i, r in enumerate(result.get("ideas", []))]}


GENERATOR_NODES = {
    "hackathon": hackathon_generator_node,
    "scientist": scientist_generator_node,
    "historian": historian_node,
}
