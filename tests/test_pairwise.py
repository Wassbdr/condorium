import json
from pathlib import Path

from typer.testing import CliRunner

from condorium import llm
from condorium.bench import pairset, pairwise
from condorium.bench.pairwise_metrics import metrics
from condorium.cli import app
from condorium.compare import compare, sample_seed

ROOT = Path(__file__).resolve().parents[1]
RUBRIC = pairset.load_rubric(ROOT / "benchmarks/rubrics/proposal.yaml")
A = {"title": "Plan", "text": "Use actual\n data and compare the baseline."}
B = {"title": "Alternative", "text": "Use a simple checklist."}


def _review(preferred, evidence):
    return json.dumps({
        "preferred": preferred, "confidence": 4, "evidence": evidence,
        "scores": {side: {c["name"]: 3 for c in RUBRIC["criteria"]} for side in ("a", "b")},
    })


def test_committee_debates_only_opposing_roles_and_checks_quotes(monkeypatch):
    calls = []

    def completion(*, messages, **_):
        system, user = [m["content"] for m in messages]
        calls.append((system, user))
        llm.record_usage(10, 2)
        if "Other reviewer's verified evidence" in user:
            assert "invented" not in user
            return _review("a", [{"proposal": "a", "quote": "Use actual data"}])
        if "Rubric Judge" in system:
            return _review("a", [{"proposal": "a", "quote": "Use actual  data"}])
        if "Skeptic" in system:
            return _review("b", [{"proposal": "b", "quote": "simple checklist"},
                                 {"proposal": "a", "quote": "invented"}])
        return _review("b", [{"proposal": "b", "quote": "compare the baseline"}])

    monkeypatch.setattr(llm, "_completion", completion)
    result = compare(A, B, RUBRIC)
    assert result.winner == "a"
    assert [r.preferred for r in result.initial] == ["a", "b", None]
    assert [r.role for r in result.debate] == ["judge", "skeptic"]
    assert result.dropped == 2 and result.abstains == 1
    assert result.usage["total_tokens"] == 60
    blind = [user for _, user in calls if "verified evidence" not in user]
    assert len(blind) == 3 and len(set(blind)) == 1
    assert len(calls) == 5


def test_committee_majority_and_all_abstain_do_not_debate(monkeypatch):
    def valid(**_):
        return _review("b", [{"proposal": "b", "quote": "checklist"}])

    monkeypatch.setattr(llm, "_completion", valid)
    result = compare(A, B, RUBRIC)
    assert result.winner == "b" and not result.debate
    monkeypatch.setattr(llm, "_completion", lambda **_: "not JSON")
    result = compare(A, B, RUBRIC)
    assert result.winner == "tie" and not result.debate and result.abstains == 3
    assert all(r.parse_failure == "not JSON" for r in result.initial)


def test_judge_fallback_and_jury_matched_votes(monkeypatch):
    calls = []
    replies = iter(("[[A]]", "[[B]]", "[[C]]", "[[A]]", "[[A]]", "[[B]]", "[[A]]"))

    def complete(**request):
        calls.append(request)
        llm.record_usage(8, 2)
        return next(replies)

    monkeypatch.setattr(llm, "_completion", complete)
    judge = pairwise.run_votes("judge", "proposals", "variant", 2, None)
    assert judge["judge_1call"].winner == "a"
    assert judge["judge"].winner == "tie" and judge["judge"].usage["calls"] == 3
    jury = pairwise.run_votes("jury", "proposals", "variant", 2, 35)["jury"]
    assert jury.winner == "a" and jury.usage["total_tokens"] == 40
    assert [request["model"] for request in calls[3:]] == [
        *pairwise.JURY_MODELS, pairwise.JURY_MODELS[0],
    ]
    assert calls[0]["seed"] == calls[3]["seed"]
    assert calls[0]["temperature"] == 0.7
    assert len({sample_seed(seed, "judge", "variant", 0) for seed in range(3)}) == 3
    assert pairwise.parse_verdict("Reason\n[[b]]") == "b"
    assert pairwise.parse_verdict("[[A]] or [[B]]") is None


def test_chateval_uses_transcript_and_only_final_turns(monkeypatch):
    replies = ("draft [[A]]", "bad format", "final [[B]]", "final [[A]]")
    seen = []

    def complete(*, messages, **_):
        system, user = [m["content"] for m in messages]
        index = len(seen)
        assert ("Critic" if index % 2 == 0 else "Domain Scientist") in system
        transcript = json.loads(user.split("Discussion so far (JSON):\n", 1)[1])
        assert [turn["response"] for turn in transcript] == list(replies[:index])
        seen.append(index)
        return replies[index]

    monkeypatch.setattr(llm, "_completion", complete)
    result = pairwise.run_chateval("proposals", "variant", 0)
    assert result.winner == "tie" and result.usage["calls"] == 4
    assert [failure.raw for failure in result.failures] == ["bad format"]


def test_metrics_resample_pair_units_and_use_matched_controls():
    def row(pair_id, source, kind, order, better, winner, tokens=20):
        return {
            "pair_id": pair_id, "source": source, "seed": 0, "kind": kind, "order": order,
            "better": better, "winner": winner, "method": "committee",
            "usage": {"total_tokens": tokens, "calls": 3}, "debated": kind == "tone",
            "evidence_dropped": 2, "abstains": 1,
        }

    rows = [
        row("x", "synthetic", "position", "ab", "a", "a"),
        row("x", "synthetic", "position", "ba", "b", "a"),
        row("x", "synthetic", "verbosity", "ab", "a", "b", 80),
        row("y", "iclr", "position", "ab", "b", "tie"),
        row("y", "iclr", "position", "ba", "a", "tie"),
        row("y", "iclr", "tone", "ab", "b", "b"),
    ]
    result = metrics(rows)
    assert result == metrics(rows)
    assert result["accuracy"].value == 0.5
    assert result["synthetic"].value == result["iclr"].value == 0.5
    assert result["position_flip"].value == 0.5
    assert (result["position_flip"].lo, result["position_flip"].hi) == (0, 1)
    assert result["slot_a"].value == 0.5
    assert result["verbosity"].value == -1
    assert result["tone"].value == 0.5
    assert result["tokens"].value == 30
    assert result["calls"].value == 3
    assert result["debate"].value == 1 / 6
    assert result["dropped"].value == 2 and result["abstains"].value == 1
    assert metrics([])["accuracy"] is None


def _bench_completion(*, messages, **_):
    system = messages[0]["content"]
    llm.record_usage(10, 5)
    if "confidence" in system and "scores" in system:
        user = messages[1]["content"]
        title = user.split("Proposal A\nTitle: ", 1)[1].splitlines()[0]
        return _review("a", [{"proposal": "a", "quote": title}])
    return "The most relevant constraint points to A. [[A]]"


def test_two_pair_cli_run_replays_all_methods_offline(sandbox, monkeypatch):
    root = sandbox / "benchmarks"
    pairs = pairset.synthetic_pairs()[:2]
    pairset.write_jsonl(root / "data/pairs.jsonl", pairs)
    (root / "rubrics").mkdir()
    (root / "rubrics/proposal.yaml").write_bytes(
        (ROOT / "benchmarks/rubrics/proposal.yaml").read_bytes()
    )
    monkeypatch.setenv("CONDORIUM_CACHE", str(root / "cache"))
    monkeypatch.setattr(llm, "_completion", _bench_completion)
    runner = CliRunner()
    args = ["bench", "pairwise", "--split", "dev", "--seeds", "0", "--limit", "2"]
    warm = runner.invoke(app, args)
    assert warm.exit_code == 0, (warm.output, warm.exception)
    path = root / "results/dev.json"
    live = json.loads(path.read_text())
    assert len(live["decisions"]) == 40 and live["cache_hits"] == 8
    assert live["live_calls"] == live["live_attempts"] == 96
    monkeypatch.setenv("CONDORIUM_OFFLINE", "1")

    def forbidden(**_):
        raise AssertionError("offline replay attempted a live completion")

    monkeypatch.setattr(llm, "_completion", forbidden)
    replay = runner.invoke(app, args + ["--max-calls", "0"])
    assert replay.exit_code == 0, (replay.output, replay.exception)
    offline = json.loads(path.read_text())
    assert live["decisions"] == offline["decisions"]
    assert offline["live_calls"] == offline["live_attempts"] == 0
    assert offline["cache_hits"] == 104
    assert "| committee | pooled |" in (root / "results.md").read_text()


def test_live_cap_is_shared_across_nested_workers_and_partial_results(monkeypatch):
    monkeypatch.setattr(llm, "_completion", _bench_completion)
    result = pairwise.run_pairwise(
        pairset.synthetic_pairs()[:2], RUBRIC, split="dev", seeds=(0,), max_calls=3,
        position_only=True,
    )
    assert result["live_calls"] == result["live_attempts"] == 3
    assert "committee" in result["limited_methods"]


def test_legacy_versus_cli_still_dispatches(mock_llm, tmp_path):
    output = tmp_path / "versus.json"
    result = CliRunner().invoke(app, [
        "bench", "--versus", "--n", "1", "--tone", "0", "--seeds", "0",
        "--dataset", str(ROOT / "fixtures/bench/synthetic_pairs.json"), "--out", str(output),
    ])
    assert result.exit_code == 0, (result.output, result.exception)
    assert json.loads(output.read_text())["summary"]["n_pairs_per_seed"] == [1]
