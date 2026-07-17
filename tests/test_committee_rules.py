"""Code-enforced guardrails: believer cap, neutral score exclusion,
skeptic doubt-without-test rule, scientist reference gate."""

from condorium.graph.build import compile_main_graph
from condorium.state import opinion_scores


def _eval_state():
    return {"command": "eval", "mode": "general", "raw_input": "a generic AI app",
            "interactive": False, "lang": "en", "run_id": "run-rules"}


def test_believer_capped_at_median_plus_3(mock_llm):
    mock_llm.scores = {"judge": 4, "scientist_eval": 4, "skeptic": 4,
                       "investor": 4, "strategist": 4, "believer": 5}
    mock_llm.round2_scores = {"believer": 10}
    result = compile_main_graph().invoke(_eval_state())
    believer = result["evaluations"][0]["round2"]["believer"]
    assert believer["score"] == 7  # median(4) + 3
    assert believer["capped"] is True
    assert believer["uncapped_score"] == 10


def test_believer_not_capped_within_range(mock_llm):
    mock_llm.scores = {"judge": 7, "scientist_eval": 7, "skeptic": 7,
                       "investor": 7, "strategist": 7, "believer": 8}
    result = compile_main_graph().invoke(_eval_state())
    believer = result["evaluations"][0]["round2"]["believer"]
    assert believer["score"] == 8
    assert "capped" not in believer


def test_scientist_neutral_score_null_and_excluded(mock_llm):
    mock_llm.agent_extra = {"scientist_eval": {
        "scientific_verdict": "neutral", "references": []}}
    result = compile_main_graph().invoke(_eval_state())
    record = result["evaluations"][0]
    assert record["round2"]["scientist_eval"]["score"] is None
    assert "scientist_eval" not in opinion_scores(record["round2"])


def test_neutral_scientist_excluded_from_believer_cap(mock_llm):
    # others at 4; a neutral scientist "10" must NOT raise the median
    mock_llm.scores = {"judge": 4, "skeptic": 4, "investor": 4,
                       "strategist": 4, "believer": 5, "scientist_eval": 10}
    mock_llm.agent_extra = {"scientist_eval": {"scientific_verdict": "neutral"}}
    mock_llm.round2_scores = {"believer": 10}
    result = compile_main_graph().invoke(_eval_state())
    assert result["evaluations"][0]["round2"]["believer"]["score"] == 7


def test_skeptic_doubt_without_test_is_deleted(mock_llm):
    mock_llm.agent_extra = {"skeptic": {
        "watchouts": ["doubt A", "doubt B", "doubt C"],
        "proposed_tests": ["test for A"]}}
    result = compile_main_graph().invoke(_eval_state())
    skeptic = result["evaluations"][0]["round2"]["skeptic"]
    assert skeptic["watchouts"] == ["doubt A"]
    assert skeptic["trimmed_doubts_without_test"] == 2


def test_scientist_memory_references_stripped(mock_llm):
    mock_llm.agent_extra = {"scientist_eval": {
        "scientific_verdict": "grounded",
        "references": [
            {"title": "A mock paper on the eye-brain link",
             "url": "https://arxiv.org/abs/0000.00001"},   # retrieved -> kept
            {"title": "from memory", "url": "https://memory.example/paper"},  # dropped
        ]}}
    result = compile_main_graph().invoke(_eval_state())
    refs = result["evaluations"][0]["round2"]["scientist_eval"]["references"]
    assert [r["url"] for r in refs] == ["https://arxiv.org/abs/0000.00001"]
