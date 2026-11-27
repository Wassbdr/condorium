# Compare your own proposals

Install from the repository with `make install`, then activate the environment:

```sh
source .venv/bin/activate
```

## Write a rubric

Give your rubric a name and list the criteria that should separate a stronger
proposal from a weaker one. Each criterion needs a unique name and a one-line
description. Write descriptions that point to something a reviewer can find
in the proposal. See [the pilot rubric](../examples/pilot-rubric.yaml) for a
worked example. JSON files use the same fields.

## Compare two items

For the default NVIDIA NIM model, set `NVIDIA_NIM_API_KEY` in your environment.
For another provider, set its key (for example, `OPENAI_API_KEY`) and pass its
LiteLLM model ID with `--model` or set `CONDORIUM_MODEL`.

```sh
export CONDORIUM_CACHE="$HOME/.cache/condorium"
panel compare examples/pilot-a.md examples/pilot-b.md --rubric examples/pilot-rubric.yaml
```

You can also pass quoted inline text. Use `--text` when that text resembles
a path, such as a sentence that ends in `.md`. Omit `--rubric` to use
the default proposal rubric. To paste proposals and edit a rubric in a
browser, install the `ui` extra and open the Compare tab in `panel ui`.
Use `--brief 'The pilot must cost no more than $500.'` (or the optional shared
problem field in the Compare tab) to give both proposals the same constraints.

The winner is A, B, or a tie. Read the blind votes and their quotes to
see why reviewers preferred each item. Quotes that cannot be matched
against the cited item are removed. A reviewer without surviving evidence
abstains. If opposing reviewers go to debate, the debate votes are shown
separately. Use `--json` for the same decision and the token counts in a
machine-readable result.

## Run a batch

Put one object per line in `pairs.jsonl`. Each object has `a` and `b`
items, plus an optional string `id`. An item is inline text or an object
with `title` and `text` fields. A batch does not resolve filenames inside
those fields. The chosen rubric applies to every pair.

```json
{"id":"pilot-1","a":{"title":"Borrow","text":"Borrow existing monitors for a one-week pilot."},"b":"Buy monitors for all sites before measuring demand."}
{"id":"pilot-2","a":"Review battery life weekly.","b":"Replace all batteries daily."}
```

```sh
panel compare --batch pairs.jsonl --rubric examples/pilot-rubric.yaml --json
```

The command emits one JSON object per pair in input order. Without
`--json`, it prints the votes and evidence for each pair.

## Use the Python API

```python
from condorium import Rubric, compare

rubric = Rubric.load("examples/pilot-rubric.yaml")
result = compare(
    {"title": "Borrow", "text": "Borrow existing monitors for a one-week pilot."},
    "Buy monitors for all sites before measuring demand.",
    rubric,
)
print(result.winner)
for review in result.initial:
    print(review.role, review.preferred, review.evidence)
```

`Rubric.from_dict(...)` validates an in-memory mapping. Use
`Rubric.from_yaml(...)` or `Rubric.from_json(...)` for serialized text.
See [the full script](../examples/compare_pilot.py) for an example using files.

## Replay without a key

A successful request writes the response, its usage, and a request hash
to the configured cache, not the request itself. Responses can quote your
items, so keep the cache private if it contains sensitive text.

Repeat the same command with the same rubric, item order, model, and cache
directory. Set `CONDORIUM_OFFLINE=1` to block live requests:

```sh
CONDORIUM_OFFLINE=1 panel compare examples/pilot-a.md examples/pilot-b.md --rubric examples/pilot-rubric.yaml
```

A miss means the directory has no response for at least one exact request.
Use the original cache and inputs, or turn off offline mode and record
the missing responses with a provider key.
