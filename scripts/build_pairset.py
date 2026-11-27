"""Build the synthetic proposal pairs without a model or network access."""

import argparse
from pathlib import Path

from condorium.bench.pairset import DEFAULT_SEED, synthetic_pairs, write_jsonl

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=ROOT / "benchmarks/data/pairs.jsonl")
    args = parser.parse_args()
    pairs = synthetic_pairs(args.seed)
    write_jsonl(args.out, pairs)
    print(f"Wrote {len(pairs)} synthetic pairs to {args.out}")


if __name__ == "__main__":
    main()
