"""Graph state definitions.

EvalState is the state of ONE evaluation subgraph run: it contains exactly one
idea. Isolation between ideas is structural — the map step spawns one subgraph
invocation per idea and nothing else ever enters that state.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


def merge_dicts(a: dict, b: dict) -> dict:
    return {**(a or {}), **(b or {})}


class Idea(TypedDict, total=False):
    id: str
    title: str
    text: str
    provenance: str  # user | hackathon | scientist | historian | demo
    references: list[dict]  # scientist generator: [{title, url}]
    inspired_by: list[str]  # historian: knowledge-graph node ids
    prefilter: dict


class EvalState(TypedDict, total=False):
    idea: Idea
    mode: str  # general | hackathon
    constraints: str
    official_criteria: str
    custom_criteria: str
    mask_provenance: bool
    lang: str
    intake: dict
    research: dict  # scientist_eval: papers/web results retrieved this run
    round1: Annotated[dict, merge_dicts]  # agent -> opinion JSON
    round2: Annotated[dict, merge_dicts]
    synthesis: dict
    debate: dict
    eval_id: str
    interactive: bool
    no_persist: bool  # bench runs: full pipeline, no trace on disk


class PanelState(TypedDict, total=False):
    mode: str
    command: str  # eval | generate | tournament
    sources: list[str]
    constraints: str
    official_criteria: str
    custom_criteria: str
    context: str
    theme: str
    duration: str
    n_ideas: int
    top: int | None
    lang: str
    interactive: bool
    raw_input: str
    interview: dict  # interviewer dialogue: transcript, questions, step
    ideas: Annotated[list[Idea], operator.add]
    selected: list[Idea]
    eliminated: list[Idea]
    evaluations: Annotated[list[dict], operator.add]
    ranking: dict
    run_id: str


def opinion_scores(opinions: dict[str, dict]) -> dict[str, int]:
    """Numeric scores only — a `null` score (scientist 'neutral') is excluded."""
    return {
        name: op["score"]
        for name, op in opinions.items()
        if isinstance(op, dict) and isinstance(op.get("score"), (int, float))
    }


def median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return float(s[mid]) if n % 2 else (s[mid - 1] + s[mid]) / 2
