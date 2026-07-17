"""Tournament: fan-out, provenance masking, clerk restricted to syntheses."""

from condorium.graph.build import compile_main_graph


def _tournament_state(**kw):
    return {
        "command": "tournament", "mode": "hackathon",
        "sources": ["hackathon", "scientist", "historian"],
        "theme": "civic tech", "duration": "24h", "context": "city data hackathon",
        "n_ideas": 3, "top": 2, "interactive": False, "lang": "en",
        "run_id": "run-tourney", **kw,
    }


def test_tournament_end_to_end(mock_llm, sandbox):
    result = compile_main_graph().invoke(_tournament_state())
    # hackathon generated 3, scientist kept 1 of 2 (citation gate), historian
    # abstained (empty knowledge base) -> 4 ideas, top 2 evaluated
    assert len(result["ideas"]) == 4
    assert len(result["evaluations"]) == 2
    assert len(result["eliminated"]) == 2
    assert all(i["prefilter"]["total"] > 0 for i in result["eliminated"])
    ranking = result["ranking"]["ranking"]
    assert [r["rank"] for r in ranking] == [1, 2]


def test_scientist_citation_gate(mock_llm, sandbox):
    result = compile_main_graph().invoke(_tournament_state(sources=["scientist"], top=1))
    titles = [i["title"] for i in result["ideas"]]
    assert "cited idea" in titles
    assert "uncited idea" not in titles  # rejected: URL not API-retrieved


def test_historian_abstains_on_empty_base(mock_llm, sandbox):
    result = compile_main_graph().invoke(_tournament_state(sources=["historian"], top=1))
    assert result.get("ideas", []) == []
    assert not any("THE HISTORIAN" in c["system"] for c in mock_llm.calls)


def test_provenance_masked_from_committee(mock_llm, sandbox):
    result = compile_main_graph().invoke(_tournament_state())
    committee_calls = [c for c in mock_llm.calls
                       if c["user"].startswith(("ROUND 1", "ROUND 2"))]
    assert committee_calls
    for c in committee_calls:
        assert "provenance" not in c["user"].lower()
        assert "hackathon generator" not in c["user"].lower()
    # ...but revealed in the final run record
    assert set(result["ranking"]) and result["evaluations"]
    provenances = {e["idea"].get("provenance") for e in result["evaluations"]}
    assert provenances <= {"hackathon", "scientist", "historian"}
    assert provenances  # re-attached after evaluation


def test_clerk_sees_syntheses_only(mock_llm, sandbox):
    compile_main_graph().invoke(_tournament_state())
    clerk_calls = [c for c in mock_llm.calls if "THE CLERK" in c["system"]]
    assert len(clerk_calls) == 1
    system = clerk_calls[0]["system"]
    assert '"synthesis"' in system
    # never the raw ideas nor the detailed per-agent evaluations
    assert "gen idea" not in system and "pitch 0" not in system
    assert '"round1"' not in system and '"criteria_scores"' not in system
