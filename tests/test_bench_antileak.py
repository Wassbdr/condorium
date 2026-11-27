import json

import pytest

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


FICTITIOUS_PROJECT = (
    "Compost Courier connects restaurants with community gardens: a driver app "
    "batches food-scrap pickups by street and the gardens confirm each delivery "
    "with a photo. {clue} Stack: Flask, a routing API."
)


def test_explicit_winning_clue_is_removed():
    clue = "This project won the Grand Prize ($5,000) at GreenHack 2025."
    dirty = FICTITIOUS_PROJECT.format(clue=clue)
    assert has_leak(dirty)
    clean = strip_victory_clues(dirty)
    assert not has_leak(clean)
    for token in ("won", "Grand Prize", "$5,000", "GreenHack"):
        assert token not in clean
    assert "community gardens" in clean and "routing API" in clean  # substance survives


@pytest.mark.xfail(strict=True, reason=(
    "KNOWN LIMIT: the cleaner is lexical. A paraphrased victory clue with no "
    "keyword ('took home the top honour') survives. Kept as an expected "
    "failure on purpose; strict=True flags it the day the cleaner catches it."))
def test_paraphrased_winning_clue_is_removed():
    clue = "The judges were so impressed that we took home the top honour of the night."
    clean = strip_victory_clues(FICTITIOUS_PROJECT.format(clue=clue))
    assert "top honour" not in clean
    assert "judges were so impressed" not in clean
