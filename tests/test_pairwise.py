import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from condorium import llm
from condorium.bench import pairset, pairwise
from condorium.bench.pairwise_metrics import metrics, render_results, write_results
from condorium.cli import app
from condorium.compare import (
    Requirement,
    RequirementCache,
    _committee_input,
    _normalize,
    _order_key,
    compare,
    proposal_input,
    sample_seed,
)

ROOT = Path(__file__).resolve().parents[1]
RUBRIC = pairset.load_rubric(ROOT / "benchmarks/rubrics/proposal.yaml")
A = {"title": "Plan", "text": "Use actual\n data and compare the baseline."}
B = {"title": "Alternative", "text": "Use a simple checklist."}


def _review(preferred, evidence, checks=()):
    return json.dumps({
        "preferred": preferred, "confidence": 4, "evidence": evidence, "checks": checks,
        "scores": {side: {c["name"]: 3 for c in RUBRIC["criteria"]} for side in ("a", "b")},
    })


def _typed_requirement(quote, kind="rule", limit=None, unit=""):
    return {"quote": quote, "kind": kind, "limit": limit, "unit": unit}


def _fixture_slots(user):
    first = f"Title: {A['title']}\n" in user.split("Proposal B\n", 1)[0]
    if "Other reviewer's verified evidence" in user:
        first = f"Proposal A: {A['title']}\n" in user
    return ("a", "b") if first else ("b", "a")


def test_committee_debates_only_opposing_roles_and_checks_quotes(monkeypatch):
    calls = []

    def completion(*, messages, **_):
        system, user = [m["content"] for m in messages]
        calls.append((system, user))
        llm.record_usage(10, 2)
        a, b = _fixture_slots(user)
        if "Other reviewer's verified evidence" in user:
            assert "invented" not in user
            return _review(a, [{"proposal": a, "quote": "Use actual data"}])
        if "Rubric Judge" in system:
            return _review(a, [{"proposal": a, "quote": "Use actual  data"}])
        if "Skeptic" in system:
            return _review(b, [{"proposal": b, "quote": "simple checklist"},
                               {"proposal": a, "quote": "invented"}])
        return _review(b, [{"proposal": b, "quote": "compare the baseline"}])

    monkeypatch.setattr(llm, "_completion", completion)
    result = compare(A, B, RUBRIC)
    assert result.winner == "a"
    assert [r.preferred for r in result.initial] == ["a", "b", None]
    assert {r.role for r in result.debate} == {"judge", "skeptic"}
    assert result.dropped == 2 and result.abstains == 1
    assert result.usage["total_tokens"] == 60
    blind = [user for _, user in calls if "verified evidence" not in user]
    assert len(blind) == 3 and len(set(blind)) == 2
    assert len(calls) == 5
    debated = [user for _, user in calls if "verified evidence" in user]
    assert {_fixture_slots(user)[0] for user in debated} == {"a", "b"}


def test_committee_majority_and_all_abstain_do_not_debate(monkeypatch):
    def valid(*, messages, **_):
        _, b = _fixture_slots(messages[1]["content"])
        return _review(b, [{"proposal": b, "quote": "checklist"}])

    monkeypatch.setattr(llm, "_completion", valid)
    result = compare(A, B, RUBRIC)
    assert result.winner == "b" and not result.debate
    monkeypatch.setattr(llm, "_completion", lambda **_: "not JSON")
    result = compare(A, B, RUBRIC)
    assert result.winner == "tie" and not result.debate and result.abstains == 3
    assert all(r.parse_failure == "not JSON" for r in result.initial)


def test_violation_quotes_must_match_requirement_and_cited_proposal():
    shared = "Only aggregate data may leave."
    a = {"title": A["title"], "text": f"{shared} Use actual logs."}
    b = {"title": B["title"], "text": f"{shared} Use totals."}
    valid = [0, "a", 0, "Use actual logs.", ""]
    checks = [valid, [0, "b", 0, valid[3], ""], [1, *valid[1:]], [-1, *valid[1:]], valid, None]
    review = _normalize("judge", _review("a", [{"proposal": "a", "quote": "Use actual logs."}],
                                        checks), a, b, RUBRIC, (Requirement(shared, "rule", None, ""),))
    assert review.preferred == "b"
    assert review.parse_failure is None
    assert review.violations_dropped == 5
    assert [v.requirement_quote for v in review.violations] == [shared]

    both = [0, "b", 0, "Use totals.", ""]
    review = _normalize("judge", _review("a", [{"proposal": "a", "quote": "Use actual logs."}],
                                        [valid, both]), a, b, RUBRIC,
                        (Requirement(shared, "rule", None, ""),))
    assert review.preferred == "a" and len(review.violations) == 2


@pytest.mark.parametrize("extract_reply", [None, "[]", "not JSON"])
def test_requirement_extraction_is_blind_and_shared_across_orders_and_seeds(
    monkeypatch, extract_reply,
):
    brief = "Only share totals. Keep a log. No export. Cap is 5. Minimum 2. Use a lock."
    extracted = [_typed_requirement(q) for q in ("Only share\n totals.", "Not in brief.",
                                                 "Keep a log.", "No export.")]
    extracted += [_typed_requirement("Cap is 5.", "max", 50),
                  _typed_requirement("Cap is 5.", "max", 5),
                  _typed_requirement("Minimum 2.", "min", True),
                  _typed_requirement("Minimum 2.", "min", 2),
                  _typed_requirement("Use a lock."), _typed_requirement("Only share totals.")]
    extraction_requests = []

    def completion(*, messages, seed, **_):
        system, user = [m["content"] for m in messages]
        if "at most five" in system:
            assert "Use actual" not in user and "simple checklist" not in user
            assert user.startswith(f"Brief:\n{brief}")
            extraction_requests.append(seed)
            return json.dumps(extracted) if extract_reply is None else extract_reply
        assert ("Fixed requirements" in user) is (extract_reply is None)
        return _review("a", [{"proposal": "a", "quote": "Only share totals."}])

    monkeypatch.setattr(llm, "_completion", completion)
    cache = RequirementCache()
    first = compare(A, B, RUBRIC, brief=brief, requirement_cache=cache)
    second = compare(B, A, RUBRIC, brief=brief, requirement_cache=cache, seed=9)
    assert first.requirements == second.requirements
    assert first.requirements == (("Only share totals.", "Keep a log.", "No export.", "Cap is 5.",
                                   "Minimum 2.") if extract_reply is None else ())
    assert second.extraction_failure == ("not JSON" if extract_reply == "not JSON" else None)
    assert extraction_requests == [0]


@pytest.mark.parametrize(("agree", "expected"), [(True, "b"), (False, "b")])
def test_committee_violation_veto_and_disagreement_without_debate(
    monkeypatch, agree, expected,
):
    brief = "Use aggregate data only."
    ballots = []

    def completion(*, messages, **_):
        system, user = [m["content"] for m in messages]
        if "at most five" in system:
            return json.dumps([_typed_requirement(brief)])
        assert f"Problem brief:\n{brief}" in user
        ballots.append(user)
        llm.record_usage(10, 3)
        a, b = _fixture_slots(user)
        a_violation = [0, a, 0, "Use actual data", ""]
        b_violation = [0, b, 0, "Use a simple checklist", ""]
        preferred = a if agree else b
        evidence = [{"proposal": a, "quote": "Use actual data"}]
        if "Rubric Judge" in system:
            return _review(preferred, evidence, [a_violation])
        if "Skeptic" in system:
            return _review(preferred, evidence, [a_violation] if agree else [b_violation])
        return _review(preferred, evidence)

    monkeypatch.setattr(llm, "_completion", completion)
    result = compare(A, B, RUBRIC, brief=brief)
    assert result.winner == expected
    assert len(ballots) == 3 and not result.debate
    assert result.violations_kept == 2 and result.violations_dropped == 0


def test_committee_sends_shared_problem_once(monkeypatch):
    shared = "Only share totals."
    a = {"title": A["title"], "text": f"{shared}\n\n{A['text']}"}
    b = {"title": B["title"], "text": f"{shared}\n\n{B['text']}"}

    def completion(*, messages, **_):
        if "at most five" in messages[0]["content"]:
            return "[]"
        user = messages[1]["content"]
        assert user.count(shared) == 1
        assert f"Problem brief:\n{shared}" in user
        slot, _ = _fixture_slots(user)
        return _review(slot, [{"proposal": slot, "quote": shared}])

    monkeypatch.setattr(llm, "_completion", completion)
    assert compare(a, b, RUBRIC).winner == "a"


def test_committee_mirrors_results_and_reuses_identical_requests_when_swapped(monkeypatch):
    brief = "Only share totals."
    requests = {}

    def complete(*, messages, seed, **kwargs):
        requests[seed] = messages, kwargs
        system, user = [m["content"] for m in messages]
        if "at most five" in system:
            return json.dumps([_typed_requirement(brief)])
        a, b = _fixture_slots(user)
        if "Scientist" in system:
            assert a != ("a" if _order_key(A) < _order_key(B) else "b")
        else:
            assert a == ("a" if _order_key(A) < _order_key(B) else "b")
        return json.dumps({
            "preferred": a, "confidence": 4, "scores": {a: [1, 2, 3, 4], b: [4, 3, 2, 1]},
            "evidence": [{"proposal": a, "quote": "Use actual data"}],
            "checks": [[0, a, 0, "Use actual data", ""]],
        })

    monkeypatch.setattr(llm, "_completion", complete)
    forward = compare(A, B, RUBRIC, seed=7, brief=brief)
    captured = requests.copy()
    requests.clear()
    backward = compare(B, A, RUBRIC, seed=7, brief=brief)
    assert len(requests) == 4 and requests == captured
    assert forward.winner == "b" and backward.winner == "a"
    for x, y in zip(forward.initial, backward.initial, strict=True):
        assert x.preferred == "b" and y.preferred == "a"
        assert x.scores["a"] == y.scores["b"] and x.scores["b"] == y.scores["a"]
        assert x.evidence[0].proposal == x.violations[0].proposal == "a"
        assert y.evidence[0].proposal == y.violations[0].proposal == "b"
    monkeypatch.setattr(llm, "_completion",
                        lambda **_: _review("a", [{"proposal": "a", "quote": "Use actual data"}]))
    assert compare(A, A, RUBRIC, model="custom").winner == "tie"


@pytest.mark.parametrize("style", ["end", "middle", "nested"])
def test_committee_recovers_bad_checks_bracket_without_accepting_fabricated_quotes(style):
    evidence = [{"proposal": "a", "quote": "Use actual data"}]
    checks = [[0, "a", 0, "Use actual data", ""], [0, "b", 0, "invented", ""]]
    review = json.loads(_review("a", evidence, checks))
    check_json = json.dumps(checks)
    if style == "middle":
        review = {"checks": checks, **review}
    if style == "nested":
        review = {"scores": review.pop("scores") | review}
    raw = json.dumps(review).replace(check_json, check_json[:-1] + "}", 1)
    result = _normalize("skeptic", raw, A, B, RUBRIC, (Requirement("Hard limit", "rule", None, ""),))
    assert result.parse_failure is None and result.preferred == "b"
    assert len(result.violations) == result.violations_dropped == 1
    assert result.violations[0].proposal_quote == "Use actual data"


def test_committee_recovers_latex_escapes_and_still_checks_evidence_verbatim():
    a = {"title": A["title"], "text": r"Show \boldsymbol{x} \mid t and 10\%."}
    evidence = [{"proposal": "a", "quote": a["text"]},
                {"proposal": "b", "quote": r"Invented \ell_2"}]
    raw = _review("a", evidence).replace("\\\\", "\\")
    result = _normalize("scientist", raw, a, B, RUBRIC)
    assert result.parse_failure is None and result.preferred == "a"
    assert result.dropped == 1 and [e.quote for e in result.evidence] == [a["text"]]


@pytest.mark.parametrize(("ordinal", "requirement", "good", "bad"), [
    (1, ("hard spending limit of $1033", "max", 1033, "USD"), 1022, 1060),
    (2, ("Policy permits disclosure to third parties only as site-wide totals.",), 1, 0),
    (3, ("every one of the 25 selected delivery runs to be checked", "min", 25, "runs"), 33, 22),
    (4, ("hard spending limit of $845", "max", 845, "USD"), 830, 968),
    (5, ("Policy permits disclosure to third parties only as site-wide totals.",), 1, 0),
    (6, ("every one of the 36 selected display cases to be checked", "min", 36, "cases"), 40, 30),
    (7, ("hard spending limit of $899", "max", 899, "USD"), 886, 942),
    (8, ("Policy permits disclosure to third parties only as site-wide totals.",), 1, 0),
])
def test_v4_regression_on_synthetic_dev_failures(monkeypatch, ordinal, requirement, good, bad):
    pairs = [pair for pair in pairset.synthetic_pairs() if pair["split"] == "dev"]
    pair = pairs[ordinal - 1]
    variants = [v for v in pairset.build_variants(pairs) if v["pair_id"] == pair["id"]]
    brief = pair["a"]["text"].split("\n\n", 1)[0]
    better = pair["better"]
    worse = pairset.opposite(better)
    good_quote = pair[better]["text"].split("\n\n")[-2]
    bad_quote = pair[worse]["text"].split("\n\n")[-2]
    typed = _typed_requirement(*requirement)
    seen_extractions = []

    def completion(*, messages, **_):
        system, user = [m["content"] for m in messages]
        if "at most five" in system:
            assert user.startswith(f"Brief:\n{brief}\n")
            assert "Permits ... only" in system
            seen_extractions.append(user)
            return json.dumps([typed])
        assert f"Problem brief:\n{brief}" in user
        assert "Fixed requirements" in user
        good_slot = "a" if good_quote in user.split("Proposal B\n", 1)[0] else "b"
        bad_slot = pairset.opposite(good_slot)
        skeptic = "Skeptic" in system
        judge = "Rubric Judge" in system
        index = typed["quote"] if skeptic and ordinal in (4, 7) else "0"
        if judge and ordinal == 3:
            return "truncated ballot"
        cite = bad_quote.replace("per unit", "per check") if judge and ordinal == 1 else bad_quote
        preferred = (good_slot if skeptic and ordinal == 1 else "tie"
                     if skeptic and ordinal in (4, 7) else bad_slot)
        return _review(preferred, [{"proposal": bad_slot, "quote": cite}], [
            [index, good_slot, str(good) if len(requirement) == 1 else good, good_quote, "violated"],
            [index, bad_slot, str(bad) if len(requirement) == 1 else bad, cite, "met"],
        ])

    monkeypatch.setattr(llm, "_completion", completion)
    cache = RequirementCache()
    for variant in variants:
        reviewed = compare(variant["a"], variant["b"], RUBRIC, brief=brief, requirement_cache=cache)
        assert reviewed.requirements == (typed["quote"],)
        assert reviewed.winner == variant["better"] and not reviewed.debate
        assert reviewed.violations_kept == (2 if ordinal in (1, 3, 4, 7) else 3)
        assert reviewed.violations_dropped == (1 if ordinal == 1 else 2 if ordinal in (4, 7) else 0)
    assert len(seen_extractions) == 1


def test_benchmark_passes_original_brief_to_every_synthetic_variant(monkeypatch):
    pairs = [pair for pair in pairset.synthetic_pairs() if pair["split"] == "dev"]
    expected = {p["id"]: p["a"]["text"].split("\n\n", 1)[0] for p in pairs}
    seen = set()

    def compared(a, b, rubric, *, variant_id, brief, **kwargs):
        pair_id, kind = variant_id.split(":")
        assert brief == expected[pair_id]
        seen.add(kind)
        return compare(a, b, rubric, brief=brief, **kwargs)

    monkeypatch.setattr(pairwise, "compare", compared)
    monkeypatch.setattr(llm, "_completion", _bench_completion)
    result = pairwise.run_pairwise(pairs, {"proposal": RUBRIC}, split="dev", seeds=(0,),
                                   methods=("committee",))
    assert len(result["decisions"]) == 22
    assert seen == {"position", "verbosity", "tone"}


@pytest.mark.parametrize("repeat", [False, True])
def test_committee_recovers_misnested_review_and_checks_evidence(repeat):
    payload = json.loads(_review("a", [{"proposal": "a", "quote": "Use actual data"},
                                      {"proposal": "b", "quote": "invented"}]))
    scores = payload.pop("scores")
    review = json.dumps({"scores": scores | payload})[:-1]
    raw = review + review[:len(review) // 2] if repeat else review
    normalized = _normalize("scientist", raw, A, B, RUBRIC)
    assert normalized.parse_failure is None
    assert normalized.preferred == "a"
    assert [e.quote for e in normalized.evidence] == ["Use actual data"]
    assert normalized.dropped == 1
    assert normalized.scores == scores

    unrelated = review + '{"preferred":"b"'
    assert _normalize("scientist", unrelated, A, B, RUBRIC).parse_failure == unrelated


@pytest.mark.parametrize("fenced", [False, True])
def test_committee_reads_first_complete_review_before_trailing_text(fenced):
    review = _review("a", [{"proposal": "a", "quote": "Use actual data"},
                          {"proposal": "b", "quote": "invented"}])
    leading = f"```json\n{review}\n```" if fenced else review
    raw = leading + "\n\n**Rubric application**\n" + review[:-20]
    result = _normalize("judge", raw, A, B, RUBRIC)
    assert result.parse_failure is None
    assert result.preferred == "a"
    assert [quote.quote for quote in result.evidence] == ["Use actual data"]
    assert result.dropped == 1


def test_committee_does_not_retry_capped_ballots(monkeypatch):
    requests = {}
    truncated = '{"scores":{"a":{"Problem fit":1'
    valid = _review("a", [{"proposal": "a", "quote": "Use actual data"}])

    def completion(*, messages, seed, max_tokens, **_):
        if "Rubric Judge" in messages[0]["content"]:
            requests[max_tokens] = seed
            llm.record_usage(20, max_tokens)
            return truncated
        llm.record_usage(20, max_tokens)
        return valid

    monkeypatch.setattr(llm, "_completion", completion)
    result = compare(A, B, RUBRIC)
    assert result.usage["calls"] == 3 and len(requests) == 1
    assert result.initial[0].parse_failure == truncated


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
    assert pairwise.parse_verdict("[[A]] or [[B]]") == "b"


@pytest.mark.parametrize(("raw", "expected"), [
    ("Preliminary [[A]]. Final [[ b ]].", "b"), ("[[B]] then [[c]]", "tie"),
    ("[[A]] copied twice: [[A]]", "a"), ("", None), ("No final marker.", None),
])
def test_verdict_uses_last_marker(raw, expected):
    assert pairwise.parse_verdict(raw) == expected


@pytest.mark.parametrize(("third_reply", "expected"), [("", "tie"), ("[[A]]", "a")])
def test_jury_requests_kimi_without_thinking_and_counts_invalid_ballots(
    monkeypatch, third_reply, expected,
):
    requests = []
    replies = iter(("[[A]]", "no verdict", third_reply))

    def complete(**request):
        requests.append(request)
        return next(replies)

    monkeypatch.setattr(llm, "_completion", complete)
    jury = pairwise.run_votes("jury", "proposals", "variant", 0, None)["jury"]
    assert jury.winner == expected
    assert [request["max_tokens"] for request in requests] == [384, 384, 768]
    assert requests[-1]["model"] == "nvidia_nim/moonshotai/kimi-k3.1-pro"
    assert requests[-1]["extra_body"] == {"thinking": {"type": "disabled"}}
    missing = ["no verdict", ""] if not third_reply else ["no verdict"]
    assert [f.raw for f in jury.failures] == missing
    assert jury.abstains == len(missing)


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
    if "at most five" in system:
        return "[]"
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
    (root / "iterations.yaml").write_bytes((ROOT / "benchmarks/iterations.yaml").read_bytes())
    monkeypatch.setenv("CONDORIUM_CACHE", str(root / "cache"))
    monkeypatch.setattr(llm, "_completion", _bench_completion)
    runner = CliRunner()
    args = ["bench", "pairwise", "--split", "dev", "--seeds", "0", "--limit", "2"]
    warm = runner.invoke(app, args)
    assert warm.exit_code == 0, (warm.output, warm.exception)
    path = root / "results/dev.json"
    live = json.loads(path.read_text())
    assert len(live["decisions"]) == 40 and live["cache_hits"] >= 14
    assert live["live_calls"] == live["live_attempts"] >= 92
    monkeypatch.setenv("CONDORIUM_OFFLINE", "1")

    def forbidden(**_):
        raise AssertionError("offline replay attempted a live completion")

    monkeypatch.setattr(llm, "_completion", forbidden)
    replay = runner.invoke(app, args + ["--max-calls", "0"])
    assert replay.exit_code == 0, (replay.output, replay.exception)
    offline = json.loads(path.read_text())
    def total_by_method(report):
        return {method: sum(row["usage"]["total_tokens"] for row in report["decisions"]
                            if row["method"] == method) for method in report["methods"]}

    assert total_by_method(live) == total_by_method(offline)
    assert [row["winner"] for row in live["decisions"]] == [
        row["winner"] for row in offline["decisions"]
    ]
    assert offline["live_calls"] == offline["live_attempts"] == 0
    assert offline["cache_hits"] == live["live_calls"] + live["cache_hits"]
    assert "| committee | pooled |" in (root / "results.md").read_text()
    assert "### Iteration 0: Baseline: protocol v1, dev split, seed 0" in (
        root / "results.md"
    ).read_text()


def test_mixed_pair_cli_sends_each_rubric_to_all_methods(sandbox, monkeypatch):
    root = sandbox / "benchmarks"
    synthetic = pairset.synthetic_pairs()[0]
    paper = pairset.Pair(**(pairset.synthetic_pairs()[1] | {
        "id": "iclr-01", "source": "iclr", "rubric": "paper",
    }))
    pairset.write_jsonl(root / "data/pairs.jsonl", [synthetic])
    cached_papers = root / "data/.cache/iclr_pairs.jsonl"
    pairset.write_jsonl(cached_papers, [paper])
    (root / "rubrics").mkdir()
    rubrics = {
        name: pairset.load_rubric(ROOT / f"benchmarks/rubrics/{name}.yaml")
        for name in ("proposal", "paper")
    }
    for name in rubrics:
        (root / f"rubrics/{name}.yaml").write_bytes(
            (ROOT / f"benchmarks/rubrics/{name}.yaml").read_bytes()
        )
    expected = {
        proposal_input(pair[a], pair[b], rubrics[pair["rubric"]]): (pair["rubric"], pair[a]["title"])
        for pair in (synthetic, paper) for a, b in (("a", "b"), ("b", "a"))
    }
    expected_committee = {
        _committee_input(pair[a], pair[b], rubrics[pair["rubric"]], ""):
        (pair["rubric"], pair[a]["title"])
        for pair in (synthetic, paper) for a, b in (("a", "b"), ("b", "a"))
    }
    received = set()

    def completion(*, messages, model, **_):
        system, user = [m["content"] for m in messages]
        if "at most five" in system:
            return "[]"
        is_committee = "confidence" in system and "scores" in system
        prompts = expected_committee if is_committee else expected
        [prompt] = [prompt for prompt in prompts if prompt in user]
        rubric, title = prompts[prompt]
        llm.record_usage(10, 5)
        if is_committee:
            received.add((rubric, "committee"))
            return json.dumps({
                "preferred": "a", "confidence": 4, "violations": [],
                "evidence": [{"proposal": "a", "quote": title}],
                "scores": {side: {c["name"]: 3 for c in rubrics[rubric]["criteria"]}
                           for side in ("a", "b")},
            })
        if "Discussion so far (JSON):" in user:
            received.add((rubric, "chateval"))
        else:
            received.add((rubric, "judge" if model == pairwise.MODEL else "jury"))
        return "[[A]]"

    monkeypatch.setattr(llm, "_completion", completion)
    result = CliRunner().invoke(app, [
        "bench", "pairwise", "--split", "dev", "--seeds", "0", "--limit", "2", "--position-only",
    ])
    assert result.exit_code == 0, (result.output, result.exception)
    assert received == {(name, method) for name in rubrics for method in pairwise.METHODS}
    report = json.loads((root / "results/dev.json").read_text())
    assert report["dataset_version"] == 2
    assert all(not row["failures"] for row in report["decisions"])
    assert {row["source"]: row["rubric"] for row in report["decisions"]} == {
        "synthetic": "proposal", "iclr": "paper",
    }

    pairset.write_jsonl(cached_papers, [paper | {"version": 1, "rubric": "proposal"}])
    with pytest.raises(ValueError, match="out of date.*fetch_iclr_pairs.py"):
        pairwise.load_pairs(root / "data", split="dev", limit=2)


def test_missing_pairwise_rubric_is_reported_before_running():
    with pytest.raises(ValueError, match="Missing pairwise rubrics: proposal"):
        pairwise.run_pairwise(pairset.synthetic_pairs(), {}, split="dev")


def test_results_render_iteration_deltas_only_for_matching_split_and_seeds():
    def entry(index, split, seeds, accuracy, flip, tokens):
        return {"id": index, "change": "Change", "split": split, "seeds": seeds,
                "metrics": {"judge": {"accuracy": accuracy, "position_flip": flip,
                                      "tokens": tokens}}}

    assert "## Iterations" not in render_results([])
    output = render_results([], [
        entry(0, "dev", [0], 0.75, 0.25, 100),
        entry(1, "dev", [0], 0.875, 0.125, 90),
        entry(2, "test", [0], 0.5, 0.5, 95),
        entry(3, "test", [0, 1], 0.75, 0.5, 100),
    ])
    assert "| judge | Accuracy | 87.50% | +12.50 pp |" in output
    assert "| judge | Position flip | 12.50% | -12.50 pp |" in output
    assert "| judge | Tokens / decision | 90.0 | -10.0 |" in output
    assert "| judge | Accuracy | 50.00% | n/a |" in output.split("### Iteration 2:")[1]
    assert "| judge | Accuracy | 75.00% | n/a |" in output.split("### Iteration 3:")[1]


def test_results_reject_malformed_iteration_history(tmp_path):
    path = tmp_path / "iterations.yaml"
    path.write_text("- id: 0\n")
    with pytest.raises(ValueError, match=r"Invalid iteration history in .*iterations\.yaml"):
        write_results({}, tmp_path / "results", iterations_path=path)
    assert not (tmp_path / "results").exists()


def test_live_cap_is_shared_across_nested_workers_and_partial_results(monkeypatch):
    monkeypatch.setattr(llm, "_completion", _bench_completion)
    result = pairwise.run_pairwise(
        pairset.synthetic_pairs()[:2], {"proposal": RUBRIC}, split="dev", seeds=(0,), max_calls=3,
        position_only=True,
    )
    assert result["live_calls"] == result["live_attempts"] == 3
    assert "committee" in result["limited_methods"]


def test_matched_judge_cap_preserves_single_vote(monkeypatch):
    monkeypatch.setattr(llm, "_completion", _bench_completion)
    with llm.call_budget(1):
        decisions = pairwise.run_votes("judge", "proposals", "variant", 0, 100)
    assert set(decisions) == {"judge_1call"}
    assert decisions["judge_1call"].usage["calls"] == 1


def test_new_committee_replays_reference_budget_and_preserves_omitted_rows(monkeypatch, tmp_path):
    monkeypatch.setenv("CONDORIUM_CACHE", str(tmp_path))
    monkeypatch.setattr(llm, "_completion", _bench_completion)
    pairs = pairset.synthetic_pairs()[:1]
    args = (pairs, {"proposal": RUBRIC})
    options = {"split": "dev", "seeds": (0,), "position_only": True}
    old = pairwise.run_pairwise(*args, **options)
    old["committee_protocol"] = "v1"
    changed = []

    def completion(*, messages, **kwargs):
        system = messages[0]["content"]
        if "at most five" in system:
            llm.record_usage(1, 1)
            return "[]"
        assert "confidence" in system and "scores" in system
        changed.append(kwargs["model"])
        llm.record_usage(99, 1)
        return _review("b", [{"proposal": "b", "quote": pairs[0]["b"]["title"]}])

    monkeypatch.setattr(llm, "_completion", completion)
    monkeypatch.setenv("CONDORIUM_CACHE", str(tmp_path / "missing"))
    with pytest.raises(llm.OfflineCacheMiss, match="Incomplete reference cache: judge"):
        pairwise.run_pairwise(*args, **options, previous_report=old, max_calls=0, workers=1)
    monkeypatch.setenv("CONDORIUM_CACHE", str(tmp_path))

    real_input = pairwise.compare

    def fresh_compare(a, b, rubric, **kwargs):
        return real_input(a, b, rubric, **(kwargs | {"brief": "Use the audit log."}))

    monkeypatch.setattr(pairwise, "compare", fresh_compare)
    new = pairwise.run_pairwise(*args, **options, previous_report=old,
                                methods=("judge", "committee"))
    assert new["reference_budget"] == "v1"
    assert len(changed) == 3 and new["live_calls"] == 4
    assert sorted(row["usage"]["total_tokens"] for row in new["decisions"]
                  if row["method"] == "committee") == [300, 302]
    def reference_rows(report):
        return {(row["method"], row["variant_id"]): row for row in report["decisions"]
                if row["method"] != "committee"}

    assert reference_rows(new) == reference_rows(old)


def test_exhausted_rate_limit_preserves_results_and_stops_live_calls(monkeypatch, tmp_path):
    class RateLimitError(Exception):
        status_code = 429

    waits = []

    def limited(**request):
        if "impartial judge" in request["messages"][0]["content"]:
            raise RateLimitError
        return _bench_completion(**request)

    monkeypatch.setattr(llm, "_completion", limited)
    monkeypatch.setattr(llm.time, "sleep", waits.append)
    ledger = tmp_path / "calls.log"
    monkeypatch.setenv("CONDORIUM_CALL_LOG", str(ledger))
    result = pairwise.run_pairwise(
        pairset.synthetic_pairs()[:1], {"proposal": RUBRIC}, split="dev", seeds=(0,), max_calls=80,
        position_only=True, workers=1,
    )
    assert result["rate_limited"]
    assert result["live_calls"] == 4
    assert result["live_attempts"] == 4 + llm.SETTINGS.llm_retries + 1
    assert waits == [min(300, 15 * 2**i) for i in range(llm.SETTINGS.llm_retries)]
    assert [row["method"] for row in result["decisions"]] == ["committee"]
    assert [line for line in ledger.read_text().splitlines() if line.startswith("429")] == [
        f"429 {pairwise.MODEL}"
    ] * (llm.SETTINGS.llm_retries + 1)


def test_pairwise_cli_exits_75_after_saving_rate_limited_report(monkeypatch, tmp_path):
    class RateLimitError(Exception):
        status_code = 429

    def limited(**request):
        raise RateLimitError

    monkeypatch.setenv("CONDORIUM_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(llm, "_completion", limited)
    monkeypatch.setattr(llm.time, "sleep", lambda _: None)
    output = tmp_path / "results"
    result = CliRunner().invoke(app, [
        "bench", "pairwise", "--split", "dev", "--seeds", "0", "--limit", "1",
        "--methods", "judge", "--position-only", "--results-dir", str(output),
    ])
    assert result.exit_code == 75, (result.output, result.exception)
    assert "Saved partial results" in result.stderr
    report = json.loads((output / "dev.json").read_text())
    assert report["rate_limited"] and report["live_calls"] == 0
    assert report["model"] == "nvidia_nim/nvidia/nemotron-3.5-super-vl-120b-a12b"
    assert report["jury_models"] == [
        report["model"], "nvidia_nim/poolside/laguna-xs-2.1", "nvidia_nim/moonshotai/kimi-k3.1-pro",
    ]
    assert "HTTP 429" in (tmp_path / "results.md").read_text()


@pytest.mark.parametrize(("pace", "expected"), [(None, "30"), ("12", "12")])
def test_pairwise_cli_default_pace_respects_override(monkeypatch, tmp_path, pace, expected):
    if pace is None:
        monkeypatch.delenv("CONDORIUM_RPM")
    else:
        monkeypatch.setenv("CONDORIUM_RPM", pace)
    monkeypatch.setenv("CONDORIUM_CACHE", str(tmp_path / "cache"))
    output = CliRunner().invoke(app, [
        "bench", "pairwise", "--split", "dev", "--seeds", "0", "--limit", "1",
        "--methods", "judge", "--max-calls", "0", "--results-dir", str(tmp_path / "results"),
    ])
    assert output.exit_code == 0, output.output
    assert os.environ["CONDORIUM_RPM"] == expected


def test_legacy_versus_cli_still_dispatches(mock_llm, tmp_path):
    output = tmp_path / "versus.json"
    result = CliRunner().invoke(app, [
        "bench", "--versus", "--n", "1", "--tone", "0", "--seeds", "0",
        "--dataset", str(ROOT / "fixtures/bench/synthetic_pairs.json"), "--out", str(output),
    ])
    assert result.exit_code == 0, (result.output, result.exception)
    assert json.loads(output.read_text())["summary"]["n_pairs_per_seed"] == [1]
