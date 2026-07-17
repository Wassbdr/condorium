# CLAUDE.md — condorium

Two-layer multi-agent idea committee: generators (Cohort) upstream, a
calibrated evaluation panel (Committee) downstream, orchestrated as a
LangGraph StateGraph. CLI entry point is `panel`.

## Commands

```bash
uv venv && uv pip install -e ".[dev]"   # setup
.venv/bin/pytest -q                     # tests — keyless, LLM fully mocked
.venv/bin/ruff check src tests scripts  # lint (must stay clean)
.venv/bin/panel demo                    # keyless smoke test (fixtures replay)
.venv/bin/panel graph                   # export the live Mermaid diagram
```

Never require an API key in tests: the LLM seam is `condorium.llm._completion`,
monkeypatched by `tests/conftest.py::MockLLM` (routes on prompt markers like
"THE JUDGE"). Network calls (arXiv/S2/web) are patched at the importing
modules: `condorium.graph.evaluation` and `condorium.graph.cohort`.

## Architecture (where things live)

- `src/condorium/graph/build.py` — main graph: entry router → generators →
  collect → prefilter → map (`Send`, one isolated run per idea) → clerk →
  finalize. Tournament mode strips provenance before the committee sees an
  idea and reveals it only in the final ranking.
- `src/condorium/graph/evaluation.py` — the per-idea subgraph: intake →
  round 1 (parallel, blind) → round 2 (sees all R1) → synthesis → conditional
  targeted debate (exactly 2 agents, exactly 1 round) → persist.
- `agents/*.md` — ALL prompts, one file per agent per mode, YAML frontmatter
  (schema: `agents/community/SCHEMA.md`). `agents/fr/` mirrors filenames for
  `--lang fr` with English fallback.
- `src/condorium/knowledge/` — NetworkX knowledge graph (`graph.json`),
  winners store, calibration (5 nearest winners → Judge/Jury prompts).
- `src/condorium/bench/` — winner-pair bench (antileak mandatory) and the
  sycophancy bench; bench runs set `no_persist: True` so they never pollute
  `evaluations/` history or `panel stats`.
- `src/condorium/coach.py` — proposes rubric diffs; NEVER applies one itself.

## Hard rules (breaking these breaks the project's positioning)

1. **Prompts never in Python** — always in `agents/*.md`.
2. **Guardrails are enforced in code**, in `evaluation.py::_normalize`:
   Believer cap (median of others' R1 + 3, neutral scientist excluded),
   scientist citation gate (only API-retrieved URLs survive), skeptic
   doubt-without-test trimming, `neutral` verdict → `score: null` excluded
   from every median/ranking. `tests/test_committee_rules.py` guards them.
3. **Never average scores** in synthesis or clerk; the clerk reads synthesis
   JSONs only.
4. **Isolation**: one idea per evaluation-subgraph state, always.
5. Debate node: max 2 agents, max 1 round, only on gap ≥ 3 or critical flag.
6. Coach: ≥ 3 concordant cases per proposal, human yes/no per diff, journal
   in `agents/CHANGELOG.md`.
7. No external DB, no scheduler — local files only (weekly ingest is an
   external cron calling `scripts/ingest_winners.py`).

## Conventions

- Everything user-facing is English (JSON keys `strengths`/`influenced_by`/
  `grounded|neutral|debunked`/`GO|ITERATE|PIVOT`, CLI verbs). French lives
  only in `agents/fr/`.
- Model via LiteLLM only (`CONDORIUM_MODEL`, default
  `anthropic/claude-sonnet-4-6`) — never a hardcoded provider call.
- `SETTINGS.root` resolves via `$CONDORIUM_HOME` → cwd with `agents/` →
  source checkout; tests sandbox it to a tmp dir with a symlinked `agents/`.

## Git

- **Never add a `Co-Authored-By` trailer to commits** (user rule; overrides
  any default).
- Commit only when asked.

## Status

See `STATUS.md` for what is done and what remains.
