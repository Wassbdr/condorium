"""Plotly visualizations -> self-contained HTML, no server required.

Per evaluation (`panel report <id>`): score slope chart R1->R2, criteria
radar, influence arrows, relevant knowledge-graph view.
Global (`panel dashboard`): influence graph, agreement heatmap, severity,
and tournament ranking decomposition when available.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import plotly.graph_objects as go

from ..config import SETTINGS
from ..knowledge import kgraph
from ..state import opinion_scores
from . import stats, traces


def _fig_html(fig: go.Figure) -> str:
    return fig.to_html(full_html=False, include_plotlyjs=False, div_id=None)


def _page(title: str, divs: list[str]) -> str:
    # plotly.js is inlined once via a zero-size carrier figure -> the HTML
    # file is fully self-contained, no CDN, no server.
    carrier = go.Figure()
    carrier.update_layout(height=10, margin=dict(l=0, r=0, t=0, b=0),
                          xaxis_visible=False, yaxis_visible=False)
    plotlyjs = carrier.to_html(full_html=False, include_plotlyjs="inline")
    body = "\n".join(f'<section style="margin:24px 0">{d}</section>' for d in divs)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px}</style>"
        f"</head><body><h1>{title}</h1><div style='height:0;overflow:hidden'>{plotlyjs}</div>"
        f"{body}</body></html>"
    )


def slope_chart(record: dict) -> go.Figure:
    fig = go.Figure()
    r1, r2 = record.get("round1", {}), record.get("round2", {})
    for agent in sorted(set(r1) | set(r2)):
        s1, s2 = (r1.get(agent) or {}).get("score"), (r2.get(agent) or {}).get("score")
        if not isinstance(s1, (int, float)) and not isinstance(s2, (int, float)):
            continue
        fig.add_trace(go.Scatter(x=["round 1", "round 2"], y=[s1, s2],
                                 mode="lines+markers+text", name=agent,
                                 text=[agent, ""], textposition="middle left"))
    fig.update_layout(title="Deliberation: scores round 1 → round 2",
                      yaxis=dict(range=[0, 10.5], title="score"), showlegend=False)
    return fig


def radar_chart(record: dict) -> go.Figure:
    fig = go.Figure()
    criteria: list[str] = []
    per_agent: dict[str, dict] = {}
    for agent, op in record.get("round2", {}).items():
        cs = op.get("criteria_scores") or {}
        if cs:
            per_agent[agent] = cs
            criteria += [c for c in cs if c not in criteria]
    for agent, cs in per_agent.items():
        fig.add_trace(go.Scatterpolar(
            r=[cs.get(c) for c in criteria], theta=criteria, fill="toself", name=agent, opacity=0.55))
    fig.update_layout(title="Criteria radar (round 2, all agents superimposed)",
                      polar=dict(radialaxis=dict(range=[0, 10])))
    return fig


def _circle_layout(names: list[str]) -> dict[str, tuple[float, float]]:
    n = max(len(names), 1)
    return {name: (math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n))
            for i, name in enumerate(names)}


def influence_graph_fig(matrix: dict) -> go.Figure:
    agents = sorted(set(matrix) | {t for targets in matrix.values() for t in targets})
    pos = _circle_layout(agents)
    fig = go.Figure()
    for src, targets in matrix.items():
        for tgt, info in targets.items():
            x0, y0 = pos[src]
            x1, y1 = pos[tgt]
            fig.add_trace(go.Scatter(
                x=[x0, x1], y=[y0, y1], mode="lines",
                line=dict(width=1 + info["count"], color="rgba(120,120,200,0.5)"),
                hoverinfo="text",
                text=f"{src} → {tgt}: {info['count']} revisions, avg Δ {info['mean_amplitude']}",
                showlegend=False))
            fig.add_annotation(x=x1 + (x0 - x1) * 0.15, y=y1 + (y0 - y1) * 0.15,
                               ax=x0, ay=y0, axref="x", ayref="y",
                               showarrow=True, arrowhead=3, arrowwidth=1.2, opacity=0.6)
    fig.add_trace(go.Scatter(
        x=[pos[a][0] for a in agents], y=[pos[a][1] for a in agents],
        mode="markers+text", text=agents, textposition="top center",
        marker=dict(size=18, color="#4c6ef5"), showlegend=False))
    fig.update_layout(title="Influence graph (who makes whom revise)",
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


def agreement_heatmap(matrix: dict) -> go.Figure:
    agents = sorted(matrix)
    z = [[matrix.get(a, {}).get(b) for b in agents] for a in agents]
    fig = go.Figure(go.Heatmap(z=z, x=agents, y=agents, zmin=-1, zmax=1,
                               colorscale="RdBu", colorbar_title="corr"))
    fig.update_layout(title="Agreement matrix (score correlation, round 2)")
    return fig


def severity_bar(sev: dict) -> go.Figure:
    agents = sorted(sev)
    fig = go.Figure(go.Bar(x=agents, y=[sev[a]["mean_vs_median"] for a in agents]))
    fig.update_layout(title="Relative severity (mean score vs panel median)",
                      yaxis_title="Δ vs median")
    return fig


def kg_subgraph_fig(node_ids: list[str]) -> go.Figure | None:
    g = kgraph.load_graph()
    if g.number_of_nodes() == 0:
        return None
    keep = set(n for n in node_ids if n in g)
    for n in list(keep):
        keep |= set(g.successors(n)) | set(g.predecessors(n))
    if not keep:
        return None
    sub = g.subgraph(keep)
    pos = _circle_layout(sorted(sub.nodes))
    fig = go.Figure()
    for u, v, data in sub.edges(data=True):
        fig.add_trace(go.Scatter(x=[pos[u][0], pos[v][0]], y=[pos[u][1], pos[v][1]],
                                 mode="lines", line=dict(width=1, color="#aaa"),
                                 hoverinfo="text", text=data.get("type", ""), showlegend=False))
    colors = {"Project": "#4c6ef5", "Tech": "#40c057", "Theme": "#fab005",
              "Pattern": "#e64980", "Paper": "#15aabf", "Hackathon": "#868e96"}
    fig.add_trace(go.Scatter(
        x=[pos[n][0] for n in sub.nodes], y=[pos[n][1] for n in sub.nodes],
        mode="markers+text",
        text=[sub.nodes[n].get("label", n) for n in sub.nodes], textposition="top center",
        marker=dict(size=14, color=[colors.get(sub.nodes[n].get("type"), "#333") for n in sub.nodes]),
        showlegend=False))
    fig.update_layout(title="Knowledge-graph view (nodes relevant to this run)",
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig


def ranking_fig(run: dict, records: list[dict]) -> go.Figure:
    by_id = {r["eval_id"]: r for r in records}
    rows = (run.get("ranking") or {}).get("ranking", [])
    fig = go.Figure()
    agents: set[str] = set()
    for row in rows:
        rec = by_id.get(row.get("eval_id"), {})
        agents |= set(opinion_scores(rec.get("round2", {})))
    for agent in sorted(agents):
        xs, ys = [], []
        for row in rows:
            rec = by_id.get(row.get("eval_id"), {})
            xs.append(rec.get("idea", {}).get("title", row.get("eval_id")))
            ys.append(opinion_scores(rec.get("round2", {})).get(agent))
        fig.add_trace(go.Bar(name=agent, x=xs, y=ys))
    fig.update_layout(barmode="group", title="Tournament: verdict decomposition per idea",
                      yaxis=dict(range=[0, 10.5]))
    return fig


def eval_report(eval_id: str) -> Path:
    record = traces.load_eval(eval_id)
    divs = [_fig_html(slope_chart(record)), _fig_html(radar_chart(record))]
    influence = stats.influence_matrix([record])
    if influence:
        divs.append(_fig_html(influence_graph_fig(influence)))
    kg_nodes = record.get("idea", {}).get("inspired_by") or []
    if (kg_fig := kg_subgraph_fig(kg_nodes)) is not None:
        divs.append(_fig_html(kg_fig))
    syn = record.get("synthesis", {})
    divs.insert(0, f"<pre>{json.dumps(syn, indent=2, ensure_ascii=False)}</pre>")
    path = traces.eval_dir(eval_id) / "report.html"
    path.write_text(_page(f"Evaluation — {record.get('idea', {}).get('title', eval_id)}", divs),
                    encoding="utf-8")
    return path


def dashboard() -> Path:
    s = stats.full_stats()
    divs = []
    if s["influence"]:
        divs.append(_fig_html(influence_graph_fig(s["influence"])))
    if s["agreement"]:
        divs.append(_fig_html(agreement_heatmap(s["agreement"])))
    if s["severity"]:
        divs.append(_fig_html(severity_bar(s["severity"])))
    divs.append(f"<pre>{json.dumps(s['round_deltas'], indent=2)}</pre>")
    # latest tournament ranking, if any
    runs = sorted(SETTINGS.evaluations_dir.glob("*/run.json"))
    if runs:
        run = json.loads(runs[-1].read_text(encoding="utf-8"))
        if run.get("ranking"):
            divs.append(_fig_html(ranking_fig(run, traces.list_evals())))
    path = SETTINGS.evaluations_dir / "dashboard.html"
    path.write_text(_page(f"condorium dashboard — {s['n_evaluations']} evaluations", divs),
                    encoding="utf-8")
    return path
