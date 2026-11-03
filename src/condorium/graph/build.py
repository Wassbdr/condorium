"""The main StateGraph: Cohort -> [Pre-filter] -> map over ideas ->
Evaluation subgraph (per idea, isolated) -> [Clerk if tournament] -> report.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from ..analytics import traces
from ..llm import safe_complete_json
from ..prompts import load_prompt, render
from ..schemas import PREFILTER_CRITERIA, coerce_prefilter, coerce_ranking
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
        return "interviewer_step" if state.get("interactive") else "direct_idea"
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
    """One light call per idea (in parallel), 3 criteria. Scoring only — the
    threshold interrupt lives in prefilter_gate, so resuming an interrupted
    tournament never re-pays these calls."""
    ideas = state.get("selected") or []
    if len(ideas) <= 1:
        return {"selected": ideas, "eliminated": []}
    prompt = load_prompt("system/prefilter.md", state.get("lang"))
    system = render(prompt.body,
                    context=state.get("context") or state.get("theme") or "(none)",
                    constraints=state.get("constraints") or "(none)")

    def score(idea: dict) -> dict:
        raw, error = safe_complete_json(system, f"IDEA:\n{idea.get('title')}\n{idea.get('text')}")
        s = coerce_prefilter(raw)
        if error:
            s["error"] = error  # scored 0: ranked last, still eligible if the user wants it
        total = sum(v for v in (s.get(k) for k in PREFILTER_CRITERIA)
                    if isinstance(v, (int, float)))
        return {**idea, "prefilter": {**s, "total": total}}

    with ThreadPoolExecutor(max_workers=min(8, len(ideas))) as pool:
        scored = list(pool.map(score, ideas))
    scored.sort(key=lambda i: -i["prefilter"]["total"])
    warnings = [f"prefilter '{i.get('title')}': {i['prefilter']['error']}"
                for i in scored if i["prefilter"].get("error")]
    return {"selected": scored, "eliminated": [], "warnings": warnings}


def prefilter_gate(state: PanelState) -> dict:
    """The USER picks the threshold (interrupt) unless --top was given.
    Eliminated ideas keep their pre-filter scores."""
    scored = state.get("selected") or []
    if len(scored) <= 1:
        return {}
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
            "theme": state.get("theme", ""),
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
            # checkpointer=True: inherit the parent graph's checkpointer, so
            # interrupts inside the subgraph (intake validation) resume
            # without re-running its completed nodes.
            compiled[mode] = compile_evaluation_graph(
                mode, eval_input.get("lang"), checkpointer=True)
        provenance = eval_input.pop("_provenance", None)
        result = compiled[mode].invoke(eval_input, config)
        record = {
            "eval_id": result.get("eval_id"),
            "idea": {**result.get("idea", {}), "provenance": provenance},
            "synthesis": result.get("synthesis", {}),
            "round1": result.get("round1", {}),
            "round2": result.get("round2", {}),
            "debate": result.get("debate", {}),
            "errors": result.get("errors", []),
        }
        warnings = [f"{record['eval_id']}: {e}" for e in record["errors"]]
        return {"evaluations": [record], "warnings": warnings}

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
    raw, error = safe_complete_json(system, "Rank now.")
    if error:
        return {"ranking": {}, "warnings": [f"clerk: {error} — no ranking, "
                                            "the evaluations themselves are saved"]}
    return {"ranking": coerce_ranking(raw)}


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

    g.add_node("interviewer_step", cohort.interviewer_step)
    g.add_node("interviewer_gate", cohort.interviewer_gate)
    g.add_node("interviewer_done", cohort.interviewer_done)
    g.add_node("direct_idea", cohort.passthrough_idea_node)
    g.add_node("gen_hackathon", cohort.hackathon_generator_node)
    g.add_node("gen_scientist", cohort.scientist_generator_node)
    g.add_node("gen_historian", cohort.historian_node)

    g.add_conditional_edges(
        "entry", route_entry,
        ["interviewer_step", "direct_idea", "gen_hackathon", "gen_scientist", "gen_historian"],
    )
    # dialogue cycle: step (LLM) -> gate (interrupt) -> step ... -> done
    g.add_conditional_edges("interviewer_step", cohort.interviewer_route,
                            {"interviewer_gate": "interviewer_gate",
                             "interviewer_done": "interviewer_done"})
    g.add_edge("interviewer_gate", "interviewer_step")

    g.add_node("collect", collect_node)
    for n in ("interviewer_done", "direct_idea", "gen_hackathon", "gen_scientist", "gen_historian"):
        g.add_edge(n, "collect")

    g.add_node("prefilter", prefilter_node)
    g.add_node("prefilter_gate", prefilter_gate)
    g.add_conditional_edges(
        "collect",
        lambda s: "prefilter" if len(s.get("selected") or []) > 1 else "fanout",
        {"prefilter": "prefilter", "fanout": "fanout"},
    )
    g.add_node("fanout", lambda s: {})
    g.add_edge("prefilter", "prefilter_gate")
    g.add_edge("prefilter_gate", "fanout")

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
