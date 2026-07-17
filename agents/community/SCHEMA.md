# Community agents — add a committee member with zero Python

Drop a single `.md` file in this folder. It is loaded automatically and your
agent sits on the committee like any built-in member: round 1 blind, round 2
deliberation, `influenced_by`, the works.

## File format

```markdown
---
name: my_agent            # snake_case, unique; used in influenced_by, stats, reports
layer: committee          # only "committee" is loaded from this folder
modes: [general, hackathon]   # in which modes your agent sits
timeout: 90               # optional, seconds; raise it if your agent needs long context
criteria:                 # your rubric — EVERY criterion needs an anchor
  - name: my_criterion
    anchors: "3 = ...; 8 = ..."   # what a low and a high score MEAN
---
You are THE <ROLE>. <What you evaluate and how — the prompt body.>

Criteria (1-10):
- my_criterion: <definition and anchors again, in prose>
```

## Rules (enforced by review, and some by the orchestrator)

1. **Anchored rubrics only.** A criterion without anchors ("innovation: 1-10")
   will be rejected. Say what 3 means and what 8 means.
2. **The shared contract is prepended automatically** (`committee/_base.md`):
   strict JSON output, no phrasing bias, round-2 revision rules. Don't
   restate it; don't contradict it.
3. **No lazy rejection, no flattery.** If your agent's whole prompt is "be
   harsh" or "be supportive", it will score poorly on the sycophancy bench
   (`panel bench --sycophancy`) and that's on the README for everyone to see.
4. **Optional placeholders** available in the body: `{constraints}`,
   `{official_criteria}`, `{custom_criteria}`. Unknown `{...}` braces are
   left untouched (JSON examples are safe).
5. **Name collisions**: a community agent may not reuse a built-in name.

Test locally: `panel eval "some idea" --mode general` — your agent appears in
the panel output and in `panel stats` once it has history.
