"""`panel resume`: lists unfinished runs and drives them to completion on the
same thread — the CLI's promise that an interrupted run is never lost."""

from typer.testing import CliRunner

from condorium.cli import _compiled_graph, _config, app


def _start_tournament_until_prefilter(run_id: str):
    graph = _compiled_graph()
    result = graph.invoke({
        "command": "tournament", "mode": "hackathon", "sources": ["hackathon"],
        "theme": "civic tech", "n_ideas": 3, "interactive": False, "lang": "en",
        "run_id": run_id}, _config(run_id))
    assert result["__interrupt__"][0].value["type"] == "prefilter_threshold"


def test_resume_lists_then_completes_a_paused_run(mock_llm):
    _start_tournament_until_prefilter("run-paused")
    runner = CliRunner()
    listing = runner.invoke(app, ["resume"])
    assert listing.exit_code == 0, listing.output
    assert "panel resume run-paused" in listing.output

    done = runner.invoke(app, ["resume", "run-paused"], input="1\n")
    assert done.exit_code == 0, done.output
    state = _compiled_graph().get_state(_config("run-paused"))
    assert not state.next
    assert len(state.values["evaluations"]) == 1  # the threshold answer was applied

    again = runner.invoke(app, ["resume", "run-paused"])
    assert "already completed" in again.output
    assert "run-paused" not in runner.invoke(app, ["resume"]).output


def test_resume_unknown_run(mock_llm):
    result = CliRunner().invoke(app, ["resume", "run-nope"])
    assert result.exit_code != 0
