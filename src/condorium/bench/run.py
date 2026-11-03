"""Benchmark runner: does the committee identify real winners?

Reproducible (`--seed`, temperature pinned), leak-free (antileak on every
title and description, the pair excluded from its own calibration), and
honest: the committee's rate is reported with a 95% CI next to two
baselines on the same pairs — "the longer description wins" (free) and a
single LLM call — because a rate means nothing without them.

Cases are appended to evaluations/bench_cases.jsonl as they finish, so an
interrupted bench resumes with `--resume` instead of re-paying every pair.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..config import SETTINGS
from ..graph.evaluation import compile_evaluation_graph
from ..llm import safe_complete_json
from ..prompts import load_prompt, render
from ..schemas import coerce_score
from ..state import median, opinion_scores
from .pairs import build_pairs
from .stats import pair_outcome, summarize

VERDICT_RANK = {"GO": 2, "ITERATE": 1, "PIVOT": 0}
DEFAULT_CRITERIA = "innovation, feasibility, impact, execution"


def evaluate_idea_silently(title: str, text: str, mode: str = "hackathon",
                           **extra) -> dict:
    """Full committee pipeline on one idea, nothing persisted to history.
    `extra` goes into the evaluation state (calibration_exclude, criteria...)."""
    app = compile_evaluation_graph(mode)
    return app.invoke({
        "idea": {"id": "bench", "title": title, "text": text},
        "mode": mode,
        "no_persist": True,
        "interactive": False,
        **extra,
    })


@contextmanager
def pinned_temperature(temperature: float | None) -> Iterator[None]:
    previous = SETTINGS.temperature
    SETTINGS.temperature = temperature
    try:
        yield
    finally:
        SETTINGS.temperature = previous


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a half-written last line from a killed run
    return rows


def append_jsonl(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _strength(result: dict) -> tuple[int, float]:
    """Comparator for a pair: verdict rank first, then panel median (median,
    not mean — the synthesis itself never aggregates)."""
    verdict = (result.get("synthesis") or {}).get("verdict", "")
    med = median(list(opinion_scores(result.get("round2", {})).values())) or 0.0
    return (VERDICT_RANK.get(verdict, 0), med)


def single_call_score(title: str, text: str, criteria: str) -> int | None:
    """Baseline: ONE model call, no committee, no rounds."""
    prompt = load_prompt("system/baseline_judge.md")
    raw, error = safe_complete_json(render(prompt.body, official_criteria=criteria),
                                    f"TITLE: {title}\nIDEA: {text}")
    if error or not isinstance(raw, dict):
        return None
    return coerce_score(raw.get("score"))[0]


def run_pair(pair: dict, mode: str, baselines: bool) -> dict:
    criteria = pair.get("criteria") or DEFAULT_CRITERIA
    # anti-leak: neither project of the pair, nor any winner of its
    # hackathon, may appear in the Judge's calibration block
    exclude = {"projects": [e["original_title"] for e in pair["entries"]],
               "hackathons": [pair["hackathon"]]}
    by_role = {e["role"]: e for e in pair["entries"]}
    results = {}
    for entry in pair["entries"]:  # shuffled order: the committee never knows which is which
        results[entry["role"]] = evaluate_idea_silently(
            entry["title"], entry["text"], mode, calibration_exclude=exclude,
            official_criteria=criteria, theme=pair.get("theme") or "")
    outcome = pair_outcome(_strength(results["winner"]), _strength(results["loser"]))

    w_scores = opinion_scores(results["winner"].get("round2", {}))
    l_scores = opinion_scores(results["loser"].get("round2", {}))
    case = {
        "case_id": f"bench-{pair['pair_id']}",
        "pair_id": pair["pair_id"],
        "hackathon": pair["hackathon"],
        "outcome": outcome,
        "correct": outcome == 1.0,
        "verdicts": {r: (results[r].get("synthesis") or {}).get("verdict") for r in results},
        "medians": {"winner": median(list(w_scores.values())),
                    "loser": median(list(l_scores.values()))},
        "agent_scores": {"winner": w_scores, "loser": l_scores},
        "baselines": {"length": pair_outcome(len(by_role["winner"]["text"]),
                                             len(by_role["loser"]["text"]))},
    }
    if baselines:
        scores = {r: single_call_score(by_role[r]["title"], by_role[r]["text"], criteria)
                  for r in ("winner", "loser")}
        case["baselines"]["single_call"] = pair_outcome(scores["winner"], scores["loser"])
        case["single_call_scores"] = scores
    return case


def build_report(cases: list[dict], n_pairs: int, seed: int,
                 temperature: float | None) -> dict:
    ok = [c for c in cases if not c.get("error")]
    agent_hits: dict[str, list[float]] = {}
    for c in ok:
        w, lo = c["agent_scores"]["winner"], c["agent_scores"]["loser"]
        for agent in set(w) & set(lo):
            agent_hits.setdefault(agent, []).append(pair_outcome(w[agent], lo[agent]))
    winner_meds = [c["medians"]["winner"] for c in ok if c["medians"]["winner"] is not None]
    loser_meds = [c["medians"]["loser"] for c in ok if c["medians"]["loser"] is not None]
    baseline_names = sorted({b for c in ok for b in c.get("baselines", {})})
    committee = summarize([c["outcome"] for c in ok], seed)
    return {
        "n_pairs": n_pairs,
        "n_evaluated": len(ok),
        "n_errors": len(cases) - len(ok),
        "n_ties": sum(c["outcome"] == 0.5 for c in ok),
        "seed": seed,
        "temperature": temperature,
        "winner_identification_rate": committee["value"],
        "winner_identification_ci95": committee["ci95"],
        "baselines": {
            name: summarize([c["baselines"][name] for c in ok if name in c["baselines"]], seed)
            for name in baseline_names
        },
        "per_agent_precision": {a: round(sum(h) / len(h), 3)
                                for a, h in sorted(agent_hits.items()) if h},
        "calibration": {
            "winner_median_avg": round(sum(winner_meds) / len(winner_meds), 2)
            if winner_meds else None,
            "loser_median_avg": round(sum(loser_meds) / len(loser_meds), 2)
            if loser_meds else None,
        },
        "cases": cases,
    }


def run_bench(dataset: Path, n: int = 50, seed: int = 42, mode: str = "hackathon",
              baselines: bool = True, resume: bool = False,
              temperature: float | None = 0.0) -> dict:
    pairs = build_pairs(dataset, n, seed)
    cases_file = SETTINGS.evaluations_dir / "bench_cases.jsonl"
    done = {c["pair_id"]: c for c in load_jsonl(cases_file)
            if resume and c.get("seed") == seed and not c.get("error")}
    if not resume:
        cases_file.write_text("", encoding="utf-8")

    cases = []
    with pinned_temperature(temperature):
        for pair in pairs:
            if pair["pair_id"] in done:
                cases.append(done[pair["pair_id"]])
                continue
            try:
                case = run_pair(pair, mode, baselines)
            except Exception as exc:  # noqa: BLE001 — one bad pair must not void the bench
                case = {"case_id": f"bench-{pair['pair_id']}", "pair_id": pair["pair_id"],
                        "hackathon": pair["hackathon"], "correct": None,
                        "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
            case["seed"] = seed
            append_jsonl(cases_file, case)
            cases.append(case)

    report = build_report(cases, len(pairs), seed, temperature)
    out = SETTINGS.evaluations_dir / "bench_results.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def _fmt(summary: dict | None) -> str:
    if not summary or summary.get("value") is None:
        return "n/a"
    ci = summary.get("ci95")
    return f"{summary['value']} [{ci[0]}, {ci[1]}]" if ci else str(summary["value"])


def readme_table(report: dict) -> str:
    rate = {"value": report["winner_identification_rate"],
            "ci95": report.get("winner_identification_ci95")}
    lines = [
        "| metric | value (95% CI) |", "|---|---|",
        f"| pairs evaluated | {report.get('n_evaluated', report['n_pairs'])}/{report['n_pairs']} "
        f"(seed {report['seed']}, temperature {report.get('temperature')}, "
        f"{report.get('n_ties', 0)} ties, {report.get('n_errors', 0)} errors) |",
        f"| **committee** winner identification | **{_fmt(rate)}** |",
    ]
    labels = {"single_call": "baseline — single LLM call",
              "length": "baseline — longer description wins"}
    for name, summary in (report.get("baselines") or {}).items():
        lines.append(f"| {labels.get(name, name)} | {_fmt(summary)} |")
    cal = report.get("calibration", {})
    lines.append(f"| winner vs loser median | {cal.get('winner_median_avg')} vs "
                 f"{cal.get('loser_median_avg')} |")
    for agent, p in (report.get("per_agent_precision") or {}).items():
        lines.append(f"| precision — {agent} | {p} |")
    return "\n".join(lines)
