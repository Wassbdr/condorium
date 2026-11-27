# Pairwise benchmark results

Cells show the estimate and a 95% percentile interval from 2,000 pair-bootstrap draws (seed 42). Pooled intervals resample pairs across seeds. Accuracy uses both orders with ties worth half a hit. Verbosity and tone compare the altered item with the same pair in its original order. Slot A counts explicit A picks; a tie is not an A pick. Token totals include cached usage.

## Dev

16 pairs, 38 variants, seeds [0], nvidia_nim/nvidia/nemotron-3.5-super-vl-120b-a12b, temperature 0.7, committee protocol v2.1, evaluation set v2.
Live calls: 15; live attempts: 24; cache hits: 660.
References replay the protocol v1 token targets from the same evaluation set.
Parse failures: 20. See the per-decision JSON for raw outputs.

| Method | Seed | Decisions | Accuracy | Synthetic | ICLR | Position flip | Slot A | Verbosity delta | Tone delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| judge_1call | pooled | 38 | 44% [22%, 66%] | 38% [12%, 69%] | 50% [19%, 81%] | 25% [6%, 44%] | 56% [44%, 69%] | +0 pp [+0 pp, +0 pp] | +0 pp [+0 pp, +0 pp] |
| judge_1call | 0 | 38 | 44% [22%, 66%] | 38% [12%, 69%] | 50% [19%, 81%] | 25% [6%, 44%] | 56% [44%, 69%] | +0 pp [+0 pp, +0 pp] | +0 pp [+0 pp, +0 pp] |
| judge | pooled | 38 | 41% [22%, 62%] | 38% [19%, 62%] | 44% [12%, 75%] | 31% [12%, 56%] | 53% [41%, 66%] | +67 pp [+0 pp, +100 pp] | +0 pp [+0 pp, +0 pp] |
| judge | 0 | 38 | 41% [22%, 62%] | 38% [19%, 62%] | 44% [12%, 75%] | 31% [12%, 56%] | 53% [41%, 66%] | +67 pp [+0 pp, +100 pp] | +0 pp [+0 pp, +0 pp] |
| jury | pooled | 38 | 45% [25%, 67%] | 31% [0%, 62%] | 59% [31%, 88%] | 19% [0%, 38%] | 41% [31%, 50%] | -17 pp [-50 pp, +0 pp] | +67 pp [+0 pp, +100 pp] |
| jury | 0 | 38 | 45% [25%, 67%] | 31% [0%, 62%] | 59% [31%, 88%] | 19% [0%, 38%] | 41% [31%, 50%] | -17 pp [-50 pp, +0 pp] | +67 pp [+0 pp, +100 pp] |
| chateval | pooled | 38 | 56% [34%, 78%] | 56% [25%, 88%] | 56% [31%, 81%] | 25% [6%, 50%] | 50% [38%, 62%] | -33 pp [-100 pp, +0 pp] | +0 pp [+0 pp, +0 pp] |
| chateval | 0 | 38 | 56% [34%, 78%] | 56% [25%, 88%] | 56% [31%, 81%] | 25% [6%, 50%] | 50% [38%, 62%] | -33 pp [-100 pp, +0 pp] | +0 pp [+0 pp, +0 pp] |
| committee | pooled | 38 | 45% [31%, 61%] | 38% [25%, 53%] | 53% [31%, 75%] | 75% [50%, 94%] | 28% [12%, 44%] | +50 pp [+0 pp, +100 pp] | +0 pp [-50 pp, +50 pp] |
| committee | 0 | 38 | 45% [31%, 61%] | 38% [25%, 53%] | 53% [31%, 75%] | 75% [50%, 94%] | 28% [12%, 44%] | +50 pp [+0 pp, +100 pp] | +0 pp [-50 pp, +50 pp] |

| Method | Seed | Decisions | Tokens / decision | Calls / decision | Debate rate | Quotes dropped / decision | Abstains / decision | Violations kept / decision | Violations dropped / decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| judge_1call | pooled | 38 | 704.9 [647.8, 758.6] | 1.0 [1.0, 1.0] | n/a | n/a | n/a | n/a | n/a |
| judge_1call | 0 | 38 | 704.9 [647.8, 758.6] | 1.0 [1.0, 1.0] | n/a | n/a | n/a | n/a | n/a |
| judge | pooled | 38 | 3,831.6 [3,460.0, 4,208.3] | 5.4 [5.1, 5.8] | n/a | n/a | n/a | n/a | n/a |
| judge | 0 | 38 | 3,831.6 [3,460.0, 4,208.3] | 5.4 [5.1, 5.8] | n/a | n/a | n/a | n/a | n/a |
| jury | pooled | 38 | 3,903.7 [3,526.3, 4,280.2] | 4.9 [4.6, 5.3] | n/a | n/a | n/a | n/a | n/a |
| jury | 0 | 38 | 3,903.7 [3,526.3, 4,280.2] | 4.9 [4.6, 5.3] | n/a | n/a | n/a | n/a | n/a |
| chateval | pooled | 38 | 3,844.6 [3,593.8, 4,068.1] | 4.0 [4.0, 4.0] | n/a | n/a | n/a | n/a | n/a |
| chateval | 0 | 38 | 3,844.6 [3,593.8, 4,068.1] | 4.0 [4.0, 4.0] | n/a | n/a | n/a | n/a | n/a |
| committee | pooled | 38 | 2,391.2 [2,193.5, 2,566.5] | 3.4 [3.2, 3.7] | 11% [3%, 21%] | 0.2 [0.1, 0.3] | 0.6 [0.3, 0.9] | 0.6 [0.2, 1.0] | 0.0 [0.0, 0.1] |
| committee | 0 | 38 | 2,391.2 [2,193.5, 2,566.5] | 3.4 [3.2, 3.7] | 11% [3%, 21%] | 0.2 [0.1, 0.3] | 0.6 [0.3, 0.9] | 0.6 [0.2, 1.0] | 0.0 [0.0, 0.1] |

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

### Iteration 1: Evaluation set v2 baseline, protocol v1

Split: `dev`. Seeds: `0`.

| Method | Metric | Value | Delta vs previous |
| --- | --- | --- | --- |
| committee | Accuracy | 31.25% | n/a |
| committee | Position flip | 31.25% | n/a |
| committee | Tokens / decision | 3,498.6 | n/a |
| judge | Accuracy | 40.62% | n/a |
| judge | Position flip | 31.25% | n/a |
| judge | Tokens / decision | 3,831.6 | n/a |
| jury | Accuracy | 39.06% | n/a |
| jury | Position flip | 31.25% | n/a |
| jury | Tokens / decision | 3,903.7 | n/a |
| chateval | Accuracy | 56.25% | n/a |
| chateval | Position flip | 25.00% | n/a |
| chateval | Tokens / decision | 3,844.6 | n/a |
