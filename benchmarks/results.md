# Pairwise benchmark results

Cells show the estimate and a 95% percentile interval from 2,000 pair-bootstrap draws (seed 42). Pooled intervals resample pairs across seeds. Accuracy uses both orders with ties worth half a hit. Verbosity and tone compare the altered item with the same pair in its original order. Slot A counts explicit A picks; a tie is not an A pick. Token totals include cached usage.

## Dev

16 pairs, 38 variants, seeds [0], nvidia_nim/nvidia/nemotron-3.5-super-vl-120b-a12b, temperature 0.7, committee protocol v4, evaluation set v2.
Live calls: 40; live attempts: 100; cache hits: 631.
References replay the protocol v1 token targets from the same evaluation set.
Swapping the two input arguments does not change which proposal the committee picks. Roles alternate between the two content-based orders, so the committee's position flip rate measures a property of the protocol.
Parse failures: 40. See the per-decision JSON for raw outputs.

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
| committee | pooled | 38 | 66% [44%, 88%] | 81% [62%, 94%] | 50% [12%, 88%] | 0% [0%, 0%] | 41% [31%, 50%] | +17 pp [-50 pp, +100 pp] | +33 pp [+0 pp, +100 pp] |
| committee | 0 | 38 | 66% [44%, 88%] | 81% [62%, 94%] | 50% [12%, 88%] | 0% [0%, 0%] | 41% [31%, 50%] | +17 pp [-50 pp, +100 pp] | +33 pp [+0 pp, +100 pp] |

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
| committee | pooled | 38 | 2,658.2 [2,535.2, 2,786.4] | 3.3 [3.2, 3.5] | 5% [0%, 12%] | 0.2 [0.0, 0.4] | 1.1 [0.6, 1.7] | 1.0 [0.3, 1.8] | 0.0 [0.0, 0.0] |
| committee | 0 | 38 | 2,658.2 [2,535.2, 2,786.4] | 3.3 [3.2, 3.5] | 5% [0%, 12%] | 0.2 [0.0, 0.4] | 1.1 [0.6, 1.7] | 1.0 [0.3, 1.8] | 0.0 [0.0, 0.0] |

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

### Iteration 2: Protocol v2.1: shared requirement extraction and compact ballots

Split: `dev`. Seeds: `0`.

| Method | Metric | Value | Delta vs previous |
| --- | --- | --- | --- |
| committee | Accuracy | 45.31% | +14.06 pp |
| committee | Position flip | 75.00% | +43.75 pp |
| committee | Tokens / decision | 2,391.2 | -1,107.4 |
| judge | Accuracy | 40.62% | +0.00 pp |
| judge | Position flip | 31.25% | +0.00 pp |
| judge | Tokens / decision | 3,831.6 | +0.0 |
| jury | Accuracy | 45.31% | +6.25 pp |
| jury | Position flip | 18.75% | -12.50 pp |
| jury | Tokens / decision | 3,903.7 | +0.0 |
| chateval | Accuracy | 56.25% | +0.00 pp |
| chateval | Position flip | 25.00% | +0.00 pp |
| chateval | Tokens / decision | 3,844.6 | +0.0 |

### Iteration 3: Protocol v3: content-based ordering, alternating slots, and ballot recovery

Split: `dev`. Seeds: `0`.

| Method | Metric | Value | Delta vs previous |
| --- | --- | --- | --- |
| committee | Accuracy | 37.50% | -7.81 pp |
| committee | Position flip | 0.00% | -75.00 pp |
| committee | Tokens / decision | 2,461.9 | +70.7 |
| judge | Accuracy | 40.62% | +0.00 pp |
| judge | Position flip | 31.25% | +0.00 pp |
| judge | Tokens / decision | 3,831.6 | +0.0 |
| jury | Accuracy | 45.31% | +0.00 pp |
| jury | Position flip | 18.75% | +0.00 pp |
| jury | Tokens / decision | 3,903.7 | +0.0 |
| chateval | Accuracy | 56.25% | +0.00 pp |
| chateval | Position flip | 25.00% | +0.00 pp |
| chateval | Tokens / decision | 3,844.6 | +0.0 |

### Iteration 4: Protocol v4: explicit briefs and typed hard requirements

Split: `dev`. Seeds: `0`.

| Method | Metric | Value | Delta vs previous |
| --- | --- | --- | --- |
| committee | Accuracy | 65.62% | +28.12 pp |
| committee | Position flip | 0.00% | +0.00 pp |
| committee | Tokens / decision | 2,658.2 | +196.3 |
| judge | Accuracy | 40.62% | +0.00 pp |
| judge | Position flip | 31.25% | +0.00 pp |
| judge | Tokens / decision | 3,831.6 | +0.0 |
| jury | Accuracy | 45.31% | +0.00 pp |
| jury | Position flip | 18.75% | +0.00 pp |
| jury | Tokens / decision | 3,903.7 | +0.0 |
| chateval | Accuracy | 56.25% | +0.00 pp |
| chateval | Position flip | 25.00% | +0.00 pp |
| chateval | Tokens / decision | 3,844.6 | +0.0 |
