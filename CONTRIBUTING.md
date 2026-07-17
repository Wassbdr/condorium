# Contributing to condorium

Thanks for stopping by. The design constraint behind every rule here: **the
committee must stay calibrated** — no flattery, no lazy rejection, and every
guardrail measurable.

## Quick start

```bash
git clone https://github.com/Wassbdr/condorium && cd condorium
uv venv && uv pip install -e ".[dev]"
pytest                    # no API key needed — the LLM is fully mocked
panel demo                # no API key needed either
```

## The easiest contribution: a community agent

One markdown file, zero Python. Read [agents/community/SCHEMA.md](agents/community/SCHEMA.md),
drop your file in `agents/community/`, run `panel eval "some idea"` and your
agent sits on the committee. Ground rules:

- **anchored rubrics only** — say what a 3 means and what an 8 means;
- your agent will be measured by `panel bench --sycophancy` like everyone else;
- no "be harsh" / "be nice" personas — those are the two failure modes this
  project exists to kill.

## Good first issues

Labeled [`good first issue`](https://github.com/Wassbdr/condorium/labels/good%20first%20issue). Ideas that are always welcome:

- new `agents/fr/` translations, or a new language pack (`agents/<lang>/`)
- more leak patterns in `src/condorium/bench/antileak.py` (with a test)
- dataset adapters for `scripts/bootstrap_from_dataset.py` (new column aliases)
- example ideas for `examples/` (famous products at their initial stage —
  written WITHOUT hindsight)
- plotly polish in `src/condorium/analytics/viz.py`

## Rules the codebase enforces (don't fight them)

- prompts live in `agents/*.md`, never in Python;
- scores are never averaged in the synthesis; the Believer cap, the Skeptic's
  doubt-with-test rule and the Scientist's citation gate are enforced in
  `src/condorium/graph/evaluation.py` — tests in `tests/test_committee_rules.py`
  must keep passing;
- the Coach never applies a diff without an explicit human yes;
- no external database, no scheduler — everything runs locally on files.

## PR checklist

- [ ] `pytest` green (CI runs it on 3.11 and 3.12, keyless)
- [ ] `ruff check src tests scripts` clean
- [ ] prompt changes: explain the expected effect on the sycophancy bench or
      the winner bench — that's the project's currency
- [ ] agent rubric changes by hand also get a line in `agents/CHANGELOG.md`
