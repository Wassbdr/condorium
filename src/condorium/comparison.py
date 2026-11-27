"""Public helpers for comparing two items against a custom rubric."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import yaml

from .bench.pairset import Criterion, Item
from .bench.pairset import Rubric as ProtocolRubric
from .compare import MODEL, TEMPERATURE, Comparison, Evidence, Review, Winner
from .compare import compare as _compare
from .config import BUNDLED_DIR, SETTINGS
from .llm import OfflineCacheMiss, is_rate_limit

__all__ = ["Comparison", "Criterion", "Evidence", "Item", "Review", "Rubric", "Winner", "compare"]


def _mapping(value: object, keys: set[str], field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a mapping")
    if missing := keys - value.keys():
        raise ValueError(f"{field}.{min(missing)} is required")
    if unknown := value.keys() - keys:
        raise ValueError(f"{field}.{min(map(str, unknown))} is not a supported field")
    return value


def _line(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip().splitlines()) != 1:
        raise ValueError(f"{field} must be a non-empty single line of text")
    return value.strip()


@dataclass(frozen=True)
class Rubric:
    """A comparison rubric with a name and named criteria."""

    name: str
    criteria: tuple[Criterion, ...]

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Self:
        """Validate a mapping with a name and a non-empty list of criteria."""
        root = _mapping(data, {"name", "criteria"}, "rubric")
        name = _line(root["name"], "rubric.name")
        rows = root["criteria"]
        if not isinstance(rows, list) or not rows:
            raise ValueError("rubric.criteria must be a non-empty list")
        criteria: list[Criterion] = []
        seen = set()
        for index, row in enumerate(rows):
            field = f"rubric.criteria[{index}]"
            entry = _mapping(row, {"name", "description"}, field)
            label = _line(entry["name"], f"{field}.name")
            if label.casefold() in seen:
                raise ValueError(f"{field}.name duplicates an earlier criterion")
            seen.add(label.casefold())
            criteria.append({"name": label,
                             "description": _line(entry["description"], f"{field}.description")})
        return cls(name, tuple(criteria))

    @classmethod
    def from_yaml(cls, text: str) -> Self:
        """Parse and validate YAML text."""
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            mark = exc.problem_mark if isinstance(exc, yaml.MarkedYAMLError) else None
            location = f" on line {mark.line + 1}" if mark else ""
            raise ValueError(f"Invalid rubric YAML{location}") from exc
        return cls.from_dict(data)

    @classmethod
    def from_json(cls, text: str) -> Self:
        """Parse and validate JSON text."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid rubric JSON on line {exc.lineno}: {exc.msg}") from exc
        return cls.from_dict(data)

    @classmethod
    def load(cls, path: str | Path) -> Self:
        """Read a rubric file, using JSON for .json files and YAML otherwise."""
        path = Path(path).expanduser()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"Cannot read rubric {path}. Supply a readable UTF-8 rubric file.") from exc
        try:
            return cls.from_json(text) if path.suffix.lower() == ".json" else cls.from_yaml(text)
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from exc

    @classmethod
    def default(cls) -> Self:
        """Load the bundled proposal rubric."""
        return cls.load(default_rubric_path())


def default_rubric_path() -> Path:
    path = Path("benchmarks/rubrics/proposal.yaml")
    local = SETTINGS.root / path
    if local.is_file():
        return local
    checkout = Path(__file__).resolve().parents[2] / path
    return checkout if checkout.is_file() else BUNDLED_DIR / "rubrics/proposal.yaml"


def comparison_model(model: str | None = None) -> str:
    return model or os.environ.get("CONDORIUM_MODEL") or MODEL


def compare(
    a: Item | str,
    b: Item | str,
    rubric: Rubric,
    *,
    model: str | None = None,
    temperature: float = TEMPERATURE,
    seed: int = 0,
    variant_id: str = "",
) -> Comparison:
    """Compare two items with checked evidence and return the verdict and reviews.

    An item can be plain text or a mapping with a title and text. Set
    CONDORIUM_CACHE and CONDORIUM_OFFLINE to replay recorded requests.
    The comparison includes the winner, blind reviews, debate reviews, and
    token usage. A review records a role's preference and checked evidence.
    """
    protocol_rubric: ProtocolRubric = {"name": rubric.name, "criteria": list(rubric.criteria)}
    return _compare(item_from_value(a, "A"), item_from_value(b, "B"), protocol_rubric,
                    model=comparison_model(model), temperature=temperature, seed=seed,
                    variant_id=variant_id)


def item_from_value(value: object, label: str) -> Item:
    if isinstance(value, str):
        value = {"title": f"Proposal {label}", "text": value}
    field = f"Item {label}"
    entry = _mapping(value, {"title", "text"}, field)
    text = entry["text"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{field}.text must be non-empty text")
    return {"title": _line(entry["title"], f"{field}.title"), "text": text}


def comparison_error(exc: Exception, model: str) -> str | None:
    if isinstance(exc, OfflineCacheMiss):
        return (f"Offline cache miss for {model}. Set CONDORIUM_CACHE to a directory with a "
                f"matching response, or unset CONDORIUM_OFFLINE and set {_provider_key(model)}.")
    if isinstance(exc, ValueError):
        return str(exc)
    kind = type(exc).__name__
    status = getattr(exc, "status_code", None)
    provider_error = kind in {"OpenAIError", "BadRequestError", "APIError"} or (
        type(exc).__module__.startswith(("litellm.", "openai.", "anthropic."))
    )
    detail = str(exc).lower() if provider_error else ""
    if (status in (401, 403) or kind in {"AuthenticationError", "PermissionDeniedError"}
            or "api key" in detail or "api_key" in detail):
        return f"Authentication failed for {model}. Set or check {_provider_key(model)}, then retry."
    if is_rate_limit(exc):
        return f"{model} is rate limited. Wait and retry with the same CONDORIUM_CACHE."
    if provider_error:
        code = f" (HTTP {status})" if isinstance(status, int) else ""
        return f"Request to {model} failed{code}. Check the model ID and provider configuration."
    return None


def _provider_key(model: str) -> str:
    provider = model.split("/", 1)[0].lower() if "/" in model else "openai"
    keys = {
        "nvidia_nim": "NVIDIA_NIM_API_KEY or NIM_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    return keys.get(provider, "the provider's API key environment variable")


def format_comparison(result: Comparison) -> str:
    winner = {"a": "Proposal A", "b": "Proposal B", "tie": "Tie"}[result.winner]
    lines = [f"Winner: {winner}", f"Debate: {'yes' if result.debate else 'no'}"]
    for label, reviews in (("Blind votes", result.initial), ("Debate votes", result.debate)):
        if reviews:
            lines.extend(("", label))
            for review in reviews:
                lines.append(f"  {review.role}: {review.preferred or 'abstain'}")
                for evidence in review.evidence:
                    lines.append(f'    Proposal {evidence.proposal.upper()}: "{evidence.quote}"')
    return "\n".join(lines)
