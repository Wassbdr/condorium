"""Run the pairwise committee and three reference protocols."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from contextvars import copy_context
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..compare import (
    MAX_TOKENS,
    MODEL,
    PROTOCOL,
    TEMPERATURE,
    RequirementCache,
    Winner,
    compare,
    majority,
    proposal_input,
    sample_seed,
)
from ..llm import (
    CallBudgetExceeded,
    OfflineCacheMiss,
    call_budget,
    complete_text,
    is_rate_limit,
    usage_meter,
)
from ..prompts import load_prompt, render
from .pairset import (
    DATASET_VERSION,
    PAPER_RUBRIC,
    Pair,
    Rubric,
    Split,
    Variant,
    build_variants,
    position_variants,
)

METHODS = ("judge", "jury", "chateval", "committee")
KIMI_MODEL = "nvidia_nim/moonshotai/kimi-k3.1-pro"
JURY_MODELS = (MODEL, "nvidia_nim/poolside/laguna-xs-2.1", KIMI_MODEL)
_ORDER: tuple[Literal["committee", "judge", "jury", "chateval"], ...] = (
    "committee", "judge", "jury", "chateval",
)
_VERDICT = re.compile(r"\[\[\s*([abc])\s*\]\]", re.IGNORECASE)


@dataclass
class ParseFailure:
    turn: str
    raw: str


@dataclass
class Decision:
    winner: Winner
    usage: dict
    failures: list[ParseFailure] = field(default_factory=list)
    debated: bool = False
    evidence_dropped: int = 0
    abstains: int = 0
    target_tokens: int | None = None
    violations_kept: int = 0
    violations_dropped: int = 0


def parse_verdict(raw: str) -> Winner | None:
    markers = _VERDICT.findall(raw)
    if markers:
        verdicts: dict[str, Winner] = {"a": "a", "b": "b", "c": "tie"}
        return verdicts[markers[-1].lower()]
    return None


def _sample(system: str, user: str, model: str, seed: int) -> str:
    params: dict[str, Any] = {}
    max_tokens = MAX_TOKENS
    if model == KIMI_MODEL:
        params["extra_body"] = {"thinking": {"type": "disabled"}}
        max_tokens = 768
    return complete_text(system, user, model=model, temperature=TEMPERATURE,
                         seed=seed, max_tokens=max_tokens, max_retries=0, num_retries=0, **params)


def run_votes(
    method: Literal["judge", "jury"], proposals: str, variant_id: str, seed: int,
    target_tokens: int | None,
) -> dict[str, Decision]:
    system = load_prompt("system/pairwise_judge.md").body
    models = (MODEL,) if method == "judge" else JURY_MODELS
    votes: list[Winner | None] = []
    failures = []
    minimum = 3 if target_tokens is None or method == "jury" else 1
    first: Decision | None = None
    with usage_meter(scoped=True) as meter:
        while len(votes) < minimum or (target_tokens is not None
                                       and meter.total_tokens < target_tokens):
            index = len(votes)
            model = models[index % len(models)]
            seed_method = "judge" if method == "jury" and index == 0 else method
            try:
                raw = _sample(system, proposals, model,
                              sample_seed(seed, seed_method, variant_id, index))
            except Exception as exc:
                if not isinstance(exc, CallBudgetExceeded) and not is_rate_limit(exc):
                    raise
                return {"judge_1call": first} if first is not None else {}
            vote = parse_verdict(raw)
            votes.append(vote)
            if vote is None:
                failures.append(ParseFailure(f"{model}:{index}", raw))
            if method == "judge" and index == 0:
                first = Decision(vote or "tie", meter.as_dict(), failures.copy())
        winner = majority(votes, include_abstentions=method == "jury")
        decision = Decision(winner or "tie", meter.as_dict(), failures,
                            abstains=len(failures) if method == "jury" else 0,
                            target_tokens=target_tokens)
    return {method: decision, **({"judge_1call": first} if first is not None else {})}


def run_chateval(proposals: str, variant_id: str, seed: int) -> Decision:
    roles = ("critic", "scientist")
    prompts = {role: load_prompt(f"system/chateval_{role}.md").body for role in roles}
    template = load_prompt("system/chateval_input.md").body
    transcript: list[dict[str, str]] = []
    final = []
    failures = []
    with usage_meter(scoped=True) as meter:
        for index, role in enumerate(roles * 2):
            user = render(template, proposals=proposals,
                          transcript=json.dumps(transcript, ensure_ascii=False))
            raw = _sample(prompts[role], user, MODEL, sample_seed(seed, "chateval", variant_id, index))
            transcript.append({"reviewer": role, "response": raw})
            vote = parse_verdict(raw)
            if vote is None:
                failures.append(ParseFailure(f"{role}:{index}", raw))
            if index >= len(roles):
                final.append(vote or "tie")
    return Decision(majority(final) or "tie", meter.as_dict(), failures)


def load_pairs(data_dir: Path, *, split: Split, limit: int | None = None) -> list[Pair]:
    def read(path: Path) -> list[Pair]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    pairs = read(data_dir / "pairs.jsonl")
    if limit is not None and sum(p["split"] == split for p in pairs) >= limit:
        return pairs
    iclr = data_dir / ".cache/iclr_pairs.jsonl"
    if not iclr.is_file():
        raise ValueError("ICLR pair text is missing. Run python scripts/fetch_iclr_pairs.py first.")
    papers = read(iclr)
    if not papers or any(p.get("version") != DATASET_VERSION or p["rubric"] != PAPER_RUBRIC
                         for p in papers):
        raise ValueError("ICLR pair text is out of date. Run python scripts/fetch_iclr_pairs.py.")
    pairs.extend(papers)
    if len({pair["id"] for pair in pairs}) != len(pairs):
        raise ValueError("Pair IDs must be unique across the synthetic and ICLR sets")
    return pairs


def run_pairwise(
    pairs: Sequence[Pair],
    rubrics: Mapping[str, Rubric],
    *,
    split: Split,
    seeds: Sequence[int] = (0, 1, 2),
    methods: Sequence[str] = METHODS,
    max_calls: int | None = None,
    limit: int | None = None,
    position_only: bool = False,
    workers: int = 5,
    previous_report: dict | None = None,
) -> dict:
    """Evaluate each variant and seed independently, sharing only the request cache."""
    selected = [p for p in pairs if p["split"] == split][:limit]
    if not selected:
        raise ValueError(f"No pairs selected for split {split!r}")
    if not methods or set(methods) - set(METHODS):
        raise ValueError(f"Choose methods from {', '.join(METHODS)}")
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("Supply at least one seed, with no duplicates")
    selected_by_id = {p["id"]: p for p in selected}
    missing = {p["rubric"] for p in selected} - rubrics.keys()
    if missing:
        raise ValueError(f"Missing pairwise rubrics: {', '.join(sorted(missing))}")
    variants = position_variants(selected) if position_only else build_variants(selected)
    reference_targets: dict[tuple[int, str], int] = {}
    if (previous_report and previous_report.get("dataset_version") == DATASET_VERSION
            and previous_report.get("split") == split and previous_report.get("model") == MODEL
            and previous_report.get("jury_models") == list(JURY_MODELS)
            and (previous_report.get("committee_protocol") == "v1"
                 or previous_report.get("reference_budget") == "v1")):
        for row in previous_report["decisions"]:
            if row["method"] in ("judge", "jury") and type(row.get("target_tokens")) is int:
                reference_targets[row["seed"], row["variant_id"]] = row["target_tokens"]

    def variant_key(variant: Variant) -> str:
        return f"{variant['pair_id']}:{variant['kind']}:{variant['order']}"

    replay_references = all((seed, variant_key(v)) in reference_targets
                            for seed in seeds for v in variants)
    requirement_cache = RequirementCache()

    def work(variant: Variant, seed: int) -> tuple[list[dict], set[str]]:
        variant_id = variant_key(variant)
        pair = selected_by_id[variant["pair_id"]]
        rubric = rubrics[pair["rubric"]]
        proposals = proposal_input(variant["a"], variant["b"], rubric)
        target = None
        rows = []
        limited: set[str] = set()
        for method in _ORDER:
            if method not in methods:
                continue
            decisions: dict[str, Decision]
            try:
                if method == "committee":
                    comparison = compare(
                        variant["a"], variant["b"], rubric, seed=seed,
                        variant_id=f"{variant['pair_id']}:{variant['kind']}",
                        brief=pair["a"]["text"].split("\n\n", 1)[0]
                        if pair["source"] == "synthetic" else "",
                        requirement_cache=requirement_cache,
                    )
                    target = comparison.usage["total_tokens"] - comparison.extraction_tokens
                    failures = [
                        ParseFailure(f"{stage}:{r.role}", r.parse_failure)
                        for stage, reviews in (("blind", comparison.initial),
                                               ("debate", comparison.debate))
                        for r in reviews if r.parse_failure is not None
                    ]
                    if comparison.extraction_failure is not None:
                        failures.append(ParseFailure("requirements", comparison.extraction_failure))
                    decisions = {method: Decision(
                            comparison.winner, comparison.usage, failures, bool(comparison.debate),
                            comparison.dropped, comparison.abstains,
                            violations_kept=comparison.violations_kept,
                            violations_dropped=comparison.violations_dropped,
                        )}
                else:
                    with call_budget(0) if replay_references else nullcontext():
                        if method == "chateval":
                            decisions = {method: run_chateval(proposals, variant_id, seed)}
                        else:
                            budget = (reference_targets[seed, variant_id]
                                      if replay_references else target)
                            decisions = run_votes(method, proposals, variant_id, seed, budget)
                    if method not in decisions:
                        if replay_references:
                            raise CallBudgetExceeded("Reference cache miss")
                        limited.add(method)
            except (CallBudgetExceeded, OfflineCacheMiss) as exc:
                if replay_references and method != "committee":
                    raise OfflineCacheMiss(f"Incomplete reference cache: {method}, {variant_id}, "
                                           f"seed {seed}. The prior report was not replaced.") from exc
                if isinstance(exc, OfflineCacheMiss):
                    raise
                limited.add(method)
                continue
            except Exception as exc:
                if not is_rate_limit(exc):
                    raise
                limited.add(method)
                continue
            for name, decision in decisions.items():
                rows.append({
                    "method": name, "seed": seed, "pair_id": variant["pair_id"],
                    "source": pair["source"], "rubric": pair["rubric"], "variant_id": variant_id,
                    "kind": variant["kind"], "order": variant["order"],
                    "better": variant["better"], **asdict(decision),
                })
        return rows, limited

    grouped_variants: dict[str, list[Variant]] = {}
    for variant in variants:
        grouped_variants.setdefault(variant["pair_id"], []).append(variant)

    def work_pair(group: Sequence[Variant], seed: int) -> dict[str, tuple[list[dict], set[str]]]:
        return {variant_key(v): work(v, seed) for v in group}

    records = []
    limited_methods: set[str] = set()
    with call_budget(max_calls) as budget, usage_meter(scoped=True) as meter:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for seed in seeds:
                tasks = {pair: pool.submit(copy_context().run, work_pair, group, seed)
                         for pair, group in grouped_variants.items()}
                for variant in variants:
                    rows, limited = tasks[variant["pair_id"]].result()[variant_key(variant)]
                    records.extend(rows)
                    limited_methods.update(limited)
    reported_methods = list(methods)
    if replay_references and previous_report:
        selected_keys = {(seed, variant_key(v)) for seed in seeds for v in variants}
        present = {(row["method"], row["seed"], row["variant_id"]) for row in records}
        for row in previous_report["decisions"]:
            method, seed, variant_id = row["method"], row["seed"], row["variant_id"]
            if (method != "committee" and (seed, variant_id) in selected_keys
                    and (method, seed, variant_id) not in present):
                records.append(row)
                name = "judge" if method == "judge_1call" else method
                if name not in reported_methods:
                    reported_methods.append(name)
    return {
        "split": split, "seeds": list(seeds), "methods": reported_methods,
        "pair_count": len(selected), "variant_count": len(variants),
        "dataset_version": DATASET_VERSION,
        "position_only": position_only, "max_calls": max_calls,
        "model": MODEL, "jury_models": list(JURY_MODELS),
        "temperature": TEMPERATURE, "committee_protocol": PROTOCOL,
        "reference_budget": "v1" if replay_references else PROTOCOL,
        "live_attempts": budget.attempts,
        "live_calls": meter.calls - meter.cache_hits, "cache_hits": meter.cache_hits,
        "rate_limited": budget.rate_limited, "limited_methods": sorted(limited_methods),
        "decisions": records,
    }
