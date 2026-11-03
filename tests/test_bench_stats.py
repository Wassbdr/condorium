"""Bench rigor: CIs, baselines, ties, errors and resume — the numbers the
README will quote must mean what they say."""

import json

from condorium.bench.stats import bootstrap_ci, pair_outcome, summarize


def test_bootstrap_ci_is_seeded_and_brackets_the_mean():
    values = [1.0] * 30 + [0.0] * 20
    a, b = bootstrap_ci(values, seed=3), bootstrap_ci(values, seed=3)
    assert a == b
    assert a[0] < 0.6 < a[1]
    assert bootstrap_ci([], seed=3) is None
    assert summarize([1.0, 0.0], seed=1)["value"] == 0.5


def test_pair_outcome_ties_and_none():
    assert pair_outcome((2, 7.0), (1, 9.0)) == 1.0
    assert pair_outcome(5, 5) == 0.5
    assert pair_outcome(None, 3) == 0.5
    assert pair_outcome(3, 8) == 0.0


def _dataset(sandbox, n_hackathons=2):
    rows = []
    for h in range(n_hackathons):
        rows.append({"title": f"Winner app {h}", "hackathon": f"H{h}", "prizes": "1st",
                     "description": "A long and detailed description of a project "
                                    "with a lot of substance and a live demo. " * 3})
        rows.append({"title": f"Other {h}", "hackathon": f"H{h}", "prizes": "",
                     "description": "Short one."})
    path = sandbox / "ds.json"
    path.write_text(json.dumps(rows))
    return path


def test_report_has_ci_baselines_and_ties(mock_llm, sandbox):
    from condorium.bench.run import readme_table, run_bench

    # the committee scores both sides the same -> every pair is a tie
    mock_llm.baseline_score = lambda user: 8 if "detailed description" in user else 4
    report = run_bench(_dataset(sandbox), n=2, seed=1)
    assert report["n_evaluated"] == 2 and report["n_errors"] == 0
    assert report["n_ties"] == 2
    assert report["winner_identification_rate"] == 0.5
    assert report["baselines"]["length"]["value"] == 1.0  # winner text is longer
    assert report["baselines"]["single_call"]["value"] == 1.0
    assert report["winner_identification_ci95"] is not None
    assert report["temperature"] == 0.0
    table = readme_table(report)
    assert "baseline — single LLM call" in table and "longer description" in table
    # titles cleaned by antileak before the committee sees them
    committee_users = [c["user"] for c in mock_llm.calls if c["user"].startswith("ROUND 1")]
    assert committee_users and not any("Winner app" in u for u in committee_users)


def test_failing_pair_is_counted_not_fatal_and_resume_skips_done(mock_llm, sandbox,
                                                                monkeypatch):
    from condorium.bench import run as bench_run

    dataset = _dataset(sandbox)
    real = bench_run.run_pair
    calls = []
    failed = []

    def flaky(pair, mode, baselines):
        calls.append(pair["pair_id"])
        if pair["pair_id"] == "pair-1" and not failed:
            failed.append(True)
            raise RuntimeError("provider down")
        return real(pair, mode, baselines)

    monkeypatch.setattr(bench_run, "run_pair", flaky)
    first = bench_run.run_bench(dataset, n=2, seed=1, baselines=False)
    assert first["n_errors"] == 1 and first["n_evaluated"] == 1

    calls.clear()
    second = bench_run.run_bench(dataset, n=2, seed=1, baselines=False, resume=True)
    assert calls == ["pair-1"]  # pair-0 came from the jsonl, not re-paid
    assert second["n_errors"] == 0 and second["n_evaluated"] == 2


def test_coach_ignores_crashed_pairs(sandbox):
    from condorium.coach import _collect_errors
    from condorium.config import SETTINGS

    (SETTINGS.evaluations_dir / "bench_results.json").write_text(json.dumps({"cases": [
        {"case_id": "a", "correct": False}, {"case_id": "b", "correct": None, "error": "x"},
        {"case_id": "c", "correct": True}]}))
    bench_errors, _, _ = _collect_errors()
    assert [c["case_id"] for c in bench_errors] == ["a"]
