"""Anti-leak cleaning — MANDATORY before any benchmark evaluation.

The committee must only see the project's initial description: every clue of
victory (badges, 'winner', prize amounts, post-hoc mentions) is stripped, or
the benchmark measures nothing.
"""

from __future__ import annotations

import re

_LEAK_PATTERNS = [
    r"(?i)\b(grand[- ]prize|first[- ]place|1st[- ]place|2nd[- ]place|3rd[- ]place)\b[^.!?\n]*",
    r"(?i)\b(winner|winning|won|wins)\b[^.!?\n]*",
    r"(?i)\b(champion|finalist|runner[- ]up|laureate|awarded|award|prize|trophy)\b[^.!?\n]*",
    r"(?i)\b(best (overall|hack|project|use of)[^.!?\n]*)",
    r"(?i)\b(selected by the (judges|jury)[^.!?\n]*)",
    r"[🏆🥇🥈🥉🎖🏅]",
    r"\$\s?\d[\d,]*(\.\d+)?\s*(k|K)?(?=\D|$)",  # prize amounts
    r"(?i)\b(check out (the|our) (press|coverage|article)[^.!?\n]*)",
]

_COMPILED = [re.compile(p) for p in _LEAK_PATTERNS]


def strip_victory_clues(text: str) -> str:
    cleaned = text or ""
    for pattern in _COMPILED:
        cleaned = pattern.sub("", cleaned)
    # collapse the holes left behind
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip(" \n.-—")


def has_leak(text: str) -> bool:
    return any(p.search(text or "") for p in _COMPILED)
