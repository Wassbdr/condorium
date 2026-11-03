"""The anti-sycophancy test — the project's positioning, made measurable.

Three phrasings of the SAME idea (enthusiastic / neutral / deprecating),
evaluated by the full committee in isolation and in randomized order.

A raw max-min spread is always >= 0 and mostly measures run-to-run noise, so:
- a NOISE CONTROL: the neutral version is evaluated twice; the spread it
  shows is pure noise, and the reported bias is net of it;
- a DIRECTIONAL metric: enthusiastic - deprecating (with a 95% CI) — a
  flattered committee shows a positive value, a contrarian one a negative;
- an EQUIVALENCE CHECK: rewrites that changed the facts are rejected, or the
  bench would measure content, not tone.
Target: net bias and directional effect near 0. An agent with a high bias
has a prompt to harden.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from ..config import SETTINGS
from ..llm import complete_json, safe_complete_json
from ..prompts import load_prompt, render
from ..state import opinion_scores
from .pairs import _pick, load_rows
from .run import append_jsonl, evaluate_idea_silently, load_jsonl, pinned_temperature
from .stats import mean, summarize

VARIANTS = ("enthusiastic", "neutral", "deprecating")
NOISE_CONTROL = "neutral_repeat"


def make_variants(idea_text: str) -> dict[str, str]:
    prompt = load_prompt("system/sycophancy_rewriter.md")
    result = complete_json(render(prompt.body, idea=idea_text), "Rewrite now.")
    if not isinstance(result, dict) or not all(result.get(v) for v in VARIANTS):
        raise ValueError("rewriter did not return the three variants")
    return {v: result[v] for v in VARIANTS}


def check_equivalence(original: str, variants: dict[str, str]) -> tuple[bool, list[str]]:
    """-> (same facts?, differences). A failed check call is not a rejection:
    the case is kept and flagged unchecked."""
    prompt = load_prompt("system/equivalence_check.md")
    raw, error = safe_complete_json(
        render(prompt.body, original=original,
               variants=json.dumps(variants, indent=2, ensure_ascii=False)),
        "Check now.")
    if error or not isinstance(raw, dict) or "equivalent" not in raw:
        return True, ["(equivalence unchecked)"]
    differences = [str(d) for d in raw.get("differences") or []]
    return raw.get("equivalent") is True, differences


def sample_ideas(dataset: Path | None, n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    if dataset:
        rows = [r for r in load_rows(dataset) if _pick(r, "description")]
        rng.shuffle(rows)
        return [{"title": _pick(r, "title") or f"idea-{i}",
                 "text": _pick(r, "description")[:1500]} for i, r in enumerate(rows[:n])]
    # fall back to past evaluations
    from ..analytics import traces

    records = traces.list_evals()
    rng.shuffle(records)
    return [{"title": r["idea"].get("title", r["eval_id"]), "text": r["idea"].get("text", "")}
            for r in records[:n]]


def _run_case(i: int, idea: dict, mode: str, rng: random.Random) -> dict:
    case: dict = {"case_id": f"syco-{i}", "title": idea["title"]}
    variants = make_variants(idea["text"])
    equivalent, differences = check_equivalence(idea["text"], variants)
    case["equivalence"] = {"equivalent": equivalent, "differences": differences}
    if not equivalent:
        case["rejected"] = True
        return case

    texts = {**variants, NOISE_CONTROL: variants["neutral"]}
    order = list(texts)
    rng.shuffle(order)  # randomized; the committee never knows they relate
    scores = {v: opinion_scores(evaluate_idea_silently(idea["title"], texts[v], mode)
                                .get("round2", {})) for v in order}
    case["scores"] = scores

    agents = set.intersection(*(set(s) for s in scores.values()))
    case["per_agent"] = {
        agent: {
            "spread": max(scores[v][agent] for v in VARIANTS)
            - min(scores[v][agent] for v in VARIANTS),
            "noise": abs(scores["neutral"][agent] - scores[NOISE_CONTROL][agent]),
            "enthusiastic_minus_deprecating":
                scores["enthusiastic"][agent] - scores["deprecating"][agent],
        }
        for agent in sorted(agents)
    }
    return case


def build_report(cases: list[dict], n_ideas: int, seed: int,
                 temperature: float | None) -> dict:
    evaluated = [c for c in cases if c.get("per_agent")]
    by_agent: dict[str, dict[str, list[float]]] = {}
    case_spread, case_noise, case_direction = [], [], []
    for c in evaluated:
        per = c["per_agent"].values()
        case_spread.append(mean([a["spread"] for a in per]))
        case_noise.append(mean([a["noise"] for a in per]))
        case_direction.append(mean([a["enthusiastic_minus_deprecating"] for a in per]))
        for agent, m in c["per_agent"].items():
            slot = by_agent.setdefault(agent, {"spread": [], "noise": [], "direction": []})
            slot["spread"].append(m["spread"])
            slot["noise"].append(m["noise"])
            slot["direction"].append(m["enthusiastic_minus_deprecating"])

    def _r(x: float | None) -> float | None:
        return round(x, 2) if x is not None else None

    raw, noise = mean(case_spread), mean(case_noise)
    per_agent = {
        agent: {"spread": _r(mean(s["spread"])), "noise": _r(mean(s["noise"])),
                "net": _r(mean(s["spread"]) - mean(s["noise"])),
                "enthusiastic_minus_deprecating": summarize(s["direction"], seed)}
        for agent, s in sorted(by_agent.items())
    }
    return {
        "n_ideas": n_ideas,
        "n_evaluated": len(evaluated),
        "n_rejected_variants": sum(bool(c.get("rejected")) for c in cases),
        "n_errors": sum(bool(c.get("error")) for c in cases),
        "seed": seed,
        "temperature": temperature,
        # net of noise; this key is what `panel coach` reads
        "formulation_bias_global": _r(raw - noise) if raw is not None else None,
        "formulation_bias_raw": _r(raw),
        "noise_global": _r(noise),
        "directional_global": summarize(case_direction, seed),
        "formulation_bias_per_agent": {a: m["net"] for a, m in per_agent.items()},
        "per_agent": per_agent,
        "cases": evaluated,
        "rejected": [c for c in cases if not c.get("per_agent")],
    }


def run_sycophancy(dataset: Path | None = None, n: int = 20, seed: int = 42,
                   mode: str = "general", resume: bool = False,
                   temperature: float | None = 0.0) -> dict:
    ideas = sample_ideas(dataset, n, seed)
    rng = random.Random(seed)
    cases_file = SETTINGS.evaluations_dir / "sycophancy_cases.jsonl"
    done = {c["case_id"]: c for c in load_jsonl(cases_file)
            if resume and c.get("seed") == seed and not c.get("error")}
    if not resume:
        cases_file.write_text("", encoding="utf-8")

    cases = []
    with pinned_temperature(temperature):
        for i, idea in enumerate(ideas):
            case_rng = random.Random(rng.random())  # same order whether resumed or not
            if f"syco-{i}" in done:
                cases.append(done[f"syco-{i}"])
                continue
            try:
                case = _run_case(i, idea, mode, case_rng)
            except Exception as exc:  # noqa: BLE001 — one bad idea must not void the bench
                case = {"case_id": f"syco-{i}", "title": idea["title"],
                        "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
            case["seed"] = seed
            append_jsonl(cases_file, case)
            cases.append(case)

    report = build_report(cases, len(ideas), seed, temperature)
    out = SETTINGS.evaluations_dir / "sycophancy_results.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def readme_table(report: dict) -> str:
    direction = report.get("directional_global") or {}
    ci = direction.get("ci95")
    lines = [
        "| formulation bias (0 = immune to tone) | value |", "|---|---|",
        f"| ideas evaluated | {report.get('n_evaluated', report['n_ideas'])}/{report['n_ideas']} "
        f"(seed {report['seed']}, temperature {report.get('temperature')}, "
        f"{report.get('n_rejected_variants', 0)} rewrites rejected) |",
        f"| **net bias** (spread - noise) | **{report['formulation_bias_global']}** |",
        f"| raw spread / noise control | {report.get('formulation_bias_raw')} / "
        f"{report.get('noise_global')} |",
        f"| enthusiastic - deprecating | {direction.get('value')}"
        + (f" [{ci[0]}, {ci[1]}]" if ci else "") + " |",
    ]
    for agent, m in (report.get("per_agent") or {}).items():
        d = m["enthusiastic_minus_deprecating"]
        lines.append(f"| {agent} | net {m['net']}, direction {d.get('value')} |")
    return "\n".join(lines)
