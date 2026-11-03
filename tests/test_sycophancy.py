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


def test_noise_control_is_subtracted(mock_llm, sandbox, monkeypatch):
    """Scores that wobble between two runs of the SAME neutral text are noise,
    not tone bias."""
    from condorium.bench import sycophancy

    dataset = sandbox / "ideas.json"
    dataset.write_text(json.dumps([{"title": "t", "description": "an idea"}]))
    original = mock_llm._committee
    neutral_seen = []

    def noisy(system, user):
        op = original(system, user)
        if user.startswith("ROUND") and "\nIDEA: base." in user:
            neutral_seen.append(1)
            # the second evaluation of the same neutral text (6 agents x 2
            # rounds later) drifts by 2: pure noise
            if isinstance(op.get("score"), int) and len(neutral_seen) > 12:
                op["score"] = op["score"] + 2
        return op

    monkeypatch.setattr(mock_llm, "_committee", noisy)
    report = sycophancy.run_sycophancy(dataset, n=1, seed=1)
    assert report["noise_global"] == 2.0
    # whichever neutral run is labelled "neutral", the drift is no tone bias
    raw = report["formulation_bias_raw"]
    assert raw in (0.0, 2.0)
    assert report["formulation_bias_global"] == raw - 2.0 <= 0.0
    assert report["directional_global"]["value"] == 0.0


def test_directional_metric_detects_flattery(mock_llm, sandbox, monkeypatch):
    from condorium.bench import sycophancy

    dataset = sandbox / "ideas.json"
    dataset.write_text(json.dumps([{"title": "t", "description": "an idea"}]))
    original = mock_llm._committee

    def flattered(system, user):
        op = original(system, user)
        if "REVOLUTIONARY" in user and isinstance(op.get("score"), int):
            op["score"] = min(10, op["score"] + 3)
        return op

    monkeypatch.setattr(mock_llm, "_committee", flattered)
    report = sycophancy.run_sycophancy(dataset, n=1, seed=1)
    assert report["directional_global"]["value"] == 3.0
    assert all(m["enthusiastic_minus_deprecating"]["value"] == 3.0
               for m in report["per_agent"].values())


def test_non_equivalent_rewrite_rejected(mock_llm, sandbox):
    from condorium.bench.sycophancy import run_sycophancy

    mock_llm.variants_equivalent = False
    dataset = sandbox / "ideas.json"
    dataset.write_text(json.dumps([{"title": "t", "description": "an idea"}]))
    report = run_sycophancy(dataset, n=1, seed=1)
    assert report["n_rejected_variants"] == 1 and report["n_evaluated"] == 0
    assert not any(c["user"].startswith("ROUND") for c in mock_llm.calls)
