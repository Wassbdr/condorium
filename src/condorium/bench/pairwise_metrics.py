"""Pair-clustered metrics and Markdown for pairwise runs."""

from __future__ import annotations

import json
import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 42
QUALITY = ("accuracy", "synthetic", "iclr", "position_flip", "slot_a", "verbosity", "tone")
COST = ("tokens", "calls", "debate", "dropped", "abstains", "violations_kept",
        "violations_dropped")


@dataclass(frozen=True)
class Estimate:
    value: float
    lo: float
    hi: float
    pairs: int


def _accuracy(row: dict) -> float:
    if row["winner"] == "tie":
        return 0.5
    return float(row["winner"] == row["better"])


@lru_cache(maxsize=128)
def _draws(n: int) -> tuple[tuple[int, ...], ...]:
    rng = random.Random(BOOTSTRAP_SEED)
    return tuple(tuple(rng.choices(range(n), k=n)) for _ in range(BOOTSTRAP_DRAWS))


def _estimate(groups: dict[str, list[float]]) -> Estimate | None:
    if not groups:
        return None
    sums, counts = zip(*[(sum(values), len(values)) for _, values in sorted(groups.items())],
                       strict=True)
    value = sum(sums) / sum(counts)
    if len(sums) == 1 or all(total / n == value for total, n in zip(sums, counts, strict=True)):
        return Estimate(value, value, value, len(sums))
    draws = sorted(sum(sums[i] for i in sample) / sum(counts[i] for i in sample)
                   for sample in _draws(len(sums)))
    return Estimate(value, draws[int(0.025 * (len(draws) - 1))],
                    draws[int(0.975 * (len(draws) - 1))], len(sums))


def metrics(rows: Sequence[dict]) -> dict[str, Estimate | None]:
    groups: dict[tuple[str, int], dict[tuple[str, str], dict]] = defaultdict(dict)
    observations: dict[str, dict[str, list[float]]] = {
        name: defaultdict(list) for name in QUALITY + COST
    }
    for row in rows:
        pair = row["pair_id"]
        groups[pair, row["seed"]][row["kind"], row["order"]] = row
        observations["tokens"][pair].append(row["usage"]["total_tokens"])
        observations["calls"][pair].append(row["usage"]["calls"])
        if row["method"] == "committee":
            observations["debate"][pair].append(float(row["debated"]))
            observations["dropped"][pair].append(row["evidence_dropped"])
            observations["abstains"][pair].append(row["abstains"])
            for name in ("violations_kept", "violations_dropped"):
                if name in row:
                    observations[name][pair].append(row[name])
        if row["kind"] == "position":
            observations["slot_a"][pair].append(float(row["winner"] == "a"))

    for (pair, _), cases in groups.items():
        ab = cases.get(("position", "ab"))
        ba = cases.get(("position", "ba"))
        if ab is None:
            continue
        if ba is not None:
            score = (_accuracy(ab) + _accuracy(ba)) / 2
            observations["accuracy"][pair].append(score)
            observations[ab["source"]][pair].append(score)
            swapped = {"a": "b", "b": "a", "tie": "tie"}[ba["winner"]]
            observations["position_flip"][pair].append(float(ab["winner"] != swapped))
        for kind in ("verbosity", "tone"):
            if altered := cases.get((kind, "ab")):
                observations[kind][pair].append(_accuracy(altered) - _accuracy(ab))
    return {name: _estimate(values) for name, values in observations.items()}


def _cell(value: Estimate | None, name: str) -> str:
    if value is None:
        return "n/a"
    if name in {"verbosity", "tone"}:
        form = lambda v: f"{100 * v:+.0f} pp"  # noqa: E731
    elif name in QUALITY or name == "debate":
        form = lambda v: f"{v:.0%}"  # noqa: E731
    else:
        form = lambda v: f"{v:,.1f}"  # noqa: E731
    return f"{form(value.value)} [{form(value.lo)}, {form(value.hi)}]"


def _render_split(report: dict) -> str:
    records = report["decisions"]
    lines = [
        f"## {report['split'].capitalize()}",
        "",
        f"{report['pair_count']} pairs, {report['variant_count']} variants, "
        f"seeds {report['seeds']}, {report['model']}, temperature {report['temperature']}, "
        f"committee protocol {report.get('committee_protocol', 'v1')}, "
        f"evaluation set v{report.get('dataset_version', 1)}.",
        f"Live calls: {report['live_calls']}; live attempts: {report['live_attempts']}; "
        f"cache hits: {report['cache_hits']}.",
    ]
    if report["position_only"]:
        lines.append("Position-only run. Verbosity and tone were not measured.")
    if report.get("reference_budget") == "v1":
        lines.append("References replay the protocol v1 token targets from the same evaluation set.")
    if report.get("committee_protocol") == "v3":
        lines.append("Swapping the two input arguments does not change which proposal the committee "
                     "picks. Roles alternate between the two content-based orders, so the "
                     "committee's position flip rate measures a property of the protocol.")
    if report["limited_methods"]:
        skipped = ", ".join(report["limited_methods"])
        if report.get("rate_limited"):
            cause = "Repeated HTTP 429 responses"
        elif report.get("max_calls") == 0:
            cause = "Cache-only replay with missing responses"
        else:
            cause = "Call limit reached"
        lines.append(f"{cause}. Results are partial for: {skipped}.")
    failures = sum(len(r["failures"]) for r in records if r["method"] != "judge_1call")
    lines.extend([f"Parse failures: {failures}. See the per-decision JSON for raw outputs.", ""])
    methods = [m for m in ("judge_1call", *report["methods"]) if m != "judge_1call"
               or "judge" in report["methods"]]
    summaries = []
    for method in methods:
        all_rows = [r for r in records if r["method"] == method]
        for seed in (None, *report["seeds"]):
            rows = all_rows if seed is None else [r for r in all_rows if r["seed"] == seed]
            summaries.append((method, "pooled" if seed is None else str(seed),
                              len(rows), metrics(rows)))
    for columns, names in (
        (QUALITY, ("Accuracy", "Synthetic", "ICLR", "Position flip", "Slot A",
                   "Verbosity delta", "Tone delta")),
        (COST, ("Tokens / decision", "Calls / decision", "Debate rate",
                "Quotes dropped / decision", "Abstains / decision", "Violations kept / decision",
                "Violations dropped / decision")),
    ):
        header = ("Method", "Seed", "Decisions", *names)
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        for method, seed, n, summary in summaries:
            cells = [method, seed, str(n), *(_cell(summary[name], name) for name in columns)]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines)


def _render_iterations(iterations: Sequence[dict]) -> str:
    if not iterations:
        return ""
    columns = ("Method", "Metric", "Value", "Delta vs previous")
    fields = (("accuracy", "Accuracy"), ("position_flip", "Position flip"),
              ("tokens", "Tokens / decision"))
    lines = ["", "## Iterations", ""]
    previous: dict = {}
    for iteration in iterations:
        seeds = ", ".join(map(str, iteration["seeds"]))
        lines.extend([
            f"### Iteration {iteration['id']}: {iteration['change']}",
            "",
            f"Split: `{iteration['split']}`. Seeds: `{seeds}`.",
            "",
            "| " + " | ".join(columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
        ])
        comparable = (
            all(iteration[key] == previous.get(key) for key in ("split", "seeds"))
            and iteration.get("dataset_version", 1) == previous.get("dataset_version", 1)
        )
        for method, values in iteration["metrics"].items():
            old = previous["metrics"].get(method, {}) if comparable else {}
            for key, label in fields:
                value = values[key]
                percent = key != "tokens"
                display = f"{value:.2%}" if percent else f"{value:,.1f}"
                delta = "n/a"
                if key in old:
                    change = value - old[key]
                    delta = f"{100 * change:+.2f} pp" if percent else f"{change:+,.1f}"
                lines.append(f"| {method} | {label} | {display} | {delta} |")
        lines.append("")
        previous = iteration
    return "\n".join(lines)


def render_results(reports: Sequence[dict], iterations: Sequence[dict] = ()) -> str:
    header = (
        "# Pairwise benchmark results\n\n"
        "Cells show the estimate and a 95% percentile interval from 2,000 pair-bootstrap "
        "draws (seed 42). Pooled intervals resample pairs across seeds. Accuracy uses both "
        "orders with ties worth half a hit. Verbosity and tone compare the altered item with "
        "the same pair in its original order. Slot A counts explicit A picks; a tie is "
        "not an A pick. Token totals include cached usage.\n\n"
    )
    return header + "\n".join(_render_split(report) for report in reports) + _render_iterations(
        iterations
    )


def write_results(report: dict, path: Path, *, iterations_path: Path | None = None) -> None:
    iterations = []
    if iterations_path is not None and iterations_path.is_file():
        try:
            iterations = yaml.safe_load(iterations_path.read_text(encoding="utf-8"))
            if iterations is None:
                iterations = []
            if not isinstance(iterations, list):
                raise ValueError("expected a list of iterations")
            _render_iterations(iterations)
        except (yaml.YAMLError, KeyError, AttributeError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid iteration history in {iterations_path}: {exc}") from exc
    path.mkdir(parents=True, exist_ok=True)
    out = path / f"{report['split']}.json"
    partial = out.with_suffix(".tmp")
    partial.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    partial.replace(out)
    reports = [json.loads(f.read_text(encoding="utf-8")) for split in ("test", "dev")
               if (f := path / f"{split}.json").is_file()]
    (path.parent / "results.md").write_text(render_results(reports, iterations), encoding="utf-8")
