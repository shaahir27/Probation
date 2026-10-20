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
webfacts_app = typer.Typer(help="Web facts and Tavily vetting operations.")

app.add_typer(db_app, name="db")
app.add_typer(ledger_app, name="ledger")
app.add_typer(budget_app, name="budget")
app.add_typer(synth_app, name="synth")
app.add_typer(import_app, name="import")
app.add_typer(exam_app, name="exam")
app.add_typer(webfacts_app, name="webfacts")

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
    class_key: str | None = typer.Option(
        None, "--class-key", "-c", help="Specific class key to test"
    ),
    action: str | None = typer.Option(
        None, "--action", "-a", help="Action to test (e.g. REPLY, ARCHIVE)"
    ),
    level: int = typer.Option(2, "--level", "-l", help="Autonomy level to test (2 or 3)"),
    pack: str = typer.Option(
        "mail", "--pack", "-p", help="Domain pack fallback if class_key omitted"
    ),
    seed: int = typer.Option(42, "--seed", "-s", help="Random seed for sampling"),
) -> None:
    """Run examination board on candidate policies.

    Authority: docs/ENGINE_SPEC.md section 15.
    """
    from datetime import UTC, datetime

    from probation.engine.licence import find_exam_candidates
    from probation.workers.examiner import run_examiner_job

    conn = get_connection(settings.db_path)
    try:
        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        results = []
        console.print("[bold cyan]Running examination board (Phase 7)...[/]")

        if class_key and action:
            console.print(
                f"[bold cyan]Running diagnostic exam for ({class_key}, {action}) at Level {level}...[/]"
            )
            res = run_examiner_job(
                conn, class_key=class_key, action=action, level=level, seed=seed, as_of=now_iso
            )
            results.append(res)
        else:
            candidates = find_exam_candidates(
                conn, as_of=now_iso, max_candidates=settings.exam_max_per_day
            )
            if not candidates:
                # Fallback to test with default pack if requested
                default_action = (
                    "REPLY"
                    if pack in ("mail", "email")
                    else "ACCEPT"
                    if pack in ("cal", "calendar")
                    else "LEAVE"
                )
                default_class = f"{pack}|default|standard"
                console.print(
                    f"[yellow]No pending candidates found meeting numeric thresholds. Testing default ({default_class}, {default_action})...[/]"
                )
                res = run_examiner_job(
                    conn,
                    class_key=default_class,
                    action=default_action,
                    level=level,
                    seed=seed,
                    as_of=now_iso,
                )
                results.append(res)
            else:
                console.print(
                    f"[bold cyan]Found {len(candidates)} candidate(s) qualifying numerically. Running exams...[/]"
                )
                for c_key, act, lvl in candidates:
                    res = run_examiner_job(
                        conn, class_key=c_key, action=act, level=lvl, seed=seed, as_of=now_iso
                    )
                    results.append(res)

        table = Table(title="Probation Examination Board Results")
        table.add_column("Run ID", style="cyan")
        table.add_column("Class Key", style="magenta")
        table.add_column("Action", style="blue")
        table.add_column("Level", justify="center")
        table.add_column("Cases", justify="right")
        table.add_column("Flip Rate", justify="right")
        table.add_column("Critical Violations", justify="right")
        table.add_column("Result", justify="center")

        for r in results:
            flip_str = (
                f"{r.invariance_flip_rate:.1%}" if r.invariance_flip_rate is not None else "N/A"
            )
            res_str = "[bold green]PASS[/]" if r.passed else "[bold red]FAIL[/]"
            table.add_row(
                r.run_id,
                r.class_key,
                r.action,
                str(r.level_tested),
                str(r.n_cases),
                flip_str,
                str(r.critical_violations),
                res_str,
            )

        console.print(table)
    finally:
        conn.close()


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


@webfacts_app.command("vet")
def webfacts_vet(
    domain: str = typer.Argument(..., help="Domain to vet"),
    brand: str | None = typer.Option(None, "--brand", "-b", help="Display brand name token"),
) -> None:
    """Vet an entity domain and display derived EntityFacts and sources."""
    from probation.db.connection import apply_schema
    from probation.workers.webfacts import vet_entity

    conn = get_connection(settings.db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='web_facts';")
        if not cur.fetchone():
            apply_schema(conn)

        console.print(f"[bold cyan]Vetting domain:[/] {domain} (brand: {brand or 'auto'})...")
        res = vet_entity(conn, domain=domain, brand_token=brand)
        table = Table(title=f"Entity Facts — {domain}")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Status", str(res.get("status")))
        table.add_row("Origin", str(res.get("origin")))
        table.add_row("Facts", str(res.get("facts", {})))
        sources = res.get("sources", [])
        table.add_row("Sources Count", str(len(sources)))
        for idx, src in enumerate(sources, 1):
            table.add_row(f"Source {idx}", f"{src.get('title')} -> {src.get('url')}")

        console.print(table)
    finally:
        conn.close()


@webfacts_app.command("audit")
def webfacts_audit() -> None:
    """Display recorded Tavily calls and credit consumption."""
    from probation.db.connection import apply_schema

    conn = get_connection(settings.db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tavily_calls';")
        if not cur.fetchone():
            apply_schema(conn)

        cur.execute(
            """
            SELECT COUNT(*) AS total_calls, COALESCE(SUM(credits), 0) AS total_credits
            FROM tavily_calls;
            """
        )
        row = cur.fetchone()
        total_calls = row[0] if row else 0
        total_credits = float(row[1]) if row else 0.0

        cur.execute(
            """
            SELECT id, endpoint, purpose, query_text, credits, ok, latency_ms, created_at
            FROM tavily_calls
            ORDER BY created_at DESC LIMIT 20;
            """
        )
        rows = cur.fetchall()

        table = Table(
            title=f"Tavily Call Audit (Total Calls: {total_calls}, Total Credits: {total_credits:.1f})"
        )
        table.add_column("Created At", style="cyan")
        table.add_column("Endpoint", style="magenta")
        table.add_column("Purpose", style="blue")
        table.add_column("Query / URL", style="yellow")
        table.add_column("Credits", justify="right")
        table.add_column("OK", justify="center")
        table.add_column("Latency (ms)", justify="right")

        for r in rows:
            table.add_row(
                str(r["created_at"]),
                str(r["endpoint"]),
                str(r["purpose"]),
                str(r["query_text"]),
                f"{float(r['credits']):.1f}",
                "[green]YES[/]" if r["ok"] else "[red]NO[/]",
                str(r["latency_ms"] or 0),
            )

        console.print(table)
    finally:
        conn.close()


@webfacts_app.command("load-fixtures")
def webfacts_load_fixtures() -> None:
    """Load recorded entity facts fixtures into web_facts table."""
    from probation.db.connection import apply_schema
    from probation.web.fixtures import load_web_facts_fixtures

    conn = get_connection(settings.db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='web_facts';")
        if not cur.fetchone():
            apply_schema(conn)

        count = load_web_facts_fixtures(conn)
        console.print(f"[bold green]Loaded {count} entity facts fixtures into web_facts table.[/]")
    finally:
        conn.close()


def main() -> None:
    """Run CLI application."""
    app()


if __name__ == "__main__":
    main()
