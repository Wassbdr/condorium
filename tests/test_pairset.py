import importlib.util
import re
from collections import Counter
from pathlib import Path

import httpx
import pytest

from condorium.bench import pairset

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fetcher():
    spec = importlib.util.spec_from_file_location(
        "fetch_iclr_pairs", ROOT / "scripts/fetch_iclr_pairs.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_synthetic_bytes_and_split_counts(tmp_path):
    first, second = tmp_path / "first.jsonl", tmp_path / "second.jsonl"
    pairs = pairset.synthetic_pairs()
    pairset.write_jsonl(first, pairs)
    pairset.write_jsonl(second, pairset.synthetic_pairs())
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes() == (ROOT / "benchmarks/data/pairs.jsonl").read_bytes()
    assert pairs != pairset.synthetic_pairs(43)
    assert Counter(p["split"] for p in pairs) == {"dev": 10, "test": 30}
    assert len({p["id"] for p in pairs}) == 40
    assert {p["source"] for p in pairs} == {"synthetic"}
    assert {p["rubric"] for p in pairs} == {"proposal"}
    dev = {p["a"]["title"] for p in pairs if p["split"] == "dev"}
    test = {p["a"]["title"] for p in pairs if p["split"] == "test"}
    assert not dev & test and len(dev | test) == 15


def test_synthetic_labels_identify_one_substantive_change():
    hard: Counter[str] = Counter()
    cases = set()
    for pair in pairset.synthetic_pairs():
        good, bad = pair[pair["better"]], pair[pairset.opposite(pair["better"])]
        assert good["title"] == bad["title"]
        code, note = pair["note"].split(": ", 1)
        assert (bad["title"], code) not in cases
        cases.add((bad["title"], code))
        defect = pairset._DEFECTS[code]
        assert defect.note == note
        scenario = next(s for s in pairset._SCENARIOS if s.title == good["title"])
        fields = scenario._asdict()
        good_paragraphs = good["text"].split("\n\n")
        bad_paragraphs = bad["text"].split("\n\n")
        if bad_paragraphs[-1] in pairset._POLISH:
            hard[pair["split"]] += 1
            assert len(bad["text"].split()) > len(good["text"].split())
            bad_paragraphs.pop()
        changes = [(g, b) for g, b in zip(good_paragraphs, bad_paragraphs, strict=True) if g != b]
        assert changes == [(defect.strong.format(**fields), defect.weak.format(**fields))]
    assert hard == {"dev": 5, "test": 15}


def test_variants_are_deterministic_and_leave_ground_truth_unchanged():
    pairs = pairset.synthetic_pairs()
    by_id = {p["id"]: p for p in pairs}
    variants = pairset.build_variants(pairs)
    assert variants == pairset.build_variants(pairs)
    assert Counter((v["kind"], by_id[v["pair_id"]]["split"]) for v in variants) == {
        ("position", "dev"): 20, ("position", "test"): 60,
        ("verbosity", "dev"): 4, ("verbosity", "test"): 12,
        ("tone", "dev"): 4, ("tone", "test"): 10,
    }
    assert pairset.build_variants([]) == []
    for v in variants:
        pair = by_id[v["pair_id"]]
        if v["kind"] == "position":
            if v["order"] == "ba":
                assert (v["a"], v["b"], v["better"]) == (
                    pair["b"], pair["a"], pairset.opposite(pair["better"])
                )
            else:
                assert (v["a"], v["b"], v["better"]) == (pair["a"], pair["b"], pair["better"])
            continue
        better = pair["better"]
        weak = pairset.opposite(better)
        assert v["better"] == better and v[better] == pair[better]
        assert v["order"] == "ab" and v[weak]["title"] == pair[weak]["title"]
        original, altered = pair[weak]["text"], v[weak]["text"]
        assert original in altered
        if v["kind"] == "verbosity":
            assert 1.85 <= len(altered.split()) / len(original.split()) <= 2.15
            assert re.findall(r"\d+", altered) == re.findall(r"\d+", original)
        else:
            before, after = altered.split(original)
            assert (before.strip(), after.strip()) in pairset._TONE


def test_padding_does_not_repeat_numbers_in_original():
    pair = pairset.synthetic_pairs()[0]
    weak = pairset.opposite(pair["better"])
    pair[weak]["text"] += " Allow 30 minutes for each test over 4 shifts."
    [variant] = pairset.verbosity_variants([pair])
    assert re.findall(r"\d+", variant[weak]["text"]) == ["30", "4"]


@pytest.mark.parametrize(("text", "field"), [
    ("name: Proposal\ncriteria: []\n", "criteria"),
    ("name: Proposal\ncriteria: [{name: Feasibility, description: 17}]",
     r"criteria\[0\]\.description"),
    ("name: null\ncriteria: [{name: Evidence, description: Claims}]", "name"),
    ("name: Proposal\ncriteria: [{name: Evidence, description: Claims}, "
     "{name: evidence, description: Sources}]", r"criteria\[1\]\.name"),
])
def test_rubric_invalid_fields_are_named(tmp_path, text, field):
    path = tmp_path / "rubric.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match=field):
        pairset.load_rubric(path)


def test_default_rubric_is_valid():
    rubric = pairset.load_rubric(ROOT / "benchmarks/rubrics/proposal.yaml")
    assert rubric["name"] == "Proposal"
    assert {c["name"] for c in rubric["criteria"]} == {
        "Problem fit", "Feasibility", "Evidence", "Trade-offs",
    }


def test_committed_iclr_ids_are_distinct_and_have_no_paper_text(fetcher):
    ids = fetcher.read_ids(ROOT / "benchmarks/data/iclr_pairs.ids.jsonl")
    assert Counter(row["split"] for row in ids) == {"dev": 6, "test": 12}
    assert len({row["conference"] for row in ids}) >= 2
    assert all(set(row[side]) == {"row_index", "title_sha256"}
               for row in ids for side in ("a", "b"))


def test_iclr_selection_and_fetch_with_mocked_parquet(fetcher, tmp_path, monkeypatch):
    papers = {}
    for i, topic in enumerate("abcdefghijklmnopqrst"):
        conference = "ICLR 2021" if i % 2 else "ICLR 2022"
        text = f"topic{topic} kinetic energy"
        papers[i * 2] = fetcher.Paper(conference, f"Accept {i}", text, "Accept (Spotlight)")
        papers[i * 2 + 1] = fetcher.Paper(conference, f"Reject {i}", text, "Reject")
    ids = fetcher.select_ids(papers)
    assert ids == fetcher.select_ids(papers)
    assert all(abs(row["a"]["row_index"] - row["b"]["row_index"]) == 1 for row in ids)
    ids_path = tmp_path / "ids.jsonl"
    pairset.write_jsonl(ids_path, ids)
    requests = []

    def download(request):
        requests.append(request)
        assert str(request.url) == fetcher.URL and fetcher.REVISION in str(request.url)
        assert request.headers["User-Agent"] == fetcher.USER_AGENT
        return httpx.Response(200, content=b"mock parquet")

    def read(path):
        assert path.read_bytes() == b"mock parquet"
        return papers

    monkeypatch.setattr(fetcher, "read_papers", read)
    cache = tmp_path / "cache"
    with httpx.Client(transport=httpx.MockTransport(download)) as client:
        monkeypatch.setattr(fetcher.httpx, "stream", client.stream)
        pairs = fetcher.fetch(ids_path, cache)
        first = ids[0]
        papers[first["a"]["row_index"]] = fetcher.Paper(first["conference"], "Changed",
                                                       "Abstract", "Reject")
        with pytest.raises(ValueError, match=r"iclr-01\.a.*title SHA-256 mismatch"):
            fetcher.fetch(ids_path, cache)
    assert len(requests) == 1
    assert Counter(p["split"] for p in pairs) == {"dev": 6, "test": 12}
    assert all(p[p["better"]]["title"].startswith("Accept") for p in pairs)
    saved = cache / "iclr_pairs.jsonl"
    assert len(saved.read_text().splitlines()) == 18
    first["a"]["title_sha256"] = "invalid"
    pairset.write_jsonl(ids_path, ids)
    with pytest.raises(ValueError, match=r"a\.title_sha256"):
        fetcher.read_ids(ids_path)


def test_reject_match_stays_in_year_and_prefers_most_similar(fetcher):
    papers = {
        0: fetcher.Paper("2021", "Accepted", "protein folding protein", "Accept (Oral)"),
        1: fetcher.Paper("2021", "Less similar", "protein language", "Reject"),
        2: fetcher.Paper("2021", "Nearest", "protein folding", "Reject"),
        3: fetcher.Paper("2022", "Other year", "protein folding protein", "Reject"),
    }
    assert fetcher._nearest_reject(papers, [0], [1, 2]) == {0: 2}
    with pytest.raises(ValueError, match="only 1 distinct ICLR pairs"):
        fetcher.select_ids(papers)
