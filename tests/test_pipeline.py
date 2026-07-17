"""Full mocked evaluation through the main graph, isolation asserted."""

from condorium.analytics import traces
from condorium.config import COMMITTEE_GENERAL, COMMITTEE_HACKATHON
from condorium.graph.build import compile_main_graph, mermaid_diagram


def _eval_state(mode="general", **kw):
    return {
        "command": "eval", "mode": mode, "raw_input": "An app that matches "
        "volunteer developers with local nonprofits for weekend fixes.",
        "interactive": False, "lang": "en", "run_id": "run-test", **kw,
    }


def test_full_general_evaluation(mock_llm):
    result = compile_main_graph().invoke(_eval_state())
    assert len(result["evaluations"]) == 1
    record = traces.load_eval(result["evaluations"][0]["eval_id"])
    assert set(record["round1"]) == set(COMMITTEE_GENERAL)
    assert set(record["round2"]) == set(COMMITTEE_GENERAL)
    assert record["synthesis"]["verdict"] in ("GO", "ITERATE", "PIVOT")
    assert record["intake"]["restatement"]
    for op in record["round2"].values():
        assert "revision" in op and "influenced_by" in op


def test_hackathon_adds_jury(mock_llm):
    result = compile_main_graph().invoke(_eval_state(mode="hackathon", constraints="24h, team of 3"))
    record = result["evaluations"][0]
    assert set(record["round1"]) == set(COMMITTEE_HACKATHON)


def test_round1_is_blind_round2_sees_all(mock_llm):
    compile_main_graph().invoke(_eval_state())
    r1_calls = [c for c in mock_llm.calls if c["user"].startswith("ROUND 1")]
    r2_calls = [c for c in mock_llm.calls if c["user"].startswith("ROUND 2")]
    assert len(r1_calls) == len(COMMITTEE_GENERAL)
    assert len(r2_calls) == len(COMMITTEE_GENERAL)
    for c in r1_calls:
        assert "ROUND 1 OPINIONS" not in c["user"]  # no other agent visible
    for c in r2_calls:
        assert "ROUND 1 OPINIONS" in c["user"]


def test_no_debate_without_major_disagreement(mock_llm):
    compile_main_graph().invoke(_eval_state())
    assert not any("TARGETED DEBATE" in c["system"] for c in mock_llm.calls)


def test_debate_two_agents_one_round(mock_llm):
    mock_llm.synthesis = {
        "consensus": "split", "verdict": "ITERATE", "action": "test it",
        "disagreements": [{"topic": "adoption", "agents": ["believer", "skeptic"],
                           "positions": "b: high; s: low", "why_it_matters": "core bet",
                           "gap": 4, "critical": True}],
    }
    result = compile_main_graph().invoke(_eval_state())
    record = result["evaluations"][0]
    assert sorted(record["debate"]["agents"]) == ["believer", "skeptic"]
    debate_calls = [c for c in mock_llm.calls if "TARGETED DEBATE" in c["system"]]
    assert len(debate_calls) == 2  # exactly two agents, exactly one round
    assert record["synthesis"]["debate_outcome"] == "upheld"


def test_mermaid_export(mock_llm):
    diagram = mermaid_diagram()
    for node in ("prefilter", "evaluate", "clerk", "interviewer"):
        assert node in diagram
