"""Write showcase/showcase.json from the measured bench results (never by hand)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
results = json.loads((root / "showcase/results/versus_results.json").read_text())
trace = sys.argv[1] if len(sys.argv) > 1 else "fixtures/demo/01-transit-copilot.json"
s = results["summary"]
sysm = s["systems"]
model = results["model"].split("/", 1)[-1]
setup = (f"{sum(s['n_pairs_per_seed'])} synthetic winner/non-winner pairs "
         f"(fixtures/bench), seeds {results['seeds']}, {model} via NVIDIA NIM, "
         "8-CPU VM, no GPU")
bench_cmd = ("panel bench --versus --n {n} --tone {t} --seeds 0,1,2 --workers 3"
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
