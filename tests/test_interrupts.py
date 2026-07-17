"""Interrupt flows and checkpoint economics.

The promise under test: interrupts pause exactly where a human decision is
needed, and resuming NEVER re-pays completed LLM calls (LLM work and
interrupt() live in separate nodes)."""

import sqlite3

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from condorium.analytics import traces
from condorium.graph.build import compile_main_graph


def _drain(app, initial, config, answers):
    """Run the graph, answering interrupts from a scripted handler."""
    seen = []
    result = app.invoke(initial, config)
    while result.get("__interrupt__"):
        payload = result["__interrupt__"][0].value or {}
        seen.append(payload)
        result = app.invoke(Command(resume=answers(payload)), config)
    return result, seen


def test_interviewer_dialogue_and_intake_validation(mock_llm):
    app = compile_main_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "iv-1"}, "recursion_limit": 120}

    def answers(payload):
        kind = payload["type"]
        if kind == "interview_question":
            return f"my answer to: {payload['question']}"
        if kind == "tech_tradeoff":
            assert payload["wow_option"]["risk"] == 7  # both options quantified
            return "mastered tech"
        if kind == "intake_validation":
            edited = dict(payload["intake"])
            edited["restatement"] = "edited by the human"
            return {"intake": edited}
        raise AssertionError(f"unexpected interrupt {kind}")

    result, seen = _drain(app, {
        "command": "eval", "mode": "general", "raw_input": "a vague app idea",
        "interactive": True, "lang": "en", "run_id": "run-iv",
    }, config, answers)

    kinds = [p["type"] for p in seen]
    assert kinds == ["interview_question", "interview_question",
                     "tech_tradeoff", "intake_validation"]
    # the user's answers actually reached the interviewer's later turns
    later_interviews = [c for c in mock_llm.calls
                        if "THE INTERVIEWER" in c["system"] and "my answer to" in c["system"]]
    assert later_interviews
    # the human-edited intake is the one persisted and shown to the committee
    record = traces.load_eval(result["evaluations"][0]["eval_id"])
    assert record["intake"]["restatement"] == "edited by the human"
    r1 = [c for c in mock_llm.calls if c["user"].startswith("ROUND 1")]
    assert all("edited by the human" in c["user"] for c in r1)


def test_interviewer_question_budget_capped_at_5(mock_llm, monkeypatch):
    # a chatty interviewer that always wants one more question
    monkeypatch.setitem(
        mock_llm.__dict__, "always_ask", True)

    def always_ask(system, user):
        if "THE INTERVIEWER" in system:
            return {"action": "ask", "question": "and another thing?"}
        return mock_llm._route_original(system, user)

    mock_llm._route_original = mock_llm._route
    monkeypatch.setattr(mock_llm, "_route", always_ask)

    app = compile_main_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "iv-2"}, "recursion_limit": 120}
    result, seen = _drain(app, {
        "command": "eval", "mode": "general", "raw_input": "idea",
        "interactive": True, "lang": "en", "run_id": "run-iv2",
    }, config, lambda p: "sure")
    assert sum(1 for p in seen if p["type"] == "interview_question") == 5
    assert result["evaluations"]  # falls back to the raw idea and completes


def test_prefilter_threshold_interrupt(mock_llm):
    app = compile_main_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "pf-1"}, "recursion_limit": 120}
    result = app.invoke({
        "command": "tournament", "mode": "hackathon", "sources": ["hackathon"],
        "theme": "civic", "n_ideas": 3, "top": None, "interactive": False,
        "lang": "en", "run_id": "run-pf",
    }, config)
    payload = result["__interrupt__"][0].value
    assert payload["type"] == "prefilter_threshold"
    assert len(payload["ranking"]) == 3 and payload["default"] == 3
    result = app.invoke(Command(resume=2), config)
    assert len(result["evaluations"]) == 2
    assert len(result["eliminated"]) == 1
    assert result["eliminated"][0]["prefilter"]["total"] > 0


def test_resume_does_not_repay_completed_calls(mock_llm, sandbox):
    """A NEW process (new graph, new saver on the same sqlite file) resumes
    the tournament without re-running the generator or the pre-filter."""
    db = sandbox / "ckpt.sqlite"

    def make_app():
        conn = sqlite3.connect(str(db), check_same_thread=False)
        return compile_main_graph(checkpointer=SqliteSaver(conn))

    config = {"configurable": {"thread_id": "resume-1"}, "recursion_limit": 120}
    state = {"command": "tournament", "mode": "hackathon", "sources": ["hackathon"],
             "theme": "civic", "n_ideas": 3, "top": None, "interactive": False,
             "lang": "en", "run_id": "run-resume"}

    first = make_app().invoke(state, config)
    assert first["__interrupt__"][0].value["type"] == "prefilter_threshold"

    def count(marker):
        return sum(1 for c in mock_llm.calls if marker in c["system"])

    gen_before, pf_before = count("HACKATHON GENERATOR"), count("fast pre-filter")
    assert (gen_before, pf_before) == (1, 3)

    # simulate the interrupted-process restart
    result = make_app().invoke(Command(resume=2), config)
    assert len(result["evaluations"]) == 2
    assert count("HACKATHON GENERATOR") == gen_before  # not re-paid
    assert count("fast pre-filter") == pf_before       # not re-paid


def test_intake_llm_not_repaid_on_validation_interrupt(mock_llm):
    """The intake LLM call and the validation interrupt are separate nodes."""
    app = compile_main_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "in-1"}, "recursion_limit": 120}
    result = app.invoke({
        "command": "eval", "mode": "general", "raw_input": "idea",
        "interactive": True, "lang": "en", "run_id": "run-in",
    }, config)
    # drain the interview first
    while result.get("__interrupt__"):
        payload = result["__interrupt__"][0].value
        if payload["type"] == "intake_validation":
            break
        result = app.invoke(Command(resume="ok"), config)

    intake_calls = sum(1 for c in mock_llm.calls if "INTAKE step" in c["system"])
    assert intake_calls == 1
    result = app.invoke(Command(resume={"intake": payload["intake"]}), config)
    assert sum(1 for c in mock_llm.calls if "INTAKE step" in c["system"]) == 1
    assert result["evaluations"]


@pytest.mark.parametrize("lang", ["fr"])
def test_fr_prompts_load_with_english_fallback(sandbox, lang):
    from condorium.prompts import committee_prompts, load_prompt

    agents = committee_prompts("hackathon", lang=lang)
    assert set(agents) == {"judge", "believer", "scientist_eval", "skeptic",
                           "investor", "strategist", "jury"}
    assert "LE JUGE" in agents["judge"].body           # FR variant used
    assert "membre d'un comité" in agents["judge"].body  # FR base prepended
    assert "LE COACH" in load_prompt("system/coach.md", lang=lang).body
    # unknown language pack -> clean English fallback
    assert "THE COACH" in load_prompt("system/coach.md", lang="de").body
