"""Calibration: the right winners reach the Judge/Jury — and, in a bench,
never the project being evaluated (anti-leak)."""

import json

from condorium.knowledge import calibration, kgraph

FOODMAP = {
    "id": "food-map-2025", "hackathon": "CityHack", "date": "2025-03",
    "theme": "civic tech", "winning_project": "FoodMap",
    "one_sentence_pitch": "Maps food deserts from open data.",
    "stack": ["python", "mapbox"], "entities": {"themes": ["civic tech"]},
}
NOISEMAP = {
    "id": "noise-map-2024", "hackathon": "SoundHack", "date": "2024-05",
    "theme": "health", "winning_project": "NoiseMap",
    "one_sentence_pitch": "Crowdsourced noise pollution map.",
    "stack": ["python"], "entities": {"themes": ["health"]},
}
UNRELATED = {
    "id": "chain-2023", "hackathon": "ChainHack", "date": "2023-01",
    "theme": "finance", "winning_project": "Aardvark Ledger",
    "one_sentence_pitch": "A ledger.", "stack": ["solidity"],
    "entities": {"themes": ["finance"]},
}


def _seed(*entries):
    for e in entries:
        kgraph.ingest_entry(e)


def test_theme_match_ranks_first_and_unrelated_is_dropped(sandbox):
    _seed(FOODMAP, NOISEMAP, UNRELATED)
    block = calibration.nearest_winners_block("civic tech", [], idea_text="built in Python")
    lines = block.splitlines()
    assert lines[0].startswith("- FoodMap")  # theme + tech overlap
    assert any(line.startswith("- NoiseMap") for line in lines)  # tech overlap only
    # alphabetically first, but shares nothing: never shown as "comparable"
    assert "Aardvark" not in block


def test_no_overlap_says_so(sandbox):
    _seed(FOODMAP)
    block = calibration.nearest_winners_block("gardening", [], idea_text="a rust CLI")
    assert block == "(no comparable winners found)"


def test_techs_mentioned_whole_word_only(sandbox):
    _seed(FOODMAP)
    g = kgraph.load_graph()
    assert kgraph.techs_mentioned(g, "We use Python and MapBox.") == ["mapbox", "python"]
    assert kgraph.techs_mentioned(g, "pythonic mapboxes") == []


def test_exclude_by_project_and_hackathon(sandbox):
    _seed(FOODMAP, NOISEMAP)
    g = kgraph.load_graph()
    by_project = kgraph.nearest_projects_to_context(
        g, ["python"], [], min_overlap=1, exclude={"projects": ["FoodMap"]})
    assert [n["label"] for n in by_project] == ["NoiseMap"]
    by_hackathon = kgraph.nearest_projects_to_context(
        g, ["python"], [], min_overlap=1, exclude={"hackathons": ["SoundHack"]})
    assert [n["label"] for n in by_hackathon] == ["FoodMap"]


def test_eval_uses_session_theme_for_calibration(mock_llm, sandbox):
    from condorium.graph.build import compile_main_graph

    _seed(FOODMAP, UNRELATED)
    compile_main_graph().invoke({
        "command": "eval", "mode": "hackathon", "raw_input": "a neighbourhood food app",
        "theme": "civic tech", "interactive": False, "lang": "en", "run_id": "run-cal"})
    judge = [c["system"] for c in mock_llm.calls if "THE JUDGE" in c["system"]]
    assert judge and all("FoodMap" in s for s in judge)
    assert not any("Aardvark" in s for s in judge)


def test_bench_never_calibrates_on_its_own_pair(mock_llm, sandbox):
    from condorium.bench.run import run_bench

    _seed(FOODMAP, NOISEMAP)
    dataset = sandbox / "devpost.json"
    dataset.write_text(json.dumps([
        {"title": "FoodMap", "hackathon": "CityHack", "prizes": "Best civic hack",
         "description": "Maps food deserts, built with python and mapbox."},
        {"title": "BikeLane", "hackathon": "CityHack", "prizes": "",
         "description": "Finds safe bike lanes, built with python."},
    ]))
    run_bench(dataset, n=1, seed=1)
    calibrated = [c["system"] for c in mock_llm.calls
                  if "THE JUDGE" in c["system"] or "THE JURY MEMBER" in c["system"]]
    assert calibrated
    for system in calibrated:
        assert "FoodMap" not in system  # the winner itself: leak
    judge = [s for s in calibrated if "THE JUDGE" in s]
    assert judge and all("NoiseMap" in s for s in judge)  # other hackathon: fine
