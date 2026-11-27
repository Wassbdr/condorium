"""Pairwise proposal comparison with checked evidence and vote aggregation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import asdict, dataclass, field
from typing import Literal, cast

from .bench.pairset import Item, Rubric, Side
from .llm import complete_text, parse_json, usage_meter
from .prompts import load_prompt, render

MODEL = "nvidia_nim/nvidia/nemotron-3.5-super-vl-120b-a12b"
TEMPERATURE = 0.7
MAX_TOKENS = 384
ROLES = ("judge", "skeptic", "scientist")
Winner = Literal["a", "b", "tie"]


@dataclass(frozen=True)
class Evidence:
    """A quote verified against the proposal it cites."""

    proposal: Side
    quote: str


@dataclass
class Review:
    """One role's scores, preference, and checked evidence."""

    role: str
    preferred: Winner | None
    confidence: int | None
    scores: dict[Side, dict[str, int]]
    evidence: list[Evidence] = field(default_factory=list)
    dropped: int = 0
    parse_failure: str | None = None


@dataclass
class Comparison:
    """The winning side, blind reviews, debate reviews, and token usage."""

    winner: Winner
    initial: list[Review]
    debate: list[Review]
    usage: dict

    @property
    def dropped(self) -> int:
        return sum(review.dropped for review in self.initial + self.debate)

    @property
    def abstains(self) -> int:
        return sum(review.preferred is None for review in self.initial + self.debate)


def sample_seed(seed: int, method: str, variant_id: str, call_index: int) -> int:
    raw = json.dumps([seed, method, variant_id, call_index], separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(raw.encode()).digest()[:4], "big") & 0x7FFFFFFF


def proposal_input(a: Item, b: Item, rubric: Rubric) -> str:
    return render(load_prompt("system/pairwise_input.md").body, rubric_name=rubric["name"],
                  criteria=json.dumps(rubric["criteria"], ensure_ascii=False),
                  a_title=a["title"], a_text=a["text"], b_title=b["title"], b_text=b["text"])


def majority(votes: Iterable[Winner | None], *, include_abstentions: bool = False) -> Winner | None:
    counts = Counter(votes)
    abstentions = counts.pop(None, 0)
    total = counts.total() + (abstentions if include_abstentions else 0)
    for vote, count in counts.items():
        if count * 2 > total:
            return vote
    return None


def _preference(value: object) -> Winner | None:
    if isinstance(value, str):
        value = value.strip().lower()
        if value in ("a", "b", "tie"):
            return cast(Winner, value)
    return None


def _rating(value: object) -> int | None:
    return value if type(value) is int and 1 <= value <= 5 else None


def _review_json(raw: str) -> dict:
    try:
        data = parse_json(raw)
    except ValueError:
        data = None
    if isinstance(data, dict):
        return data

    text = raw.strip()
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        prefix, suffix = text[:exc.pos].rstrip(), text[exc.pos:].lstrip()
        if not prefix.startswith(suffix):
            return {}
        try:
            envelope = json.loads(prefix + "}")
        except json.JSONDecodeError:
            return {}
        if isinstance(envelope, dict) and envelope.keys() == {"scores"}:
            fields = envelope["scores"]
            if isinstance(fields, dict) and fields.keys() == {
                "a", "b", "preferred", "confidence", "evidence",
            }:
                return {"scores": {"a": fields["a"], "b": fields["b"]},
                        **{key: fields[key] for key in ("preferred", "confidence", "evidence")}}
    return {}


def _normalize(role: str, raw: str, a: Item, b: Item, rubric: Rubric) -> Review:
    data = _review_json(raw)
    preference = _preference(data.get("preferred"))
    texts = {side: tuple(" ".join(part.split()) for part in (item["title"], item["text"]))
             for side, item in (("a", a), ("b", b))}
    evidence = []
    dropped = 0
    raw_quotes = data.get("evidence")
    if isinstance(raw_quotes, list):
        for entry in raw_quotes:
            cited_side = _preference(entry.get("proposal")) if isinstance(entry, dict) else None
            quote = entry.get("quote") if isinstance(entry, dict) else None
            quote = " ".join(quote.split()) if isinstance(quote, str) else ""
            if cited_side in ("a", "b") and quote and any(quote in text for text in texts[cited_side]):
                evidence.append(Evidence(cast(Side, cited_side), quote))
            else:
                dropped += 1

    scores: dict[Side, dict[str, int]] = {}
    raw_scores = data.get("scores")
    sides: tuple[Side, Side] = ("a", "b")
    for side in sides:
        values = raw_scores.get(side) if isinstance(raw_scores, dict) else None
        scores[side] = {
            name: value for criterion in rubric["criteria"] if isinstance(values, dict)
            if (name := criterion["name"]) and (value := _rating(values.get(name))) is not None
        }
    confidence = _rating(data.get("confidence"))
    failed = (preference is None or confidence is None or not isinstance(raw_quotes, list)
              or any(len(values) != len(rubric["criteria"]) for values in scores.values()))
    return Review(role, preference if evidence else None, confidence, scores, evidence,
                  dropped, raw if failed else None)


def compare(
    a: Item,
    b: Item,
    rubric: Rubric,
    *,
    model: str = MODEL,
    temperature: float = TEMPERATURE,
    seed: int = 0,
    variant_id: str = "",
) -> Comparison:
    """Run blind reviews and at most one round of targeted debate."""
    folder = "committee/pairwise"
    proposals = proposal_input(a, b, rubric)
    contract = load_prompt(f"{folder}/_contract.md").body

    def assess(role: str, index: int, *, extra: str = "", user: str = proposals) -> Review:
        persona = load_prompt(f"{folder}/{role}.md").body
        system = "\n\n".join(part for part in (persona, extra, contract) if part)
        raw = complete_text(system, user, model=model, temperature=temperature,
                            seed=sample_seed(seed, "committee", variant_id, index),
                            max_tokens=MAX_TOKENS, max_retries=0, num_retries=0)
        return _normalize(role, raw, a, b, rubric)

    with usage_meter(scoped=True) as usage, ThreadPoolExecutor(max_workers=len(ROLES)) as pool:
        initial = [pool.submit(copy_context().run, assess, role, index)
                   for index, role in enumerate(ROLES)]
        reviews = [future.result() for future in initial]
        winner = majority(review.preferred for review in reviews)
        debate: list[Review] = []
        first = next((review for review in reviews if review.preferred == "a"), None)
        second = next((review for review in reviews if review.preferred == "b"), None)
        if winner is None and first is not None and second is not None:
            extra = load_prompt(f"{folder}/debate.md").body
            template = load_prompt(f"{folder}/debate_input.md").body
            turns = []
            for index, (own, other) in enumerate(((first, second), (second, first)), len(ROLES)):
                user = render(template, proposals=proposals, own_preference=own.preferred,
                              other_preference=other.preferred,
                              other_evidence=json.dumps([asdict(e) for e in other.evidence]))
                turns.append(pool.submit(copy_context().run, assess, own.role, index,
                                         extra=extra, user=user))
            debate = [future.result() for future in turns]
            final = {review.role: review.preferred for review in reviews + debate}
            winner = majority(final.values())
        return Comparison(winner or "tie", reviews, debate, usage.as_dict())
