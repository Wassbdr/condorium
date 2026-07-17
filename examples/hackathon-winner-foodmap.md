# Example input — a real hackathon-winner profile, at its initial stage

A composite of a recurring civic-tech winner profile (open-data mapping +
live demo), written as the team would have described it BEFORE the event —
the archetype behind entries like the winners you'll find once you run
`panel bootstrap` on a Devpost dataset. Use it to sanity-check the hackathon
mode and the Judge's dual grid.

Run it:

```bash
panel eval --file examples/hackathon-winner-foodmap.md \
  --mode hackathon --constraints "24h, team of 4" \
  --criteria "impact, innovation, execution" --no-interview
```

---

Idea:

Food banks throw away produce because they can't predict demand, while
families two blocks away skip meals. We combine the city's open food-bank
inventory feed with anonymized demand signals to generate a live map that
routes surplus food to pickup points before it spoils. Demo: watch a surplus
crate appear on the map and get claimed in real time during the pitch.
Stack we know: Python, PostGIS, a map front-end. Team of 4, 24 hours.
