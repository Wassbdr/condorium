"""Record one LIVE committee evaluation as a replayable demo trace.

usage: CONDORIUM_MODEL=... python scripts/record_trace.py OUT.json "Title" "Idea text" [mode]

The trace is the exact record `persist_node` writes, plus a `recorded` block
(model, UTC date, LLM calls and tokens) so a replay can say where it came from.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

from condorium.bench.run import evaluate_idea_silently
from condorium.config import SETTINGS
from condorium.llm import usage_meter


def main(out: Path, title: str, text: str, mode: str = "general") -> None:
    with usage_meter() as meter:
        state = evaluate_idea_silently(title, text, mode)
    record = {
        "eval_id": f"recorded-{out.stem}",
        "idea": {"id": out.stem, "title": title, "text": text, "provenance": "user"},
        "mode": mode,
        "constraints": "",
        **{k: state.get(k, {}) for k in ("intake", "round1", "round2", "synthesis", "debate")},
        "recorded": {"model": SETTINGS.model, "seed": SETTINGS.llm_seed,
                     "date_utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d"),
                     **meter.as_dict()},
    }
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    b = record["round2"].get("believer", {})
    print(f"wrote {out}: verdict {record['synthesis'].get('verdict')}, believer "
          f"{b.get('uncapped_score', b.get('score'))} -> {b.get('score')}"
          f"{' (capped)' if b.get('capped') else ''}, {meter.calls} calls")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2], sys.argv[3], *(sys.argv[4:5]))
