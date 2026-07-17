import json


def test_zero_bias_when_scores_ignore_tone(mock_llm, sandbox):
    from condorium.bench.sycophancy import run_sycophancy

    dataset = sandbox / "ideas.json"
    dataset.write_text(json.dumps([
        {"title": "idea one", "description": "an app for community gardens"},
        {"title": "idea two", "description": "a tool for bike repair shops"},
    ]))
    report = run_sycophancy(dataset, n=2, seed=1)
    assert report["n_ideas"] == 2
    assert report["formulation_bias_global"] == 0.0
    assert all(b == 0.0 for b in report["formulation_bias_per_agent"].values())
    assert (sandbox / "evaluations" / "sycophancy_results.json").exists()


def test_bias_detected_when_tone_moves_scores(mock_llm, sandbox, monkeypatch):
    from condorium.bench import sycophancy

    dataset = sandbox / "ideas.json"
    dataset.write_text(json.dumps([{"title": "t", "description": "an idea"}]))

    original = mock_llm._committee

    def tone_sensitive(system, user):
        op = original(system, user)
        if isinstance(op.get("score"), int):
            if "REVOLUTIONARY" in user:
                op["score"] = min(10, op["score"] + 2)
            elif "probably taken" in user:
                op["score"] = max(1, op["score"] - 2)
        return op

    monkeypatch.setattr(mock_llm, "_committee", tone_sensitive)
    report = sycophancy.run_sycophancy(dataset, n=1, seed=1)
    assert report["formulation_bias_global"] == 4.0  # +2 vs -2 spread


def test_bench_runs_leave_no_trace_in_history(mock_llm, sandbox):
    from condorium.analytics import traces
    from condorium.bench.run import evaluate_idea_silently

    evaluate_idea_silently("t", "an idea", mode="general")
    assert traces.list_evals() == []
