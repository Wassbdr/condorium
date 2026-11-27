import json

import pytest
from typer.testing import CliRunner

from condorium import Rubric, llm
from condorium import compare as compare_items
from condorium.cli import app
from condorium.ui import run_comparison

runner = CliRunner()
RUBRIC = {"name": "Delivery", "criteria": [{"name": "cost", "description": "Check cost."}]}


@pytest.fixture(autouse=True)
def fake_reviews(monkeypatch):
    def complete(*, model, messages, timeout, **kwargs):
        criteria = json.loads(messages[1]["content"].split("Rubric: ", 1)[1].splitlines()[1])
        return json.dumps({
            "preferred": "a", "confidence": 4,
            "scores": {side: {criterion["name"]: 4 for criterion in criteria} for side in ("a", "b")},
            "violations": [],
            "evidence": [{"proposal": "a", "quote": "Reuse existing equipment."},
                         {"proposal": "a", "quote": "A fabricated claim."}],
        })

    monkeypatch.setattr(llm, "_completion", complete)


def test_compare_text_and_files(tmp_path):
    rubric = tmp_path / "rubric.yaml"
    rubric.write_text("name: Delivery\ncriteria:\n  - name: cost\n    description: Check cost.\n")
    a = tmp_path / "small.md"
    a.write_text("Reuse existing equipment.")
    output = runner.invoke(app, ["compare", str(a), "Buy new equipment.", "--rubric", str(rubric)])
    assert output.exit_code == 0, output.output
    assert "Winner: Proposal A" in output.stdout
    assert "Debate: no" in output.stdout
    assert 'Proposal A: "Reuse existing equipment."' in output.stdout
    assert "fabricated" not in output.stdout
    for role in ("scientist", "skeptic", "judge"):
        assert f"{role}: a" in output.stdout


def test_compare_batch_json(tmp_path):
    batch = tmp_path / "pairs.jsonl"
    batch.write_text(json.dumps({"a": "Reuse existing equipment.", "b": "Buy new equipment.",
                                 "id": "pilot"}) + "\n\n")
    output = runner.invoke(app, ["compare", "--batch", str(batch), "--json"])
    assert output.exit_code == 0, output.output
    row = json.loads(output.stdout)
    assert (row["id"], row["winner"], row["debated"]) == ("pilot", "a", False)
    assert row["initial"][0]["evidence"] == [{"proposal": "a", "quote": "Reuse existing equipment."}]


def test_compare_long_inline_text():
    output = runner.invoke(app, ["compare", "Reuse existing equipment. " * 30, "Buy new."])
    assert output.exit_code == 0, output.output
    assert "Winner: Proposal A" in output.stdout


def test_compare_api_and_rubric_formats(tmp_path):
    path = tmp_path / "rubric.json"
    path.write_text(json.dumps(RUBRIC))
    rubric = Rubric.load(path)
    assert rubric == Rubric.from_dict(RUBRIC)
    assert compare_items("Reuse existing equipment.", "Buy new equipment.", rubric).winner == "a"
    with pytest.raises(ValueError, match=r"rubric.criteria\[0\].description"):
        Rubric.from_dict({"name": "Delivery", "criteria": [{"name": "cost"}]})


def test_compare_input_errors(tmp_path):
    batch = tmp_path / "empty.jsonl"
    batch.write_text("\n")
    rubric = tmp_path / "invalid.json"
    rubric.write_text('{"name": "Delivery", "criteria": []}')
    for args, expected in [
        ([], "Supply two item arguments"),
        (["missing.md", "B"], "Use --text to pass literal text"),
        (["--batch", str(batch)], "add at least one JSON pair"),
        (["A", "B", "--rubric", str(rubric)], "rubric.criteria must be a non-empty list"),
    ]:
        output = runner.invoke(app, ["compare", *args])
        assert output.exit_code == 1
        assert expected in output.stderr


def test_compare_authentication_error(monkeypatch):
    class AuthenticationError(RuntimeError):
        pass

    def fail(**kwargs):
        raise AuthenticationError("Example private error details")

    monkeypatch.setattr(llm, "_completion", fail)
    for model, key in [("nvidia_nim/test", "NVIDIA_NIM_API_KEY"), ("openai/test", "OPENAI_API_KEY")]:
        output = runner.invoke(app, ["compare", "A", "B", "--model", model])
        assert output.exit_code == 1
        assert key in output.stderr
        assert "Example private error details" not in output.stderr


def test_compare_offline_miss(monkeypatch, tmp_path):
    monkeypatch.setenv("CONDORIUM_CACHE", str(tmp_path))
    monkeypatch.setenv("CONDORIUM_OFFLINE", "1")
    output = runner.invoke(app, ["compare", "A", "B"])
    assert output.exit_code == 1
    assert "CONDORIUM_OFFLINE" in output.stderr
    assert "NVIDIA_NIM_API_KEY" in output.stderr


def test_compare_ui_callback():
    rubric = json.dumps(RUBRIC)
    assert "Winner: Proposal A" in run_comparison("Reuse existing equipment.", "Buy new.", rubric)
    assert "Item B.text must be non-empty" in run_comparison("Reuse existing equipment.", "", rubric)
    assert "Error: rubric.criteria is required" in run_comparison("A", "B", "name: Delivery")
