# STATUS — condorium

_Last updated: 2026-07-17 (initial build)._

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
- [x] 31 tests green (fully mocked, keyless), ruff clean,
      `uvx --from . panel demo` verified

## Next up 🔜 (ordered)

1. **Initial commit + GitHub repo** — files are staged, nothing committed yet.
   No `Co-Authored-By` trailer. Then: push, check the CI badge goes green,
   create the `good first issue` labels referenced by CONTRIBUTING.
2. **First live run** (needs a key): `panel eval --file examples/airbnb-2008.md
   --no-interview`, then `panel report <id>`. Watch for: JSON parse retries
   with real models, scientist timeout budget (240s), interviewer loop
   behavior with a real interrupt dialogue.
3. **Real dataset**: download a Devpost dump (e.g. Kaggle/HF
   `devpost-hackathon-projects`), run `panel bootstrap`, then
   `panel bench --dataset ... --n 50 --seed 42` and
   `panel bench --sycophancy --n 20`; paste both result tables into the
   README (they are the project's proof — currently the README describes
   them without numbers).
4. **asciinema GIF** for the top of the README (record `panel demo`).
5. **PyPI publish** — the README's `pip install condorium` claim is not true
   until then; either publish 0.1.0 or soften the claim to the git install.
6. **Test gaps**: add automated tests for the interviewer interrupt dialogue
   and the intake-validation interrupt (the pre-filter interrupt was verified
   manually, not in the suite); a checkpoint-resume test through SqliteSaver.
7. **FR completeness**: `agents/fr/system/` still falls back to English for
   `coach.md`, `sycophancy_rewriter.md`, `ingest.md`.
8. **Examples**: replace the illustrative demo fixtures' committee content
   with real recorded runs once a key is available (fixtures are hand-crafted
   sample output today), and add a real evaluation of the Airbnb 2008 example
   to `examples/`.
9. **Phase 2**: implement `panel population <id>` (6 personas, ≥2 natural
   skeptics, adoption verdicts, global insight) behind the existing stub.
10. **Later / nice to have**: per-node LLM retry-with-backoff policy,
    parallel pre-filter calls (currently sequential), a `panel coach` dry-run
    flag, more antileak patterns from real dataset observations.

## Known limitations

- Demo fixtures and `examples/` evals are illustrative (hand-written in the
  trace schema), not recorded live runs — see Next up #8.
- Web search channel is a keyless DuckDuckGo HTML scrape: best-effort, may
  degrade silently (papers channel alone still satisfies the citation gate).
- `panel bench` cost scales fast: 2 ideas × ~15 LLM calls per pair.
