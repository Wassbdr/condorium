"""Compare proposals against a rubric with an evidence-checking committee."""

from .comparison import Comparison, Criterion, Evidence, Item, Review, Rubric, Winner, compare

__version__ = "0.2.0"
__all__ = ["Comparison", "Criterion", "Evidence", "Item", "Review", "Rubric", "Winner", "compare"]
