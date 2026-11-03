"""Agent statistics over the full evaluation history.

- influence matrix: who makes whom revise (source: `influenced_by`), with the
  mean amplitude of the caused revisions
- round-1 -> round-2 delta per agent
- agreement matrix: score correlation between agents across evaluations
- relative severity: each agent's mean score vs the panel median (drift
  detector for a sycophantic or demolishing prompt)
"""

from __future__ import annotations

from collections import defaultdict

from ..state import median, opinion_scores
from . import traces


def influence_matrix(records: list[dict] | None = None) -> dict:
    """matrix[influencer][revised_agent] = {count, mean_amplitude}."""
    records = records if records is not None else traces.list_evals()
    counts: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for rec in records:
        r1, r2 = rec.get("round1", {}), rec.get("round2", {})
        for agent, op2 in r2.items():
            s1 = (r1.get(agent) or {}).get("score")
            s2 = op2.get("score")
            amplitude = abs(s2 - s1) if isinstance(s1, (int, float)) and isinstance(s2, (int, float)) else 0.0
            for src in op2.get("influenced_by") or []:
                if src != agent:
                    counts[src][agent].append(amplitude)
    return {
        src: {tgt: {"count": len(a), "mean_amplitude": round(sum(a) / len(a), 2)}
              for tgt, a in targets.items()}
        for src, targets in counts.items()
    }


def round_deltas(records: list[dict] | None = None) -> dict:
    """Per agent: how often it changes its mind, in which direction, by how much."""
    records = records if records is not None else traces.list_evals()
    deltas: dict[str, list[float]] = defaultdict(list)
    for rec in records:
        r1, r2 = rec.get("round1", {}), rec.get("round2", {})
        for agent in set(r1) & set(r2):
            s1, s2 = r1[agent].get("score"), r2[agent].get("score")
            if isinstance(s1, (int, float)) and isinstance(s2, (int, float)):
                deltas[agent].append(s2 - s1)
    return {
        agent: {
            "n": len(d),
            "revised_share": round(sum(1 for x in d if x != 0) / len(d), 2),
            "mean_delta": round(sum(d) / len(d), 2),
            "mean_abs_delta": round(sum(abs(x) for x in d) / len(d), 2),
        }
        for agent, d in deltas.items() if d
    }


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    vx = sum((x - mx) ** 2 for x in xs) ** 0.5
    vy = sum((y - my) ** 2 for y in ys) ** 0.5
    if vx == 0 or vy == 0:
        return None
    return round(cov / (vx * vy), 2)


def agreement_matrix(records: list[dict] | None = None) -> dict:
    records = records if records is not None else traces.list_evals()
    series: dict[str, dict[str, float]] = defaultdict(dict)  # agent -> eval_id -> score
    for rec in records:
        for agent, score in opinion_scores(rec.get("round2", {})).items():
            series[agent][rec["eval_id"]] = score
    agents = sorted(series)
    matrix: dict[str, dict[str, float | None]] = {}
    for a in agents:
        matrix[a] = {}
        for b in agents:
            if a == b:
                continue
            common = sorted(set(series[a]) & set(series[b]))
            matrix[a][b] = _pearson([series[a][e] for e in common], [series[b][e] for e in common])
    return matrix


def severity(records: list[dict] | None = None) -> dict:
    """Mean signed distance of each agent's score to the panel median."""
    records = records if records is not None else traces.list_evals()
    gaps: dict[str, list[float]] = defaultdict(list)
    for rec in records:
        scores = opinion_scores(rec.get("round2", {}))
        med = median(list(scores.values()))
        if med is None:
            continue
        for agent, s in scores.items():
            gaps[agent].append(s - med)
    return {a: {"n": len(g), "mean_vs_median": round(sum(g) / len(g), 2)} for a, g in gaps.items() if g}


def full_stats() -> dict:
    records = traces.list_evals()
    return {
        "n_evaluations": len(records),
        "influence": influence_matrix(records),
        "round_deltas": round_deltas(records),
        "agreement": agreement_matrix(records),
        "severity": severity(records),
    }
