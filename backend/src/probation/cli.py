"""CLI entry point for Probation.

Authority: docs/TECH_STACK_AND_REPO.md section 3 and docs/ENGINE_SPEC.md.
"""

import typer
from rich.console import Console

app = typer.Typer(help="Probation: Earned autonomy personal AI engine.")
db_app = typer.Typer(help="Database operations.")
ledger_app = typer.Typer(help="Ledger operations.")
budget_app = typer.Typer(help="Budget inspection.")
synth_app = typer.Typer(help="Synthetic world generation.")
exam_app = typer.Typer(help="Examination board.")

app.add_typer(db_app, name="db")
app.add_typer(ledger_app, name="ledger")
app.add_typer(budget_app, name="budget")
app.add_typer(synth_app, name="synth")
app.add_typer(exam_app, name="exam")

console = Console()


@db_app.command("init")
def db_init() -> None:
    """Initialize database schema in WAL mode."""
    console.print("[green]Database initialization placeholder (Phase 1).[/green]")


@ledger_app.command("verify")
def ledger_verify() -> None:
    """Verify hash chain integrity."""
    console.print("[green]Ledger verification placeholder (Phase 1).[/green]")


@budget_app.command("show")
def budget_show() -> None:
    """Display current LLM and Tavily budget consumption."""
    console.print("[green]Budget display placeholder (Phase 1).[/green]")


@synth_app.command("generate")
def synth_generate(
    persona: int = typer.Option(1, "--persona", "-p", help="Persona ID to generate"),
    seed: int = typer.Option(1, "--seed", "-s", help="Random seed"),
) -> None:
    """Generate synthetic persona history and world database."""
    console.print(f"[green]Generating persona {persona} with seed {seed} (Phase 2).[/green]")


@exam_app.command("run")
def exam_run(
    pack: str = typer.Option("mail", "--pack", help="Domain pack to test"),
) -> None:
    """Run examination board on candidate policies."""
    console.print(f"[green]Running exam for pack {pack} (Phase 7).[/green]")


@app.command("backtest")
def backtest(
    family: str = typer.Option("email_action", "--family", "-f", help="Action family"),
) -> None:
    """Run event-sourced replay backtest."""
    console.print(f"[green]Running backtest for family {family} (Phase 4).[/green]")


@app.command("eval")
def run_eval(
    suite: str = typer.Option("main", "--suite", "-s", help="Evaluation suite name"),
) -> None:
    """Execute evaluation suite and compute metrics."""
    console.print(f"[green]Running evaluation suite {suite} (Phase 10).[/green]")


def main() -> None:
    """Run CLI application."""
    app()


if __name__ == "__main__":
    main()
