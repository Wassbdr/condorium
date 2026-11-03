"""Resource resolution: prompts and fixtures are found even when the working
directory has no agents/ (pip/uvx install, run from anywhere)."""

from condorium.config import SETTINGS
from condorium.prompts import committee_prompts


def test_prompts_and_fixtures_resolve_without_local_agents(monkeypatch, tmp_path):
    monkeypatch.setattr(SETTINGS, "root", tmp_path)  # empty dir: no agents/, no fixtures/
    assert (SETTINGS.agents_dir / "committee").is_dir()
    assert SETTINGS.agents_dir != tmp_path / "agents"
    assert sorted(committee_prompts("general")) == [
        "believer", "investor", "judge", "scientist_eval", "skeptic", "strategist"]
    assert list(SETTINGS.fixtures_dir.glob("*.json"))


def test_local_agents_win(sandbox):
    assert SETTINGS.agents_dir == sandbox / "agents"
    assert SETTINGS.agents_editable


def test_init_copies_prompts(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from condorium.cli import app

    monkeypatch.setattr(SETTINGS, "root", tmp_path)
    result = CliRunner().invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "agents" / "committee" / "judge.general.md").is_file()
    again = CliRunner().invoke(app, ["init"])
    assert again.exit_code == 1  # never overwrites


def test_mode_specific_prompt_wins_regardless_of_file_order(monkeypatch, tmp_path):
    committee = tmp_path / "agents" / "committee"
    committee.mkdir(parents=True)
    (committee / "_base.md").write_text("BASE")
    # "x.md" sorts BEFORE "x.zz.md": the generic file is read first
    (committee / "x.md").write_text("---\nname: x\nmodes: [general, zz]\n---\nGENERIC")
    (committee / "x.zz.md").write_text("---\nname: x\n---\nSPECIFIC")
    monkeypatch.setattr(SETTINGS, "root", tmp_path)
    assert committee_prompts("zz")["x"].body == "BASE\n\nSPECIFIC"
    assert committee_prompts("general")["x"].body == "BASE\n\nGENERIC"
