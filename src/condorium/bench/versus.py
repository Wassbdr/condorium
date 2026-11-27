"""Committee vs single judge at equal token budget — measured, not assumed.

For every (winner, non-winner) pair from `pairs.build_pairs`:
  (a) the full committee evaluates each entry (two rounds, synthesis, debate);
  (b) a single judge evaluates the same entry, re-sampled until it has spent
      the SAME number of tokens as the committee did on that entry, and its
      samples are aggregated by majority verdict + median score (never a mean).
The first judge sample alone is also reported (the cheap 1-call baseline).

Tone sensitivity: the same idea in an enthusiastic and a neutral phrasing;
a verdict flip between the two is a sycophancy failure.

Everything goes through `llm.complete_json`, so a fake deterministic LLM
(tests) and a live provider (NIM, Anthropic, ... via LiteLLM) run the same
code path.
"""

from __future__ import annotations

import json
import math
import random
import statistics
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

from ..config import SETTINGS
from ..llm import CallBudgetExceeded, complete_json, usage_meter
from ..prompts import load_prompt, render
from ..state import median, opinion_scores
from .antileak import strip_victory_clues
from .pairs import _pick, build_pairs, load_rows
from .run import VERDICT_RANK, evaluate_idea_silently

SYSTEMS = ("committee", "judge_matched", "judge_1call")
MAX_JUDGE_SAMPLES = 56


# ----------------------------------------------------------- evaluators

def run_committee(title: str, text: str, mode: str) -> dict:
    with usage_meter() as meter:
        result = evaluate_idea_silently(title, text, mode)
    r2 = opinion_scores(result.get("round2", {}))
    syn = result.get("synthesis") or {}
    return {
        "verdict": syn.get("verdict"),
        "score": median(list(r2.values())),
        "round1": opinion_scores(result.get("round1", {})),
        "round2": r2,
        "capped": [a for a, o in (result.get("round2") or {}).items()
                   if isinstance(o, dict) and o.get("capped")],
        "disagreements": len(syn.get("disagreements") or []),
        "debate": bool(result.get("debate")),
        "usage": meter.as_dict(),
    }


def _judge_call(title: str, text: str, mode: str, constraints: str, seed: int | None) -> dict:
    prompt = load_prompt("system/single_judge.md")
    system = render(prompt.body, constraints=constraints or "(none stated)")
    out = complete_json(system, f"MODE: {mode}\nTITLE: {title}\nIDEA: {text}", seed=seed)
    out = out if isinstance(out, dict) else {}
    score = out.get("score")
    verdict = str(out.get("verdict", "")).strip().upper()
    return {"score": score if isinstance(score, (int, float)) else None,
            "verdict": verdict if verdict in VERDICT_RANK else None}


def _majority_verdict(samples: list[dict]) -> str | None:
    counts = Counter(s["verdict"] for s in samples if s["verdict"])
    if not counts:
        return None
    top = max(counts.values())
    tied = sorted((v for v, c in counts.items() if c == top), key=VERDICT_RANK.get)
    return tied[0]  # tie between verdicts -> the more conservative one


def run_single_judge(title: str, text: str, mode: str, token_budget: int,
                     seed: int, constraints: str = "", parallel: int = 8) -> dict:
    """Sample one judge until it has spent `token_budget` tokens (the
    committee's spend on this entry). Batches run concurrently; the stop
    rule is the same as sequential sampling: stop once the budget is met."""
    samples: list[dict] = []

    def call(i: int) -> dict:
        return _judge_call(title, text, mode, constraints, seed * 1000 + i)

    with usage_meter() as meter, ThreadPoolExecutor(max_workers=parallel) as pool:
        samples.append(call(0))
        while meter.total_tokens < token_budget and len(samples) < MAX_JUDGE_SAMPLES:
            per_call = meter.total_tokens / len(samples) or 1
            need = max(1, math.ceil((token_budget - meter.total_tokens) / per_call))
            batch = range(len(samples), min(len(samples) + need, MAX_JUDGE_SAMPLES))
            samples.extend(pool.map(call, batch))
        usage = meter.as_dict()
    first_tokens = usage["total_tokens"] // max(1, len(samples))
    scores = [s["score"] for s in samples if s["score"] is not None]
    return {
        "verdict": _majority_verdict(samples),
        "score": median(scores),
        "n_samples": len(samples),
        "budget_reached": usage["total_tokens"] >= token_budget,
        "usage": usage,
        "first": {**samples[0], "approx_tokens": first_tokens},
        "samples": samples,
    }


# ---------------------------------------------------------- comparison

def strength(verdict: str | None, score: float | None) -> tuple[int, float]:
    """Verdict first, then median score — the same comparator for every system."""
    return (VERDICT_RANK.get(verdict or "", -1), score if score is not None else -1.0)


def pick(winner: tuple, loser: tuple) -> float:
    """1 = picked the real winner, 0 = picked the non-winner, 0.5 = tie."""
    return 1.0 if winner > loser else 0.0 if winner < loser else 0.5


def _system_view(system: str, ev: dict) -> tuple[str | None, float | None]:
    if system == "committee":
        return ev["committee"]["verdict"], ev["committee"]["score"]
    if system == "judge_matched":
        return ev["judge"]["verdict"], ev["judge"]["score"]
    first = ev["judge"]["first"]
    return first["verdict"], first["score"]


def _system_tokens(system: str, ev: dict) -> int:
    if system == "committee":
        return ev["committee"]["usage"]["total_tokens"]
    if system == "judge_matched":
        return ev["judge"]["usage"]["total_tokens"]
    return ev["judge"]["first"]["approx_tokens"]


def _system_calls(system: str, ev: dict) -> int:
    if system == "committee":
        return ev["committee"]["usage"]["calls"]
    if system == "judge_matched":
        return ev["judge"]["usage"]["calls"]
    return 1


def evaluate_entry(title: str, text: str, mode: str, seed: int) -> dict:
    committee = run_committee(title, text, mode)
    judge = run_single_judge(title, text, mode, committee["usage"]["total_tokens"], seed)
    return {"committee": committee, "judge": judge}


# --------------------------------------------------------------- runner

def _tone_variants(rows: list[dict]) -> dict[str, str]:
    return {_pick(r, "title"): strip_victory_clues(r["enthusiastic"])
            for r in rows if r.get("enthusiastic")}


def _tiers(rows: list[dict]) -> dict[str, str]:
    return {_pick(r, "hackathon"): r.get("tier", "all") for r in rows}


def run_seed(dataset: Path, n_pairs: int, n_tone: int, seed: int, mode: str = "hackathon",
             log: Callable[[str], None] = lambda _: None) -> dict:
    rows = load_rows(dataset)
    tiers = _tiers(rows)
    pairs = build_pairs(dataset, n_pairs, seed)
    previous_seed = SETTINGS.llm_seed
    SETTINGS.llm_seed = seed
    try:
        pair_cases = []
        for pair in pairs:
            evs = {}
            for entry in pair["entries"]:
                t0 = time.time()
                evs[entry["role"]] = evaluate_entry(entry["title"], entry["text"], mode, seed)
                evs[entry["role"]]["title"] = entry["title"]
                evs[entry["role"]]["text"] = entry["text"]
                log(f"seed {seed} {pair['hackathon']} / {entry['role']}: "
                    f"committee {evs[entry['role']]['committee']['verdict']} "
                    f"judge {evs[entry['role']]['judge']['verdict']} "
                    f"({time.time() - t0:.0f}s)")
            case = {"hackathon": pair["hackathon"], "tier": tiers.get(pair["hackathon"], "all"),
                    "entries": evs, "picks": {}}
            for system in SYSTEMS:
                w = strength(*_system_view(system, evs["winner"]))
                lo = strength(*_system_view(system, evs["loser"]))
                case["picks"][system] = pick(w, lo)
            pair_cases.append(case)

        variants = _tone_variants(rows)
        rng = random.Random(seed)
        candidates = [(c, role) for c in pair_cases for role in ("winner", "loser")
                      if c["entries"][role]["title"] in variants]
        rng.shuffle(candidates)
        tone_cases = []
        truncated = False
        for case, role in candidates[:n_tone]:
            neutral = case["entries"][role]
            try:
                hyped = evaluate_entry(neutral["title"], variants[neutral["title"]], mode, seed)
            except CallBudgetExceeded:
                truncated = True  # keep the finished pairs, report fewer tone cases
                log(f"seed {seed}: call budget reached, tone cases truncated")
                break
            log(f"seed {seed} tone {neutral['title']}: committee "
                f"{neutral['committee']['verdict']}->{hyped['committee']['verdict']} judge "
                f"{neutral['judge']['verdict']}->{hyped['judge']['verdict']}")
            tone = {"title": neutral["title"], "role": role, "neutral": neutral,
                    "enthusiastic": hyped, "flips": {}, "score_delta": {}}
            for system in SYSTEMS:
                vn, sn = _system_view(system, neutral)
                ve, se = _system_view(system, hyped)
                tone["flips"][system] = vn != ve
                tone["score_delta"][system] = (se - sn) if None not in (se, sn) else None
            tone_cases.append(tone)
    finally:
        SETTINGS.llm_seed = previous_seed
    return {"seed": seed, "pairs": pair_cases, "tone": tone_cases, "tone_truncated": truncated}


def summarize(seed_runs: list[dict]) -> dict:
    def mean(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs), 3) if xs else None

    def sd(xs):
        xs = [x for x in xs if x is not None]
        return round(statistics.stdev(xs), 3) if len(xs) > 1 else 0.0

    systems = {}
    for system in SYSTEMS:
        per_seed_acc = [mean([c["picks"][system] for c in run["pairs"]]) for run in seed_runs]
        entries = [e for run in seed_runs for c in run["pairs"] for e in c["entries"].values()]
        tones = [t for run in seed_runs for t in run["tone"]]
        by_tier: dict[str, list[float]] = {}
        for run in seed_runs:
            for c in run["pairs"]:
                by_tier.setdefault(c["tier"], []).append(c["picks"][system])
        systems[system] = {
            "accuracy_mean": mean(per_seed_acc),
            "accuracy_sd_across_seeds": sd(per_seed_acc),
            "accuracy_per_seed": per_seed_acc,
            "accuracy_by_tier": {t: mean(v) for t, v in sorted(by_tier.items())},
            "ties": sum(c["picks"][system] == 0.5 for run in seed_runs for c in run["pairs"]),
            "tokens_per_idea": mean([_system_tokens(system, e) for e in entries]),
            "calls_per_idea": mean([_system_calls(system, e) for e in entries]),
            "tone_flip_rate": mean([float(t["flips"][system]) for t in tones]),
            "tone_score_delta": mean([t["score_delta"][system] for t in tones]),
        }

    def agree(a: str, b: str) -> float | None:
        both = [(c["picks"][a], c["picks"][b]) for run in seed_runs for c in run["pairs"]]
        return mean([float(x == y) for x, y in both])

    def verdict_agree(a: str, b: str) -> float | None:
        entries = [e for run in seed_runs for c in run["pairs"] for e in c["entries"].values()]
        return mean([float(_system_view(a, e)[0] == _system_view(b, e)[0]) for e in entries])

    committee_by_entry: dict[str, list] = {}
    for run in seed_runs:
        for c in run["pairs"]:
            for e in c["entries"].values():
                committee_by_entry.setdefault(e["title"], []).append(e["committee"]["verdict"])
    repeated = [v for v in committee_by_entry.values() if len(v) > 1]
    entries = [e for run in seed_runs for c in run["pairs"] for e in c["entries"].values()]
    return {
        "n_seeds": len(seed_runs),
        "seeds": [r["seed"] for r in seed_runs],
        "n_pairs_per_seed": [len(r["pairs"]) for r in seed_runs],
        "n_tone_cases": sum(len(r["tone"]) for r in seed_runs),
        "systems": systems,
        "pick_agreement_committee_vs_judge_matched": agree("committee", "judge_matched"),
        "verdict_agreement_committee_vs_judge_matched": verdict_agree("committee",
                                                                       "judge_matched"),
        "committee_verdict_stability_across_seeds": mean(
            [float(len(set(v)) == 1) for v in repeated]) if repeated else None,
        "believer_cap_fired": sum(bool(e["committee"]["capped"]) for e in entries),
        "debates_triggered": sum(e["committee"]["debate"] for e in entries),
        "llm_calls_total": sum(e["committee"]["usage"]["calls"] + e["judge"]["usage"]["calls"]
                               for run in seed_runs for c in run["pairs"]
                               for e in c["entries"].values())
        + sum(t["enthusiastic"]["committee"]["usage"]["calls"]
              + t["enthusiastic"]["judge"]["usage"]["calls"]
              for run in seed_runs for t in run["tone"]),
        "judge_budget_reached": mean([float(e["judge"]["budget_reached"]) for e in entries]),
        "tokens_estimated": any(e["committee"]["usage"]["estimated"] for e in entries),
    }


def _print(msg: str) -> None:
    print(msg, flush=True)


def run_versus(dataset: Path, n_pairs: int = 6, n_tone: int = 3, seeds: tuple[int, ...] = (0, 1, 2),
               mode: str = "hackathon", out: Path | None = None,
               log: Callable[[str], None] = lambda _: None, workers: int = 1) -> dict:
    """Run every seed (optionally one process per seed: the usage meter is
    process-global, so seeds never share a meter) and write the report."""
    out = out or SETTINGS.evaluations_dir / "versus_results.json"
    runs: list[dict] = []

    def write() -> dict:
        report = {"model": SETTINGS.model, "mode": mode, "dataset": str(dataset),
                  "n_pairs": n_pairs, "n_tone": n_tone, "seeds": list(seeds),
                  "summary": summarize(sorted(runs, key=lambda r: r["seed"])),
                  "runs": sorted(runs, key=lambda r: r["seed"])}
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
        return report

    if workers > 1 and len(seeds) > 1:
        import multiprocessing

        ctx = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
            futures = [pool.submit(run_seed, dataset, n_pairs, n_tone, seed, mode, _print)
                       for seed in seeds]
            for fut in futures:
                runs.append(fut.result())
                write()
    else:
        for seed in seeds:
            runs.append(run_seed(dataset, n_pairs, n_tone, seed, mode, log))
            write()
    return write()


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.0f}%"


LABELS = {"committee": "Committee (7 agents, 2 rounds)",
          "judge_matched": "Single judge, same token budget",
          "judge_1call": "Single judge, 1 call"}


def readme_table(report: dict) -> str:
    s = report["summary"]
    lines = ["| system | winner picked | ± sd (3 seeds) | tone flip rate | "
             "tokens / idea | calls / idea |", "|---|---|---|---|---|---|"]
    for system in SYSTEMS:
        m = s["systems"][system]
        tokens = f"{m['tokens_per_idea']:,.0f}" if m["tokens_per_idea"] is not None else "n/a"
        lines.append(f"| {LABELS[system]} | {_pct(m['accuracy_mean'])} | "
                     f"{_pct(m['accuracy_sd_across_seeds'])} | {_pct(m['tone_flip_rate'])} | "
                     f"{tokens} | {m['calls_per_idea']} |")
    return "\n".join(lines)
