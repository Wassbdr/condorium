---
name: ingest
layer: system
modes: [general, hackathon]
---
Extrais une entrée structurée de gagnant de hackathon depuis la source
ci-dessous. N'utilise que des faits présents dans la source ; laisse un champ
vide si la source ne le dit pas.

SOURCE :
{source}

Sors du JSON strict correspondant exactement à ce schéma :
{"id": "slug-en-kebab-case", "hackathon": "...", "date": "YYYY-MM",
 "theme": "...", "duration": "...", "winning_project": "...",
 "one_sentence_pitch": "...", "stack": ["..."],
 "official_criteria": ["..."], "why_it_won": "2-3 phrases",
 "source_url": "...",
 "entities": {"techs": ["..."], "themes": ["..."],
              "patterns": ["ex : démo temps réel, données publiques détournées"],
              "papers": [{"title": "...", "url": "..."}]}}
