"""Web UI logic, keyless: replay of a recorded trace and a live run on the mock LLM."""

from condorium import ui


def test_replay_streams_and_says_it_is_recorded(sandbox):
    traces = ui.recorded_traces()
    assert traces, "bundled demo traces must be found"
    frames = list(ui.replay(next(iter(traces.values())), pause=0))
    assert len(frames) > 10
    assert all("Replay of a recorded run" in f for f in frames)
    assert "Verdict:" in frames[-1] and "No average" in frames[-1]
    assert "median(others' blind scores) + 3" in frames[-1]


def test_live_streams_every_round(mock_llm, sandbox):
    frames = list(ui.live("Compost Courier", "Food scraps to gardens.", "general"))
    assert "Live run" in frames[-1]
    assert "Verdict:" in frames[-1]
    assert frames[-1].count("| ") > 10  # one row per agent
    assert any("round 1" in f.lower() for f in frames)


def test_capped_believer_is_rendered():
    rec = {"idea": {"title": "x"},
           "round1": {"believer": {"score": 10}, "judge": {"score": 4}, "skeptic": {"score": 4}},
           "round2": {"believer": {"score": 7, "uncapped_score": 10, "capped": True}}}
    md = ui.render(rec, ui.REPLAY_NOTE)
    assert "capped to 7" in md and "= **7**" in md
