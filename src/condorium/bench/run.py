"""Benchmark runner: does the committee identify real winners?

Reproducible (`--seed`), leak-free (antileak on every description), results
saved to evaluations/bench_results.json and rendered as a markdown table for
the README.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import SETTINGS
from ..graph.evaluation import compile_evaluation_graph
from ..state import median, opinion_scores
from .pairs import build_pairs

VERDICT_RANK = {"GO": 2, "ITERATE": 1, "PIVOT": 0}


def evaluate_idea_silently(title: str, text: str, mode: str = "hackathon") -> dict:
    """Full committee pipeline on one idea, nothing persisted to history."""
    app = compile_evaluation_graph(mode)
    return app.invoke({
        "idea": {"id": "bench", "title": title, "text": text},
        "mode": mode,
        "no_persist": True,
        "interactive": False,
    })


def _strength(result: dict) -> tuple[int, float]:
    """Comparator for a pair: verdict rank first, then panel median (median,
    not mean — the synthesis itself never aggregates)."""
    verdict = (result.get("synthesis") or {}).get("verdict", "")
    med = median(list(opinion_scores(result.get("round2", {})).values())) or 0.0
    return (VERDICT_RANK.get(verdict, 0), med)


def run_bench(dataset: Path, n: int = 50, seed: int = 42, mode: str = "hackathon") -> dict:
    pairs = build_pairs(dataset, n, seed)
    cases = []
    agent_hits: dict[str, list[bool]] = {}
    winner_scores: list[float] = []
    loser_scores: list[float] = []

    for pair in pairs:
        results = {}
        for entry in pair["entries"]:
            results[entry["role"]] = evaluate_idea_silently(entry["title"], entry["text"], mode)
        predicted_winner = max(results, key=lambda role: _strength(results[role]))
        correct = predicted_winner == "winner"

        w_scores = opinion_scores(results["winner"].get("round2", {}))
        l_scores = opinion_scores(results["loser"].get("round2", {}))
        for agent in set(w_scores) & set(l_scores):
            agent_hits.setdefault(agent, []).append(w_scores[agent] > l_scores[agent])
        if (wm := median(list(w_scores.values()))) is not None:
            winner_scores.append(wm)
        if (lm := median(list(l_scores.values()))) is not None:
            loser_scores.append(lm)

        cases.append({
            "case_id": f"bench-{pair['pair_id']}",
            "hackathon": pair["hackathon"],
            "correct": correct,
            "verdicts": {r: (results[r].get("synthesis") or {}).get("verdict") for r in results},
            "medians": {"winner": wm, "loser": lm},
            "agent_scores": {"winner": w_scores, "loser": l_scores},
        })

    report = {
        "n_pairs": len(pairs),
        "seed": seed,
        "winner_identification_rate": round(
            sum(c["correct"] for c in cases) / len(cases), 3) if cases else None,
        "per_agent_precision": {
            a: round(sum(h) / len(h), 3) for a, h in sorted(agent_hits.items()) if h
        },
        "calibration": {
            "winner_median_avg": round(sum(winner_scores) / len(winner_scores), 2) if winner_scores else None,
            "loser_median_avg": round(sum(loser_scores) / len(loser_scores), 2) if loser_scores else None,
        },
        "cases": cases,
    }
    out = SETTINGS.evaluations_dir / "bench_results.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def readme_table(report: dict) -> str:
    lines = [
        "| metric | value |", "|---|---|",
        f"| pairs evaluated | {report['n_pairs']} (seed {report['seed']}) |",
        f"| winner identification rate | {report['winner_identification_rate']} |",
    ]
    cal = report.get("calibration", {})
    lines.append(f"| winner vs loser median | {cal.get('winner_median_avg')} vs {cal.get('loser_median_avg')} |")
    for agent, p in (report.get("per_agent_precision") or {}).items():
        lines.append(f"| precision — {agent} | {p} |")
    return "\n".join(lines)
