"""`panel` — the condorium CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt

from .analytics import traces
from .config import SETTINGS
from .display import console, show_evaluation, show_prefilter, show_ranking

app = typer.Typer(help="A calibrated idea committee: no flattery, no lazy rejection.",
                  no_args_is_help=True, pretty_exceptions_show_locals=False)


# ------------------------------------------------------ interrupt handling

def _answer_interrupt(payload: dict):
    kind = payload.get("type")
    if kind == "interview_question":
        return Prompt.ask(f"[bold cyan]Interviewer[/bold cyan] {payload.get('question')}")
    if kind == "tech_tradeoff":
        wow, mastered = payload.get("wow_option") or {}, payload.get("mastered_option") or {}
        console.print(Panel(
            f"[bold]1. demo-wow[/bold]: {wow.get('tech')} (wow {wow.get('wow')}/10, "
            f"risk {wow.get('risk')}/10)\n"
            f"[bold]2. mastered[/bold]: {mastered.get('tech')} (wow {mastered.get('wow')}/10, "
            f"risk {mastered.get('risk')}/10)",
            title="Tech trade-off — you decide"))
        choice = Prompt.ask("Which one?", choices=["1", "2"], default="2")
        return "demo-wow tech" if choice == "1" else "mastered tech"
    if kind == "intake_validation":
        intake = payload.get("intake") or {}
        console.print(Panel(json.dumps(intake, indent=2, ensure_ascii=False), title="Intake — validate"))
        if Confirm.ask("Accept this intake?", default=True):
            return {"intake": intake}
        intake["restatement"] = Prompt.ask("Your restatement", default=intake.get("restatement", ""))
        return {"intake": intake}
    if kind == "prefilter_threshold":
        show_prefilter(payload)
        return IntPrompt.ask("How many ideas go to the committee?",
                             default=payload.get("default", 3))
    return None


def _run_graph(initial: dict, thread_id: str) -> dict:
    from langgraph.types import Command

    from .graph.build import compile_main_graph
    from .graph.checkpoint import get_checkpointer

    graph = compile_main_graph(initial.get("lang"), checkpointer=get_checkpointer())
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 120}
    result = graph.invoke(initial, config)
    while result.get("__interrupt__"):
        answer = _answer_interrupt(result["__interrupt__"][0].value or {})
        result = graph.invoke(Command(resume=answer), config)
    return result


def _show_results(result: dict) -> None:
    for record in result.get("evaluations", []):
        try:
            show_evaluation(traces.load_eval(record["eval_id"]))
        except FileNotFoundError:
            show_evaluation(record)
    if result.get("ranking"):
        show_ranking(result, result.get("evaluations", []))
    if result.get("run_id"):
        console.print(f"[dim]run saved: evaluations/{result['run_id']}/run.json[/dim]")


# ---------------------------------------------------------------- commands

@app.command()
def eval(
    idea: Optional[str] = typer.Argument(None, help="The idea, inline"),
    file: Optional[Path] = typer.Option(None, "--file", help="Read the idea from a file"),
    mode: str = typer.Option("general", help="general | hackathon"),
    constraints: str = typer.Option("", help='e.g. "24h, team of 3"'),
    criteria: str = typer.Option("", help="Official criteria (hackathon)"),
    custom_criteria: str = typer.Option("", help="Extra Judge criteria for this session"),
    interview: bool = typer.Option(True, help="Refine through the Interviewer first"),
    lang: str = typer.Option("en", help="Prompt language (en, fr)"),
):
    """Evaluate one idea with the full committee (2 rounds + synthesis)."""
    raw = file.read_text(encoding="utf-8") if file else (idea or "")
    if not raw.strip():
        raise typer.BadParameter("give an idea inline or via --file")
    run_id = traces.new_id("run", "eval")
    result = _run_graph({
        "command": "eval", "mode": mode, "raw_input": raw,
        "constraints": constraints, "official_criteria": criteria,
        "custom_criteria": custom_criteria, "interactive": interview,
        "lang": lang, "run_id": run_id,
    }, run_id)
    _show_results(result)


@app.command()
def generate(
    source: str = typer.Option("hackathon", help="hackathon | scientist | historian"),
    theme: str = typer.Option("", help="Theme / track"),
    duration: str = typer.Option("", help='e.g. "24h"'),
    context: str = typer.Option("", help="Context or problem statement"),
    criteria: str = typer.Option("", help="Official criteria"),
    constraints: str = typer.Option("", help="Team constraints"),
    n: int = typer.Option(5, help="Ideas to generate"),
    top: Optional[int] = typer.Option(None, help="Pre-filter threshold (skips the question)"),
    mode: str = typer.Option("hackathon"),
    lang: str = typer.Option("en"),
):
    """Generate ideas from ONE source, pre-filter, evaluate the survivors."""
    run_id = traces.new_id("run", f"gen-{source}")
    result = _run_graph({
        "command": "generate", "sources": [source], "mode": mode, "theme": theme,
        "duration": duration, "context": context, "official_criteria": criteria,
        "constraints": constraints, "n_ideas": n, "top": top, "lang": lang,
        "run_id": run_id,
    }, run_id)
    _show_results(result)


@app.command()
def tournament(
    sources: str = typer.Option("hackathon,scientist,historian", help="Comma-separated generators"),
    context: Optional[Path] = typer.Option(None, help="Context file (theme, rules...)"),
    theme: str = typer.Option(""),
    duration: str = typer.Option(""),
    criteria: str = typer.Option(""),
    constraints: str = typer.Option(""),
    top: Optional[int] = typer.Option(None, help="Ideas passing the pre-filter"),
    n: int = typer.Option(5, help="Ideas per generator"),
    mode: str = typer.Option("hackathon"),
    lang: str = typer.Option("en"),
):
    """Multiple generators -> pre-filter -> committee (provenance masked) -> Clerk ranking."""
    ctx = context.read_text(encoding="utf-8") if context else ""
    run_id = traces.new_id("run", "tournament")
    result = _run_graph({
        "command": "tournament", "sources": [s.strip() for s in sources.split(",") if s.strip()],
        "mode": mode, "theme": theme, "duration": duration, "context": ctx,
        "official_criteria": criteria, "constraints": constraints,
        "n_ideas": n, "top": top, "lang": lang, "run_id": run_id,
    }, run_id)
    _show_results(result)
    console.print("[dim]interrupted? re-run the same command — the SqliteSaver "
                  "checkpoint resumes without re-paying completed calls[/dim]")


@app.command()
def demo(
    traces_: Optional[list[Path]] = typer.Argument(None, metavar="[TRACE.json]...",
                                                    help="Recorded traces (default: bundled)"),
    pause: float = typer.Option(0.0, help="Seconds between deliberation steps"),
):
    """Replay recorded evaluations step by step (offline, no API key needed)."""
    from .display import show_deliberation

    fixtures = traces_ or sorted(SETTINGS.demo_dir.glob("*.json"))
    if not fixtures:
        console.print(f"[red]no recorded traces found in {SETTINGS.demo_dir}[/red]")
        raise typer.Exit(1)
    for f in fixtures:
        show_deliberation(json.loads(f.read_text(encoding="utf-8")), pause=pause, source=f.name)
    console.print(f"\n[bold]Replayed {len(fixtures)} recorded run(s)[/bold] — no model was "
                  "called. Set an API key (any LiteLLM provider) for live evaluations.")


@app.command()
def history():
    """List saved evaluations."""
    from rich.table import Table

    table = Table(title="Evaluations")
    for col in ("eval id", "idea", "mode", "verdict"):
        table.add_column(col)
    for rec in traces.list_evals():
        table.add_row(rec.get("eval_id", "?"), rec.get("idea", {}).get("title", "?"),
                      rec.get("mode", "?"), (rec.get("synthesis") or {}).get("verdict", "?"))
    console.print(table)


@app.command()
def show(eval_id: str):
    """Display one saved evaluation."""
    show_evaluation(traces.load_eval(eval_id))


@app.command()
def graph():
    """Print the LangGraph pipeline as a Mermaid diagram."""
    from .graph.build import mermaid_diagram

    print(mermaid_diagram())


@app.command()
def ingest(target: str):
    """Ingest a hackathon winner (URL or file) into the knowledge base + graph."""
    import subprocess
    import sys

    script = SETTINGS.root / "scripts" / "ingest_winners.py"
    raise typer.Exit(subprocess.call([sys.executable, str(script), target]))


@app.command()
def bootstrap(dataset: Path = typer.Option(..., "--dataset", help="Devpost-style dataset path")):
    """Populate the winners base + knowledge graph from a public dataset."""
    import subprocess
    import sys

    script = SETTINGS.root / "scripts" / "bootstrap_from_dataset.py"
    raise typer.Exit(subprocess.call([sys.executable, str(script), str(dataset)]))


@app.command()
def report(eval_id: str):
    """Self-contained HTML report (plotly) for one evaluation."""
    from .analytics.viz import eval_report

    console.print(f"report: {eval_report(eval_id)}")


@app.command()
def dashboard():
    """Aggregated HTML dashboard over the whole history."""
    from .analytics.viz import dashboard as build_dashboard

    console.print(f"dashboard: {build_dashboard()}")


@app.command()
def stats():
    """Influence matrix, round deltas, agreement, severity — full history."""
    from .analytics.stats import full_stats

    console.print_json(json.dumps(full_stats(), ensure_ascii=False))


@app.command()
def bench(
    dataset: Optional[Path] = typer.Option(None, help="Devpost-style dataset path"),
    n: int = typer.Option(50),
    seed: int = typer.Option(42),
    sycophancy: bool = typer.Option(False, "--sycophancy", help="Formulation-bias test"),
    versus: bool = typer.Option(False, "--versus",
                                help="Committee vs single judge at equal token budget"),
    seeds: str = typer.Option("0,1,2", help="--versus: comma-separated seeds"),
    tone: int = typer.Option(3, help="--versus: tone-sensitivity cases per seed"),
    mode: str = typer.Option("hackathon", help="--versus: general | hackathon"),
    out: Optional[Path] = typer.Option(None, help="--versus: results JSON path"),
    workers: int = typer.Option(1, help="--versus: seeds run in parallel processes"),
):
    """Benchmark the committee: winner identification, formulation bias, or
    committee vs single judge (`--versus`)."""
    if versus:
        from .bench.versus import readme_table as versus_table
        from .bench.versus import run_versus

        dataset = dataset or SETTINGS.root / "fixtures" / "bench" / "synthetic_pairs.json"
        result = run_versus(dataset, n_pairs=n, n_tone=tone,
                            seeds=tuple(int(s) for s in seeds.split(",") if s.strip()),
                            mode=mode, out=out, workers=workers,
                            log=lambda m: console.print(f"[dim]{m}[/dim]"))
        console.print(versus_table(result))
        console.print(f"[dim]model {result['model']} — "
                      f"{result['summary']['llm_calls_total']} LLM calls[/dim]")
        return
    if sycophancy:
        from .bench.sycophancy import readme_table, run_sycophancy

        result = run_sycophancy(dataset, n=n, seed=seed)
    else:
        if not dataset:
            raise typer.BadParameter("--dataset is required (unless --sycophancy)")
        from .bench.run import readme_table, run_bench

        result = run_bench(dataset, n=n, seed=seed)
    console.print(readme_table(result))
    console.print("[dim]full results in evaluations/*.json — paste the table in the README[/dim]")


@app.command()
def pitch(eval_id: str):
    """Assemble the pitch pack from the stored evaluation (no new LLM calls)."""
    from .pitch import build_pitch

    console.print(f"pitch pack: {build_pitch(eval_id)}")


@app.command()
def coach(dry_run: bool = typer.Option(False, "--dry-run",
                                       help="Show the proposals and diffs, apply nothing")):
    """Propose rubric diffs from measured errors. Human validates each one."""
    from . import coach as coach_mod

    proposals = coach_mod.propose()
    if not proposals:
        console.print("Not enough concordant error cases (minimum 3 per proposal). "
                      "Run `panel bench`, `panel bench --sycophancy` and `panel record` first.")
        return
    accepted = 0
    for p in proposals:
        console.print(Panel(
            f"[bold]{p['agent_file']}[/bold]\nMetric: {p.get('metric')}\n"
            f"Cases: {', '.join(p.get('case_ids', []))}\n{p.get('rationale', '')}",
            title="Coach proposal"))
        console.print(p["diff"])
        if dry_run:
            continue
        if Confirm.ask("Apply this diff?", default=False):
            coach_mod.apply_proposal(p)
            accepted += 1
            console.print("[green]applied + journaled in agents/CHANGELOG.md[/green]")
        else:
            console.print("[yellow]skipped[/yellow]")
    if dry_run:
        console.print(f"[dim]dry run — {len(proposals)} proposal(s) shown, none applied[/dim]")
    else:
        console.print(f"{accepted}/{len(proposals)} diffs applied.")


@app.command()
def record(eval_id: str, result: str = typer.Option(..., "--result", help='e.g. "2nd place"')):
    """Record the real-world outcome vs the committee's prediction."""
    from .record import record_result

    outcome = record_result(eval_id, result)
    console.print(f"recorded: {outcome['verdict']} predicted, real result: {result}")


@app.command()
def population(eval_id: str):
    """Phase 2 (stub): simulated population reaction to an evaluated idea."""
    from .population import simulate

    try:
        simulate(eval_id)
    except NotImplementedError as e:
        console.print(f"[yellow]{e}[/yellow]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
