"""Coach guardrails: >=3 concordant cases, real quoted rule, human-only apply."""

import json
import shutil

import pytest
from conftest import REPO


@pytest.fixture
def coach_sandbox(monkeypatch, tmp_path):
    """Like `sandbox`, but agents/ is a COPY (never a symlink): apply_proposal
    writes into it and must not touch the real prompt files."""
    from condorium.config import SETTINGS

    shutil.copytree(REPO / "agents", tmp_path / "agents")
    (tmp_path / "knowledge").mkdir()
    monkeypatch.setattr(SETTINGS, "root", tmp_path)
    return tmp_path


@pytest.fixture
def coach_llm(monkeypatch, coach_sandbox):
    from condorium import llm

    class CoachMock:
        def __init__(self):
            self.proposals = []

        def __call__(self, *, model, messages, timeout, **kw):
            assert "THE COACH" in messages[0]["content"]
            return json.dumps({"proposals": self.proposals})

    mock = CoachMock()
    monkeypatch.setattr(llm, "_completion", mock)
    return mock


def _seed_bench_errors(root, n=4):
    from condorium.config import SETTINGS

    report = {"cases": [{"case_id": f"bench-{i}", "correct": False} for i in range(n)]}
    (SETTINGS.evaluations_dir / "bench_results.json").write_text(json.dumps(report))


def test_no_proposal_without_enough_error_cases(coach_llm, coach_sandbox):
    from condorium import coach

    _seed_bench_errors(coach_sandbox, n=2)  # below MIN_CASES
    coach_llm.proposals = [{"agent_file": "committee/believer.md",
                            "rule_in_cause": "x", "replacement": "y",
                            "case_ids": ["bench-0", "bench-1"]}]
    assert coach.propose() == []  # never even calls the LLM on thin signal


def test_proposals_validated_in_code(coach_llm, coach_sandbox):
    from condorium import coach

    _seed_bench_errors(coach_sandbox, n=4)
    coach_llm.proposals = [
        {  # valid: 3 cases, rule exists verbatim in the file
            "agent_file": "committee/believer.md",
            "rule_in_cause": "1. GENERIC IDEAS GET NO LOVE.",
            "replacement": "1. GENERIC IDEAS GET TOUGH LOVE.",
            "case_ids": ["bench-0", "bench-1", "bench-2"],
            "metric": "believer over-scored losers by +2.1 avg", "rationale": "r"},
        {  # dropped: only 2 distinct cases
            "agent_file": "committee/believer.md",
            "rule_in_cause": "PRECEDENT REQUIRED.", "replacement": "x",
            "case_ids": ["bench-0", "bench-0", "bench-1"]},
        {  # dropped: quoted rule does not exist in the file
            "agent_file": "committee/skeptic.general.md",
            "rule_in_cause": "THIS LINE IS NOT IN THE FILE", "replacement": "x",
            "case_ids": ["bench-0", "bench-1", "bench-2"]},
    ]
    validated = coach.propose()
    assert len(validated) == 1
    assert validated[0]["diff"].startswith("--- a/agents/committee/believer.md")
    assert "+1. GENERIC IDEAS GET TOUGH LOVE." in validated[0]["diff"]


def test_apply_writes_file_and_changelog(coach_llm, coach_sandbox):
    from condorium import coach

    _seed_bench_errors(coach_sandbox, n=4)
    coach_llm.proposals = [{
        "agent_file": "committee/believer.md",
        "rule_in_cause": "1. GENERIC IDEAS GET NO LOVE.",
        "replacement": "1. GENERIC IDEAS GET TOUGH LOVE.",
        "case_ids": ["bench-0", "bench-1", "bench-2"],
        "metric": "m", "rationale": "r"}]
    proposal = coach.propose()[0]
    coach.apply_proposal(proposal)

    changed = (coach_sandbox / "agents" / "committee" / "believer.md").read_text()
    assert "TOUGH LOVE" in changed
    changelog = (coach_sandbox / "agents" / "CHANGELOG.md").read_text()
    assert "committee/believer.md" in changelog and "bench-0" in changelog
    # the real repo's prompt file is untouched
    assert "TOUGH LOVE" not in (REPO / "agents" / "committee" / "believer.md").read_text()


def test_transient_llm_errors_retried(monkeypatch):
    from condorium import llm

    class RateLimitError(Exception):
        pass

    calls, sleeps = [], []
    monkeypatch.setattr(llm.time, "sleep", sleeps.append)

    def flaky(*, model, messages, timeout, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise RateLimitError("429")
        return '{"ok": true}'

    monkeypatch.setattr(llm, "_completion", flaky)
    assert llm.complete_json("s", "u") == {"ok": True}
    assert len(calls) == 2 and sleeps == [15]  # 429s back off longer than other errors


def test_non_transient_llm_errors_not_retried(monkeypatch):
    from condorium import llm

    class AuthenticationError(Exception):
        pass

    calls = []

    def broken(*, model, messages, timeout, **kw):
        calls.append(1)
        raise AuthenticationError("bad key")

    monkeypatch.setattr(llm, "_completion", broken)
    with pytest.raises(AuthenticationError):
        llm.complete_text("s", "u")
    assert len(calls) == 1
