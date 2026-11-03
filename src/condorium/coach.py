"""The Coach — closes the loop: measured errors -> rubric diffs.

ABSOLUTE RULES, enforced in code, not just in the prompt:
- the Coach NEVER applies a diff; each one goes through a human yes/no
- a proposal backed by fewer than 3 concordant cases is dropped
- every accepted diff is journaled in agents/CHANGELOG.md with its metric
"""

from __future__ import annotations

import difflib
import json
import re
import time
from pathlib import Path

from .config import SETTINGS
from .llm import complete_json
from .prompts import load_prompt, render
from .record import load_track_record

MIN_CASES = 3
EDITABLE_FOLDERS = ("committee", "community")

_WIN_RE = re.compile(r"\b(1st|first|1er|1ère|winner|won|win|victoire|gagn\w*|grand prize)\b",
                     re.IGNORECASE)
_NEGATION_RE = re.compile(r"\b(not|didn'?t|did not|no|pas|never|lost|perdu)\b", re.IGNORECASE)


def _is_win(result: str) -> bool:
    """'1st place' / 'winner' / 'victoire' -> True; '2nd place', 'did not win',
    'pas gagné' -> False. A podium that is not first is not a win."""
    text = result or ""
    return bool(_WIN_RE.search(text)) and not _NEGATION_RE.search(text)


def _proposal_path(agent_file: str) -> Path | None:
    """The coach may only touch committee/community rubrics."""
    if not agent_file:
        return None
    root = SETTINGS.agents_dir.resolve()
    path = (SETTINGS.agents_dir / agent_file).resolve()
    allowed = [root / folder for folder in EDITABLE_FOLDERS]
    if not any(path.is_relative_to(folder) for folder in allowed) or not path.is_file():
        return None
    return path


def _collect_errors() -> tuple[list[dict], list[dict], dict]:
    bench_file = SETTINGS.evaluations_dir / "bench_results.json"
    bench_errors = []
    if bench_file.exists():
        report = json.loads(bench_file.read_text(encoding="utf-8"))
        # ties count as misses; crashed pairs (correct=None) are no evidence
        bench_errors = [c for c in report.get("cases", []) if c.get("correct") is False]

    track_errors = []
    for outcome in load_track_record():
        verdict = outcome.get("verdict")
        won = _is_win(outcome.get("result") or "")
        if (verdict == "GO" and not won) or (verdict in ("ITERATE", "PIVOT") and won):
            track_errors.append({"case_id": f"record-{outcome['eval_id']}", **outcome})

    syco_file = SETTINGS.evaluations_dir / "sycophancy_results.json"
    bias = {}
    if syco_file.exists():
        report = json.loads(syco_file.read_text(encoding="utf-8"))
        bias = {
            "global": report.get("formulation_bias_global"),
            "per_agent": report.get("formulation_bias_per_agent", {}),
            "n_cases": len(report.get("cases", [])),
        }
    return bench_errors, track_errors, bias


def _agent_files_block() -> str:
    parts = []
    for path in sorted((SETTINGS.agents_dir / "committee").glob("*.md")):
        parts.append(f"=== {path.relative_to(SETTINGS.agents_dir)} ===\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def propose(max_error_chars: int = 30000) -> list[dict]:
    """Analyze errors and return validated proposals (>= MIN_CASES each)."""
    bench_errors, track_errors, bias = _collect_errors()
    if len(bench_errors) + len(track_errors) < MIN_CASES and not (
        bias.get("per_agent") and bias.get("n_cases", 0) >= MIN_CASES
    ):
        return []  # not enough signal: no proposal on isolated cases, ever

    prompt = load_prompt("system/coach.md")
    system = render(
        prompt.body,
        bench_errors=json.dumps(bench_errors, ensure_ascii=False)[:max_error_chars],
        track_errors=json.dumps(track_errors, ensure_ascii=False)[:max_error_chars],
        bias_report=json.dumps(bias, ensure_ascii=False),
        agent_files=_agent_files_block(),
    )
    result = complete_json(system, "Analyze and propose now.")
    proposals = (result or {}).get("proposals", []) if isinstance(result, dict) else []

    validated = []
    for p in proposals:
        if len(set(p.get("case_ids", []))) < MIN_CASES:
            continue  # anti-overfitting guardrail
        path = _proposal_path(p.get("agent_file", ""))
        if path is None or not p.get("rule_in_cause") or not p.get("replacement"):
            continue
        old_text = path.read_text(encoding="utf-8")
        if p["rule_in_cause"] not in old_text:
            continue  # the quoted rule must actually exist
        new_text = old_text.replace(p["rule_in_cause"], p["replacement"], 1)
        p["diff"] = "".join(difflib.unified_diff(
            old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
            fromfile=f"a/agents/{p['agent_file']}", tofile=f"b/agents/{p['agent_file']}",
        ))
        p["_new_text"] = new_text
        validated.append(p)
    return validated


def apply_proposal(proposal: dict) -> None:
    """Called ONLY after explicit human acceptance of this individual diff."""
    if not SETTINGS.agents_editable:
        raise RuntimeError("the prompts in use are the read-only copy bundled with the "
                           "package — run `panel init` to get an editable ./agents first")
    path = SETTINGS.agents_dir / proposal["agent_file"]
    path.write_text(proposal["_new_text"], encoding="utf-8")
    changelog = SETTINGS.agents_dir / "CHANGELOG.md"
    entry = (
        f"\n## {time.strftime('%Y-%m-%d')} — {proposal['agent_file']}\n\n"
        f"**Metric**: {proposal.get('metric', 'n/a')}\n"
        f"**Cases**: {', '.join(proposal.get('case_ids', []))}\n"
        f"**Rationale**: {proposal.get('rationale', '')}\n\n"
        f"```diff\n{proposal['diff']}\n```\n"
    )
    changelog.write_text(changelog.read_text(encoding="utf-8") + entry, encoding="utf-8")
