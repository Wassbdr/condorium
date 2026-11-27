# Architecture

Condorium uses two LangGraph layers: the Cohort generates ideas, and the
Committee evaluates them. The CLI entry point is `panel`. Run `panel graph`
to export the current graph as Mermaid.

## Execution

- [Main graph](../src/condorium/graph/build.py): route the request, run the
  generators, collect and prefilter ideas, then dispatch one run per idea
  with LangGraph's `Send`. The clerk ranks the results. Tournament mode hides
  provenance from the Committee and reveals it in the final ranking.
- [Evaluation graph](../src/condorium/graph/evaluation.py): intake, blind and
  parallel first-round opinions, second-round opinions with all first-round
  responses visible, synthesis, conditional debate, then persistence.
- [Prompts](../agents/): keep prompts out of Python. Role prompts are Markdown
  files with YAML front matter, one per role and mode. See the
  [prompt schema](../agents/community/SCHEMA.md). French prompts in
  `agents/fr/` mirror the English paths and fall back to English when absent.
- [Knowledge](../src/condorium/knowledge/): a NetworkX graph stored in
  `graph.json` holds past winners. The five nearest winners provide
  calibration examples for the Judge and Jury.
- [Benchmarks](../src/condorium/bench/): winner-pair tests strip victory
  clues before judging; the sycophancy benchmark measures the effect of tone.
  Benchmark evaluations set `no_persist: True`, so they do not enter
  `evaluations/` or contribute to `panel stats`.

## Evaluation invariants

1. The evaluation subgraph state contains exactly one idea.
2. `evaluation.py::_normalize` caps the Believer's second-round score at the
   median of the other first-round scores plus three. The Scientist may cite
   only URLs retrieved for the idea. A neutral scientific verdict gets
   `score: null` and cannot affect a median or ranking. The Skeptic keeps only
   as many objections as it proposes tests.
   [Committee tests](../tests/test_committee_rules.py) exercise these rules.
3. Synthesis and the clerk do not average scores. The clerk reads synthesis
   JSON only.
4. Targeted debate has at most two participants and one round. It runs only
   when synthesis identifies a disagreement with a score gap of at least
   three or marks it critical.
5. The [Coach](../src/condorium/coach.py) requires at least three concordant
   cases for a proposed rubric change. Applying an individual diff requires
   explicit human approval and writes an entry to
   [the rubric changelog](../agents/CHANGELOG.md).
6. The application uses local files, with no external database or internal
   scheduler. A weekly ingest, if configured, is an external cron job that
   runs [`scripts/ingest_winners.py`](../scripts/ingest_winners.py).

## Runtime and tests

User-facing text, CLI verbs and result fields are English. French translations
live only in `agents/fr/`. Result names include `strengths`, `influenced_by`,
scientific verdicts `grounded`, `neutral` and `debunked`, and synthesis
verdicts `GO`, `ITERATE` and `PIVOT`.

All model calls go through LiteLLM. `CONDORIUM_MODEL` selects the model and
defaults to `anthropic/claude-sonnet-4-6`.

`SETTINGS.root` uses `CONDORIUM_HOME` when set, then the working directory if
it contains `agents/committee/`, then the source checkout if it contains
that directory. Otherwise it uses the working directory. Installed packages
can load bundled prompts when the working root has none.

Tests do not need keys. [`tests/conftest.py`](../tests/conftest.py) sets the
working root to a temporary directory with a symlink to `agents/`.
`MockLLM` replaces `condorium.llm._completion` and routes on prompt markers
such as `THE JUDGE`. Tests patch arXiv, Semantic Scholar and web lookups at
their import sites in `condorium.graph.evaluation` and `condorium.graph.cohort`.
