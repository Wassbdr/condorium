"""Pairwise proposal comparison with checked evidence and vote aggregation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import asdict, dataclass, field, replace
from threading import Lock
from typing import Literal, cast

from .bench.pairset import Item, Rubric, Side, opposite
from .llm import complete_text, parse_json, usage_meter
from .prompts import load_prompt, render

MODEL = "nvidia_nim/nvidia/nemotron-3.5-super-vl-120b-a12b"
TEMPERATURE = 0.7
MAX_TOKENS = 384
ROLES = ("judge", "skeptic", "scientist")
PROTOCOL = "v2.1"
_FOLDER = "committee/pairwise"
_MAX_REQUIREMENTS = 5
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
    requirements: tuple[str, ...] = ()
    extraction_failure: str | None = None
    extraction_tokens: int = 0

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


def _problem_brief(a: Item, b: Item, brief: str) -> str:
    if brief.strip():
        return brief.strip()
    first_a, first_b = (_quote(item["text"].split("\n\n", 1)[0]) for item in (a, b))
    if first_a == first_b and a["text"] != b["text"]:
        return first_a
    return ""


def _criteria(rubric: Rubric) -> str:
    return "\n".join(f"{c['name']}: {c['description']}" for c in rubric["criteria"])


@dataclass(frozen=True)
class Requirements:
    quotes: tuple[str, ...] = ()
    parse_failure: str | None = None


def _extract(brief: str, criteria: str, model: str) -> Requirements:
    if not brief:
        return Requirements()
    user = render(load_prompt(f"{_FOLDER}/requirements_input.md").body, brief=brief,
                  criteria=criteria)
    raw = complete_text(load_prompt(f"{_FOLDER}/requirements.md").body, user, model=model,
                        seed=0, temperature=0, max_tokens=164, max_retries=0, num_retries=0)
    try:
        values = parse_json(raw)
    except ValueError:
        return Requirements(parse_failure=raw)
    if not isinstance(values, list):
        return Requirements(parse_failure=raw)
    quotes = dict.fromkeys(q for value in values if (q := _quote(value)) and q in _quote(brief))
    return Requirements(tuple(quotes)[:_MAX_REQUIREMENTS])


class RequirementCache:
    """Share identical extractions across simultaneous comparisons in one run."""

    def __init__(self) -> None:
        self._pending: dict[tuple[str, str, str], Future[Requirements]] = {}
        self._lock = Lock()

    def get(self, brief: str, criteria: str, model: str) -> Requirements:
        key = brief, criteria, model
        with self._lock:
            future = self._pending.get(key)
            if future is None:
                future = Future()
                self._pending[key] = future
                owner = True
            else:
                owner = False
        if owner:
            try:
                future.set_result(_extract(*key))
            except BaseException as exc:
                future.set_exception(exc)
        return future.result()


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
                    <= required | {"checks", "requirements", "violations"}):
                return {"scores": {"a": fields["a"], "b": fields["b"]},
                        **{key: value for key, value in fields.items() if key not in ("a", "b")}}
    return {}


def _quote(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _violation_sides(review: Review) -> frozenset[Side]:
    return frozenset(v.proposal for v in review.violations)


def _normalize(role: str, raw: str, a: Item, b: Item, rubric: Rubric,
               requirements: tuple[str, ...] = (), initial: Review | None = None) -> Review:
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

    violations: list[Violation] = []
    violations_dropped = 0
    checks = data.get("checks")
    seen = set()
    if initial is None and isinstance(checks, list):
        for entry in checks:
            if isinstance(entry, list) and len(entry) == 5:
                index, side, status, quote, reason = entry
                proposed = _quote(quote)
                if (type(index) is int and 0 <= index < len(requirements)
                        and side in ("a", "b") and type(status) is int and status in (0, 1)
                        and (index, side) not in seen and proposed
                        and any(proposed in text for text in texts[side])):
                    seen.add((index, side))
                    if status == 0:
                        violations.append(Violation(side, requirements[index], proposed,
                                                    _quote(reason)))
                    continue
                if status == 1:
                    continue
            violations_dropped += 1
    if isinstance(unlisted := data.get("violations"), list):
        violations_dropped += len(unlisted)

    scores: dict[Side, dict[str, int]] = {}
    raw_scores = data.get("scores")
    sides: tuple[Side, Side] = ("a", "b")
    if initial is not None:
        scores = initial.scores
    else:
        names = [criterion["name"] for criterion in rubric["criteria"]]
        for side in sides:
            values = raw_scores.get(side) if isinstance(raw_scores, dict) else None
            if isinstance(values, list):
                values = dict(zip(names, values, strict=False))
            scores[side] = {
                name: value for name in names if isinstance(values, dict)
                if (value := _rating(values.get(name))) is not None
            }
    confidence = _rating(data.get("confidence"))
    failed = (preference is None or confidence is None or not isinstance(raw_quotes, list)
              or any(len(values) != len(rubric["criteria"]) for values in scores.values()))
    enforced = violations if initial is None else initial.violations
    if (preference == "a" or preference == "b") and {v.proposal for v in enforced} == {preference}:
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
    requirement_cache: RequirementCache | None = None,
) -> Comparison:
    """Run blind reviews and at most one round of targeted debate."""
    folder = _FOLDER
    proposals = _committee_input(a, b, rubric, brief)
    contract = load_prompt(f"{folder}/_contract.md").body
    criteria = _criteria(rubric)

    def assess(role: str, index: int, system: str, user: str, max_tokens: int,
               initial: Review | None = None) -> Review:
        review_seed = sample_seed(seed, "committee", variant_id, index)
        raw = complete_text(system, user, model=model, temperature=temperature,
                            seed=review_seed, max_tokens=max_tokens, max_retries=0, num_retries=0)
        review = _normalize(role, raw, a, b, rubric, requirements.quotes, initial)
        return replace(review, preferred=None) if review.parse_failure is not None else review

    def quote_data(review: Review) -> str:
        return json.dumps({"evidence": [asdict(e) for e in review.evidence],
                           "violations": [asdict(v) for v in review.violations]}, separators=(",", ":"))

    with usage_meter(scoped=True) as usage, ThreadPoolExecutor(max_workers=len(ROLES)) as pool:
        with usage_meter(scoped=True) as extraction:
            requirements = (requirement_cache or RequirementCache()).get(
                _problem_brief(a, b, brief), criteria, model,
            )
        user = proposals
        max_tokens = 172
        if requirements.quotes:
            contract += "\n" + load_prompt(f"{folder}/checks.md").body
            user += "\n\n" + render(load_prompt(f"{folder}/checks_input.md").body,
                                     requirements=json.dumps(requirements.quotes, ensure_ascii=False))
            max_tokens = min(480, 200 + 60 * len(requirements.quotes))
        initial = [pool.submit(copy_context().run, assess, role, index,
                               load_prompt(f"{folder}/{role}.md").body + "\n" + contract,
                               user, max_tokens) for index, role in enumerate(ROLES)]
        reviews = [future.result() for future in initial]
        winner = majority(review.preferred for review in reviews)
        debate: list[Review] = []
        flagged = [_violation_sides(review) for review in reviews]
        sides = set().union(*flagged)
        first = next((r for r in reviews if r.preferred == "a"), None)
        second = next((r for r in reviews if r.preferred == "b"), None)
        if len(sides) == 1 and sum(bool(s) for s in flagged) >= 2:
            winner = opposite(next(iter(sides)))
        elif winner is None and first is not None and second is not None:
            system = load_prompt(f"{folder}/debate.md").body
            template = load_prompt(f"{folder}/debate_input.md").body
            turns = []
            for index, (own, other) in enumerate(((first, second), (second, first)), len(ROLES)):
                user = render(template, criteria=criteria, own_preference=own.preferred,
                              other_preference=other.preferred, own_quotes=quote_data(own),
                              other_quotes=quote_data(other))
                turns.append(pool.submit(copy_context().run, assess, own.role, index, system,
                                         user, 144, own))
            debate = [future.result() for future in turns]
            final = {review.role: review.preferred for review in reviews + debate}
            winner = majority(final.values())
        return Comparison(winner or "tie", reviews, debate, usage.as_dict(), requirements.quotes,
                          requirements.parse_failure, extraction.total_tokens)
