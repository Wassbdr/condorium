# Pairwise evaluation data

The benchmark compares two items against the same rubric. Each JSONL row has
`id`, `source` (`synthetic` or `iclr`), `split` (`dev` or `test`),
`rubric`, `a` and `b` (each with `title` and `text`), `better` (`a` or
`b`), and `note` (the reason for the label). Evaluators receive the items
and the rubric, not the label or note. Use `dev` to tune the protocol and
leave `test` alone until measurement.

## Synthetic proposals

[`pairs.jsonl`](pairs.jsonl) has 40 pairs across 15 domains (10 dev, 30 test).
The domains do not overlap across splits. Each pair shares a problem and
changes a single substantive sentence. The weaker item contains a defect
such as a missed deadline, an unavailable input, or a measurement that
does not test the goal. Half of each split makes the weaker proposal
longer and more polished without changing its substance.

From an editable install, regenerate the file with the default seed, 42:

```sh
python scripts/build_pairset.py
```

## ICLR decisions

Source: [Yuntian Deng, `yuntian-deng/iclr-decisions`](https://huggingface.co/datasets/yuntian-deng/iclr-decisions),
revision [`881bab41b57b85916ba462758f7be016505f26dc`](https://huggingface.co/datasets/yuntian-deng/iclr-decisions/tree/881bab41b57b85916ba462758f7be016505f26dc).
The dataset does not state an explicit licence, so we do not redistribute
titles or abstracts. [`iclr_pairs.ids.jsonl`](iclr_pairs.ids.jsonl) stores
the conference, zero-based parquet row indices, SHA-256 hashes of titles,
and split and side metadata. ICLR decisions are noisy ground truth, not
proof that one proposal is intrinsically better.

The setup follows the accepted-versus-rejected comparison used by
[Si et al. (2024)](https://arxiv.org/abs/2409.04109). Use TF-IDF cosine on
the abstracts to find the nearest rejected paper for each accepted paper
from the same conference year. Prefer oral and spotlight accepts, break
similarity ties by row index, and skip candidates that would repeat a title.
Seed 42 determines candidate order, orientation and the 6 dev / 12 test split.

```sh
uv pip install duckdb==1.5.0  # parquet reader for this script only
python scripts/fetch_iclr_pairs.py
```

The fetch requires no account. It writes the pinned parquet and the verified
full pairs to the ignored `.cache/` directory. Pass `--select` to repeat
selection on the pinned file and rebuild the identifier manifest.

## Bias variants

`condorium.bench.pairset.build_variants(pairs, seed=42)` generates cases at
benchmark time. Its labels follow the item if the order changes.

| Variant | Dev | Test | Change |
| --- | ---: | ---: | --- |
| Position | 32 | 84 | Run every pair in both orders. |
| Verbosity | 4 | 12 | Pad the weaker item to about twice its original word count with generic framing that adds no facts or numbers. |
| Tone | 4 | 10 | Add enthusiastic, confident framing around the unchanged weaker item. |

Verbosity and tone sample within each split from the combined set; they
retain the original order so each result can be compared with its unmodified
case. No model is used to build the data or variants.

## Rubric

All pairs use [`proposal`](../rubrics/proposal.yaml). A rubric is YAML or
JSON with a `name` and a non-empty `criteria` list. Each criterion has a
unique `name` and a one-line `description`. Use
`condorium.bench.pairset.load_rubric(path)` to validate it.

## Run the benchmark

After fetching the ICLR text, run `make bench-dev` for protocol changes or
`make bench` for the held-out split. For example:

```sh
panel bench pairwise --split dev --seeds 0,1,2 --methods judge,jury,chateval,committee
```

The runner writes per-decision JSON to `benchmarks/results/<split>.json`
and a report to `benchmarks/results.md`. It resumes through request
responses in `benchmarks/cache/` or `CONDORIUM_CACHE`. Set
`CONDORIUM_OFFLINE=1` to reject cache misses. For a live NIM run, set
`NIM_API_KEY` or `NVIDIA_NIM_API_KEY`. Use `--max-calls` to cap live attempts
and keep `CONDORIUM_RPM` at 15 or below when sharing a key. Do not publish
responses that quote unlicensed ICLR text.

The references are the pairwise judge from [MT-Bench](https://arxiv.org/abs/2306.05685),
[PoLL](https://arxiv.org/abs/2404.18796) majority voting across three model
families, and [ChatEval](https://arxiv.org/abs/2308.07201) with four turns.
The judge and jury sample until they meet the committee's token spend
or use three votes if the committee was not run. The jury always includes
its three families. Discrete votes can overshoot the target; per-decision
records include the target and actual usage. ChatEval keeps its four-turn
protocol and is not token-matched. The first judge sample is reported
separately, and its shared Nemotron request with the jury counts only once
against live traffic.
