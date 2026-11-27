"""Write showcase/showcase.json from the measured bench results (never by hand)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from condorium.bench.versus import readme_table
from condorium.display import believer_cap

root = Path(__file__).resolve().parents[1]
results = json.loads((root / "showcase/results/versus_results.json").read_text())
trace = sys.argv[1] if len(sys.argv) > 1 else "fixtures/demo/01-transit-copilot.json"
s = results["summary"]
sysm = s["systems"]
model = results["model"].split("/", 1)[-1]
setup = (f"{sum(s['n_pairs_per_seed'])} synthetic winner/non-winner pairs "
         f"(fixtures/bench), seeds {s['seeds']}, {model} via NVIDIA NIM, "
         "8-CPU VM, no GPU")
bench_cmd = ("CONDORIUM_RPM=24 panel bench --versus --n {n} --tone {t} --seeds 0,1,2 --resume"
             .format(n=results["n_pairs"], t=results["n_tone"]))


def pct(x):
    return "n/a" if x is None else f"{100 * x:.0f}%"


showcase = {
    "slug": "condorium",
    "title": "Condorium",
    "tagline": "A committee of LLM agents that judges ideas in two rounds and is "
               "built, in code, not to flatter you.",
    "problem": "A single LLM asked to judge an idea tends to agree with the person asking, "
               "drifts with the tone of the pitch and averages away the real objections. "
               "That makes LLM feedback on ideas cheap but hard to trust.",
    "approach": "A LangGraph pipeline runs seven role agents in a blind first round, then a "
                "deliberation round where each sees every other opinion and must justify "
                "any revision. Guardrails are code, not prompts: the most enthusiastic score "
                "is capped at the others' median + 3, citations must come from papers "
                "retrieved during the run, and the synthesis reports disagreements instead "
                "of an average. Runs are checkpointed in SQLite and resumable.",
    "stack": ["Python", "LangGraph", "LiteLLM", "SQLite", "Gradio", "Rich", "pytest"],
    "demo": {
        "gif": "showcase/demo.gif", "mp4": "showcase/demo.mp4",
        "poster": "showcase/poster.png", "kind": "replay",
        "caption": f"Replay of a recorded run ({Path(trace).name}): blind round-1 scores, "
                   "the believer cap, round-2 revisions, and the disagreements the "
                   "synthesis reports instead of an average.",
    },
    "reproduce": [
        "uv venv -p 3.11 && uv pip install -e '.[dev]'",
        "panel demo",
        "pytest -q",
        "NVIDIA_NIM_API_KEY=... CONDORIUM_MODEL=nvidia_nim/" + model + " " + bench_cmd,
        "bash showcase/make_showcase.sh",
    ],
    "results": [
        {"label": "Winner picked, committee vs single judge at the same token budget",
         "value": f"{pct(sysm['committee']['accuracy_mean'])} vs "
                  f"{pct(sysm['judge_matched']['accuracy_mean'])} "
                  f"(1-call judge {pct(sysm['judge_1call']['accuracy_mean'])})",
         "command": bench_cmd, "setup": setup},
        {"label": "Verdict flips when the same idea is pitched enthusiastically",
         "value": f"committee {pct(sysm['committee']['tone_flip_rate'])}, judge "
                  f"{pct(sysm['judge_matched']['tone_flip_rate'])} "
                  f"({s['n_tone_cases']} cases)",
         "command": bench_cmd, "setup": setup},
        {"label": "Tokens per idea, committee",
         "value": f"{sysm['committee']['tokens_per_idea']:,.0f} tokens, "
                  f"{sysm['committee']['calls_per_idea']} calls",
         "command": bench_cmd, "setup": setup},
        {"label": "Offline test suite (LLM fully mocked)", "value": "pytest green, keyless",
         "command": "pytest -q", "setup": "Python 3.11, no network, no key"},
    ],
    "limits": [
        "The anti-leak cleaner is lexical: a paraphrased victory clue survives "
        "(kept as a strict xfail test).",
        "Benchmark pairs are synthetic and few (LLM budget < 2,000 calls); accuracy "
        "differences of one pair are within noise.",
        "The demo GIF is a replay of a recorded run, not a live computation.",
        "One open model (via NIM) was measured; other providers are untested here.",
    ],
    "role": "TODO",
    "repo": "https://github.com/Wassbdr/condorium",
}
(root / "showcase/showcase.json").write_text(json.dumps(showcase, indent=2, ensure_ascii=False)
                                             + "\n")
print("wrote showcase/showcase.json")


def versus_block() -> str:
    c, j, j1 = (sysm[k] for k in ("committee", "judge_matched", "judge_1call"))
    ratio = c["tokens_per_idea"] / j1["tokens_per_idea"] if j1["tokens_per_idea"] else 0
    return "\n".join([
        f"**Winner picked: committee {pct(c['accuracy_mean'])}, single judge at the same "
        f"token budget {pct(j['accuracy_mean'])}, single judge in one call "
        f"{pct(j1['accuracy_mean'])}.** The committee costs {ratio:.0f}x the tokens of one "
        "judge call.",
        "",
        readme_table(results),
        "",
        f"Setup: {setup}. Tone cases (same idea rewritten enthusiastically): "
        f"{s['n_tone_cases']}. Agreement committee vs same-budget judge: "
        f"{pct(s['pick_agreement_committee_vs_judge_matched'])} of pair picks, "
        f"{pct(s['verdict_agreement_committee_vs_judge_matched'])} of verdicts. "
        f"{s['llm_calls_total']:,} LLM calls in the measured systems. Believer cap fired "
        f"{s['believer_cap_fired']} times, debates {s['debates_triggered']}. "
        "Raw data: [`showcase/results/versus_results.json`](showcase/results/versus_results.json), "
        "regenerate with `LIVE=1 bash showcase/make_showcase.sh`.",
    ])


def verdict_block() -> str:
    rec = json.loads((root / trace).read_text())
    r1, r2, syn = rec["round1"], rec["round2"], rec["synthesis"]
    cap = believer_cap(rec)
    b1, b2 = r1.get("believer", {}), r2.get("believer", {})
    scores = lambda r: ", ".join(  # noqa: E731
        f"{k} {v.get('score') if v.get('score') is not None else '∅'}" for k, v in r.items())
    moved = [f"{k} {r1[k].get('score')}→{v.get('score')}" for k, v in r2.items()
             if k in r1 and v.get("score") != r1[k].get("score")]
    dis = syn.get("disagreements") or []
    lines = [
        f"From the recorded run [`{Path(trace).name}`]({trace}) (`panel demo {trace}`): "
        f"*{rec['idea']['title']}* — {rec['idea']['text'][:160].rstrip()}…",
        "",
        f"1. **Round 1, blind**: {scores(r1)}.",
        f"2. **Cap**: the believer may not exceed median(others' blind scores) + 3 = "
        f"**{cap}**; it asked for {b2.get('uncapped_score', b2.get('score'))}"
        + (f" and was **cut to {b2.get('score')}**." if b2.get("capped") else
           " (blind: " + str(b1.get("score")) + "), within the cap."),
        f"3. **Round 2, after reading everyone**: {', '.join(moved) or 'no score moved'}; "
        "every change comes with a stated reason.",
        f"4. **Verdict {syn.get('verdict')}**: {syn.get('consensus', '')}",
    ]
    if dis:
        d = dis[0]
        lines.append(f"5. **No average**: the synthesis reports the disagreement instead — "
                     f"*{d.get('topic', '')}* ({d.get('positions', '')}), because "
                     f"{d.get('why_it_matters', '')}.")
    if syn.get("action"):
        lines.append(f"6. **One next action**: {syn['action']}")
    return "\n".join(lines)


def fill(text: str, name: str, body: str) -> str:
    a, b = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    return text[: text.index(a) + len(a)] + "\n" + body + "\n" + text[text.index(b):]


readme = root / "README.md"
readme.write_text(fill(fill(readme.read_text(), "versus", versus_block()),
                       "verdict", verdict_block()))
print("filled README result blocks")
