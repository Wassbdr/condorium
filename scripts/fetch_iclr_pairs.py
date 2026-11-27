"""Resolve the ICLR pair identifiers against the pinned public parquet."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple, TypedDict

import httpx

from condorium.bench.pairset import DEFAULT_RUBRIC, DEFAULT_SEED, Pair, Side, Split, write_jsonl

ROOT = Path(__file__).resolve().parents[1] / "benchmarks/data"
REVISION = "881bab41b57b85916ba462758f7be016505f26dc"
URL = (f"https://huggingface.co/datasets/yuntian-deng/iclr-decisions/resolve/{REVISION}/"
       "data/train-00000-of-00001-476ea511455f6c74.parquet")
USER_AGENT = "condorium-pairset/1.0"
_WORD = re.compile(r"\b[^\W\d_]{2,}\b")
_STOP = set("an and are as at be by for from has have in is it not of on or that the "
            "their this to use was we were which will with".split())
_SPLIT_COUNTS = {"dev": 6, "test": 12}


class Paper(NamedTuple):
    conference: str
    title: str
    abstract: str
    decision: str


class Reference(TypedDict):
    row_index: int
    title_sha256: str


class Identifiers(TypedDict):
    id: str
    split: Split
    conference: str
    a: Reference
    b: Reference
    better: Side


def download_parquet(path: Path) -> None:
    if path.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".partial")
    with httpx.stream("GET", URL, headers={"User-Agent": USER_AGENT},
                      follow_redirects=True, timeout=60) as response:
        response.raise_for_status()
        with partial.open("wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
    partial.replace(path)


def read_papers(path: Path) -> dict[int, Paper]:
    try:
        import duckdb
    except ImportError as exc:
        raise ValueError("Reading parquet requires DuckDB: uv pip install duckdb==1.5.0") from exc
    with duckdb.connect() as connection:
        rows = connection.execute(
            "SELECT file_row_number, conference, title, abstract, decision "
            "FROM read_parquet(?, file_row_number=true)", [str(path)],
        ).fetchall()
    return {index: Paper(conference, title, abstract, decision)
            for index, conference, title, abstract, decision in rows}


def _title_hash(title: str) -> str:
    return hashlib.sha256(title.encode("utf-8")).hexdigest()


def _decision(paper: Paper) -> str:
    return (paper.decision or "").strip().casefold()


def _terms(text: str) -> Counter[str]:
    return Counter(word for word in _WORD.findall(text.casefold()) if word not in _STOP)


def _nearest_reject(papers: dict[int, Paper], accepted: Sequence[int],
                    rejected: Sequence[int]) -> dict[int, int]:
    counts = {i: _terms(papers[i].abstract) for i in (*accepted, *rejected)}
    df: Counter[str] = Counter()
    for terms in counts.values():
        df.update(terms.keys())
    idf = {word: 1 + math.log((1 + len(counts)) / (1 + frequency))
           for word, frequency in df.items()}

    def weights(index: int) -> dict[str, float]:
        raw = {word: (1 + math.log(count)) * idf[word] for word, count in counts[index].items()}
        norm = math.sqrt(sum(value * value for value in raw.values()))
        return {word: value / norm for word, value in raw.items()}

    inverted: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for index in sorted(rejected):
        for word, weight in weights(index).items():
            inverted[word].append((index, weight))

    nearest = {}
    for index in accepted:
        similarities: dict[int, float] = defaultdict(float)
        for word, weight in weights(index).items():
            for reject, reject_weight in inverted.get(word, []):
                similarities[reject] += weight * reject_weight
        if similarities:
            nearest[index] = max(similarities, key=lambda r: (similarities[r], -r))
    return nearest


def select_ids(papers: dict[int, Paper], seed: int = DEFAULT_SEED) -> list[Identifiers]:
    """Prefer oral and spotlight accepts; keep the exact same-year nearest reject."""
    by_year: dict[str, list[int]] = defaultdict(list)
    for index, paper in sorted(papers.items()):
        if paper.conference and paper.title and paper.abstract:
            by_year[paper.conference].append(index)

    nearest: dict[int, int] = {}
    for indices in by_year.values():
        accepted = [i for i in indices if _decision(papers[i]).startswith("accept")]
        rejected = [i for i in indices if _decision(papers[i]).startswith("reject")]
        nearest.update(_nearest_reject(papers, accepted, rejected))

    rng = random.Random(seed)
    candidates = list(nearest)
    rng.shuffle(candidates)
    candidates.sort(key=lambda i: not any(
        track in _decision(papers[i]) for track in ("oral", "spotlight")
    ))
    target = sum(_SPLIT_COUNTS.values())
    chosen: list[tuple[int, int]] = []
    used: set[str] = set()
    for accept in candidates:
        reject = nearest[accept]
        titles = {papers[accept].title.strip().casefold(), papers[reject].title.strip().casefold()}
        if len(titles) != 2 or titles & used:
            continue
        chosen.append((accept, reject))
        used.update(titles)
        if len(chosen) == target:
            break
    if len(chosen) != target:
        raise ValueError(f"Found only {len(chosen)} distinct ICLR pairs; need {target}")

    rng.shuffle(chosen)

    def ref(index: int) -> Reference:
        return {"row_index": index, "title_sha256": _title_hash(papers[index].title)}

    result: list[Identifiers] = []
    for i, (accept, reject) in enumerate(chosen):
        split: Split = "dev" if i < _SPLIT_COUNTS["dev"] else "test"
        better: Side = rng.choice(("a", "b"))
        result.append({
            "id": f"iclr-{i + 1:02d}", "split": split, "conference": papers[accept].conference,
            "a": ref(accept if better == "a" else reject),
            "b": ref(accept if better == "b" else reject), "better": better,
        })
    return result


def read_ids(path: Path) -> list[Identifiers]:
    ids: list[Identifiers] = []
    seen_ids, seen_rows, seen_hashes = set(), set(), set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        at = f"{path}:{line_no}"
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{at}: invalid JSON: {exc.msg}") from exc
        if not isinstance(item, dict) or item.keys() != {"id", "split", "conference", "a", "b",
                                                          "better"}:
            raise ValueError(f"{at}: expected id, split, conference, a, b and better")
        if not isinstance(item["id"], str) or not item["id"] or item["id"] in seen_ids:
            raise ValueError(f"{at}: id must be non-empty and unique")
        if item["split"] not in ("dev", "test") or item["better"] not in ("a", "b"):
            raise ValueError(f"{at}: split must be dev or test and better must be a or b")
        if not isinstance(item["conference"], str) or not item["conference"].strip():
            raise ValueError(f"{at}: conference must be non-empty")
        for side in ("a", "b"):
            ref = item[side]
            if not isinstance(ref, dict) or ref.keys() != {"row_index", "title_sha256"}:
                raise ValueError(f"{at}: {side} must contain row_index and title_sha256")
            row, digest = ref["row_index"], ref["title_sha256"]
            if type(row) is not int or row < 0 or row in seen_rows:
                raise ValueError(f"{at}: {side}.row_index must be non-negative and unique")
            if (not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
                    or digest in seen_hashes):
                raise ValueError(f"{at}: {side}.title_sha256 must be a unique SHA-256 digest")
            seen_rows.add(row)
            seen_hashes.add(digest)
        seen_ids.add(item["id"])
        ids.append(item)
    if Counter(item["split"] for item in ids) != _SPLIT_COUNTS:
        raise ValueError(f"{path}: expected {_SPLIT_COUNTS['dev']} dev and "
                         f"{_SPLIT_COUNTS['test']} test pairs")
    return ids


def resolve_pairs(ids: Sequence[Identifiers], papers: dict[int, Paper]) -> list[Pair]:
    pairs: list[Pair] = []
    for item in ids:
        sides = {}
        for side, ref in (("a", item["a"]), ("b", item["b"])):
            index = ref["row_index"]
            p = papers.get(index)
            at = f"{item['id']}.{side} (row {index})"
            if not p or p.conference != item["conference"]:
                raise ValueError(f"{at}: row missing or conference mismatch")
            if not p.title or _title_hash(p.title) != ref["title_sha256"]:
                raise ValueError(f"{at}: title SHA-256 mismatch")
            expected = "accept" if side == item["better"] else "reject"
            if not p.abstract or not _decision(p).startswith(expected):
                raise ValueError(f"{at}: missing abstract or expected an {expected} decision")
            sides[side] = {"title": p.title, "text": p.abstract}
        pairs.append({
            "id": item["id"], "source": "iclr", "split": item["split"],
            "rubric": DEFAULT_RUBRIC, "a": sides["a"], "b": sides["b"], "better": item["better"],
            "note": "Accepted versus rejected in the same ICLR year.",
        })
    return pairs


def fetch(ids_path: Path, cache: Path, *, select: bool = False,
          examples: bool = False) -> list[Pair]:
    ids = [] if select else read_ids(ids_path)
    parquet = cache / f"iclr-{REVISION}.parquet"
    download_parquet(parquet)
    papers = read_papers(parquet)
    if select:
        ids = select_ids(papers)
    pairs = resolve_pairs(ids, papers)
    if select:
        write_jsonl(ids_path, ids)
    write_jsonl(cache / "iclr_pairs.jsonl", pairs)
    if examples:
        for item in ids[:2]:
            a, b = papers[item["a"]["row_index"]], papers[item["b"]["row_index"]]
            print(f"{item['conference']}: {a.title} [{a.decision}] | {b.title} [{b.decision}]")
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", type=Path, default=ROOT / "iclr_pairs.ids.jsonl")
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache")
    parser.add_argument("--select", action="store_true", help="Regenerate identifiers from seed 42")
    parser.add_argument("--examples", action="store_true", help="Print two title and decision pairs")
    args = parser.parse_args()
    try:
        pairs = fetch(args.ids, args.cache, select=args.select, examples=args.examples)
    except (OSError, ValueError, httpx.HTTPError) as exc:
        parser.exit(1, f"ICLR fetch failed: {exc}\n")
    print(f"Resolved {len(pairs)} ICLR pairs to {args.cache / 'iclr_pairs.jsonl'}")


if __name__ == "__main__":
    main()
