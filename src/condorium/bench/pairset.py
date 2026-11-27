"""Seeded proposal pairs and perturbations for pairwise benchmarks."""

from __future__ import annotations

import json
import random
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Literal, NamedTuple, TypedDict

import yaml

DEFAULT_SEED = 42
DEFAULT_RUBRIC = "proposal"
Split = Literal["dev", "test"]
Side = Literal["a", "b"]


class Item(TypedDict):
    """A proposal with a display title and its full text."""

    title: str
    text: str


class Pair(TypedDict):
    id: str
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
    unavailable: str
    fallback: str


_SCENARIOS = (
    _Scenario("Bus wheelchair boarding",
              "A bus operator wants to reduce boarding delays for riders using wheelchairs.",
              "Dispatch would flag stops with repeated ramp failures for preventive maintenance.",
              "wheelchair boardings delayed by a ramp fault", "historical passenger GPS traces",
              "driver ramp-fault reports and scheduled maintenance logs"),
    _Scenario("Night pharmacy stock",
              "A hospital pharmacy wants to avoid emergency substitutions during night shifts.",
              "Night staff would get reorder prompts for medicines with recurring shortages.",
              "night shifts with an emergency substitution", "supplier-level demand forecasts",
              "the pharmacy's dispense history and supplier lead-time records"),
    _Scenario("Shelter room turnover",
              "A shelter wants to shorten vacant periods between occupants without rushing cleaning.",
              "The desk would queue room turnovers from checkout through a cleaning sign-off.",
              "hours rooms sit empty between occupants", "case files from other shelters",
              "the shelter's checkout and cleaning timestamps"),
    _Scenario("Small-farm irrigation",
              "A vegetable cooperative wants to limit irrigation water without damaging crops.",
              "Growers would schedule watering by soil moisture and check affected plots for stress.",
              "litres used per marketable crate", "proprietary satellite moisture snapshots",
              "readings from soil probes the cooperative already owns"),
    _Scenario("Campus heat pumps",
              "A campus wants to cut energy use without increasing cold classrooms.",
              "Facilities would stagger heat-pump starts and keep the existing comfort limits.",
              "heating energy per occupied hour at the target temperature",
              "the utility's unpublished feeder readings", "campus submeter readings"),
    _Scenario("Court appointment reminders",
              "A court wants fewer missed appointments without revealing case details in messages.",
              "It would send neutral reminders through the existing opt-in notification system.",
              "scheduled appointments that are missed", "private phone-carrier location data",
              "the court calendar and delivery receipts"),
    _Scenario("Library laptop lending",
              "A library wants fewer long waits for laptops without shortening loan periods.",
              "It would release reserved devices when a pickup expires and keep a walk-in reserve.",
              "loan requests still waiting after a day", "patron profiles from neighboring systems",
              "local checkout timestamps and the reservation queue"),
    _Scenario("Refrigerated deliveries",
              "A meal distributor wants fewer temperature excursions in refrigerated vans.",
              "Drivers would get alerts early enough to inspect seals and move stock if needed.",
              "minutes stock spends outside the safe temperature range", "customer kitchen sensors",
              "van temperature loggers and delivery timestamps"),
    _Scenario("Water leak dispatch",
              "A water utility needs to find service-line leaks before they cause road closures.",
              "The dispatch desk would combine recurring low-flow alerts with repair tickets.",
              "leaks repaired before a road closure", "live feeds from privately owned meters",
              "municipal flow gauges and existing repair tickets"),
    _Scenario("Factory changeovers",
              "A food plant wants shorter line changeovers without relaxing allergen checks.",
              "The plant would stage clean tooling off-line before the previous run ends.",
              "minutes per changeover that passes the existing allergen check",
              "the equipment maker's confidential maintenance dataset",
              "line timestamps and the plant's sanitation checklist"),
    _Scenario("Storm drain inspections",
              "A city cannot inspect every drain before heavy rain and wants fewer street floods.",
              "Crews would schedule repeat blockages and verify drain clearance with site photos.",
              "flood calls in the inspected service area", "private building basement sensors",
              "the city's inspection records and flood reports"),
    _Scenario("Job training appointments",
              "A training program wants to reduce missed intake meetings for shift workers.",
              "The program would offer evening slots and let applicants move an existing booking.",
              "participants who miss an intake appointment", "employer payroll schedules",
              "appointment records and the hours applicants volunteer"),
    _Scenario("Bike share rebalancing",
              "A bike share wants to cut empty-dock arrivals without adding overnight routes.",
              "The crew would move bikes earlier on existing routes when a station shows a deficit.",
              "arrivals at stations with no bikes available", "personal trip logs from rival apps",
              "station counts and aggregated trip arrivals from its own fleet"),
    _Scenario("Museum humidity control",
              "A museum wants to keep display cases in range without closing galleries for rewiring.",
              "A conservator would adjust desiccant replacement using the current wireless sensors.",
              "hours display cases spend outside their humidity range",
              "manufacturer-only conservation logs", "the museum's own case sensor history"),
    _Scenario("Online checkout timeouts",
              "A shop wants fewer checkout timeouts without relaxing payment safeguards.",
              "It would queue order confirmation separately while leaving payment checks in place.",
              "checkouts abandoned after a timeout", "card networks' unpublished retry traces",
              "the shop's request timings and payment status codes"),
)


class _Defect(NamedTuple):
    constraint: str
    strong: str
    weak: str
    note: str


_DEFECTS = {
    "measurement": _Defect(
        "The pilot must show whether service actually improved.",
        "Judge the pilot by the change in {outcome} against a comparable pre-pilot window.",
        "Judge the pilot by whether the rollout checklist is complete on the review date.",
        "The completion checklist measures activity, not the service outcome.",
    ),
    "schedule": _Defect(
        "The pilot must start in six weeks and touches a shared operations system.",
        "Run the first trial beside the shared system and migrate it after the pilot is reviewed.",
        "Start the trial after replacing the shared operations system in the third month.",
        "A third-month dependency misses the six-week start deadline.",
    ),
    "unavailable-data": _Defect(
        "The team cannot obtain {unavailable}.",
        "Use {fallback} to set up and operate the pilot.",
        "Use {unavailable} as the input required for running the pilot.",
        "The proposed input is explicitly unavailable, whereas local records are available.",
    ),
    "staffing": _Defect(
        "No extra overnight staff can be assigned.",
        "Queue work outside the staffed window and assign it to the next scheduled shift.",
        "Keep the queue current by assigning an additional operator to cover each night shift.",
        "The plan depends on extra overnight staff despite the staffing constraint.",
    ),
    "unsupported-claim": _Defect(
        "The team needs an evidence-backed performance forecast before committing to expansion.",
        "Use the pilot to estimate the achievable improvement before committing to a target.",
        "Commit to a tenfold improvement based on the assumption that rollout speed predicts impact.",
        "Rollout speed does not support the tenfold performance forecast.",
    ),
    "privacy": _Defect(
        "Policy prohibits transferring identifiable records outside the organization.",
        "Keep identifiable logs on-premises and share only aggregate pilot counts.",
        "Send identifiable pilot logs to a hosted analysis vendor for the weekly review.",
        "Sending identifiable logs to an outside vendor violates policy.",
    ),
    "incumbent": _Defect(
        "The existing operations tool remains mandatory because it is the auditable record.",
        "Keep the existing tool as the record and reconcile pilot actions to its entries.",
        "Replace logging in the existing tool with a separate record maintained by the pilot.",
        "The pilot stops logging in the required system of record.",
    ),
}

_STYLES = (
    ("{problem} {constraint}", "{approach}", "{measurement}", "{decision}"),
    ("{problem} {constraint}", "{approach}", "{decision}", "{measurement}"),
    ("{problem} {constraint}", "{measurement}", "{approach}", "{decision}"),
)
_POLISH = (
    "Treat this as a focused operating trial rather than a system redesign. "
    "The case for moving ahead is the direct link between the change and the service problem.",
    "This is a practical starting point. The review can stay focused on whether the proposed "
    "change addresses the problem, not whether the team can draft a more elaborate plan.",
    "The proposal is deliberately narrow. That makes it worth trying as written rather than "
    "waiting for a larger program to settle the same operating question.",
)


def opposite(side: Side) -> Side:
    return "b" if side == "a" else "a"


def synthetic_pairs(seed: int = DEFAULT_SEED) -> list[Pair]:
    """Build forty pairs, holding out all test domains from the dev split."""
    rng = random.Random(seed)
    scenarios = list(_SCENARIOS)
    rng.shuffle(scenarios)
    pairs: list[Pair] = []
    groups: tuple[tuple[Split, int, list[_Scenario]], ...] = (
        ("dev", 10, scenarios[:5]), ("test", 30, scenarios[5:]),
    )
    for split, count, domains in groups:
        defects = list(_DEFECTS)
        rng.shuffle(defects)
        hard = [True, False] * (count // 2)
        rng.shuffle(hard)
        sides: list[Side] = ["a", "b"] * (count // 2)
        rng.shuffle(sides)
        for i, (is_hard, better) in enumerate(zip(hard, sides, strict=True)):
            trial, domain = divmod(i, len(domains))
            scenario = domains[domain]
            code = defects[(domain + 3 * trial) % len(defects)]
            defect = _DEFECTS[code]
            fields = scenario._asdict()
            measurement = f"Compare {scenario.outcome} with the pre-pilot baseline."
            style = rng.choice(_STYLES)

            def text(decision: str) -> str:
                lines = {
                    **fields, "constraint": defect.constraint.format(**fields),
                    "measurement": "" if code == "measurement" else measurement,
                    "decision": decision.format(**fields),
                }
                return "\n\n".join(part for t in style if (part := t.format(**lines)))

            strong = Item(title=scenario.title, text=text(defect.strong))
            weak = Item(title=scenario.title, text=text(defect.weak))
            if is_hard:
                weak["text"] += "\n\n" + rng.choice(_POLISH)
            pairs.append({
                "id": f"synthetic-{split}-{i + 1:02d}", "source": "synthetic",
                "split": split, "rubric": DEFAULT_RUBRIC,
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
        yield from random.Random(f"{seed}:{kind}:{split}").sample(
            candidates, min(count, len(candidates)),
        )


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
    return [_alter(p, "verbosity", seed) for p in _sample(pairs, "verbosity", seed, 4, 12)]


def tone_variants(pairs: Sequence[Pair], seed: int = DEFAULT_SEED) -> list[Variant]:
    return [_alter(p, "tone", seed) for p in _sample(pairs, "tone", seed, 4, 10)]


def build_variants(pairs: Sequence[Pair], seed: int = DEFAULT_SEED) -> list[Variant]:
    return position_variants(pairs) + verbosity_variants(pairs, seed) + tone_variants(pairs, seed)


def write_jsonl(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")
