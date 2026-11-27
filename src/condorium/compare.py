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

from .bench.pairset import Item, Rubric, Side, opposite
from .llm import complete_text, parse_json, usage_meter
from .prompts import load_prompt, render

MODEL = "nvidia_nim/nvidia/nemotron-3.5-super-vl-120b-a12b"
TEMPERATURE = 0.7
MAX_TOKENS = 384
_RETRY_MAX_TOKENS = 768
ROLES = ("judge", "skeptic", "scientist")
PROTOCOL = "v2"
Winner = Literal["a", "b", "tie"]


@dataclass(frozen=True)
class Evidence:
    """A quote verified against the proposal it cites."""

    proposal: Side
    quote: str


@dataclass(frozen=True)
class Violation:
    """A reported violation with both quotes checked against their sources."""

    proposal: Side
    requirement_quote: str
    proposal_quote: str
    reason: str


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
    violations: list[Violation] = field(default_factory=list)
    violations_dropped: int = 0


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

    @property
    def violations_kept(self) -> int:
        return sum(len(review.violations) for review in self.initial + self.debate)

    @property
    def violations_dropped(self) -> int:
        return sum(review.violations_dropped for review in self.initial + self.debate)


def sample_seed(seed: int, method: str, variant_id: str, call_index: int) -> int:
    raw = json.dumps([seed, method, variant_id, call_index], separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(raw.encode()).digest()[:4], "big") & 0x7FFFFFFF


def proposal_input(a: Item, b: Item, rubric: Rubric) -> str:
    return render(load_prompt("system/pairwise_input.md").body, rubric_name=rubric["name"],
                  criteria=json.dumps(rubric["criteria"], ensure_ascii=False),
                  a_title=a["title"], a_text=a["text"], b_title=b["title"], b_text=b["text"])


def _committee_input(a: Item, b: Item, rubric: Rubric, brief: str) -> str:
    a_parts, b_parts = (item["text"].split("\n\n") for item in (a, b))
    shared = 0
    for first, second in zip(a_parts, b_parts, strict=False):
        if first != second:
            break
        shared += 1
    input_a: Item = {"title": a["title"], "text": "\n\n".join(a_parts[shared:])}
    input_b: Item = {"title": b["title"], "text": "\n\n".join(b_parts[shared:])}
    context = "\n\n".join(part for part in (brief, *a_parts[:shared]) if part)
    proposals = proposal_input(input_a, input_b, rubric)
    if context:
        header = render(load_prompt("committee/pairwise/brief.md").body, brief=context)
        return f"{header}\n\n{proposals}"
    return proposals


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
    leading = text
    if leading.startswith("```"):
        leading = leading[3:].removeprefix("json").lstrip()
    try:
        data, _ = json.JSONDecoder().raw_decode(leading)
    except json.JSONDecodeError:
        pass
    else:
        if isinstance(data, dict):
            return data

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
            required = {"a", "b", "preferred", "confidence", "evidence"}
            if (isinstance(fields, dict) and required <= fields.keys()
                    <= required | {"requirements", "violations"}):
                return {"scores": {"a": fields["a"], "b": fields["b"]},
                        **{key: value for key, value in fields.items() if key not in ("a", "b")}}
    return {}


def _quote(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _violation_sides(review: Review) -> frozenset[Side]:
    return frozenset(v.proposal for v in review.violations)


def _normalize(role: str, raw: str, a: Item, b: Item, rubric: Rubric, brief: str = "") -> Review:
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
            quote = _quote(entry.get("quote")) if isinstance(entry, dict) else ""
            if cited_side in ("a", "b") and quote and any(quote in text for text in texts[cited_side]):
                evidence.append(Evidence(cast(Side, cited_side), quote))
            else:
                dropped += 1

    sources = [_quote(brief), _quote(rubric["name"])]
    sources.extend(_quote(f"{criterion['name']}: {criterion['description']}")
                   for criterion in rubric["criteria"])
    shared = (_quote(a["text"]), _quote(b["text"]))
    violations: list[Violation] = []
    violations_dropped = 0
    raw_violations = data.get("violations")
    if isinstance(raw_violations, list):
        for entry in raw_violations:
            if isinstance(entry, dict):
                side = _preference(entry.get("proposal"))
                requirement = _quote(entry.get("requirement_quote"))
                proposed = _quote(entry.get("proposal_quote"))
                reason = _quote(entry.get("reason"))
                if (side in ("a", "b") and requirement and proposed and reason
                        and (any(requirement in source for source in sources)
                             or all(requirement in text for text in shared))
                        and any(proposed in text for text in texts[side])):
                    violations.append(Violation(cast(Side, side), requirement, proposed, reason))
                    continue
            violations_dropped += 1

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
              or not isinstance(raw_violations, list)
              or any(len(values) != len(rubric["criteria"]) for values in scores.values()))
    if (preference == "a" or preference == "b") and {v.proposal for v in violations} == {preference}:
        preference = opposite(preference)
    return Review(role, preference if evidence else None, confidence, scores, evidence,
                  dropped, raw if failed else None, violations, violations_dropped)


def compare(
    a: Item,
    b: Item,
    rubric: Rubric,
    *,
    model: str = MODEL,
    temperature: float = TEMPERATURE,
    seed: int = 0,
    variant_id: str = "",
    brief: str = "",
) -> Comparison:
    """Run blind reviews and at most one round of targeted debate."""
    folder = "committee/pairwise"
    proposals = _committee_input(a, b, rubric, brief)
    contract = load_prompt(f"{folder}/_contract.md").body

    def assess(role: str, index: int, *, extra: str = "", user: str = proposals) -> Review:
        persona = load_prompt(f"{folder}/{role}.md").body
        system = "\n\n".join(part for part in (persona, extra, contract) if part)
        review_seed = sample_seed(seed, "committee", variant_id, index)

        def request(max_tokens: int) -> Review:
            raw = complete_text(system, user, model=model, temperature=temperature,
                                seed=review_seed, max_tokens=max_tokens,
                                max_retries=0, num_retries=0)
            return _normalize(role, raw, a, b, rubric, brief)

        with usage_meter(scoped=True) as attempt:
            review = request(MAX_TOKENS)
        if review.parse_failure is not None and not attempt.estimated and (
            attempt.completion_tokens >= MAX_TOKENS
        ):
            return request(_RETRY_MAX_TOKENS)
        return review

    with usage_meter(scoped=True) as usage, ThreadPoolExecutor(max_workers=len(ROLES)) as pool:
        initial = [pool.submit(copy_context().run, assess, role, index)
                   for index, role in enumerate(ROLES)]
        reviews = [future.result() for future in initial]
        winner = majority(review.preferred for review in reviews)
        debate: list[Review] = []
        flagged = [_violation_sides(review) for review in reviews]
        if len(sides := set().union(*flagged)) == 1 and sum(bool(s) for s in flagged) >= 2:
            return Comparison(opposite(next(iter(sides))), reviews, debate, usage.as_dict())

        disagreement = [
            (own, other) for i, own in enumerate(reviews) for other in reviews[i + 1:]
            if _violation_sides(own) != _violation_sides(other)
        ]
        opposing = [(own, other) for own in reviews for other in reviews
                    if own.preferred == "a" and other.preferred == "b"]
        pair = max(disagreement, key=lambda pair: (
            len(_violation_sides(pair[0]) ^ _violation_sides(pair[1])),
            bool(_violation_sides(pair[0])) and bool(_violation_sides(pair[1])),
        )) if disagreement else opposing[0] if winner is None and opposing else None
        if pair is not None:
            extra = load_prompt(f"{folder}/debate.md").body
            template = load_prompt(f"{folder}/debate_input.md").body
            turns = []
            first, second = pair
            for index, (own, other) in enumerate(((first, second), (second, first)), len(ROLES)):
                user = render(template, proposals=proposals, own_preference=own.preferred,
                              other_preference=other.preferred,
                              other_evidence=json.dumps([asdict(e) for e in other.evidence]),
                              other_violations=json.dumps([asdict(v) for v in other.violations]))
                turns.append(pool.submit(copy_context().run, assess, own.role, index,
                                         extra=extra, user=user))
            debate = [future.result() for future in turns]
            final = {review.role: review.preferred for review in reviews + debate}
            winner = majority(final.values())
        return Comparison(winner or "tie", reviews, debate, usage.as_dict())
