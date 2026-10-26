"""CLI entry point. Authority: docs/CONTRACT.md section 10."""

import os

import typer
from rich.table import Table

from probation import cli_extra as cli_extra
from probation.cli_apps import app, budget_app, console, db_app, import_app, ledger_app, synth_app
from probation.cli_engine import backtest as backtest
from probation.cli_engine import exam_run as exam_run
from probation.cli_eval import eval_run_cmd as eval_run_cmd
from probation.cli_safety import import_source, synthesis_target
from probation.config import settings
from probation.db.connection import get_connection, init_db
from probation.db.ledger import ledger_snapshot
from probation.synth.generator import generate_synthetic_world
from probation.synth.importers import import_calendar, import_files, import_links, import_mail


@db_app.command("init")
def db_init() -> None:
    """Initialize database schema in WAL mode."""
    console.print(f"[bold cyan]Initializing SQLite database at:[/] {settings.db_path}")
    init_db(settings.db_path)
    console.print("[bold green]Database schema initialized successfully in WAL mode.[/]")


@db_app.command("migrate")
def db_migrate() -> None:
    """Apply additive WP1 tables to an existing database; preserves ledger bytes."""
    from probation.db.migrations import migrate_wp1

    if not settings.db_path.exists():
        raise typer.BadParameter("Database does not exist; initialize it first")
    with get_connection(settings.db_path) as conn:
        migrate_wp1(conn)
    console.print("[bold green]Additive WP1 migration complete.[/]")


@app.command("examiner-tick")
def examiner_tick() -> None:
    """Drain correction review and approved administration using Examiner authority."""
    from probation.core.clock import get_clock
    from probation.db.access import Role
    from probation.db.connection import get_role_connection
    from probation.workers.admin import process_admin_commands
    from probation.workers.drift import review_outcome_events

    with get_role_connection(settings.db_path, Role.EXAMINER) as conn:
        reviewed = review_outcome_events(conn, as_of=get_clock().now_iso())
        commands = process_admin_commands(conn)
    console.print(
        f"Reviewed {reviewed} outcomes; completed {len(commands)} administrative commands."
    )


@ledger_app.command("verify")
def cli_ledger_verify() -> None:
    """Verify hash chain integrity."""
    console.print(f"[bold cyan]Verifying ledger at:[/] {settings.db_path}")
    conn = get_connection(settings.db_path)
    try:
        snapshot = ledger_snapshot(conn)
        intact, corrupted_seq = snapshot.ok, snapshot.first_broken_seq
        count = snapshot.length
        head_hash = snapshot.head_hash if count else "N/A"

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
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Allow reviewed regeneration in a nonempty directory"
    ),
    regenerate_fixture: bool = typer.Option(
        False,
        "--regenerate-fixture",
        help="Explicitly authorize reviewed tiny_synth fixture regeneration",
    ),
) -> None:
    """Generate synthetic persona history, world database, and hidden truth."""
    out_dir = synthesis_target(
        persona_id=persona_id,
        size=size,
        out=out,
        overwrite=overwrite,
        regenerate_fixture=regenerate_fixture,
    )

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
    path: str | None = typer.Argument(None, help="Legacy positional .mbox path"),
    source: str | None = typer.Option(None, "--source", help="Path to .mbox file"),
) -> None:
    """Import RFC-822 .mbox archive into raw_items."""
    path = import_source(path, source)
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
    path: str | None = typer.Argument(None, help="Legacy positional .ics path"),
    source: str | None = typer.Option(None, "--source", help="Path to .ics file"),
) -> None:
    """Import RFC-5545 .ics file into raw_items."""
    path = import_source(path, source)
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
    path: str | None = typer.Argument(None, help="Legacy positional manifest path"),
    source: str | None = typer.Option(None, "--source", help="Path to folder manifest JSON file"),
) -> None:
    """Import folder snapshot manifest into raw_items."""
    path = import_source(path, source)
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
    path: str | None = typer.Argument(None, help="Legacy positional links path"),
    source: str | None = typer.Option(None, "--source", help="Path to links file"),
) -> None:
    """Import saved links into raw_items."""
    path = import_source(path, source)
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


@app.command("ingest")
def ingest_cmd() -> None:
    """Extract situations from raw_items and featurize them."""
    from probation.workers.brain import extract_features_for_situations
    from probation.workers.ingestor import ingest_situations

    conn = get_connection(settings.db_path)
    try:
        sit_count = ingest_situations(conn)
        # Live ingest is the reader model's intended caller; replay opts in separately.
        feat_count = extract_features_for_situations(conn, allow_live_llm=True)
        conn.commit()
        console.print(
            f"[bold green]Ingestion complete.[/] Situations extracted: {sit_count}, "
            f"Features computed: {feat_count}"
        )
    finally:
        conn.close()


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Listen address"),
    port: int = typer.Option(8000, "--port", min=1, max=65535, help="Listen port"),
    reload: bool = typer.Option(False, "--reload", help="Development reload"),
    gmail_runtime: bool = typer.Option(
        False,
        "--gmail-runtime",
        help="Start the role-separated local Gmail runtime with the API",
    ),
) -> None:
    """Serve the existing FastAPI dashboard API."""
    if gmail_runtime:
        from pathlib import Path
        from threading import Event

        from probation.core.clock import Clock
        from probation.workers.gmail_role_loops import WorkLedger
        from probation.workers.gmail_runtime import GmailRuntime

        if host != "127.0.0.1":
            raise typer.BadParameter("--gmail-runtime requires host 127.0.0.1")
        if settings.probation_gmail_store is None:
            raise typer.BadParameter("PROBATION_GMAIL_STORE must name the configured private store")
        child_source = dict(os.environ)
        # Use values already loaded by Pydantic Settings; never read or copy the dotenv file.
        for field_name, value in settings.model_dump().items():
            if value is not None:
                child_source[field_name.upper()] = str(value)
        child_source["DB_PATH"] = str(settings.db_path)
        child_source["PROBATION_API_PORT"] = str(port)
        runtime = GmailRuntime(
            db_path=settings.db_path,
            private_store_path=Path(settings.probation_gmail_store),
            env=child_source,
            clock=Clock.live(),
            # The supervisor's own ledger, fed by each child's reported status lines. Without it
            # no role can ever prove it did work, so readiness would stay unavailable forever.
            work=WorkLedger(),
        )
        report = runtime.run(Event())
        for role, status in report.items():
            console.print(
                f"{role.value}: {status.state} (ready={status.capability_ready})"
                + (f" ({status.detail})" if status.detail else "")
            )
        return
    import uvicorn

    uvicorn.run("probation.api.app:app", host=host, port=port, reload=reload)


def main() -> None:
    """Run CLI application."""
    app()


if __name__ == "__main__":
    main()
