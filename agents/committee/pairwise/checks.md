Before scoring, add "checks" to the same JSON object:
[[index,"a",result,"short verbatim plan quote","short calculation"]].
Use each zero-based integer index for both plans. For max/min, result is the
plan's actual numeric value in the listed unit, not a status or the limit.
Combine the plan's relevant facts (for example fixed cost plus unit cost times
quantity, or shifts times capacity). Use null if there is no supported value.
For rule, 1 means met and 0 means violated;
use "" for the calculation. Prefer a compliant plan. Do not add requirements.
