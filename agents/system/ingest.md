---
name: ingest
layer: system
modes: [general, hackathon]
---
Extract a structured hackathon-winner entry from the source below. Only use
facts present in the source; leave a field empty if the source does not
state it.

SOURCE:
{source}

Output STRICT JSON matching this schema exactly:
{"id": "kebab-case-slug", "hackathon": "...", "date": "YYYY-MM",
 "theme": "...", "duration": "...", "winning_project": "...",
 "one_sentence_pitch": "...", "stack": ["..."],
 "official_criteria": ["..."], "why_it_won": "2-3 sentences",
 "source_url": "...",
 "entities": {"techs": ["..."], "themes": ["..."],
              "patterns": ["e.g. real-time demo, public data twist"],
              "papers": [{"title": "...", "url": "..."}]}}
