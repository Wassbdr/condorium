"""Compare two small proposals against the pilot rubric."""

from pathlib import Path

from condorium import Rubric, compare


def main() -> None:
    """Load the bundled examples and print the vote from each review."""
    here = Path(__file__).resolve().parent
    result = compare(
        {"title": "Measure before replacing", "text": (here / "pilot-a.md").read_text("utf-8")},
        {"title": "Replace the fleet", "text": (here / "pilot-b.md").read_text("utf-8")},
        Rubric.load(here / "pilot-rubric.yaml"),
    )
    print(f"Winner: {result.winner}; debated: {bool(result.debate)}")
    for review in result.initial + result.debate:
        print(f"{review.role}: {review.preferred or 'abstain'}")


if __name__ == "__main__":
    main()
