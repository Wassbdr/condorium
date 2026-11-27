"""Seeded proposal pairs and perturbations for pairwise benchmarks."""

from __future__ import annotations

import json
import random
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Literal, NamedTuple, TypedDict

import yaml

DEFAULT_SEED = 42
DATASET_VERSION = 2
DEFAULT_RUBRIC = "proposal"
PAPER_RUBRIC = "paper"
Split = Literal["dev", "test"]
Side = Literal["a", "b"]


class Item(TypedDict):
    """A proposal with a display title and its full text."""

    title: str
    text: str


class Pair(TypedDict):
    id: str
    version: int
    source: Literal["synthetic", "iclr"]
    split: Split
    rubric: str
    a: Item
    b: Item
    better: Side
    note: str


class Variant(TypedDict):
    pair_id: str
    kind: Literal["position", "verbosity", "tone"]
    order: Literal["ab", "ba"]
    a: Item
    b: Item
    better: Side


class Criterion(TypedDict):
    """A named rubric criterion with a one-line description."""

    name: str
    description: str


class Rubric(TypedDict):
    name: str
    criteria: list[Criterion]


def load_rubric(path: Path) -> Rubric:
    """Read a YAML or JSON rubric and report the path of any invalid field."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"Cannot read rubric {path}: {exc}") from exc

    def fields(value: object, expected: set[str], field: str) -> dict:
        if not isinstance(value, dict):
            raise ValueError(f"{path}: {field} must be a mapping")
        if missing := expected - value.keys():
            raise ValueError(f"{path}: {field}.{min(missing)} is required")
        if unknown := value.keys() - expected:
            raise ValueError(f"{path}: unknown field {field}.{min(map(str, unknown))}")
        return value

    def line(value: object, field: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.splitlines()) != 1:
            raise ValueError(f"{path}: {field} must be a non-empty single line of text")
        return value.strip()

    root = fields(raw, {"name", "criteria"}, "rubric")
    name = line(root["name"], "name")
    if not isinstance(root["criteria"], list) or not root["criteria"]:
        raise ValueError(f"{path}: criteria must be a non-empty list")
    criteria: list[Criterion] = []
    seen = set()
    for index, value in enumerate(root["criteria"]):
        field = f"criteria[{index}]"
        criterion = fields(value, {"name", "description"}, field)
        label = line(criterion["name"], f"{field}.name")
        if label.casefold() in seen:
            raise ValueError(f"{path}: {field}.name duplicates a previous criterion")
        seen.add(label.casefold())
        criteria.append({"name": label,
                         "description": line(criterion["description"], f"{field}.description")})
    return {"name": name, "criteria": criteria}


class _Scenario(NamedTuple):
    title: str
    problem: str
    approach: str
    outcome: str
    units: str
    records: str


_SCENARIOS = (
    _Scenario("Bus wheelchair boarding",
              "A bus operator wants to reduce boarding delays for riders using wheelchairs.",
              "Dispatch would flag stops with repeated ramp failures for preventive maintenance.",
              "wheelchair boardings delayed by a ramp fault", "stops",
              "driver ramp-fault reports and scheduled maintenance logs"),
    _Scenario("Night pharmacy stock",
              "A hospital pharmacy wants to avoid emergency substitutions during night shifts.",
              "Night staff would get reorder prompts for medicines with recurring shortages.",
              "night shifts with an emergency substitution", "stock bins",
              "the pharmacy's dispense history and supplier lead-time records"),
    _Scenario("Shelter room turnover",
              "A shelter wants to shorten vacant periods between occupants without rushing cleaning.",
              "The desk would queue room turnovers from checkout through a cleaning sign-off.",
              "hours rooms sit empty between occupants", "rooms",
              "the shelter's checkout and cleaning timestamps"),
    _Scenario("Small-farm irrigation",
              "A vegetable cooperative wants to limit irrigation water without damaging crops.",
              "Growers would schedule watering by soil moisture and check affected plots for stress.",
              "litres used per marketable crate", "plots",
              "readings from soil probes the cooperative already owns"),
    _Scenario("Campus heat pumps",
              "A campus wants to cut energy use without increasing cold classrooms.",
              "Facilities would stagger heat-pump starts and keep the existing comfort limits.",
              "heating energy per occupied hour at the target temperature",
              "classrooms", "campus submeter readings"),
    _Scenario("Court appointment reminders",
              "A court wants fewer missed appointments without revealing case details in messages.",
              "It would send neutral reminders through the existing opt-in notification system.",
              "scheduled appointments that are missed", "appointment slots",
              "the court calendar and delivery receipts"),
    _Scenario("Library laptop lending",
              "A library wants fewer long waits for laptops without shortening loan periods.",
              "It would release reserved devices when a pickup expires and keep a walk-in reserve.",
              "loan requests still waiting after a day", "laptops",
              "local checkout timestamps and the reservation queue"),
    _Scenario("Refrigerated deliveries",
              "A meal distributor wants fewer temperature excursions in refrigerated vans.",
              "Drivers would get alerts early enough to inspect seals and move stock if needed.",
              "minutes stock spends outside the safe temperature range", "delivery runs",
              "van temperature loggers and delivery timestamps"),
    _Scenario("Water leak dispatch",
              "A water utility needs to find service-line leaks before they cause road closures.",
              "The dispatch desk would combine recurring low-flow alerts with repair tickets.",
              "leaks repaired before a road closure", "service lines",
              "municipal flow gauges and existing repair tickets"),
    _Scenario("Factory changeovers",
              "A food plant wants shorter line changeovers without relaxing allergen checks.",
              "The plant would stage clean tooling off-line before the previous run ends.",
              "minutes per changeover that passes the existing allergen check",
              "changeovers",
              "line timestamps and the plant's sanitation checklist"),
    _Scenario("Storm drain inspections",
              "A city cannot inspect every drain before heavy rain and wants fewer street floods.",
              "Crews would schedule repeat blockages and verify drain clearance with site photos.",
              "flood calls in the inspected service area", "drains",
              "the city's inspection records and flood reports"),
    _Scenario("Job training appointments",
              "A training program wants to reduce missed intake meetings for shift workers.",
              "The program would offer evening slots and let applicants move an existing booking.",
              "participants who miss an intake appointment", "intake bookings",
              "appointment records and the hours applicants volunteer"),
    _Scenario("Bike share rebalancing",
              "A bike share wants to cut empty-dock arrivals without adding overnight routes.",
              "The crew would move bikes earlier on existing routes when a station shows a deficit.",
              "arrivals at stations with no bikes available", "dock stations",
              "station counts and aggregated trip arrivals from its own fleet"),
    _Scenario("Museum humidity control",
              "A museum wants to keep display cases in range without closing galleries for rewiring.",
              "A conservator would adjust desiccant replacement using the current wireless sensors.",
              "hours display cases spend outside their humidity range",
              "display cases", "the museum's own case sensor history"),
    _Scenario("Online checkout timeouts",
              "A shop wants fewer checkout timeouts without relaxing payment safeguards.",
              "It would queue order confirmation separately while leaving payment checks in place.",
              "checkouts abandoned after a timeout", "checkout sessions",
              "the shop's request timings and payment status codes"),
)


class _Defect(NamedTuple):
    constraint: str
    detail: str
    strong: str
    weak: str
    note: str


_DEFECTS = {
    "throughput": _Defect(
        "Sign-off requires every one of the {scope} selected {units} to be checked. "
        "There are {shifts} staffed shifts before handover.",
        "An on-duty team can check at most {capacity} per shift; "
        "only that team can sign off on checks.",
        "Use {shifts} shifts for the checks and write up the results after the last shift.",
        "Use {short_shifts} shifts for the checks, then turn the last shift into a review "
        "meeting. The team will close the checklist before convening.",
        "The planned checking shifts times the per-shift limit cannot cover the full scope.",
    ),
    "budget": _Defect(
        "The pilot needs to cover {scope} {units} within a hard spending limit of ${budget}.",
        "The pilot must pay a fixed ${fixed} setup fee before any checks begin.",
        "Use the standard check at ${rate} per unit and log the result.",
        "Use the priority check at ${higher_rate} per unit so each result comes back before "
        "the next check begins. Log the result as soon as it arrives.",
        "The fixed fee plus the priority rate for the required scope exceeds the spending limit.",
    ),
    "privacy": _Defect(
        "Policy permits disclosure to third parties only as site-wide totals.",
        "The team will log a reference number for every unit checked.",
        "Ask the contractor to review a single count for the whole operation.",
        "Give the contractor the spreadsheet with one line per unit and its reference "
        "number so the contractor can check each entry against the summary.",
        "Line-by-line contractor access violates the aggregate-only disclosure rule.",
    ),
}

_STYLES = (
    ("{approach}", "{detail}", "{measurement}"),
    ("{detail}", "{measurement}", "{approach}"),
    ("{measurement}", "{approach}", "{detail}"),
)
_COSMETIC = (
    "This seems worth trying. The first readout may look a bit plain.",
    "I think this is a reasonable first pass. The summary could use a clearer heading.",
    "This could be a useful start, even if the first chart is not pretty.",
)
_POLISH = (
    "The scorecard will compare one {weeks}-week pilot window with the preceding "
    "{weeks} weeks. A weekly dashboard will show both the numerator and denominator.",
    "Publish {weeks} weekly snapshots and a final chart against the prior {weeks}-week "
    "baseline. The closing report will show the change and the size of the sample.",
    "Track the measure weekly for {weeks} weeks and compare it with the preceding "
    "{weeks} weeks. Publish the sample size and the week-by-week trend.",
)


def opposite(side: Side) -> Side:
    return "b" if side == "a" else "a"


def synthetic_pairs(seed: int = DEFAULT_SEED) -> list[Pair]:
    """Build versioned hard pairs, holding out all test domains from the dev split."""
    rng = random.Random(seed)
    scenarios = list(_SCENARIOS)
    rng.shuffle(scenarios)
    pairs: list[Pair] = []
    groups: tuple[tuple[Split, int, list[_Scenario]], ...] = (
        ("dev", 8, scenarios[:4]), ("test", 30, scenarios[4:]),
    )
    for split, count, domains in groups:
        defects = list(_DEFECTS)
        rng.shuffle(defects)
        sides: list[Side] = ["a", "b"] * (count // 2)
        rng.shuffle(sides)
        for i, better in enumerate(sides):
            trial, domain = divmod(i, len(domains))
            scenario = domains[domain]
            code = defects[(domain + trial) % len(defects)]
            defect = _DEFECTS[code]
            shifts, capacity = rng.randint(3, 6), rng.randint(6, 11)
            scope = shifts * capacity - rng.randint(1, capacity - 1)
            fixed, rate = rng.randrange(120, 301, 10), rng.randint(15, 28)
            fields = dict(units=scenario.units, shifts=shifts, short_shifts=shifts - 1,
                          capacity=capacity, scope=scope, fixed=fixed, rate=rate,
                          higher_rate=rate + rng.randint(1, 3),
                          budget=fixed + rate * scope + rng.randint(1, scope - 1))
            problem = f"{scenario.problem} {defect.constraint.format(**fields)}"
            measurement = (f"Use {scenario.records} to compare {scenario.outcome} "
                           "with the pre-pilot baseline.")
            style = rng.choice(_STYLES)
            context = [part.format(approach=scenario.approach, measurement=measurement,
                                   detail=defect.detail.format(**fields)) for part in style]
            shared = [problem, *context]
            strong = Item(title=scenario.title, text="\n\n".join(
                [*shared, defect.strong.format(**fields), rng.choice(_COSMETIC)],
            ))
            weak = Item(title=scenario.title, text="\n\n".join([
                *shared, defect.weak.format(**fields),
                rng.choice(_POLISH).format(weeks=rng.randint(2, 6)),
            ]))
            pairs.append({
                "id": f"synthetic-{split}-{i + 1:02d}", "source": "synthetic",
                "version": DATASET_VERSION, "split": split, "rubric": DEFAULT_RUBRIC,
                "a": strong if better == "a" else weak, "b": strong if better == "b" else weak,
                "better": better, "note": f"{code}: {defect.note}",
            })
    return pairs


_FILLER = (
    "The background to the proposal is relevant to the way the plan is presented.",
    "The plan sets out an approach to the problem described in the proposal.",
    "The description of the problem helps put the proposed work in context.",
    "The rationale and the approach should be read together when considering the proposal.",
    "The work described here is intended to address the situation set out above.",
    "The proposal describes the intended work within the scope of the stated problem.",
    "This framing keeps the attention on the relationship between the issue and the response.",
    "The scope can be understood by reading the proposal alongside its stated objective.",
    "The background is included to make the intent of the proposed work easier to follow.",
    "The approach is described in terms of the problem that the proposal is addressing.",
    "Taken as a whole, the description sets out the work and the context for it.",
    "The focus of this discussion is the proposal as presented and the issue it describes.",
)
_TONE = (
    ("I am excited about this approach and confident in the direction.",
     "I would be enthusiastic about moving this proposal forward."),
    ("This is an exciting proposal, and I am convinced it deserves a close look.",
     "I feel strongly that this is the right direction."),
    ("I am genuinely enthusiastic about this work and eager to see it tried.",
     "I would back this approach with confidence."),
)


def position_variants(pairs: Sequence[Pair]) -> list[Variant]:
    return [
        variant
        for p in pairs
        for variant in (
            Variant(pair_id=p["id"], kind="position", order="ab",
                    a=p["a"], b=p["b"], better=p["better"]),
            Variant(pair_id=p["id"], kind="position", order="ba",
                    a=p["b"], b=p["a"], better=opposite(p["better"])),
        )
    ]


def _sample(pairs: Sequence[Pair], kind: str, seed: int, dev: int, test: int) -> Iterable[Pair]:
    for split, count in (("dev", dev), ("test", test)):
        candidates = sorted((p for p in pairs if p["split"] == split), key=lambda p: p["id"])
        random.Random(f"{seed}:{kind}:{split}").shuffle(candidates)
        picked = set()
        for source in ("synthetic", "iclr"):
            if first := next((pair for pair in candidates if pair["source"] == source), None):
                yield first
                picked.add(first["id"])
        remaining = [pair for pair in candidates if pair["id"] not in picked]
        yield from remaining[:count - len(picked)]


def _pad(text: str, rng: random.Random) -> str:
    target = len(text.split())
    sentences = list(_FILLER)
    rng.shuffle(sentences)
    padding: list[str] = []
    words = 0
    while words < target:
        sentence = sentences[len(padding) % len(sentences)]
        added = len(sentence.split())
        if padding and words + added - target > target - words:
            break
        padding.append(sentence)
        words += added
    return text + "\n\n" + " ".join(padding)


def _alter(p: Pair, kind: Literal["verbosity", "tone"], seed: int) -> Variant:
    rng = random.Random(f"{seed}:{kind}:{p['id']}")
    weak = opposite(p["better"])
    original = p[weak]
    if kind == "verbosity":
        text = _pad(original["text"], rng)
    else:
        before, after = rng.choice(_TONE)
        text = f"{before}\n\n{original['text']}\n\n{after}"
    variant = Variant(pair_id=p["id"], kind=kind, order="ab",
                      a=p["a"], b=p["b"], better=p["better"])
    variant[weak] = {"title": original["title"], "text": text}
    return variant


def verbosity_variants(pairs: Sequence[Pair], seed: int = DEFAULT_SEED) -> list[Variant]:
    return [_alter(p, "verbosity", seed) for p in _sample(pairs, "verbosity", seed, 3, 12)]


def tone_variants(pairs: Sequence[Pair], seed: int = DEFAULT_SEED) -> list[Variant]:
    return [_alter(p, "tone", seed) for p in _sample(pairs, "tone", seed, 3, 10)]


def build_variants(pairs: Sequence[Pair], seed: int = DEFAULT_SEED) -> list[Variant]:
    return position_variants(pairs) + verbosity_variants(pairs, seed) + tone_variants(pairs, seed)


def write_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")
