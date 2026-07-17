"""Terminal rendering (rich): per-agent scores, revisions, disagreements first."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

VERDICT_STYLE = {"GO": "bold green", "ITERATE": "bold yellow", "PIVOT": "bold red"}


def _fmt_score(v) -> str:
    return "∅" if v is None else str(v)


def show_evaluation(record: dict) -> None:
    idea = record.get("idea", {})
    console.rule(f"[bold]{idea.get('title', record.get('eval_id', '?'))}")
    intake = record.get("intake") or {}
    if intake:
        console.print(Panel(
            f"{intake.get('restatement', '')}\n\n"
            f"[dim]Assumptions:[/dim] {'; '.join(intake.get('implicit_assumptions', []))}\n"
            f"[dim]Open question:[/dim] {intake.get('open_question', '')}",
            title="Intake", border_style="blue"))

    table = Table(title="Committee", show_lines=False)
    table.add_column("Agent", style="cyan")
    table.add_column("R1", justify="right")
    table.add_column("R2", justify="right")
    table.add_column("↺", justify="center")
    table.add_column("Verdict", max_width=70)
    r1, r2 = record.get("round1", {}), record.get("round2", {})
    for name in sorted(set(r1) | set(r2)):
        o1, o2 = r1.get(name, {}), r2.get(name, {})
        revised = o2.get("revision") not in (None, "", "maintained")
        flags = []
        if revised:
            flags.append("↺")
        if o2.get("capped"):
            flags.append("cap")
        if o2.get("scientific_verdict"):
            flags.append(o2["scientific_verdict"])
        table.add_row(
            name, _fmt_score(o1.get("score")), _fmt_score(o2.get("score")),
            " ".join(flags), (o2.get("verdict") or o1.get("verdict") or "")[:200],
        )
    console.print(table)

    syn = record.get("synthesis") or {}
    verdict = syn.get("verdict", "?")
    lines = [f"[{VERDICT_STYLE.get(verdict, 'bold')}]{verdict}[/]  {syn.get('consensus', '')}"]
    for d in syn.get("disagreements") or []:
        crit = " [red](critical)[/red]" if d.get("critical") else ""
        lines.append(f"\n[bold]Disagreement[/bold]{crit} — {d.get('topic', '')} "
                     f"[dim](gap {d.get('gap', '?')}: {', '.join(d.get('agents', []))})[/dim]\n"
                     f"  {d.get('positions', '')}\n  [dim]{d.get('why_it_matters', '')}[/dim]")
    if syn.get("debate_outcome"):
        lines.append(f"\n[bold]Targeted debate[/bold]: {syn['debate_outcome']} — "
                     f"{syn.get('debate_conclusion', '')}")
    lines.append(f"\n[bold]Next action[/bold]: {syn.get('action', '')}")
    console.print(Panel("\n".join(lines), title="Synthesis", border_style="magenta"))


def show_ranking(run: dict, evaluations: list[dict] | None = None) -> None:
    ranking = run.get("ranking") or {}
    table = Table(title="Tournament ranking")
    table.add_column("#", justify="right")
    table.add_column("Idea")
    table.add_column("Provenance", style="dim")
    table.add_column("Verdict")
    table.add_column("Justification", max_width=60)
    by_id = {e.get("eval_id"): e for e in evaluations or []}
    provenances = run.get("provenances", {})
    for row in ranking.get("ranking", []):
        eid = row.get("eval_id")
        rec = by_id.get(eid, {})
        table.add_row(
            str(row.get("rank", "?")),
            rec.get("idea", {}).get("title", eid or "?"),
            str(provenances.get(eid, "?")),  # provenance revealed only here
            (rec.get("synthesis") or {}).get("verdict", "?"),
            row.get("justification", "")[:200],
        )
    console.print(table)
    winner = ranking.get("winner") or {}
    if winner:
        plan = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(winner.get("action_plan", [])))
        console.print(Panel(f"Winner: {winner.get('eval_id')}\n{plan}",
                            title="Action plan", border_style="green"))


def show_prefilter(payload: dict) -> None:
    table = Table(title="Pre-filter ranking")
    table.add_column("#", justify="right")
    table.add_column("Idea")
    table.add_column("Theme fit", justify="right")
    table.add_column("Wow", justify="right")
    table.add_column("Feasible", justify="right")
    table.add_column("Total", justify="right", style="bold")
    for i, row in enumerate(payload.get("ranking", []), start=1):
        table.add_row(str(i), row.get("title", "?"), str(row.get("theme_fit", "?")),
                      str(row.get("wow_potential", "?")),
                      str(row.get("apparent_feasibility", "?")), str(row.get("total", "?")))
    console.print(table)
