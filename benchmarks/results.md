# Pairwise benchmark results

Cells show the estimate and a 95% percentile interval from 2,000 pair-bootstrap draws (seed 42). Pooled intervals resample pairs across seeds. Accuracy uses both orders with ties worth half a hit. Verbosity and tone compare the altered item with the same pair in its original order. Slot A counts explicit A picks; a tie is not an A pick. Token totals include cached usage.

## Dev

2 pairs, 8 variants, seeds [0], nvidia_nim/nvidia/nemotron-3.5-super-vl-120b-a12b, temperature 0.7, committee protocol v1.
Live calls: 60; live attempts: 60; cache hits: 5.
Call limit reached. Results are partial for: chateval, committee, judge, jury.
Parse failures: 5. See the per-decision JSON for raw outputs.

| Method | Seed | Decisions | Accuracy | Synthetic | ICLR | Position flip | Slot A | Verbosity delta | Tone delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| judge_1call | pooled | 5 | 100% [100%, 100%] | 100% [100%, 100%] | n/a | 0% [0%, 0%] | 50% [50%, 50%] | +0 pp [+0 pp, +0 pp] | n/a |
| judge_1call | 0 | 5 | 100% [100%, 100%] | 100% [100%, 100%] | n/a | 0% [0%, 0%] | 50% [50%, 50%] | +0 pp [+0 pp, +0 pp] | n/a |
| judge | pooled | 5 | 100% [100%, 100%] | 100% [100%, 100%] | n/a | 0% [0%, 0%] | 50% [50%, 50%] | +0 pp [+0 pp, +0 pp] | n/a |
| judge | 0 | 5 | 100% [100%, 100%] | 100% [100%, 100%] | n/a | 0% [0%, 0%] | 50% [50%, 50%] | +0 pp [+0 pp, +0 pp] | n/a |
| jury | pooled | 4 | 100% [100%, 100%] | 100% [100%, 100%] | n/a | 0% [0%, 0%] | 50% [50%, 50%] | n/a | n/a |
| jury | 0 | 4 | 100% [100%, 100%] | 100% [100%, 100%] | n/a | 0% [0%, 0%] | 50% [50%, 50%] | n/a | n/a |
| chateval | pooled | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| chateval | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| committee | pooled | 5 | 100% [100%, 100%] | 100% [100%, 100%] | n/a | 0% [0%, 0%] | 50% [50%, 50%] | +0 pp [+0 pp, +0 pp] | n/a |
| committee | 0 | 5 | 100% [100%, 100%] | 100% [100%, 100%] | n/a | 0% [0%, 0%] | 50% [50%, 50%] | +0 pp [+0 pp, +0 pp] | n/a |

| Method | Seed | Decisions | Tokens / decision | Calls / decision | Debate rate | Quotes dropped / decision | Abstains / decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| judge_1call | pooled | 5 | 435.0 [425.5, 441.3] | 1.0 [1.0, 1.0] | n/a | n/a | n/a |
| judge_1call | 0 | 5 | 435.0 [425.5, 441.3] | 1.0 [1.0, 1.0] | n/a | n/a | n/a |
| judge | pooled | 5 | 2,290.0 [2,087.0, 2,425.3] | 5.2 [5.0, 5.3] | n/a | n/a | n/a |
| judge | 0 | 5 | 2,290.0 [2,087.0, 2,425.3] | 5.2 [5.0, 5.3] | n/a | n/a | n/a |
| jury | pooled | 4 | 2,138.2 [2,104.5, 2,172.0] | 4.2 [4.0, 4.5] | n/a | n/a | n/a |
| jury | 0 | 4 | 2,138.2 [2,104.5, 2,172.0] | 4.2 [4.0, 4.5] | n/a | n/a | n/a |
| chateval | pooled | 0 | n/a | n/a | n/a | n/a | n/a |
| chateval | 0 | 0 | n/a | n/a | n/a | n/a | n/a |
| committee | pooled | 5 | 2,130.2 [2,028.0, 2,198.3] | 3.0 [3.0, 3.0] | 0% [0%, 0%] | 0.0 [0.0, 0.0] | 0.4 [0.3, 0.5] |
| committee | 0 | 5 | 2,130.2 [2,028.0, 2,198.3] | 3.0 [3.0, 3.0] | 0% [0%, 0%] | 0.0 [0.0, 0.0] | 0.4 [0.3, 0.5] |
