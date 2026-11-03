"""Validation of model outputs.

Guardrails must not depend on model obedience: a score sent as "9" must
still be capped, "Go." is still GO, a reference sent as a bare string must
not crash the citation gate. Every parsed JSON goes through one of the
`coerce_*` helpers before any rule reads it. Lenient by design — values are
repaired, never rejected — and the original is kept when it was changed
(`raw_score`, `verdict_raw`). Pure validation: no prompt text lives here.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

VERDICTS = ("GO", "ITERATE", "PIVOT")
SCIENTIFIC_VERDICTS = ("grounded", "neutral", "debunked")
SCORE_MIN, SCORE_MAX = 1, 10


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*(?:/\s*10)?\s*", value)
        return float(m.group(1)) if m else None
    return None


def coerce_score(value: Any) -> tuple[int | None, bool]:
    """-> (score clamped to 1..10 or None, whether the value was changed)."""
    if value is None:
        return None, False
    number = _to_number(value)
    if number is None:
        return None, True
    score = min(max(round(number), SCORE_MIN), SCORE_MAX)
    return score, isinstance(value, str) or score != number


def normalize_verdict(value: Any) -> str | None:
    """'Go.' / ' iterate ' / 'PIVOT!' -> GO / ITERATE / PIVOT; anything else -> None."""
    word = re.sub(r"[^A-Za-z]", "", str(value or "")).upper()
    return word if word in VERDICTS else None


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    out = []
    for item in value:
        if isinstance(item, str):
            if item.strip():
                out.append(item)
        elif item is not None:
            out.append(json.dumps(item, ensure_ascii=False))
    return out


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return bool(value)


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="allow")


class Opinion(_Lenient):
    score: int | None = None
    verdict: str = ""
    strengths: list[str] = []
    watchouts: list[str] = []
    proposed_tests: list[str] = []
    influenced_by: list[str] = []
    references: list[dict] = []
    scientific_verdict: str | None = None

    @field_validator("verdict", mode="before")
    @classmethod
    def _verdict(cls, v):
        return "" if v is None else v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)

    @field_validator("strengths", "watchouts", "proposed_tests", "influenced_by", mode="before")
    @classmethod
    def _lists(cls, v):
        return _str_list(v)

    @field_validator("references", mode="before")
    @classmethod
    def _references(cls, v):
        return [r for r in v if isinstance(r, dict)] if isinstance(v, list) else []

    @field_validator("scientific_verdict", mode="before")
    @classmethod
    def _sci(cls, v):
        if v is None:
            return None
        word = str(v).strip().lower()
        return word if word in SCIENTIFIC_VERDICTS else str(v)


def coerce_opinion(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {"score": None, "verdict": str(raw)}
    data = dict(raw)
    score, changed = coerce_score(data.get("score"))
    if changed:
        data["raw_score"] = data.get("score")
    data["score"] = score
    return Opinion.model_validate(data).model_dump(exclude_unset=True)


class Disagreement(_Lenient):
    topic: str = ""
    agents: list[str] = []
    gap: float = 0
    critical: bool = False

    @field_validator("agents", mode="before")
    @classmethod
    def _agents(cls, v):
        return _str_list(v)

    @field_validator("gap", mode="before")
    @classmethod
    def _gap(cls, v):
        n = _to_number(v)
        return abs(n) if n is not None else 0

    @field_validator("critical", mode="before")
    @classmethod
    def _critical(cls, v):
        return _as_bool(v)


class Synthesis(_Lenient):
    consensus: str = ""
    disagreements: list[Disagreement] = []
    verdict: str | None = None
    action: str = ""

    @field_validator("disagreements", mode="before")
    @classmethod
    def _disagreements(cls, v):
        return [d for d in v if isinstance(d, dict)] if isinstance(v, list) else []


def _with_verdict(data: dict) -> dict:
    if "verdict" in data:
        verdict = normalize_verdict(data["verdict"])
        if verdict is None:
            data["verdict_raw"] = data["verdict"]
            data["verdict_invalid"] = True
        data["verdict"] = verdict
    return data


def coerce_synthesis(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {}
    data = _with_verdict(dict(raw))
    out = Synthesis.model_validate(data).model_dump(exclude_unset=True)
    if "disagreements" in out:
        out["disagreements"] = [
            Disagreement.model_validate(d).model_dump() for d in out["disagreements"]]
    return out


class DebateUpdate(_Lenient):
    verdict: str | None = None
    verdict_changed: bool = False

    @field_validator("verdict_changed", mode="before")
    @classmethod
    def _changed(cls, v):
        return _as_bool(v)


def coerce_debate_update(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {}
    return DebateUpdate.model_validate(_with_verdict(dict(raw))).model_dump(exclude_unset=True)


PREFILTER_CRITERIA = ("theme_fit", "wow_potential", "apparent_feasibility")


def coerce_prefilter(raw: Any) -> dict:
    data = dict(raw) if isinstance(raw, dict) else {}
    for key in PREFILTER_CRITERIA:
        if key in data:
            data[key] = coerce_score(data[key])[0]
    return data


def coerce_ranking(raw: Any) -> dict:
    data = dict(raw) if isinstance(raw, dict) else {}
    rows = data.get("ranking")
    data["ranking"] = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    if not isinstance(data.get("winner"), dict):
        data.pop("winner", None)
    return data
