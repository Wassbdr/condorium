# Pairwise benchmark results

Cells show the estimate and a 95% percentile interval from 2,000 pair-bootstrap draws (seed 42). Pooled intervals resample pairs across seeds. Accuracy uses both orders with ties worth half a hit. Verbosity and tone compare the altered item with the same pair in its original order. Slot A counts explicit A picks; a tie is not an A pick. Token totals include cached usage.

## Dev

2 pairs, 4 variants, seeds [0], nvidia_nim/nvidia/nemotron-3.5-lightning-30b-a3b, temperature 0.7, committee protocol v1.
Live calls: 0; live attempts: 0; cache hits: 14.
Position-only run. Verbosity and tone were not measured.
Cache-only replay with missing responses. Results are partial for: chateval, committee, judge, jury.
Parse failures: 0. See the per-decision JSON for raw outputs.

| Method | Seed | Decisions | Accuracy | Synthetic | ICLR | Position flip | Slot A | Verbosity delta | Tone delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| judge_1call | pooled | 2 | n/a | n/a | n/a | n/a | 0% [0%, 0%] | n/a | n/a |
| judge_1call | 0 | 2 | n/a | n/a | n/a | n/a | 0% [0%, 0%] | n/a | n/a |
| judge | pooled | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| judge | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jury | pooled | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jury | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| chateval | pooled | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| chateval | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| committee | pooled | 3 | 100% [100%, 100%] | 100% [100%, 100%] | n/a | 0% [0%, 0%] | 67% [50%, 100%] | n/a | n/a |
| committee | 0 | 3 | 100% [100%, 100%] | 100% [100%, 100%] | n/a | 0% [0%, 0%] | 67% [50%, 100%] | n/a | n/a |

| Method | Seed | Decisions | Tokens / decision | Calls / decision | Debate rate | Quotes dropped / decision | Abstains / decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| judge_1call | pooled | 2 | 394.0 [364.0, 424.0] | 1.0 [1.0, 1.0] | n/a | n/a | n/a |
| judge_1call | 0 | 2 | 394.0 [364.0, 424.0] | 1.0 [1.0, 1.0] | n/a | n/a | n/a |
| judge | pooled | 0 | n/a | n/a | n/a | n/a | n/a |
| judge | 0 | 0 | n/a | n/a | n/a | n/a | n/a |
| jury | pooled | 0 | n/a | n/a | n/a | n/a | n/a |
| jury | 0 | 0 | n/a | n/a | n/a | n/a | n/a |
| chateval | pooled | 0 | n/a | n/a | n/a | n/a | n/a |
| chateval | 0 | 0 | n/a | n/a | n/a | n/a | n/a |
| committee | pooled | 3 | 2,106.7 [2,069.5, 2,181.0] | 3.0 [3.0, 3.0] | 0% [0%, 0%] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] |
| committee | 0 | 3 | 2,106.7 [2,069.5, 2,181.0] | 3.0 [3.0, 3.0] | 0% [0%, 0%] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] |
