# Synthetic benchmark pairs

`synthetic_pairs.json` — 18 fictitious hackathons (12 `easy`, 6 `hard`), one "winner" and one
non-winner each, plus an enthusiastic rewrite of 12 of the 24 entries for the
tone-sensitivity test. Everything here was written for this repository: no
real project, person or company. Licence: MIT, like the rest of the repo.

**How the winner is defined (by construction, not by a real jury):** inside a
pair both entries target the same theme with descriptions of similar length
and the same neutral tone. The winner is stronger on the rubric hackathon
juries publicly use — a named user with a concrete pain, a scope that fits the
event, a working demo, and a small measured result obtained during the event.
In `easy` pairs the non-winner is plausible and well written but has one or two structural
weaknesses typical of non-winning entries (generic wrapper, over-scoped,
no evidence, unclear user). The benchmark therefore measures whether a judge
recognises *substance*, not whether it can predict a real jury's taste.

Rows use the Devpost-style keys read by `condorium.bench.pairs`
(`title`, `hackathon`, `description`, `prizes`), so the same code runs on a
real dataset. `enthusiastic` is the same content in a hyped tone.

In `hard` pairs both entries are concrete and show a small result; the
non-winner's weakness is subtler (evidence only on a public or recorded
dataset, a blocking permit/privacy/certification question, no real user
reached yet). The `tier` field lets the bench report both separately.
