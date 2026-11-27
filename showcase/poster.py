"""poster.png (1280x720): each agent's score per round for the replayed run,
the believer cap, the verdict, and the committee-vs-single-judge headline.

usage: python showcase/poster.py TRACE.json [versus_results.json] OUT.png
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from condorium.display import believer_cap  # noqa: E402

ORDER = ("judge", "believer", "scientist_eval", "skeptic", "investor", "strategist", "jury")
BG, FG, DIM = "#0f172a", "#e2e8f0", "#94a3b8"
R1C, R2C, CAPC = "#64748b", "#38bdf8", "#f87171"


def main(trace: Path, results: Path | None, out: Path) -> None:
    rec = json.loads(trace.read_text(encoding="utf-8"))
    r1, r2 = rec.get("round1", {}), rec.get("round2", {})
    names = [n for n in ORDER if n in r1 or n in r2]
    fig = plt.figure(figsize=(12.8, 7.2), dpi=100, facecolor=BG)

    fig.text(0.04, 0.93, "Condorium — a committee of LLM agents that refuses to flatter",
             color=FG, fontsize=22, weight="bold")
    fig.text(0.04, 0.885, "REPLAY OF A RECORDED RUN", color="#0f172a", fontsize=11,
             weight="bold", bbox={"facecolor": "#facc15", "edgecolor": "none", "pad": 3})
    fig.text(0.245, 0.885, f"“{rec['idea']['title']}” — every agent's score, blind round 1 "
             "vs round 2 after deliberation", color=DIM, fontsize=12)

    ax = fig.add_axes([0.14, 0.16, 0.48, 0.66], facecolor=BG)
    y = range(len(names))
    for i, n in enumerate(names):
        s1, s2 = r1.get(n, {}).get("score"), r2.get(n, {}).get("score")
        if s1 is None and s2 is None:
            ax.text(0.3, i, "neutral — score withheld (∅), excluded from medians",
                    color=DIM, va="center", fontsize=10)
            continue
        if s1 is not None and s2 is not None:
            ax.plot([s1, s2], [i, i], color=DIM, lw=1.5, zorder=1)
        if s1 is not None:
            ax.scatter(s1, i, s=140, color=R1C, zorder=2, label="round 1 (blind)" if i == 0 else "")
        if s2 is not None:
            ax.scatter(s2, i, s=140, color=R2C, zorder=3,
                       label="round 2 (deliberation)" if i == 0 else "")
        up = r2.get(n, {}).get("uncapped_score")
        if up is not None:
            ax.scatter(up, i, s=140, facecolors="none", edgecolors=CAPC, lw=2, zorder=3)
            ax.annotate("", xy=(s2, i), xytext=(up, i),
                        arrowprops={"arrowstyle": "->", "color": CAPC, "lw": 2})
    cap = believer_cap(rec)
    if cap is not None and "believer" in names:
        i = names.index("believer")
        ax.plot([cap, cap], [i - 0.4, i + 0.4], color=CAPC, lw=3)
        ax.text(cap + 0.1, i + 0.42, f"cap = median(others' R1) + 3 = {cap:g}", color=CAPC,
                fontsize=10)
    ax.set_yticks(list(y), names, color=FG, fontsize=12)
    ax.set_xlim(0, 10.5)
    ax.set_ylim(len(names) - 0.4, -0.7)
    ax.set_xticks(range(0, 11), [str(t) for t in range(11)], color=DIM)
    ax.set_xlabel("score /10", color=DIM)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(DIM)
    ax.grid(axis="x", color="#1e293b")
    leg = ax.legend(loc="lower left", frameon=False, fontsize=10)
    for t in leg.get_texts():
        t.set_color(FG)

    syn = rec.get("synthesis") or {}
    color = {"GO": "#4ade80", "ITERATE": "#facc15", "PIVOT": "#f87171"}.get(syn.get("verdict"), FG)
    fig.text(0.66, 0.78, f"Verdict: {syn.get('verdict', '?')}", color=color, fontsize=22,
             weight="bold")
    fig.text(0.66, 0.745, "no average — disagreements are the output", color=DIM, fontsize=11)
    lines = []
    for d in (syn.get("disagreements") or [])[:2]:
        lines.append(f"• {d.get('topic', '')} (gap {d.get('gap', '?')}: "
                     f"{' vs '.join(d.get('agents', []))})")
    import textwrap

    body = "\n".join(textwrap.fill(line, 46) for line in lines) or "• none recorded"
    fig.text(0.66, 0.72, body, color=FG, fontsize=11, va="top", linespacing=1.4)

    if results and results.exists():
        rep = json.loads(results.read_text(encoding="utf-8"))
        s = rep["summary"]["systems"]
        fig.text(0.66, 0.40, "Committee vs single judge, same tokens", color=FG,
                 fontsize=12, weight="bold")
        rows = [("committee", "Committee"), ("judge_matched", "Judge, = tokens"),
                ("judge_1call", "Judge, 1 call")]
        fig.text(0.66, 0.365, f"{'':16}{'winner':>8}{'tone flip':>11}", color=DIM,
                 fontsize=11, family="monospace")
        for k, (key, label) in enumerate(rows):
            m = s[key]
            acc = "n/a" if m["accuracy_mean"] is None else f"{100 * m['accuracy_mean']:.0f}%"
            flip = "n/a" if m["tone_flip_rate"] is None else f"{100 * m['tone_flip_rate']:.0f}%"
            fig.text(0.66, 0.33 - 0.035 * k, f"{label:16}{acc:>8}{flip:>11}", color=FG,
                     fontsize=11, family="monospace")
        n = rep["summary"]["n_pairs_per_seed"]
        fig.text(0.66, 0.205, f"{sum(n)} synthetic pairs, seeds {rep['summary']['seeds']},\n"
                 f"{rep['model'].split('/')[-1]} via NIM", color=DIM, fontsize=9)

    fig.text(0.04, 0.04, "Guardrails enforced in code: believer cap · citations limited to "
             "papers retrieved in the run · neutral scientist scores ∅ · no score averaging",
             color=DIM, fontsize=11)
    fig.savefig(out, dpi=100, facecolor=BG)


if __name__ == "__main__":
    args = [Path(a) for a in sys.argv[1:]]
    main(args[0], args[1] if len(args) == 3 else None, args[-1])
