"""Command-line inputs and output for pairwise comparison."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from .comparison import (
    Item,
    Rubric,
    compare,
    comparison_error,
    comparison_model,
    format_comparison,
    item_from_value,
)


def _read_text(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Cannot read {label} {path}. Supply a readable UTF-8 file.") from exc


def _argument(value: str, label: str, *, literal: bool) -> Item:
    if not literal and "\n" not in value:
        path = Path(value).expanduser()
        path_like = (path.suffix.lower() in {".md", ".markdown", ".txt", ".rst"}
                     or value.startswith(("./", "../", "/", "~/")))
        try:
            exists = path.exists()
        except OSError:
            exists = False
        if path_like or exists:
            try:
                return item_from_value({"title": path.stem, "text": _read_text(path, f"item {label}")},
                                       label)
            except ValueError as exc:
                raise ValueError(f"{exc} Use --text to pass literal text.") from exc
    return item_from_value(value, label)


def _batch_pairs(path: Path) -> list[tuple[str | None, Item, Item]]:
    pairs = []
    for number, line in enumerate(_read_text(path, "batch file").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or "a" not in row or "b" not in row:
                raise ValueError('Provide an object with "a" and "b" items.')
            pair_id = row.get("id")
            if pair_id is not None and not isinstance(pair_id, str):
                raise ValueError('"id" must be a string.')
            pairs.append((pair_id, item_from_value(row["a"], "A"), item_from_value(row["b"], "B")))
        except ValueError as exc:
            raise ValueError(f"{path}:{number}: {exc}") from exc
    if not pairs:
        raise ValueError(f"{path}: add at least one JSON pair with \"a\" and \"b\" items.")
    return pairs


def compare_command(
    a: Annotated[str | None, typer.Argument(help="Proposal A: a file path or inline text.")] = None,
    b: Annotated[str | None, typer.Argument(help="Proposal B: a file path or inline text.")] = None,
    rubric: Annotated[Path | None, typer.Option(help="YAML or JSON rubric; defaults to proposal.")] = None,
    model: Annotated[str | None, typer.Option(help="LiteLLM model ID.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit JSON (JSON Lines in batch).")] = False,
    batch: Annotated[Path | None, typer.Option(help="JSON Lines file with a and b items per line.")] = None,
    text: Annotated[bool, typer.Option("--text", help="Treat both arguments as literal text.")] = False,
) -> None:
    """Compare two proposals against a rubric, or evaluate a batch of pairs."""
    selected_model = comparison_model(model)
    try:
        if batch is not None:
            if a is not None or b is not None or text:
                raise ValueError("Use --batch without item arguments or --text.")
            pairs = _batch_pairs(batch)
        else:
            if a is None or b is None:
                raise ValueError("Supply two item arguments or use --batch PAIRS.jsonl.")
            pairs = [(None, _argument(a, "A", literal=text), _argument(b, "B", literal=text))]
        criteria = Rubric.default() if rubric is None else Rubric.load(rubric)
        for index, (pair_id, first, second) in enumerate(pairs, 1):
            result = compare(first, second, criteria, model=selected_model)
            if json_output:
                data = asdict(result)
                data["debated"] = bool(result.debate)
                if batch is not None:
                    data["id"] = pair_id if pair_id is not None else str(index)
                typer.echo(json.dumps(data, ensure_ascii=False))
            else:
                if batch is not None:
                    typer.echo(f"\nPair {pair_id if pair_id is not None else index}")
                typer.echo(format_comparison(result))
    except Exception as exc:
        error = comparison_error(exc, selected_model)
        if error is None:
            raise
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1) from None
