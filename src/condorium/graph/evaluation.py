"""The evaluation subgraph — runs for ONE idea, in total isolation.

intake -> round 1 (parallel fan-out, agents blind to each other)
       -> round 2 (parallel, each agent sees all round-1 opinions)
       -> synthesis (no averaging)
       -> [targeted debate: exactly 2 agents, exactly 1 round, only on a
           major disagreement]
       -> persist

Committee guardrails that must not depend on model obedience are enforced
HERE, in code: the Believer cap, the scientist citation gate, the skeptic
doubt-without-test rule, the neutral-score exclusion, and the debate trigger
(the score gap is computed from round-2 scores, never taken from the model).
Every model output is coerced (`schemas.py`) before a rule reads it, and a
failed call degrades that one agent instead of aborting the evaluation.
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ..analytics import traces
from ..config import SETTINGS
from ..knowledge.calibration import nearest_winners_block
from ..llm import safe_complete_json
from ..prompts import AgentPrompt, committee_prompts, load_prompt, render
from ..schemas import coerce_debate_update, coerce_opinion, coerce_synthesis
from ..sources.papers import filter_cited_references, search_papers
from ..sources.web import search_web
from ..state import EvalState, median, opinion_scores

MAJOR_GAP = 3
QUORUM = 4  # fewer numeric round-2 scores than this: the synthesis is flagged degraded


# ---------------------------------------------------------------- helpers

def _idea_block(state: EvalState) -> str:
    idea = state["idea"]
    parts = [f"TITLE: {idea.get('title', '(untitled)')}", f"IDEA: {idea.get('text', '')}"]
    # provenance is NEVER shown to the committee
    intake = state.get("intake") or {}
    if intake:
        parts += [
            f"NEUTRAL RESTATEMENT: {intake.get('restatement', '')}",
            f"IMPLICIT ASSUMPTIONS: {json.dumps(intake.get('implicit_assumptions', []))}",
            f"THE OPEN QUESTION: {intake.get('open_question', '')}",
        ]
    if state.get("constraints"):
        parts.append(f"CONSTRAINTS: {state['constraints']}")
    return "\n".join(parts)


def _render_agent_prompt(prompt: AgentPrompt, state: EvalState) -> str:
    values: dict[str, Any] = {
        "constraints": state.get("constraints") or "(none stated)",
        "official_criteria": state.get("official_criteria")
        or "innovation, feasibility, impact, execution",
        "custom_criteria": state.get("custom_criteria") or "(none)",
    }
    if "{nearest_winners}" in prompt.body:
        idea = state["idea"]
        values["nearest_winners"] = nearest_winners_block(
            state.get("theme", ""), idea.get("tech") or [],
            idea_text=f"{idea.get('title', '')}\n{idea.get('text', '')}",
            exclude=state.get("calibration_exclude"),
        )
    if "{retrieved_sources}" in prompt.body:
        research = state.get("research") or {}
        values["retrieved_sources"] = json.dumps(research.get("sources", []), indent=2) or "[]"
    return render(prompt.body, **values)


def _normalize(name: str, opinion: dict, state: EvalState, round_no: int) -> dict:
    """Code-enforced guardrails, applied to every parsed opinion."""
    opinion = coerce_opinion(opinion)
    if name == "skeptic":
        # A doubt without a test is deleted: watchouts beyond the tests list drop.
        watchouts = opinion.get("watchouts") or []
        tests = opinion.get("proposed_tests") or []
        if len(watchouts) > len(tests):
            opinion["watchouts"] = watchouts[: len(tests)]
            opinion["trimmed_doubts_without_test"] = len(watchouts) - len(tests)
    if name == "scientist_eval":
        retrieved = (state.get("research") or {}).get("sources", [])
        opinion["references"] = filter_cited_references(opinion.get("references"), retrieved)
        if opinion.get("scientific_verdict") == "neutral":
            opinion["score"] = None  # informational only, excluded everywhere
    if name == "believer" and round_no == 2:
        others = {k: v for k, v in (state.get("round1") or {}).items() if k != "believer"}
        med = median(list(opinion_scores(others).values()))
        if med is not None and isinstance(opinion.get("score"), (int, float)):
            cap = med + 3
            if opinion["score"] > cap:
                opinion["uncapped_score"] = opinion["score"]
                opinion["score"] = int(cap)
                opinion["capped"] = True
    return opinion


def _failed_opinion(error: str, round_no: int) -> dict:
    """A failed agent is excluded (score null), never invented."""
    opinion = {"score": None, "verdict": "(agent failed — excluded from this evaluation)",
               "error": error}
    if round_no == 2:
        opinion.update(revision="maintained", influenced_by=[])
    return opinion


def _with_computed_gaps(synthesis: dict, round2: dict) -> dict:
    """The debate trigger reads the REAL gap between the two named agents'
    round-2 scores; the model's own figure is kept as `gap_reported`."""
    scores = opinion_scores(round2)
    for d in synthesis.get("disagreements") or []:
        d["gap_reported"] = d.get("gap", 0)
        agents = [a for a in d.get("agents", []) if a in round2]
        if len(agents) == 2 and all(a in scores for a in agents):
            d["gap"] = abs(scores[agents[0]] - scores[agents[1]])
        else:
            d["gap"] = 0  # a null (neutral/failed) score is no quality gap
    return synthesis


def _research_for_idea(state: EvalState) -> dict:
    """Dual mandatory channel: paper APIs + web, run during round 1."""
    idea = state["idea"]
    query = " ".join((idea.get("title", "") + " " + idea.get("text", "")).split()[:14])
    channels: dict = {}
    papers = [p.as_dict() for p in search_papers(query, status=channels)]
    web = search_web(query, status=channels)
    return {"query": query, "sources": papers + web, "channels": channels}


# ------------------------------------------------------------------ nodes

def intake_node(state: EvalState) -> dict:
    """LLM call only — the human-validation interrupt lives in intake_gate so
    that resuming never re-pays this call (interrupt() replays its node)."""
    prompt = load_prompt("system/intake.md", state.get("lang"))
    idea = state["idea"]
    result, error = safe_complete_json(
        prompt.body, f"IDEA:\n{idea.get('title', '')}\n{idea.get('text', '')}")
    out: dict = {"intake": result if isinstance(result, dict) else {}}
    if error:
        out["errors"] = [f"intake: {error}"]
    return out


def intake_gate(state: EvalState) -> dict:
    """Base mode (idea comes from the user): human validates the intake."""
    if state.get("interactive") and state["idea"].get("provenance") == "user":
        answer = interrupt({"type": "intake_validation", "intake": state.get("intake") or {}})
        if isinstance(answer, dict) and answer.get("intake"):
            return {"intake": answer["intake"]}
    return {}


def make_round1_node(name: str, prompt: AgentPrompt):
    def node(state: EvalState) -> dict:
        extra: dict = {}
        if name == "scientist_eval":
            research = _research_for_idea(state)
            state = {**state, "research": research}
            extra["research"] = research
        timeout = prompt.timeout or (
            SETTINGS.research_timeout if name == "scientist_eval" else SETTINGS.llm_timeout
        )
        system = _render_agent_prompt(prompt, state)
        user = f"ROUND 1 — evaluate this idea. You have seen no other opinion.\n\n{_idea_block(state)}"
        raw, error = safe_complete_json(system, user, timeout=timeout)
        if error:
            return {"round1": {name: _failed_opinion(error, 1)},
                    "errors": [f"{name} round 1: {error}"], **extra}
        return {"round1": {name: _normalize(name, raw, state, 1)}, **extra}

    return node


def make_round2_node(name: str, prompt: AgentPrompt):
    def node(state: EvalState) -> dict:
        timeout = prompt.timeout or SETTINGS.llm_timeout
        system = _render_agent_prompt(prompt, state)
        user = (
            f"ROUND 2 — deliberation. Here are ALL round-1 opinions (yours is '{name}').\n"
            f"Revise with justification, or keep your position with a stated reason.\n"
            f"`revision` and `influenced_by` are REQUIRED.\n\n"
            f"{_idea_block(state)}\n\nROUND 1 OPINIONS:\n"
            f"{json.dumps(state.get('round1', {}), indent=2, ensure_ascii=False)}"
        )
        raw, error = safe_complete_json(system, user, timeout=timeout)
        if error:
            return {"round2": {name: _failed_opinion(error, 2)},
                    "errors": [f"{name} round 2: {error}"]}
        opinion = _normalize(name, raw, state, 2)
        opinion.setdefault("revision", "maintained")
        opinion.setdefault("influenced_by", [])
        return {"round2": {name: opinion}}

    return node


def synthesis_node(state: EvalState) -> dict:
    prompt = load_prompt("system/synthesis.md", state.get("lang"))
    user = (
        f"{_idea_block(state)}\n\nROUND 2 OPINIONS:\n"
        f"{json.dumps(state.get('round2', {}), indent=2, ensure_ascii=False)}"
    )
    raw, error = safe_complete_json(prompt.body, user)
    if error:
        return {"synthesis": {"verdict": None, "degraded": True, "error": error},
                "errors": [f"synthesis: {error}"]}
    round2 = state.get("round2", {})
    synthesis = _with_computed_gaps(coerce_synthesis(raw), round2)
    if len(opinion_scores(round2)) < QUORUM:
        synthesis["degraded"] = True
    return {"synthesis": synthesis}


def find_major_disagreement(state: EvalState) -> dict | None:
    """The ONLY trigger for a targeted debate: gap >= 3 between two agents on
    one topic (gap computed in code by synthesis_node), or a disagreement the
    synthesizer flagged critical."""
    known = set(state.get("round2", {}))
    for d in (state.get("synthesis") or {}).get("disagreements") or []:
        agents = [a for a in d.get("agents", []) if a in known]
        if len(agents) == 2 and (d.get("gap", 0) >= MAJOR_GAP or d.get("critical")):
            return {**d, "agents": agents[:2]}
    return None


def debate_node(state: EvalState) -> dict:
    """One round, two agents, one topic — hard structural limits."""
    disagreement = find_major_disagreement(state)
    if not disagreement:
        return {"debate": {}}
    agent_a, agent_b = disagreement["agents"]
    prompt = load_prompt("system/debate.md", state.get("lang"))
    round2 = state.get("round2", {})
    responses = {}
    for me, other in ((agent_a, agent_b), (agent_b, agent_a)):
        system = render(
            prompt.body,
            agent_name=me,
            other_agent=other,
            topic=disagreement.get("topic", ""),
            own_position=json.dumps(round2.get(me, {}).get("verdict", "")),
            other_position=json.dumps(round2.get(other, {}).get("verdict", "")),
        )
        responses[me], error = safe_complete_json(system, "Respond now.")
        if error:
            return {"debate": {"topic": disagreement.get("topic"), "agents": [agent_a, agent_b],
                               "error": error},
                    "errors": [f"debate ({me}): {error}"]}
    update_prompt = load_prompt("system/debate_update.md", state.get("lang"))
    raw_update, error = safe_complete_json(
        render(
            update_prompt.body,
            agent_a=agent_a,
            agent_b=agent_b,
            topic=disagreement.get("topic", ""),
            response_a=json.dumps(responses[agent_a], ensure_ascii=False),
            response_b=json.dumps(responses[agent_b], ensure_ascii=False),
            verdict=(state.get("synthesis") or {}).get("verdict", ""),
        ),
        "Close the debate.",
    )
    update = coerce_debate_update(raw_update)
    debate = {"topic": disagreement.get("topic"), "agents": [agent_a, agent_b],
              "responses": responses, "update": update}
    synthesis = dict(state.get("synthesis") or {})
    if error:
        return {"debate": {**debate, "error": error}, "errors": [f"debate update: {error}"]}
    synthesis["debate_outcome"] = update.get("debate_outcome")
    synthesis["debate_conclusion"] = update.get("conclusion")
    if update.get("verdict_changed") and update.get("verdict"):  # only a valid GO|ITERATE|PIVOT
        synthesis["verdict"] = update["verdict"]
    return {"debate": debate, "synthesis": synthesis}


def persist_node(state: EvalState) -> dict:
    record = {
        "eval_id": state.get("eval_id") or traces.new_id("eval", state["idea"].get("title", "")),
        "idea": state["idea"],
        "mode": state.get("mode", "general"),
        "constraints": state.get("constraints", ""),
        "intake": state.get("intake", {}),
        "research": state.get("research", {}),
        "round1": state.get("round1", {}),
        "round2": state.get("round2", {}),
        "synthesis": state.get("synthesis", {}),
        "debate": state.get("debate", {}),
        "errors": state.get("errors", []),
    }
    if not state.get("no_persist"):
        traces.save_eval(record)
    return {"eval_id": record["eval_id"]}


# ------------------------------------------------------------------ build

def build_evaluation_graph(mode: str, lang: str | None = None,
                           agents: dict[str, AgentPrompt] | None = None):
    agents = agents or committee_prompts(mode, lang)
    g = StateGraph(EvalState)
    g.add_node("intake", intake_node)
    g.add_node("intake_gate", intake_gate)
    g.add_edge(START, "intake")
    g.add_edge("intake", "intake_gate")

    r1_nodes, r2_nodes = [], []
    for name, prompt in agents.items():
        r1, r2 = f"r1_{name}", f"r2_{name}"
        g.add_node(r1, make_round1_node(name, prompt))
        g.add_node(r2, make_round2_node(name, prompt))
        g.add_edge("intake_gate", r1)
        r1_nodes.append(r1)
        r2_nodes.append(r2)

    g.add_node("round1_done", lambda state: {})
    g.add_edge(r1_nodes, "round1_done")
    for r2 in r2_nodes:
        g.add_edge("round1_done", r2)

    g.add_node("synthesis", synthesis_node)
    g.add_edge(r2_nodes, "synthesis")

    g.add_node("debate", debate_node)
    g.add_node("persist", persist_node)
    g.add_conditional_edges(
        "synthesis",
        lambda s: "debate" if find_major_disagreement(s) else "persist",
        ["debate", "persist"],
    )
    g.add_edge("debate", "persist")
    g.add_edge("persist", END)
    return g


def compile_evaluation_graph(mode: str, lang: str | None = None, checkpointer=None):
    return build_evaluation_graph(mode, lang).compile(checkpointer=checkpointer)
