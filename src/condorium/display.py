"""Terminal rendering (rich): per-agent scores, revisions, disagreements first."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

VERDICT_STYLE = {"GO": "bold green", "ITERATE": "bold yellow", "PIVOT": "bold red"}


def format_score(score: object) -> str:
    return "∅" if score is None else str(score)


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
            name, format_score(o1.get("score")), format_score(o2.get("score")),
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


def _clip(text: str | None, reserved: int = 26) -> str:
    width = max(24, console.width - reserved)
    text = " ".join((text or "").split())
    return text if len(text) <= width else text[: width - 1] + "…"


def believer_cap(record: dict) -> float | None:
    """The cap `_normalize` applies to the believer in round 2."""
    from .state import median, opinion_scores

    others = {k: v for k, v in (record.get("round1") or {}).items() if k != "believer"}
    med = median(list(opinion_scores(others).values()))
    return None if med is None else med + 3


REPLAY_BANNER = ("[bold black on yellow] REPLAY OF A RECORDED RUN [/] "
                 "[dim]no LLM call, no API key — outputs were recorded from a past live run[/dim]")


def show_deliberation(record: dict, pause: float = 0.0, source: str = "") -> None:
    """Replay one recorded evaluation step by step: blind round 1, the
    believer cap, round 2 revisions, then disagreements (never an average)."""
    import time

    def step() -> None:
        if pause:
            time.sleep(pause)

    idea = record.get("idea", {})
    console.print(REPLAY_BANNER)
    if source:
        console.print(f"[dim]trace: {source}[/dim]")
    console.rule(f"[bold]{idea.get('title', record.get('eval_id', '?'))}")
    console.print(f"[dim]{idea.get('text', '')}[/dim]")
    step()

    r1, r2 = record.get("round1", {}), record.get("round2", {})
    names = [n for n in r1 if n in r2] + [n for n in r2 if n not in r1]
    blind = Table(title="Round 1 — blind (no agent sees another)", title_justify="left")
    blind.add_column("Agent", style="cyan", no_wrap=True, min_width=14)
    blind.add_column("R1", justify="right", no_wrap=True, min_width=2)
    blind.add_column("One-line view")
    for name in names:
        o1 = r1.get(name, {})
        blind.add_row(name, format_score(o1.get("score")), _clip(o1.get("verdict")))
    console.print(blind)
    step()

    believer = r2.get("believer")
    limit = believer_cap(record)
    if believer and limit is not None:
        raw = believer.get("uncapped_score", believer.get("score"))
        state = (f"[bold red]{raw} → {believer.get('score')}  CAPPED[/]" if believer.get("capped")
                 else f"[green]{believer.get('score')} ≤ {limit:g}: within the cap[/]")
        console.print(Panel(
            f"believer round-2 score ≤ median(others' blind scores) + 3 = [bold]{limit:g}[/bold]"
            f"\nbeliever asked for {raw}  ->  {state}",
            title="Anti-sycophancy cap (enforced in code)", border_style="red"))
        step()

    deliberation = Table(title="Round 2 — after reading every round-1 opinion",
                         title_justify="left")
    deliberation.add_column("Agent", style="cyan", no_wrap=True, min_width=14)
    deliberation.add_column("R1", justify="right", no_wrap=True, min_width=2)
    deliberation.add_column("R2", justify="right", no_wrap=True, min_width=4)
    deliberation.add_column("Change")
    for name in names:
        o1, o2 = r1.get(name, {}), r2.get(name, {})
        s1, s2 = o1.get("score"), o2.get("score")
        moved = "" if s1 == s2 else ("[green]▲[/]" if (s2 or 0) > (s1 or 0) else "[red]▼[/]")
        deliberation.add_row(name, format_score(s1), f"{format_score(s2)} {moved}",
                             _clip(o2.get("verdict"), reserved=33))
    console.print(deliberation)
    step()

    syn = record.get("synthesis") or {}
    verdict = syn.get("verdict", "?")
    lines = [f"[{VERDICT_STYLE.get(verdict, 'bold')}]{verdict}[/]  {syn.get('consensus', '')}",
             "[dim]No average is computed: the disagreements are the output.[/dim]"]
    for d in syn.get("disagreements") or []:
        crit = " [red](critical)[/red]" if d.get("critical") else ""
        lines.append(f"\n[bold]Disagreement[/bold]{crit} — {d.get('topic', '')} "
                     f"[dim](gap {d.get('gap', '?')}: {', '.join(d.get('agents', []))})[/dim]\n"
                     f"  {d.get('positions', '')}")
    lines.append(f"\n[bold]Next action[/bold]: {syn.get('action', '')}")
    console.print(Panel("\n".join(lines), title="Synthesis", border_style="magenta"))
    console.print(REPLAY_BANNER)


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
