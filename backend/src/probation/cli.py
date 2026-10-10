"""CLI entry point for Probation.

Authority: docs/TECH_STACK_AND_REPO.md section 3, docs/ENGINE_SPEC.md, and docs/CONTRACT.md section 10.
"""

import typer
from rich.console import Console
from rich.table import Table

from probation.config import settings
from probation.db.connection import get_connection, init_db
from probation.db.ledger import verify_ledger

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
    console.print(f"[bold cyan]Initializing SQLite database at:[/] {settings.db_path}")
    init_db(settings.db_path)
    console.print("[bold green]Database schema initialized successfully in WAL mode.[/]")


@ledger_app.command("verify")
def cli_ledger_verify() -> None:
    """Verify hash chain integrity."""
    console.print(f"[bold cyan]Verifying ledger at:[/] {settings.db_path}")
    conn = get_connection(settings.db_path)
    try:
        intact, corrupted_seq = verify_ledger(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS cnt, hash FROM ledger ORDER BY seq DESC LIMIT 1;")
        row = cursor.fetchone()
        count = row[0] if row else 0
        head_hash = row[1] if row and count > 0 else "N/A"

        if intact:
            console.print(
                f"[bold green]Ledger verified OK.[/] Entries: {count}, Head Hash: [yellow]{head_hash}[/]"
            )
        else:
            console.print(
                f"[bold red]Ledger corrupted at seq {corrupted_seq}![/] Total rows: {count}"
            )
            raise typer.Exit(code=1)
    finally:
        conn.close()


@budget_app.command("show")
def budget_show() -> None:
    """Display current LLM and Tavily budget consumption."""
    conn = get_connection(settings.db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT call_kind, model_id, COUNT(*) AS calls,
                   SUM(tokens_in) AS total_in, SUM(tokens_out) AS total_out,
                   SUM(cost_usd) AS total_cost
            FROM exposure_log
            GROUP BY call_kind, model_id;
            """
        )
        rows = cursor.fetchall()

        table = Table(title="Probation LLM Budget & Exposure Summary")
        table.add_column("Call Kind", style="cyan")
        table.add_column("Model ID", style="magenta")
        table.add_column("Calls", justify="right")
        table.add_column("Tokens In", justify="right")
        table.add_column("Tokens Out", justify="right")
        table.add_column("Cost (USD)", justify="right", style="green")

        total_cost = 0.0
        for r in rows:
            cost = float(r["total_cost"])
            total_cost += cost
            table.add_row(
                str(r["call_kind"]),
                str(r["model_id"]),
                str(r["calls"]),
                f"{r['total_in']:,}",
                f"{r['total_out']:,}",
                f"${cost:.4f}",
            )

        console.print(table)
        remaining = settings.budget_hard_limit_usd - total_cost
        console.print(
            f"Total Spend: [bold green]${total_cost:.4f}[/] / "
            f"Cap: [bold red]${settings.budget_hard_limit_usd:.2f}[/] "
            f"(Remaining: [bold cyan]${remaining:.4f}[/])"
        )
    finally:
        conn.close()


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
