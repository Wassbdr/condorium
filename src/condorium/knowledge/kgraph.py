"""Knowledge graph on NetworkX — no external database.

Typed nodes: Project, Hackathon, Tech, Theme, Paper, Pattern.
Typed edges: WON, USES, ABOUT, INSPIRED_BY, EXPLOITS_PATTERN.
Serialized to knowledge/graph.json (node-link format), rebuilt incrementally
on every ingestion.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import networkx as nx

from ..config import SETTINGS

NODE_TYPES = {"Project", "Hackathon", "Tech", "Theme", "Paper", "Pattern"}
EDGE_TYPES = {"WON", "USES", "ABOUT", "INSPIRED_BY", "EXPLOITS_PATTERN"}


def _graph_file() -> Path:
    return SETTINGS.knowledge_dir / "graph.json"


def _slug(kind: str, label: str) -> str:
    return f"{kind.lower()}:{re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-')}"


def load_graph() -> nx.MultiDiGraph:
    f = _graph_file()
    if not f.exists():
        return nx.MultiDiGraph()
    data = json.loads(f.read_text(encoding="utf-8"))
    return nx.node_link_graph(data, directed=True, multigraph=True, edges="edges")


def save_graph(g: nx.MultiDiGraph) -> None:
    f = _graph_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    data = nx.node_link_data(g, edges="edges")
    f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def add_winner(g: nx.MultiDiGraph, entry: dict) -> None:
    """Incorporate one winner entry (schema of store.ENTRY_FIELDS + entities)."""
    proj = _slug("Project", entry.get("winning_project") or entry["id"])
    hack = _slug("Hackathon", entry.get("hackathon") or "unknown")
    g.add_node(proj, type="Project", label=entry.get("winning_project", entry["id"]),
               entry_id=entry["id"], pitch=entry.get("one_sentence_pitch", ""))
    g.add_node(hack, type="Hackathon", label=entry.get("hackathon", "unknown"),
               date=entry.get("date", ""))
    g.add_edge(proj, hack, key="WON", type="WON")

    ents = entry.get("entities", {}) or {}
    for tech in set((entry.get("stack") or []) + (ents.get("techs") or [])):
        t = _slug("Tech", tech)
        g.add_node(t, type="Tech", label=tech)
        g.add_edge(proj, t, key="USES", type="USES")
    for theme in set(([entry["theme"]] if entry.get("theme") else []) + (ents.get("themes") or [])):
        th = _slug("Theme", theme)
        g.add_node(th, type="Theme", label=theme)
        g.add_edge(proj, th, key="ABOUT", type="ABOUT")
    for pattern in ents.get("patterns") or []:
        p = _slug("Pattern", pattern)
        g.add_node(p, type="Pattern", label=pattern)
        g.add_edge(proj, p, key="EXPLOITS_PATTERN", type="EXPLOITS_PATTERN")
    for paper in ents.get("papers") or []:
        if not paper.get("title"):
            continue
        pp = _slug("Paper", paper["title"])
        g.add_node(pp, type="Paper", label=paper["title"], url=paper.get("url", ""))
        g.add_edge(proj, pp, key="INSPIRED_BY", type="INSPIRED_BY")


def ingest_entry(entry: dict) -> nx.MultiDiGraph:
    g = load_graph()
    add_winner(g, entry)
    save_graph(g)
    return g


def projects(g: nx.MultiDiGraph) -> list[str]:
    return [n for n, d in g.nodes(data=True) if d.get("type") == "Project"]


def neighbors_of_type(g: nx.MultiDiGraph, node: str, node_type: str) -> set[str]:
    out = set()
    for nbr in g.successors(node):
        if g.nodes[nbr].get("type") == node_type:
            out.add(nbr)
    return out


def project_similarity(g: nx.MultiDiGraph, a: str, b: str) -> float:
    """Jaccard over shared Tech/Theme/Pattern neighborhoods."""
    score = 0.0
    for t in ("Tech", "Theme", "Pattern"):
        na, nb = neighbors_of_type(g, a, t), neighbors_of_type(g, b, t)
        if na or nb:
            score += len(na & nb) / len(na | nb)
    return score / 3


def techs_mentioned(g: nx.MultiDiGraph, text: str) -> list[str]:
    """Labels of known Tech nodes named in free text (whole word, any case)."""
    lowered = (text or "").lower()
    found = []
    for _, d in g.nodes(data=True):
        label = d.get("label") or ""
        if d.get("type") == "Tech" and label and re.search(
                rf"(?<![a-z0-9]){re.escape(label.lower())}(?![a-z0-9])", lowered):
            found.append(label)
    return sorted(found)


def _excluded(g: nx.MultiDiGraph, project: str, exclude: dict | None) -> bool:
    """Bench anti-leak: a project (by title) or any winner of a given
    hackathon must never serve as its own calibration."""
    if not exclude:
        return False
    if project in {_slug("Project", t) for t in exclude.get("projects") or [] if t}:
        return True
    banned = {_slug("Hackathon", h) for h in exclude.get("hackathons") or [] if h}
    return bool(banned & neighbors_of_type(g, project, "Hackathon"))


def nearest_projects_to_context(g: nx.MultiDiGraph, techs: list[str], themes: list[str],
                                k: int = 5, *, min_overlap: int = 0,
                                exclude: dict | None = None) -> list[dict]:
    """The k winners closest to a (techs, themes) context — used for calibration.

    `min_overlap=1` drops winners sharing nothing with the context, so an
    unrelated project is never presented as "comparable"."""
    ctx_tech = {_slug("Tech", t) for t in techs}
    ctx_theme = {_slug("Theme", t) for t in themes}
    scored = []
    for p in projects(g):
        if _excluded(g, p, exclude):
            continue
        pt, pth = neighbors_of_type(g, p, "Tech"), neighbors_of_type(g, p, "Theme")
        overlap = len(pt & ctx_tech) + 2 * len(pth & ctx_theme)
        if overlap >= min_overlap:
            scored.append((overlap, p))
    scored.sort(key=lambda x: (-x[0], x[1]))
    out = []
    for overlap, p in scored[:k]:
        d = g.nodes[p]
        out.append({"node": p, "entry_id": d.get("entry_id"), "label": d.get("label"),
                    "pitch": d.get("pitch", ""), "overlap": overlap})
    return out


def unexploited_combinations(g: nx.MultiDiGraph, current_theme: str, max_items: int = 10) -> list[dict]:
    """Techs/patterns that won in >=2 other themes but never in the current one."""
    theme_node = _slug("Theme", current_theme) if current_theme else None
    combos = []
    for kind in ("Tech", "Pattern"):
        for node, d in g.nodes(data=True):
            if d.get("type") != kind:
                continue
            winning_projects = [p for p in g.predecessors(node)
                                if g.nodes[p].get("type") == "Project"]
            themes = set()
            for p in winning_projects:
                themes |= neighbors_of_type(g, p, "Theme")
            if len(themes) >= 2 and (theme_node not in themes):
                combos.append({
                    "node": node, "kind": kind, "label": d.get("label"),
                    "won_in_themes": sorted(g.nodes[t].get("label", t) for t in themes),
                    "projects": [g.nodes[p].get("label") for p in winning_projects],
                })
    combos.sort(key=lambda c: -len(c["won_in_themes"]))
    return combos[:max_items]


def historian_context(theme: str, techs: list[str] | None = None, k: int = 8) -> dict:
    """Everything the Historian prompt receives: nearest winners, gaps, patterns."""
    g = load_graph()
    if g.number_of_nodes() == 0:
        return {"empty": True, "nearest_winners": [], "unexploited": [], "patterns": []}
    patterns = [
        {"node": n, "label": d.get("label"),
         "used_by": [g.nodes[p].get("label") for p in g.predecessors(n)]}
        for n, d in g.nodes(data=True) if d.get("type") == "Pattern"
    ]
    return {
        "empty": False,
        "nearest_winners": nearest_projects_to_context(g, techs or [], [theme] if theme else [], k),
        "unexploited": unexploited_combinations(g, theme),
        "patterns": patterns[:15],
    }
