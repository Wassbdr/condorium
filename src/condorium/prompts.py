"""Prompt loading: every agent prompt lives in agents/*.md — never in code.

File naming: `<agent>.md` (all modes) or `<agent>.<mode>.md` (one mode).
Each file has YAML frontmatter (see agents/community/SCHEMA.md) and a body.
Community agents in agents/community/ are picked up automatically.
`--lang fr` loads agents/fr/<same path> when it exists, else falls back to English.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import SETTINGS


@dataclass
class AgentPrompt:
    name: str
    layer: str  # committee | generator | system
    modes: list[str]
    body: str
    meta: dict = field(default_factory=dict)
    community: bool = False

    @property
    def timeout(self) -> int | None:
        return self.meta.get("timeout")


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_agent_file(path: Path) -> AgentPrompt:
    text = path.read_text(encoding="utf-8")
    meta: dict = {}
    body = text
    if (m := _FRONTMATTER_RE.match(text)) is not None:
        meta = yaml.safe_load(m.group(1)) or {}
        body = text[m.end() :]
    stem_parts = path.stem.split(".")
    name = meta.get("name", stem_parts[0])
    modes = meta.get("modes") or (stem_parts[1:2] or ["general", "hackathon"])
    layer = meta.get("layer", path.parent.name.rstrip("s") if path.parent.name != "community" else "committee")
    return AgentPrompt(name=name, layer=layer, modes=list(modes), body=body.strip(), meta=meta,
                       community=path.parent.name == "community")


def _localized(path: Path, lang: str) -> Path:
    if lang and lang != "en":
        candidate = SETTINGS.agents_dir / lang / path.relative_to(SETTINGS.agents_dir)
        if candidate.exists():
            return candidate
    return path


def load_prompt(relative: str, lang: str | None = None) -> AgentPrompt:
    """e.g. load_prompt('system/intake.md') or load_prompt('committee/believer.md')."""
    path = _localized(SETTINGS.agents_dir / relative, lang or SETTINGS.lang)
    return parse_agent_file(path)


def committee_prompts(mode: str, lang: str | None = None) -> dict[str, AgentPrompt]:
    """All committee agents active for `mode`, keyed by name, base contract prepended."""
    base = load_prompt("committee/_base.md", lang).body
    agents: dict[str, AgentPrompt] = {}
    for folder in ("committee", "community"):
        d = SETTINGS.agents_dir / folder
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.md")):
            if path.stem.startswith("_") or path.stem.upper() == "SCHEMA":
                continue
            prompt = parse_agent_file(_localized(path, lang or SETTINGS.lang))
            if folder == "community" and prompt.meta.get("layer", "committee") != "committee":
                continue
            if mode not in prompt.modes:
                continue
            # Mode-specific file wins over the generic one for the same agent.
            if prompt.name in agents and len(agents[prompt.name].modes) == 1:
                continue
            prompt.body = f"{base}\n\n{prompt.body}"
            agents[prompt.name] = prompt
    return agents


def generator_prompt(name: str, lang: str | None = None) -> AgentPrompt:
    return load_prompt(f"generators/{name}.md", lang)


_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def render(template: str, **values: object) -> str:
    """Substitute {placeholders} for provided keys only; leave JSON braces alone."""
    return _PLACEHOLDER_RE.sub(
        lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template
    )
