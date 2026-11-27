# Changelog

## Unreleased / 0.2.0

- Compare two proposals against a YAML or JSON rubric with `panel compare`, or read pairs from JSON Lines with `--batch`. The Python API and the web UI use the same comparison protocol.
- Cache model responses by request and replay them offline with their original token usage.
- Run the pairwise benchmark against a single judge, a jury, and ChatEval. The report includes accuracy, position, verbosity, tone, and token usage.
- Build a seeded evaluation set with synthetic proposals, ICLR pair identifiers, and held-out cases.

## 0.1.0

- Evaluate one idea through blind review, deliberation, and a final verdict.
- Generate and rank ideas in a tournament or replay a recorded run with `panel demo`.
