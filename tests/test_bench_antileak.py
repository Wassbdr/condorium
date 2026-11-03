import json

from condorium.bench.antileak import has_leak, strip_victory_clues
from condorium.bench.pairs import build_pairs


def test_strips_victory_clues():
    dirty = ("🏆 Winner of the Grand Prize ($10,000)! Our app maps food deserts "
             "using open data.\nSelected by the judges as best overall hack.")
    clean = strip_victory_clues(dirty)
    assert not has_leak(clean)
    assert "food deserts" in clean or "open data" in clean  # substance survives


def test_leak_free_and_same_hackathon_pairs(tmp_path):
    rows = []
    for h in ("HackA", "HackB"):
        rows.append({"title": f"{h} champ", "hackathon": h,
                     "description": f"Winner! First place at {h}. Real substance here.",
                     "prizes": "Grand Prize"})
        rows.append({"title": f"{h} other", "hackathon": h,
                     "description": "A modest project with real substance.", "prizes": ""})
    dataset = tmp_path / "ds.json"
    dataset.write_text(json.dumps(rows))

    pairs = build_pairs(dataset, n=2, seed=42)
    assert len(pairs) == 2
    for pair in pairs:
        roles = sorted(e["role"] for e in pair["entries"])
        assert roles == ["loser", "winner"]
        for entry in pair["entries"]:
            assert not has_leak(entry["text"])


def test_pairs_are_reproducible(tmp_path):
    rows = [{"title": f"p{i}", "hackathon": f"h{i % 3}",
             "description": f"desc {i}", "prizes": "x" if i % 2 else ""}
            for i in range(12)]
    dataset = tmp_path / "ds.json"
    dataset.write_text(json.dumps(rows))
    a = build_pairs(dataset, n=3, seed=7)
    b = build_pairs(dataset, n=3, seed=7)
    assert a == b


def test_titles_cleaned_and_original_kept_aside(tmp_path):
    rows = [{"title": "Grand prize winner FoodMap", "hackathon": "H", "prizes": "1st",
             "description": "Maps food deserts."},
            {"title": "BikeLane", "hackathon": "H", "prizes": "", "description": "Bikes."}]
    dataset = tmp_path / "ds.json"
    dataset.write_text(json.dumps(rows))
    entries = build_pairs(dataset, n=1, seed=1)[0]["entries"]
    winner = next(e for e in entries if e["role"] == "winner")
    assert not has_leak(winner["title"])
    assert winner["original_title"] == "Grand prize winner FoodMap"
