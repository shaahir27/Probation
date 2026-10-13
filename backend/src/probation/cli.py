"""CLI entry point for Probation.

Authority: docs/TECH_STACK_AND_REPO.md section 3, docs/ENGINE_SPEC.md, and docs/CONTRACT.md section 10.
"""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from probation.config import settings
from probation.db.connection import get_connection, init_db
from probation.db.ledger import verify_ledger
from probation.synth.generator import generate_synthetic_world
from probation.synth.importers import (
    import_calendar,
    import_files,
    import_links,
    import_mail,
)

app = typer.Typer(help="Probation: Earned autonomy personal AI engine.")
db_app = typer.Typer(help="Database operations.")
ledger_app = typer.Typer(help="Ledger operations.")
budget_app = typer.Typer(help="Budget inspection.")
synth_app = typer.Typer(help="Synthetic world generation.")
import_app = typer.Typer(help="Source data importers.")
exam_app = typer.Typer(help="Examination board.")

app.add_typer(db_app, name="db")
app.add_typer(ledger_app, name="ledger")
app.add_typer(budget_app, name="budget")
app.add_typer(synth_app, name="synth")
app.add_typer(import_app, name="import")
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
    persona_id: int = typer.Option(
        0, "--persona-id", "--persona", "-p", help="Persona ID to generate (0..19)"
    ),
    seed: int = typer.Option(7, "--seed", "-s", help="Random seed"),
    size: str = typer.Option(
        "tiny", "--size", help="Dataset size ('tiny' ~200 items, 'full' ~3000 items)"
    ),
    out: str = typer.Option("", "--out", "-o", help="Output directory path"),
) -> None:
    """Generate synthetic persona history, world database, and hidden truth."""
    if not out:
        out_dir = f"data/synth/{persona_id}" if size == "full" else "tests/fixtures/tiny_synth"
    else:
        out_dir = out

    console.print(
        f"[bold cyan]Generating synthetic world for persona {persona_id} (seed={seed}, size={size})...[/]"
    )
    summary = generate_synthetic_world(persona_id=persona_id, seed=seed, size=size, out_dir=out_dir)

    table = Table(title="Synthetic Generation Summary")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Persona ID", str(summary["persona_id"]))
    table.add_row("Seed", str(summary["seed"]))
    table.add_row("Size", str(summary["size"]))
    table.add_row("Total Situations", str(summary["situations_total"]))
    table.add_row("Total Messages", str(summary["messages_total"]))
    table.add_row("Total Events", str(summary["events_total"]))
    table.add_row("Total Files", str(summary["files_total"]))
    table.add_row("Output Directory", str(summary["out_dir"]))
    console.print(table)
    console.print(f"[bold green]Successfully generated synthetic world at:[/] {summary['out_dir']}")


@import_app.command("mail")
def import_mail_cmd(
    path: str = typer.Argument(..., help="Path to .mbox file"),
) -> None:
    """Import RFC-822 .mbox archive into raw_items."""
    console.print(f"[bold cyan]Importing mail from:[/] {path}")
    conn = get_connection(settings.db_path)
    try:
        res = import_mail(path, conn)
        console.print(
            f"[bold green]Mail imported successfully.[/] "
            f"Imported: {res.items_imported}, Skipped (idempotent): {res.items_skipped}"
        )
    finally:
        conn.close()


@import_app.command("calendar")
def import_calendar_cmd(
    path: str = typer.Argument(..., help="Path to .ics file"),
) -> None:
    """Import RFC-5545 .ics file into raw_items."""
    console.print(f"[bold cyan]Importing calendar from:[/] {path}")
    conn = get_connection(settings.db_path)
    try:
        res = import_calendar(path, conn)
        console.print(
            f"[bold green]Calendar imported successfully.[/] "
            f"Imported: {res.items_imported}, Skipped (idempotent): {res.items_skipped}"
        )
    finally:
        conn.close()


@import_app.command("files")
def import_files_cmd(
    path: str = typer.Argument(..., help="Path to folder manifest JSON file"),
) -> None:
    """Import folder snapshot manifest into raw_items."""
    console.print(f"[bold cyan]Importing files manifest from:[/] {path}")
    conn = get_connection(settings.db_path)
    try:
        res = import_files(path, conn)
        console.print(
            f"[bold green]Files imported successfully.[/] "
            f"Imported: {res.items_imported}, Skipped (idempotent): {res.items_skipped}"
        )
    finally:
        conn.close()


@import_app.command("links")
def import_links_cmd(
    path: str = typer.Argument(..., help="Path to links file"),
) -> None:
    """Import saved links into raw_items."""
    console.print(f"[bold cyan]Importing links from:[/] {path}")
    conn = get_connection(settings.db_path)
    try:
        res = import_links(path, conn)
        console.print(
            f"[bold green]Links imported successfully.[/] "
            f"Imported: {res.items_imported}, Skipped (idempotent): {res.items_skipped}"
        )
    finally:
        conn.close()


@exam_app.command("run")
def exam_run(
    pack: str = typer.Option("mail", "--pack", help="Domain pack to test"),
) -> None:
    """Run examination board on candidate policies."""
    console.print(f"[green]Running exam for pack {pack} (Phase 7).[/green]")


@app.command("backtest")
def backtest(
    family: str = typer.Option("email_action", "--family", "-f", help="Action family"),
    until: str | None = typer.Option(None, "--until", "-u", help="Replay cutoff timestamp"),
    db: str | None = typer.Option(None, "--db", help="Path to database"),
) -> None:
    """Run event-sourced replay backtest (Phase 4)."""
    from probation.core.clock import Clock
    from probation.core.enums import ClockMode
    from probation.engine.replay import run_replay

    db_path = Path(db) if db else settings.db_path
    console.print(
        f"[bold cyan]Running event-sourced replay backtest (Phase 4) for family: {family}...[/]"
    )

    from probation.db.connection import apply_schema

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='situations';")
        if not cur.fetchone():
            apply_schema(conn)

        clock = Clock(mode=ClockMode.REPLAY)
        report = run_replay(conn, clock=clock, family=family, until=until)

        table = Table(title=f"Probation Report Card — {family} (Phase 4)")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Total Proposals Emitted", str(report.get("total_proposals", 0)))
        table.add_row("Total Evaluated (Strong)", str(report.get("total_evaluated", 0)))
        table.add_row("Same (Agreement)", str(report.get("same", 0)))
        table.add_row("Different (Disagreement)", str(report.get("different", 0)))
        table.add_row("Would Ask (Abstain / Ask)", str(report.get("would_ask", 0)))
        table.add_row("Censored / Weak", str(report.get("censored", 0)))
        table.add_row("Probation Agreement Rate", f"{report.get('accuracy', 0.0):.2%}")
        table.add_row("Baseline B0 (Majority) Rate", f"{report.get('b0_accuracy', 0.0):.2%}")
        table.add_row("Baseline B2 (Generic Rules) Rate", f"{report.get('b2_accuracy', 0.0):.2%}")

        console.print(table)
        acc = report.get("accuracy", 0.0)
        b0_acc = report.get("b0_accuracy", 0.0)
        if acc >= b0_acc:
            console.print(
                f"[bold green]Success: Probation agreement ({acc:.2%}) >= Baseline B0 ({b0_acc:.2%})[/]"
            )
        else:
            console.print(
                f"[yellow]Notice: Probation agreement ({acc:.2%}) < Baseline B0 ({b0_acc:.2%})[/]"
            )
    finally:
        conn.close()


@app.command("eval")
def run_eval(
    suite: str = typer.Option("main", "--suite", "-s", help="Evaluation suite name"),
) -> None:
    """Execute evaluation suite and compute metrics."""
    console.print(f"[green]Running evaluation suite {suite} (Phase 10).[/green]")


@app.command("ingest")
def ingest_cmd() -> None:
    """Extract situations from raw_items and featurize them."""
    from probation.workers.brain import extract_features_for_situations
    from probation.workers.ingestor import ingest_situations

    conn = get_connection(settings.db_path)
    try:
        sit_count = ingest_situations(conn)
        feat_count = extract_features_for_situations(conn)
        console.print(
            f"[bold green]Ingestion complete.[/] Situations extracted: {sit_count}, "
            f"Features computed: {feat_count}"
        )
    finally:
        conn.close()


def main() -> None:
    """Run CLI application."""
    app()


if __name__ == "__main__":
    main()
