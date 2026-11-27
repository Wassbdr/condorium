"""Committee vs single judge: both systems, same pairs, same token budget.

The fake LLM is deterministic and rewards substance (a measured result in
the text); the single judge is made tone-sensitive on purpose so the
flip-rate metric is proven to detect sycophancy.
"""

import json
import re

import pytest

from condorium.bench import versus

REPO_DATASET = "fixtures/bench/synthetic_pairs.json"


def _substance(text: str) -> int:
    return 8 if re.search(r"\b\d+ (real|of)\b", text) else 4


@pytest.fixture
def substance_llm(mock_llm, monkeypatch):
    original = mock_llm._committee

    def committee(system, user):
        op = original(system, user)
        op["score"] = _substance(user)
        return op

    def judge(user):
        score = _substance(user) + (2 if "!" in user else 0)  # tone-sensitive on purpose
        return {"score": min(score, 10), "verdict": "GO" if score >= 6 else "PIVOT",
                "rationale": "r", "main_risk": "m", "action": "a"}

    monkeypatch.setattr(mock_llm, "_committee", committee)
    monkeypatch.setattr(mock_llm, "single_judge", judge)
    monkeypatch.setattr(versus, "MAX_JUDGE_SAMPLES", 500)  # fake judge replies are tiny
    return mock_llm


def _dataset(sandbox):
    rows = []
    for h in ("HackA", "HackB", "HackC"):
        rows.append({"hackathon": h, "title": f"{h} win", "prizes": "Grand Prize",
                     "description": f"{h}: tested with 40 real users during the event.",
                     "enthusiastic": f"{h}: tested with 40 real users during the event!"})
        rows.append({"hackathon": h, "title": f"{h} other", "prizes": "",
                     "description": f"{h}: a platform for everyone, integrations planned.",
                     "enthusiastic": f"{h}: a platform for everyone, integrations planned!"})
    path = sandbox / "pairs.json"
    path.write_text(json.dumps(rows))
    return path


def test_both_systems_run_on_same_pairs_with_matched_budget(substance_llm, sandbox):
    report = versus.run_versus(_dataset(sandbox), n_pairs=3, n_tone=2, seeds=(0, 1, 2))
    s = report["summary"]
    assert s["n_seeds"] == 3 and s["n_pairs_per_seed"] == [3, 3, 3]
    for run in report["runs"]:
        for case in run["pairs"]:
            for ev in case["entries"].values():
                committee_tokens = ev["committee"]["usage"]["total_tokens"]
                judge = ev["judge"]
                assert judge["usage"]["total_tokens"] >= committee_tokens
                # one sample fewer would have stayed under the committee's budget
                per_call = judge["usage"]["total_tokens"] / judge["n_samples"]
                assert judge["usage"]["total_tokens"] - per_call < committee_tokens + per_call
                assert ev["committee"]["usage"]["calls"] >= 16  # intake + 7x2 + synthesis
    assert s["systems"]["committee"]["accuracy_mean"] == 1.0
    assert s["systems"]["judge_matched"]["accuracy_mean"] == 1.0
    assert s["pick_agreement_committee_vs_judge_matched"] == 1.0
    assert s["tokens_estimated"] is True  # fake LLM reports no usage
    assert (sandbox / "evaluations" / "versus_results.json").exists()


def test_tone_flip_rate_detects_a_sycophantic_judge(substance_llm, sandbox):
    report = versus.run_versus(_dataset(sandbox), n_pairs=3, n_tone=6, seeds=(0,))
    systems = report["summary"]["systems"]
    assert systems["committee"]["tone_flip_rate"] == 0.0
    # the non-winners (4 -> 6) cross the GO threshold when hyped; winners stay GO
    assert systems["judge_matched"]["tone_flip_rate"] == 0.5
    assert systems["judge_1call"]["tone_score_delta"] == 2.0


def test_repo_dataset_builds_leak_free_pairs():
    from pathlib import Path

    from condorium.bench.antileak import has_leak
    from condorium.bench.pairs import build_pairs

    path = Path(__file__).resolve().parents[1] / REPO_DATASET
    pairs = build_pairs(path, n=18, seed=0)
    assert len(pairs) == 18
    assert all(not has_leak(e["text"]) for p in pairs for e in p["entries"])


def test_pick_and_ties():
    assert versus.pick(versus.strength("GO", 6), versus.strength("ITERATE", 9)) == 1.0
    assert versus.pick(versus.strength("PIVOT", 6), versus.strength("PIVOT", 7)) == 0.0
    assert versus.pick(versus.strength("GO", 7), versus.strength("GO", 7)) == 0.5
    assert versus._majority_verdict([{"verdict": "GO"}, {"verdict": "PIVOT"}]) == "PIVOT"


def test_call_budget_guard(mock_llm, monkeypatch):
    from condorium import llm

    monkeypatch.setattr(llm, "_calls_made", 0)
    monkeypatch.setenv("CONDORIUM_MAX_CALLS", "2")
    llm.complete_text("s", "u")
    llm.complete_text("s", "u")
    with pytest.raises(llm.CallBudgetExceeded):
        llm.complete_text("s", "u")
