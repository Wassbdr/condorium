"""Phase 2 (stub): simulated population reaction.

Specified for v2: after a verdict, on demand, 6 realistic and varied personas
(including >= 2 natural skeptics) react to the idea in their own voice, state
adoption (yes / no / maybe), and a global insight is produced.

Interface is stable now — `panel population <id>` — so scripts written today
keep working when the module lands.
"""

from __future__ import annotations

SPEC = {
    "personas": 6,
    "min_natural_skeptics": 2,
    "per_persona": ["reaction in own voice", "adoption: yes|no|maybe"],
    "output": "global insight across personas",
}


def simulate(eval_id: str) -> dict:
    raise NotImplementedError(
        "Simulated population is Phase 2. Planned: 6 realistic personas "
        "(>= 2 natural skeptics), each reacting in their own voice with an "
        "adoption verdict, plus a global insight. Track the roadmap in the README."
    )
