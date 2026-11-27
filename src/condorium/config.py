"""Configuration: env-driven, no hardcoded providers, no external services."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"

COMMITTEE_GENERAL = ["judge", "believer", "scientist_eval", "skeptic", "investor", "strategist"]
COMMITTEE_HACKATHON = COMMITTEE_GENERAL + ["jury"]

# Prompts and demo traces bundled in the wheel (pyproject force-include):
# used when the working root has none, e.g. after `pip install` / `uvx`.
BUNDLED_DIR = Path(__file__).resolve().parent / "_data"

# Agents whose round-1 work includes live research: they get a longer timeout,
# run in the same parallel fan-out and never block the others.
RESEARCH_AGENTS = {"scientist_eval"}


def _repo_root() -> Path:
    """Root of the working project (where agents/, knowledge/, evaluations/ live).

    Resolution order: $CONDORIUM_HOME, then cwd if it has an agents/ dir,
    then the source checkout this package sits in.
    """
    env = os.environ.get("CONDORIUM_HOME")
    if env:
        return Path(env)
    cwd = Path.cwd()
    if (cwd / "agents" / "committee").is_dir():
        return cwd
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "agents" / "committee").is_dir():
        return checkout
    return cwd


@dataclass
class Settings:
    model: str = field(default_factory=lambda: os.environ.get("CONDORIUM_MODEL", DEFAULT_MODEL))
    lang: str = field(default_factory=lambda: os.environ.get("CONDORIUM_LANG", "en"))
    root: Path = field(default_factory=_repo_root)
    llm_timeout: int = 90
    research_timeout: int = 240  # scientist round-1 (papers + web)
    llm_retries: int = field(
        default_factory=lambda: int(os.environ.get("CONDORIUM_LLM_RETRIES", "2")))
    # forwarded to the provider when set (bench runs pin it for reproducibility)
    llm_seed: int | None = field(
        default_factory=lambda: int(s) if (s := os.environ.get("CONDORIUM_SEED")) else None)

    @property
    def agents_dir(self) -> Path:
        local = self.root / "agents"
        if local.is_dir() or not (BUNDLED_DIR / "agents").is_dir():
            return local
        return BUNDLED_DIR / "agents"

    @property
    def demo_dir(self) -> Path:
        local = self.root / "fixtures" / "demo"
        if local.is_dir() or not (BUNDLED_DIR / "fixtures" / "demo").is_dir():
            return local
        return BUNDLED_DIR / "fixtures" / "demo"

    @property
    def knowledge_dir(self) -> Path:
        return self.root / "knowledge"

    @property
    def evaluations_dir(self) -> Path:
        d = self.root / "evaluations"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def checkpoint_db(self) -> Path:
        return self.evaluations_dir / "checkpoints.sqlite"

    @property
    def track_record_file(self) -> Path:
        return self.root / "track_record.md"

    def committee(self, mode: str) -> list[str]:
        return COMMITTEE_HACKATHON if mode == "hackathon" else COMMITTEE_GENERAL


SETTINGS = Settings()
