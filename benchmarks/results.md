# Pairwise benchmark results

Cells show the estimate and a 95% percentile interval from 2,000 pair-bootstrap draws (seed 42). Pooled intervals resample pairs across seeds. Accuracy uses both orders with ties worth half a hit. Verbosity and tone compare the altered item with the same pair in its original order. Slot A counts explicit A picks; a tie is not an A pick. Token totals include cached usage.

## Dev

16 pairs, 40 variants, seeds [0], nvidia_nim/nvidia/nemotron-3.5-super-vl-120b-a12b, temperature 0.7, committee protocol v1, evaluation set v1.
Live calls: 561; live attempts: 561; cache hits: 85.
Parse failures: 35. See the per-decision JSON for raw outputs.

| Method | Seed | Decisions | Accuracy | Synthetic | ICLR | Position flip | Slot A | Verbosity delta | Tone delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| judge_1call | pooled | 40 | 78% [59%, 94%] | 100% [100%, 100%] | 42% [17%, 67%] | 19% [0%, 38%] | 53% [44%, 62%] | +25 pp [+0 pp, +75 pp] | +0 pp [+0 pp, +0 pp] |
| judge_1call | 0 | 40 | 78% [59%, 94%] | 100% [100%, 100%] | 42% [17%, 67%] | 19% [0%, 38%] | 53% [44%, 62%] | +25 pp [+0 pp, +75 pp] | +0 pp [+0 pp, +0 pp] |
| judge | pooled | 40 | 72% [50%, 91%] | 100% [100%, 100%] | 25% [0%, 58%] | 6% [0%, 19%] | 53% [50%, 59%] | +12 pp [+0 pp, +38 pp] | +25 pp [+0 pp, +75 pp] |
| judge | 0 | 40 | 72% [50%, 91%] | 100% [100%, 100%] | 25% [0%, 58%] | 6% [0%, 19%] | 53% [50%, 59%] | +12 pp [+0 pp, +38 pp] | +25 pp [+0 pp, +75 pp] |
| jury | pooled | 40 | 73% [55%, 91%] | 98% [92%, 100%] | 33% [17%, 62%] | 31% [12%, 56%] | 38% [25%, 47%] | +25 pp [+0 pp, +75 pp] | +12 pp [+0 pp, +38 pp] |
| jury | 0 | 40 | 73% [55%, 91%] | 98% [92%, 100%] | 33% [17%, 62%] | 31% [12%, 56%] | 38% [25%, 47%] | +25 pp [+0 pp, +75 pp] | +12 pp [+0 pp, +38 pp] |
| chateval | pooled | 40 | 70% [48%, 89%] | 100% [100%, 100%] | 21% [0%, 46%] | 12% [0%, 31%] | 53% [50%, 59%] | -12 pp [-38 pp, +0 pp] | +12 pp [-38 pp, +75 pp] |
| chateval | 0 | 40 | 70% [48%, 89%] | 100% [100%, 100%] | 21% [0%, 46%] | 12% [0%, 31%] | 53% [50%, 59%] | -12 pp [-38 pp, +0 pp] | +12 pp [-38 pp, +75 pp] |
| committee | pooled | 40 | 77% [58%, 91%] | 100% [100%, 100%] | 38% [25%, 62%] | 31% [12%, 56%] | 47% [41%, 50%] | +0 pp [+0 pp, +0 pp] | +0 pp [+0 pp, +0 pp] |
| committee | 0 | 40 | 77% [58%, 91%] | 100% [100%, 100%] | 38% [25%, 62%] | 31% [12%, 56%] | 47% [41%, 50%] | +0 pp [+0 pp, +0 pp] | +0 pp [+0 pp, +0 pp] |

| Method | Seed | Decisions | Tokens / decision | Calls / decision | Debate rate | Quotes dropped / decision | Abstains / decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| judge_1call | pooled | 40 | 608.9 [507.1, 714.9] | 1.0 [1.0, 1.0] | n/a | n/a | n/a |
| judge_1call | 0 | 40 | 608.9 [507.1, 714.9] | 1.0 [1.0, 1.0] | n/a | n/a | n/a |
| judge | pooled | 40 | 3,093.9 [2,564.3, 3,647.4] | 5.1 [4.9, 5.3] | n/a | n/a | n/a |
| judge | 0 | 40 | 3,093.9 [2,564.3, 3,647.4] | 5.1 [4.9, 5.3] | n/a | n/a | n/a |
| jury | pooled | 40 | 3,135.8 [2,625.5, 3,709.5] | 3.9 [3.6, 4.2] | n/a | n/a | n/a |
| jury | 0 | 40 | 3,135.8 [2,625.5, 3,709.5] | 3.9 [3.6, 4.2] | n/a | n/a | n/a |
| chateval | pooled | 40 | 3,163.8 [2,729.9, 3,621.3] | 4.0 [4.0, 4.0] | n/a | n/a | n/a |
| chateval | 0 | 40 | 3,163.8 [2,729.9, 3,621.3] | 4.0 [4.0, 4.0] | n/a | n/a | n/a |
| committee | pooled | 40 | 2,845.3 [2,366.3, 3,355.7] | 3.1 [3.0, 3.3] | 8% [0%, 16%] | 0.1 [0.0, 0.3] | 0.3 [0.1, 0.5] |
| committee | 0 | 40 | 2,845.3 [2,366.3, 3,355.7] | 3.1 [3.0, 3.3] | 8% [0%, 16%] | 0.1 [0.0, 0.3] | 0.3 [0.1, 0.5] |

## Iterations

### Iteration 0: Baseline: protocol v1, dev split, seed 0

Split: `dev`. Seeds: `0`.

| Method | Metric | Value | Delta vs previous |
| --- | --- | --- | --- |
| committee | Accuracy | 76.56% | n/a |
| committee | Position flip | 31.25% | n/a |
| committee | Tokens / decision | 2,845.3 | n/a |
| judge | Accuracy | 71.88% | n/a |
| judge | Position flip | 6.25% | n/a |
| judge | Tokens / decision | 3,093.9 | n/a |
| jury | Accuracy | 73.44% | n/a |
| jury | Position flip | 31.25% | n/a |
| jury | Tokens / decision | 3,135.8 | n/a |
| chateval | Accuracy | 70.31% | n/a |
| chateval | Position flip | 12.50% | n/a |
| chateval | Tokens / decision | 3,163.8 | n/a |
