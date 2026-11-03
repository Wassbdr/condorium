# STATUS — condorium

_Last updated: 2026-11-03 (repair batch after the full audit)._

## Done ✅

**Core pipeline**
- [x] LangGraph main graph (entry router, 4 generators, collect, pre-filter
      with user-chosen threshold, `Send` map, clerk, finalize) + per-idea
      evaluation subgraph (intake → R1 blind parallel → R2 deliberation →
      synthesis → conditional targeted debate → persist)
- [x] SqliteSaver checkpointing; interrupt/resume verified end-to-end
      (pre-filter threshold interrupt → `Command(resume=2)` → completion)
- [x] `interrupt()` points: interviewer dialogue, tech trade-off, intake
      validation (user ideas), pre-filter threshold, coach diff approval
- [x] Mermaid export (`panel graph`)

**Committee & guardrails (enforced in code, tested)**
- [x] 7 agents (Judge dual-grid, Believer capped, Scientist 3-verdict,
      Skeptic test-required, Investor, Strategist, Jury) + 4 generators
- [x] Believer cap median+3 (neutral scientist excluded from the median)
- [x] Scientist citation gate vs API-retrieved URLs (generation + evaluation)
- [x] `neutral` → `score: null`, excluded from medians and rankings
- [x] Skeptic doubts trimmed to the number of proposed tests
- [x] Tournament provenance masking (revealed only in final ranking)
- [x] Clerk restricted to synthesis JSONs
- [x] Debate hard-limited: 2 agents, 1 round, major disagreement only

**Everything else**
- [x] Prompts in `agents/*.md` (EN) + `agents/fr/` variants + community schema
- [x] arXiv + Semantic Scholar + web clients (`sources/`)
- [x] NetworkX knowledge graph + calibration + `scripts/ingest_winners.py` +
      `scripts/bootstrap_from_dataset.py` (verified on a synthetic dataset)
- [x] Analytics: influence matrix, R1→R2 deltas, agreement, severity;
      self-contained plotly HTML report + dashboard (plotly.js inlined)
- [x] Bench: leak-free winner pairs (seeded, reproducible) + sycophancy bench
      (formulation bias global/per-agent); bench runs excluded from history
- [x] Coach: ≥3-case rule, human-validated unified diffs, CHANGELOG journal
- [x] Pitch pack (`panel pitch`, zero LLM calls), track record (`panel record`),
      population stub (Phase 2 interface)
- [x] CLI complete (typer + rich), `panel demo` keyless with 2 fixtures
- [x] README (hook, Mermaid, guardrail table), CONTRIBUTING, MIT, CI workflow
- [x] Tests green (fully mocked, keyless), ruff clean,
      `uvx --from . panel demo` verified

**Hardening batch (2026-07-17)**
- [x] Initial commit (no Co-Authored-By trailer), GitHub publication, CI badge
- [x] **Replay-safe interrupts**: LLM calls and `interrupt()` split into
      separate nodes everywhere (intake/intake_gate, prefilter/prefilter_gate,
      interviewer as a step→gate graph cycle) — resuming re-pays nothing;
      guarded by `tests/test_interrupts.py::test_resume_does_not_repay_completed_calls`
- [x] Interrupt tests: interviewer dialogue (Q→Q→trade-off→done, 5-question
      hard cap), intake human edit, pre-filter threshold, cross-process
      SqliteSaver resume, FR loading + fallback (42 tests total)
- [x] `agents/fr/system/` complete (coach, sycophancy_rewriter, ingest)
- [x] Transient-error LLM retry with backoff (`CONDORIUM_LLM_RETRIES`, default 2)
- [x] Parallel pre-filter scoring (ThreadPoolExecutor, deterministic ordering)
- [x] `panel coach --dry-run`; coach guardrail tests (≥3 cases, rule must
      exist verbatim, apply writes file + CHANGELOG)
- [x] README install claim fixed (git install until PyPI)

**Repair batch (2026-11-03)** — from the full audit; everything keyless-testable
- [x] Lint: ruff pinned (`==0.17.3`) with an explicit rule set; CI matrix 3.11–3.13
- [x] **Research channels actually work**: arXiv over https (was a silent 301),
      keyword queries (AND, then OR), S2 `S2_API_KEY` + one 429 retry, web =
      Tavily (`TAVILY_API_KEY`) with DuckDuckGo fallback (`uddg` links decoded,
      anti-bot page detected). Every channel reports `ok:N | empty | error | blocked`
      into `research.channels`; empty research is shown, and the scientist
      generator warns instead of silently producing nothing. `scripts/check_sources.py`
- [x] **Calibration fixed**: it was called with (criteria, title) instead of
      (theme, techs) → arbitrary winners. Now theme (`--theme`) + declared tech +
      known techs named in the text; zero-overlap winners are never shown
- [x] **Bench anti-leak**: the pair and every winner of its hackathon are
      excluded from calibration; titles cleaned too
- [x] **Packaging**: prompts + demo fixtures bundled in the wheel
      (`condorium/_bundled/`), `panel init`; CI job runs the built wheel
      outside the repo (`panel demo`, `panel graph`, `panel init`)
- [x] **`panel resume [run_id]`**: lists unfinished runs, resumes interrupts
      and crashes on the same thread without re-paying (tested cross-process)
- [x] **Robust outputs**: `schemas.py` (Pydantic) coerces every model output;
      debate gap computed in code; a failed agent/synthesis/generator/clerk
      degrades (`errors` / `warnings`, quorum flag) instead of aborting;
      `CONDORIUM_TEMPERATURE`
- [x] Coach: outcome parsing fixed ("2nd place" is not a win), proposals
      confined to `agents/committee|community/`; prompt selection order-independent
- [x] **Bench rigor**: bootstrap 95% CIs, ties, per-pair errors, `--resume`
      (jsonl), length + single-call baselines (`agents/system/baseline_judge.md`);
      sycophancy: noise control, directional metric, equivalence check
      (`agents/system/equivalence_check.md`), temperature pinned (103 tests)

## Next up 🔜 (needs a key / external resources)

1. **First live run** (needs a key): `panel eval --file examples/airbnb-2008.md
   --no-interview`, then `panel report <id>`. Watch for: JSON parse retries
   and `errors` in the trace, scientist timeout budget (240s), interviewer
   dialogue with a real model, cost/latency per idea. Set `TAVILY_API_KEY`
   and `S2_API_KEY` first (`python scripts/check_sources.py`).
2. **Real dataset**: download a Devpost dump (e.g. Kaggle/HF
   `devpost-hackathon-projects`), run `panel bootstrap`, then
   `panel bench --dataset ... --n 50 --seed 42` (committee vs both baselines,
   with CIs) and `panel bench --sycophancy --n 20` (net bias + direction);
   paste both tables into the README — they are the project's proof.
3. **Examples/fixtures**: replace the illustrative demo fixtures with real
   recorded runs, add a real evaluation of the Airbnb 2008 example.
4. **asciinema GIF** for the top of the README (record `panel demo`).
5. **PyPI publish 0.1.0** (the wheel is now self-contained), then restore the
   plain `pip install condorium`.
6. **Phase 2**: implement `panel population <id>` (6 personas, ≥2 natural
   skeptics, adoption verdicts, global insight) behind the existing stub.
7. **Later / nice to have**: cost tracking per run (LiteLLM
   `completion_cost`), per-agent model override via frontmatter (cheap model
   for prefilter/intake/baselines), calibration block for the Jury prompt,
   more antileak patterns from real dataset observations, `panel stats --json`.

## Known limitations

- Demo fixtures and `examples/` evals are illustrative (hand-written in the
  trace schema), not recorded live runs — see Next up #3.
- Without `TAVILY_API_KEY` the web channel is a keyless DuckDuckGo scrape that
  is usually answered with an anti-bot page (reported as `ddg:blocked`);
  without `S2_API_KEY` Semantic Scholar often returns 429. arXiv alone still
  satisfies the citation gate.
- `panel bench` cost scales fast: 2 ideas × ~15 LLM calls per pair, plus 2
  single-call baselines; the sycophancy bench runs 4 evaluations per idea.
