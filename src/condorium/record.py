"""Track record: real outcome vs committee prediction, feeding the Coach."""

from __future__ import annotations

import time

from .analytics import traces
from .config import SETTINGS

_HEADER = (
    "# Track record\n\n"
    "Real-world results vs the committee's prediction. Fed into `panel coach`.\n\n"
    "| date | eval id | idea | committee verdict | real result |\n"
    "|------|---------|------|-------------------|-------------|\n"
)


def record_result(eval_id: str, result: str) -> dict:
    record = traces.load_eval(eval_id)
    verdict = (record.get("synthesis") or {}).get("verdict", "?")
    title = record.get("idea", {}).get("title", eval_id)
    outcome = {
        "eval_id": eval_id,
        "verdict": verdict,
        "result": result,
        "date": time.strftime("%Y-%m-%d"),
    }
    traces.save_outcome(eval_id, outcome)

    f = SETTINGS.track_record_file
    text = f.read_text(encoding="utf-8") if f.exists() else _HEADER
    if "| date |" not in text:
        text = _HEADER + text
    text += f"| {outcome['date']} | {eval_id} | {title} | {verdict} | {result} |\n"
    f.write_text(text, encoding="utf-8")
    return outcome


def load_track_record() -> list[dict]:
    out = []
    for record in traces.list_evals():
        outcome = traces.load_outcome(record["eval_id"])
        if outcome:
            out.append(outcome)
    return out
