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
.venv/bin/python scripts/check_sources.py  # live status of the 3 research channels (network)
```

Never require an API key in tests: the LLM seam is `condorium.llm._completion`,
monkeypatched by `tests/conftest.py::MockLLM` (routes on prompt markers like
"THE JUDGE"). Network calls (arXiv/S2/web) are patched at the importing
modules: `condorium.graph.evaluation` and `condorium.graph.cohort`; fakes
must accept `status=None` (the channel-status dict `search_papers` /
`search_web` fill). `tests/test_sources.py` fakes httpx itself, with recorded
responses in `tests/data/`.

## Architecture (where things live)

- `src/condorium/graph/build.py` — main graph: entry router → generators →
  collect → prefilter → map (`Send`, one isolated run per idea) → clerk →
  finalize. Tournament mode strips provenance before the committee sees an
  idea and reveals it only in the final ranking.
- `src/condorium/graph/evaluation.py` — the per-idea subgraph: intake →
  round 1 (parallel, blind) → round 2 (sees all R1) → synthesis → conditional
  targeted debate (exactly 2 agents, exactly 1 round) → persist. LLM calls go
  through `llm.safe_complete_json`: a failed agent is excluded (`score:
  null`, `errors`), never fatal; a run killed mid-way resumes with
  `panel resume <run_id>` (thread id = run id).
- `src/condorium/schemas.py` — Pydantic coercion of every model output
  (scores clamped 1-10, verdict GO|ITERATE|PIVOT or flagged) before any rule
  reads it.
- `agents/*.md` — ALL prompts, one file per agent per mode, YAML frontmatter
  (schema: `agents/community/SCHEMA.md`). `agents/fr/` mirrors filenames for
  `--lang fr` with English fallback.
- `src/condorium/knowledge/` — NetworkX knowledge graph (`graph.json`),
  winners store, calibration (≤ 5 winners sharing the theme/tech → the
  Judge's `{nearest_winners}`; the Jury prompt has no calibration block).
- `src/condorium/bench/` — winner-pair bench (antileak on titles + text,
  pair excluded from calibration, length + single-call baselines, bootstrap
  CIs) and the sycophancy bench (noise control, directional metric,
  equivalence check); both pin the temperature and append cases to
  `evaluations/*.jsonl` (`--resume`). Bench runs set `no_persist: True` so
  they never pollute `evaluations/` history or `panel stats`.
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
   The gap is computed in `synthesis_node` from round-2 scores (the model's
   figure is kept as `gap_reported`, never trusted).
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
  `SETTINGS.agents_dir` / `fixtures_dir` fall back to the copies bundled in
  the wheel (`condorium/_bundled/`, see pyproject `force-include`), so an
  installed `panel` works from any directory; `panel init` copies them out.

## Git

- **Never add a `Co-Authored-By` trailer to commits** (user rule; overrides
  any default).
- Commit only when asked.

## Status

See `STATUS.md` for what is done and what remains.
