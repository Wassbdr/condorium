"""Fully mocked LLM + sandboxed working root. No network, no keys."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

FAKE_PAPER = {
    "title": "A mock paper on the eye-brain link",
    "url": "https://arxiv.org/abs/0000.00001",
    "abstract": "Mock abstract.",
    "year": "2025",
    "source": "arxiv",
}


def _opinion(score, round_no: int, extra: dict | None = None) -> dict:
    op = {
        "score": score,
        "criteria_scores": {"realism": score or 5},
        "verdict": "Direct, specific, neither flattering nor demolishing.",
        "strengths": ["a strength"],
        "watchouts": ["a doubt"],
        "proposed_tests": ["a 30-minute test"],
    }
    if round_no == 2:
        op["revision"] = "maintained"
        op["influenced_by"] = []
    if extra:
        op.update(extra)
    return op


class MockLLM:
    """Stands in for litellm: routes on prompt markers, fully configurable."""

    def __init__(self):
        self.calls: list[dict] = []
        self.scores: dict[str, int] = {}          # agent -> default score (both rounds)
        self.round2_scores: dict[str, int] = {}   # agent -> round-2 override
        self.round2_extra: dict[str, dict] = {}   # agent -> extra fields in round 2
        self.agent_extra: dict[str, dict] = {}    # agent -> extra fields in both rounds
        self.synthesis: dict | None = None
        self.n_gen_ideas = 3

    # -- routing -----------------------------------------------------------
    def __call__(self, *, model: str, messages: list[dict], timeout: int, **kw) -> str:
        system = messages[0]["content"]
        user = messages[-1]["content"]
        self.calls.append({"system": system, "user": user, "timeout": timeout})
        return json.dumps(self._route(system, user))

    def _route(self, system: str, user: str) -> dict:
        if "INTAKE step" in system:
            return {"restatement": "A neutral restatement of the idea.",
                    "implicit_assumptions": ["users exist"], "open_question": "who pays?"}
        if "fast pre-filter" in system:
            bump = 2 if "strong" in user else 0
            return {"theme_fit": 6 + bump, "wow_potential": 6 + bump,
                    "apparent_feasibility": 6 + bump, "one_liner": "fine"}
        if "SYNTHESIZER" in system and "closing a targeted debate" not in system:
            return self.synthesis or {
                "consensus": "Solid core, unproven adoption.",
                "disagreements": [], "verdict": "ITERATE", "action": "Interview 3 users."}
        if "closing a targeted debate" in system:
            return {"debate_outcome": "upheld", "conclusion": "Both narrowed.",
                    "verdict": "ITERATE", "verdict_changed": False}
        if "TARGETED DEBATE" in system:
            return {"response": "On this topic only.", "position_after": "narrowed",
                    "score_adjustment": 0}
        if "THE CLERK" in system:
            ids = [e for e in dict.fromkeys(re.findall(r'"eval_id": "([^"]+)"', system))
                   if e != "..."]  # skip the output example in the prompt body
            return {"ranking": [{"eval_id": e, "rank": i + 1, "justification": "per syntheses"}
                                for i, e in enumerate(ids)],
                    "winner": {"eval_id": ids[0] if ids else "", "action_plan": ["step 1"]}}
        if "HACKATHON GENERATOR" in system:
            return {"ideas": [{"title": f"gen idea {i}", "pitch": f"pitch {i}",
                               "tech": "python", "wow_moment": "live demo", "audience": "devs"}
                              for i in range(self.n_gen_ideas)]}
        if "SCIENTIST GENERATOR" in system:
            return {"ideas": [
                {"title": "cited idea", "pitch": "from a real paper", "tech": "cv",
                 "wow_moment": "photo demo", "strategy": "gap",
                 "references": [{"title": FAKE_PAPER["title"], "url": FAKE_PAPER["url"]}]},
                {"title": "uncited idea", "pitch": "from memory", "tech": "x",
                 "wow_moment": "none", "strategy": "gap",
                 "references": [{"title": "hallucinated", "url": "https://fake.example/nope"}]},
            ]}
        if "THE HISTORIAN" in system:
            return {"ideas": [{"title": "graph idea", "pitch": "recombined winners",
                               "tech": "nx", "wow_moment": "unexpected combo",
                               "move": "combination", "inspired_by": ["tech:python"]}],
                    "abstained": False}
        if "THE INTERVIEWER" in system:
            # scripted dialogue driven by how many user replies the
            # transcript already contains: Q1, Q2, trade-off, then done
            replies = system.count('"role": "user"')
            if replies == 0:
                return {"action": "ask", "question": "What breaks today?"}
            if replies == 1:
                return {"action": "ask", "question": "Who feels it worst?"}
            if replies == 2:
                return {"action": "tradeoff",
                        "wow_option": {"tech": "AR overlay", "wow": 9, "risk": 7},
                        "mastered_option": {"tech": "plain web", "wow": 5, "risk": 2}}
            return {"action": "done", "idea": {"title": "refined idea",
                                               "text": "problem, audience, tech, wow"}}
        if "Rewrite the idea" in system:
            return {"enthusiastic": "MY REVOLUTIONARY IDEA: base.",
                    "neutral": "base.", "deprecating": "a small idea, probably taken: base."}
        return self._committee(system, user)

    def _committee(self, system: str, user: str) -> dict:
        markers = [
            ("THE JUDGE", "judge"), ("THE BELIEVER", "believer"),
            ("You are THE SCIENTIST:", "scientist_eval"), ("THE SKEPTIC", "skeptic"),
            ("THE INVESTOR", "investor"), ("THE STRATEGIST", "strategist"),
            ("THE JURY MEMBER", "jury"),
        ]
        agent = next((name for marker, name in markers if marker in system), "unknown")
        round_no = 2 if user.startswith("ROUND 2") else 1
        score = self.scores.get(agent, 6)
        if round_no == 2 and agent in self.round2_scores:
            score = self.round2_scores[agent]
        extra = dict(self.agent_extra.get(agent, {}))
        if round_no == 2:
            extra.update(self.round2_extra.get(agent, {}))
        if agent == "scientist_eval" and "scientific_verdict" not in extra:
            extra.update({"scientific_verdict": "grounded",
                          "references": [{"title": FAKE_PAPER["title"], "url": FAKE_PAPER["url"]}]})
        if agent == "judge":
            extra.setdefault("viable_scope", "a reduced but demonstrable version")
        if agent == "believer":
            extra.setdefault("precedents", [{"name": "RealCo", "why_comparable": "same wedge"}])
        return _opinion(score, round_no, extra)


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    """Real prompt files, isolated evaluations/knowledge dirs."""
    from condorium.config import SETTINGS

    (tmp_path / "agents").symlink_to(REPO / "agents")
    (tmp_path / "knowledge").mkdir()
    monkeypatch.setattr(SETTINGS, "root", tmp_path)
    return tmp_path


@pytest.fixture
def mock_llm(monkeypatch, sandbox):
    from condorium import llm
    from condorium.graph import cohort, evaluation
    from condorium.sources.papers import Paper

    mock = MockLLM()
    monkeypatch.setattr(llm, "_completion", mock)

    def fake_papers(q, max_results=8):
        return [Paper(**dict(FAKE_PAPER))]

    def fake_web(q, max_results=6):
        return []
    monkeypatch.setattr(evaluation, "search_papers", fake_papers)
    monkeypatch.setattr(evaluation, "search_web", fake_web)
    monkeypatch.setattr(cohort, "search_papers", fake_papers)
    monkeypatch.setattr(cohort, "search_web", fake_web)
    return mock
