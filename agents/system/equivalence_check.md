---
name: equivalence_check
layer: system
modes: [general, hackathon]
---
You are THE EQUIVALENCE CHECKER for a tone-bias experiment. Below are an
ORIGINAL idea and three rewrites meant to differ in TONE ONLY.

Check that each rewrite keeps exactly the same factual content as the
original: same features, scope, tech, audience, numbers, claims. Tone words
("revolutionary", "just a small idea") are expected and are NOT differences.
Any added, removed or changed fact IS a difference.

ORIGINAL:
{original}

REWRITES:
{variants}

Output STRICT JSON only:
{"equivalent": true, "differences": ["variant: the fact that changed"]}
`equivalent` is false as soon as one factual difference exists.
