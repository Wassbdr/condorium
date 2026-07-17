from condorium.knowledge import kgraph, store

ENTRY = {
    "id": "food-map-2025", "hackathon": "CityHack", "date": "2025-03",
    "theme": "civic tech", "duration": "24h", "winning_project": "FoodMap",
    "one_sentence_pitch": "Maps food deserts from open data.",
    "stack": ["python", "mapbox"], "official_criteria": ["impact"],
    "why_it_won": "Live map demo.", "source_url": "https://example.org/foodmap",
    "entities": {"techs": ["python"], "themes": ["civic tech"],
                 "patterns": ["public data twist"], "papers": []},
}

ENTRY2 = {**ENTRY, "id": "noise-map-2025", "winning_project": "NoiseMap",
          "theme": "health",
          "entities": {"techs": ["python"], "themes": ["health"],
                       "patterns": ["public data twist"], "papers": []}}


def test_roundtrip_and_types(sandbox):
    kgraph.ingest_entry(ENTRY)
    g = kgraph.load_graph()
    types = {d["type"] for _, d in g.nodes(data=True)}
    assert types == {"Project", "Hackathon", "Tech", "Theme", "Pattern"}
    edge_types = {d["type"] for _, _, d in g.edges(data=True)}
    assert edge_types == {"WON", "USES", "ABOUT", "EXPLOITS_PATTERN"}


def test_nearest_and_unexploited(sandbox):
    kgraph.ingest_entry(ENTRY)
    kgraph.ingest_entry(ENTRY2)
    g = kgraph.load_graph()
    nearest = kgraph.nearest_projects_to_context(g, ["python"], ["civic tech"], k=2)
    assert nearest[0]["label"] == "FoodMap"  # theme match outranks tech-only
    # python + "public data twist" won in 2 themes, never in "education"
    combos = kgraph.unexploited_combinations(g, "education")
    labels = {c["label"] for c in combos}
    assert {"python", "public data twist"} <= labels


def test_historian_context_empty_base(sandbox):
    ctx = kgraph.historian_context("anything")
    assert ctx["empty"] is True


def test_store_writes_summary(sandbox):
    store.save_winner(ENTRY)
    summary = sandbox / "knowledge" / "summaries" / "food-map-2025.md"
    assert summary.exists()
    assert "FoodMap" in summary.read_text()
    assert len(store.load_winners()) == 1
