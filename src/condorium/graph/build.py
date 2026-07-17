"""The main StateGraph: Cohort -> [Pre-filter] -> map over ideas ->
Evaluation subgraph (per idea, isolated) -> [Clerk if tournament] -> report.
"""

from __future__ import annotations

import json

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from ..analytics import traces
from ..llm import complete_json
from ..prompts import load_prompt, render
from ..state import PanelState
from . import cohort
from .evaluation import compile_evaluation_graph

DEFAULT_TOP = 3


# ------------------------------------------------------------------ nodes

def entry_node(state: PanelState) -> dict:
    return {"run_id": state.get("run_id") or traces.new_id("run", state.get("command", ""))}


def route_entry(state: PanelState) -> list[Send] | str:
    command = state.get("command", "eval")
    if command == "eval":
        return "interviewer" if state.get("interactive") else "direct_idea"
    sources = state.get("sources") or ["hackathon"]
    return [Send(f"gen_{s}", state) for s in sources if f"gen_{s}" in GEN_NODE_NAMES]


def collect_node(state: PanelState) -> dict:
    """Stamp unique ids; nothing else. Scientist citation gating already
    happened in its generator node."""
    stamped = [
        {**idea, "id": f"{state.get('run_id', 'run')}-i{i}"}
        for i, idea in enumerate(state.get("ideas", []))
    ]
    return {"selected": stamped}


def prefilter_node(state: PanelState) -> dict:
    """One light call per idea, 3 criteria; the USER picks the threshold
    (interrupt) unless --top was given. Eliminated ideas keep their scores."""
    ideas = state.get("selected") or []
    if len(ideas) <= 1:
        return {"selected": ideas, "eliminated": []}
    prompt = load_prompt("system/prefilter.md", state.get("lang"))
    scored = []
    for idea in ideas:
        system = render(prompt.body,
                        context=state.get("context") or state.get("theme") or "(none)",
                        constraints=state.get("constraints") or "(none)")
        s = complete_json(system, f"IDEA:\n{idea.get('title')}\n{idea.get('text')}")
        s = s if isinstance(s, dict) else {}
        total = sum(v for v in (s.get("theme_fit"), s.get("wow_potential"),
                                s.get("apparent_feasibility")) if isinstance(v, (int, float)))
        scored.append({**idea, "prefilter": {**s, "total": total}})
    scored.sort(key=lambda i: -i["prefilter"]["total"])

    top = state.get("top")
    if top is None:
        answer = interrupt({
            "type": "prefilter_threshold",
            "ranking": [{"id": i["id"], "title": i["title"], **i["prefilter"]} for i in scored],
            "default": min(DEFAULT_TOP, len(scored)),
        })
        try:
            top = int(answer)
        except (TypeError, ValueError):
            top = min(DEFAULT_TOP, len(scored))
    top = max(1, min(top, len(scored)))
    return {"selected": scored[:top], "eliminated": scored[top:]}


def route_to_evaluations(state: PanelState) -> list[Send]:
    """The map step: ONE isolated evaluation per idea. In tournament mode the
    provenance is stripped before the idea enters the committee's state."""
    mask = state.get("command") == "tournament"
    sends = []
    for idea in state.get("selected") or []:
        committee_idea = dict(idea)
        if mask:
            committee_idea.pop("provenance", None)
            committee_idea.pop("inspired_by", None)
        sends.append(Send("evaluate", {
            "idea": committee_idea,
            "mode": state.get("mode", "general"),
            "constraints": state.get("constraints", ""),
            "official_criteria": state.get("official_criteria", ""),
            "custom_criteria": state.get("custom_criteria", ""),
            "lang": state.get("lang", "en"),
            "interactive": state.get("interactive", False) and not mask,
            "mask_provenance": mask,
            "eval_id": f"{idea['id']}",
            "_provenance": idea.get("provenance"),  # kept outside the committee's view
        }))
    return sends


def make_evaluate_node(lang: str | None = None):
    compiled: dict[str, object] = {}

    def evaluate_node(eval_input: dict, config=None) -> dict:
        mode = eval_input.get("mode", "general")
        if mode not in compiled:
            compiled[mode] = compile_evaluation_graph(mode, eval_input.get("lang"))
        provenance = eval_input.pop("_provenance", None)
        result = compiled[mode].invoke(eval_input, config)
        record = {
            "eval_id": result.get("eval_id"),
            "idea": {**result.get("idea", {}), "provenance": provenance},
            "synthesis": result.get("synthesis", {}),
            "round1": result.get("round1", {}),
            "round2": result.get("round2", {}),
            "debate": result.get("debate", {}),
        }
        return {"evaluations": [record]}

    return evaluate_node


def clerk_node(state: PanelState) -> dict:
    """Ranks from the synthesis JSONs ONLY — never raw ideas, never the
    detailed evaluations."""
    prompt = load_prompt("system/clerk.md", state.get("lang"))
    syntheses = [
        {"eval_id": e.get("eval_id"), "synthesis": e.get("synthesis", {})}
        for e in state.get("evaluations", [])
    ]
    system = render(prompt.body, syntheses=json.dumps(syntheses, indent=2, ensure_ascii=False))
    ranking = complete_json(system, "Rank now.")
    return {"ranking": ranking if isinstance(ranking, dict) else {}}


def finalize_node(state: PanelState) -> dict:
    run = {
        "run_id": state.get("run_id"),
        "command": state.get("command"),
        "mode": state.get("mode"),
        "sources": state.get("sources"),
        "ideas": state.get("ideas", []),
        "selected": [i.get("id") for i in state.get("selected", [])],
        "eliminated": state.get("eliminated", []),
        "evaluations": [e.get("eval_id") for e in state.get("evaluations", [])],
        # provenance is revealed here, in the final ranking — not before
        "provenances": {e.get("eval_id"): e.get("idea", {}).get("provenance")
                        for e in state.get("evaluations", [])},
        "ranking": state.get("ranking", {}),
    }
    if run.get("run_id"):
        traces.save_run(run)
    return {}


GEN_NODE_NAMES = {"gen_hackathon", "gen_scientist", "gen_historian"}


# ------------------------------------------------------------------ build

def build_main_graph(lang: str | None = None) -> StateGraph:
    g = StateGraph(PanelState)
    g.add_node("entry", entry_node)
    g.add_edge(START, "entry")

    g.add_node("interviewer", cohort.interviewer_node)
    g.add_node("direct_idea", cohort.passthrough_idea_node)
    g.add_node("gen_hackathon", cohort.hackathon_generator_node)
    g.add_node("gen_scientist", cohort.scientist_generator_node)
    g.add_node("gen_historian", cohort.historian_node)

    g.add_conditional_edges(
        "entry", route_entry,
        ["interviewer", "direct_idea", "gen_hackathon", "gen_scientist", "gen_historian"],
    )

    g.add_node("collect", collect_node)
    for n in ("interviewer", "direct_idea", "gen_hackathon", "gen_scientist", "gen_historian"):
        g.add_edge(n, "collect")

    g.add_node("prefilter", prefilter_node)
    g.add_conditional_edges(
        "collect",
        lambda s: "prefilter" if len(s.get("selected") or []) > 1 else "fanout",
        {"prefilter": "prefilter", "fanout": "fanout"},
    )
    g.add_node("fanout", lambda s: {})
    g.add_edge("prefilter", "fanout")

    g.add_node("evaluate", make_evaluate_node(lang))
    g.add_conditional_edges("fanout", route_to_evaluations, ["evaluate"])

    g.add_node("clerk", clerk_node)
    g.add_node("finalize", finalize_node)
    g.add_conditional_edges(
        "evaluate",
        lambda s: "clerk" if s.get("command") == "tournament" else "finalize",
        {"clerk": "clerk", "finalize": "finalize"},
    )
    g.add_edge("clerk", "finalize")
    g.add_edge("finalize", END)
    return g


def compile_main_graph(lang: str | None = None, checkpointer=None):
    return build_main_graph(lang).compile(checkpointer=checkpointer)


def mermaid_diagram() -> str:
    """`panel graph` — export the compiled graph as Mermaid for the README."""
    app = compile_main_graph()
    return app.get_graph().draw_mermaid()
