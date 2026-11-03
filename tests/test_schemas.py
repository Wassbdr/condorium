"""Model outputs are coerced before any rule reads them, the debate trigger
uses the real score gap, and a failing agent degrades instead of aborting."""

import pytest

from condorium.analytics import traces
from condorium.graph.build import compile_main_graph
from condorium.schemas import (
    coerce_debate_update,
    coerce_opinion,
    coerce_synthesis,
    normalize_verdict,
)
from condorium.state import opinion_scores


def _eval_state(**kw):
    return {"command": "eval", "mode": "general", "raw_input": "a generic AI app",
            "interactive": False, "lang": "en", "run_id": "run-schemas", **kw}


# ------------------------------------------------------------ pure coercion

@pytest.mark.parametrize("raw, score, raw_kept", [
    (7, 7, False), (7.0, 7, False), ("8", 8, True), ("6/10", 6, True),
    (15, 10, True), (0, 1, True), ("n/a", None, True), (None, None, False), (True, None, True),
])
def test_score_coercion(raw, score, raw_kept):
    out = coerce_opinion({"score": raw, "verdict": "v"})
    assert out["score"] == score
    assert ("raw_score" in out) is raw_kept


def test_opinion_lists_and_references_repaired():
    out = coerce_opinion({"score": 5, "watchouts": "one doubt", "proposed_tests": None,
                          "references": ["https://x", {"url": "https://y"}],
                          "scientific_verdict": "Neutral"})
    assert out["watchouts"] == ["one doubt"]
    assert out["proposed_tests"] == []
    assert out["references"] == [{"url": "https://y"}]
    assert out["scientific_verdict"] == "neutral"
    assert "strengths" not in out  # absent fields are not invented
    assert coerce_opinion("plain text")["score"] is None


@pytest.mark.parametrize("raw, verdict", [
    ("GO", "GO"), ("Go.", "GO"), (" iterate ", "ITERATE"), ("PIVOT!", "PIVOT"),
    ("maybe", None), (None, None),
])
def test_verdict_normalized(raw, verdict):
    assert normalize_verdict(raw) == verdict


def test_invalid_synthesis_verdict_flagged():
    out = coerce_synthesis({"verdict": "Strong yes", "disagreements": ["junk", {
        "topic": "t", "agents": ["judge", "skeptic"], "gap": "4", "critical": "true"}]})
    assert out["verdict"] is None and out["verdict_invalid"] is True
    assert out["verdict_raw"] == "Strong yes"
    assert len(out["disagreements"]) == 1
    assert out["disagreements"][0]["gap"] == 4 and out["disagreements"][0]["critical"] is True
    assert coerce_debate_update({"verdict": "go", "verdict_changed": "yes"}) == {
        "verdict": "GO", "verdict_changed": True}


# ------------------------------------------------------- rules in the graph

def test_believer_string_score_still_capped(mock_llm):
    mock_llm.scores = {"judge": 4, "scientist_eval": 4, "skeptic": 4,
                       "investor": 4, "strategist": 4, "believer": 5}
    mock_llm.round2_scores = {"believer": "10"}
    result = compile_main_graph().invoke(_eval_state())
    believer = result["evaluations"][0]["round2"]["believer"]
    assert believer["score"] == 7
    assert believer["capped"] is True


def test_synthesis_verdict_normalized_in_pipeline(mock_llm):
    mock_llm.synthesis = {"consensus": "c", "disagreements": [], "verdict": "Go.",
                          "action": "a"}
    result = compile_main_graph().invoke(_eval_state())
    assert result["evaluations"][0]["synthesis"]["verdict"] == "GO"


def _debated(mock_llm) -> bool:
    return any("TARGETED DEBATE" in c["system"] for c in mock_llm.calls)


def test_reported_gap_ignored_when_real_gap_small(mock_llm):
    mock_llm.scores = {"judge": 6, "skeptic": 5}
    mock_llm.synthesis = {"consensus": "c", "verdict": "ITERATE", "action": "a",
                          "disagreements": [{"topic": "t", "agents": ["judge", "skeptic"],
                                             "gap": 5, "critical": False}]}
    result = compile_main_graph().invoke(_eval_state())
    d = result["evaluations"][0]["synthesis"]["disagreements"][0]
    assert d["gap"] == 1 and d["gap_reported"] == 5
    assert not _debated(mock_llm)


def test_real_gap_triggers_debate_even_if_reported_zero(mock_llm):
    mock_llm.scores = {"judge": 8, "skeptic": 4}
    mock_llm.synthesis = {"consensus": "c", "verdict": "ITERATE", "action": "a",
                          "disagreements": [{"topic": "t", "agents": ["judge", "skeptic"],
                                             "gap": 0, "critical": False}]}
    result = compile_main_graph().invoke(_eval_state())
    assert result["evaluations"][0]["synthesis"]["disagreements"][0]["gap"] == 4
    assert _debated(mock_llm)


def _break_agents(monkeypatch, mock_llm, markers):
    from condorium import llm

    def completion(**kw):
        if any(m in kw["messages"][0]["content"] for m in markers):
            mock_llm.calls.append({"system": kw["messages"][0]["content"],
                                   "user": kw["messages"][-1]["content"], "timeout": 0})
            return "I'd rather chat than output JSON."
        return mock_llm(**kw)

    monkeypatch.setattr(llm, "_completion", completion)


def test_unparseable_agent_is_excluded_not_fatal(mock_llm, monkeypatch):
    _break_agents(monkeypatch, mock_llm, ["THE SKEPTIC"])
    result = compile_main_graph().invoke(_eval_state())
    record = result["evaluations"][0]
    skeptic = record["round2"]["skeptic"]
    assert skeptic["score"] is None and "error" in skeptic
    assert "skeptic" not in opinion_scores(record["round2"])
    assert record["synthesis"]["verdict"] == "ITERATE"  # the rest of the committee delivered
    assert not record["synthesis"].get("degraded")  # 5 scores >= quorum
    assert any("skeptic round 1" in w for w in result["warnings"])
    assert traces.load_eval(record["eval_id"])["errors"]  # persisted in the trace


def test_quorum_lost_flags_degraded(mock_llm, monkeypatch):
    _break_agents(monkeypatch, mock_llm, ["THE SKEPTIC", "THE INVESTOR", "THE STRATEGIST"])
    result = compile_main_graph().invoke(_eval_state())
    assert result["evaluations"][0]["synthesis"]["degraded"] is True


def test_failed_synthesis_degrades(mock_llm, monkeypatch):
    _break_agents(monkeypatch, mock_llm, ["SYNTHESIZER"])
    result = compile_main_graph().invoke(_eval_state())
    syn = result["evaluations"][0]["synthesis"]
    assert syn["verdict"] is None and syn["degraded"] is True


def test_failed_generator_warns(mock_llm, monkeypatch):
    _break_agents(monkeypatch, mock_llm, ["HACKATHON GENERATOR"])
    result = compile_main_graph().invoke({
        "command": "generate", "sources": ["hackathon"], "mode": "hackathon", "top": 1,
        "lang": "en", "run_id": "run-genfail"})
    assert result.get("evaluations", []) == []
    assert any(w.startswith("hackathon generator:") for w in result["warnings"])


def test_temperature_passed_only_when_set(mock_llm, monkeypatch):
    from condorium import llm
    from condorium.config import SETTINGS

    seen = []

    def completion(**kw):
        seen.append(kw.get("temperature", "unset"))
        return "{}"

    monkeypatch.setattr(llm, "_completion", completion)
    llm.complete_json("s", "u")
    monkeypatch.setattr(SETTINGS, "temperature", 0.0)
    llm.complete_json("s", "u")
    assert seen == ["unset", 0.0]
