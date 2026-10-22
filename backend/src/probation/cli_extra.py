"""Existing CLI workflows, split into focused registration modules."""

import typer
from rich.table import Table

from probation.cli_apps import chains_app, console, habits_app, webfacts_app
from probation.config import settings
from probation.db.connection import get_connection


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
        conn.commit()
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


@webfacts_app.command("vet-batch")
def webfacts_vet_batch(
    as_of: str | None = typer.Option(None, "--as-of", help="Historical cutoff timestamp (ISO)"),
) -> None:
    """Vet sender and link entities for situations batch."""
    from probation.db.connection import apply_schema
    from probation.workers.webfacts import vet_situations_batch

    conn = get_connection(settings.db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='web_facts';")
        if not cur.fetchone():
            apply_schema(conn)

        count = vet_situations_batch(conn, as_of=as_of)
        conn.commit()
        console.print(f"[bold green]Vetted {count} entity domains for situations batch.[/]")
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


@habits_app.command("mine")
def habits_mine(
    as_of: str | None = typer.Option(None, "--as-of", help="Historical cutoff timestamp (ISO)"),
) -> None:
    """Mine significant habit patterns with Benjamini-Hochberg FDR correction."""
    from probation.engine.habits import mine_habits

    console.print(f"[bold cyan]Mining habits from database at:[/] {settings.db_path}")
    conn = get_connection(settings.db_path)
    try:
        habits = mine_habits(conn, as_of=as_of)
        conn.commit()
        table = Table(title=f"Mined Habits (Count: {len(habits)})")
        table.add_column("ID", style="cyan")
        table.add_column("Family", style="magenta")
        table.add_column("Clue", style="yellow")
        table.add_column("Action", style="green")
        table.add_column("k/n", justify="right")
        table.add_column("Lift", justify="right")
        table.add_column("q-val", justify="right")
        table.add_column("Statement", style="white")

        for h in habits:
            table.add_row(
                h.id,
                h.family,
                f"{h.clue}={h.clue_value}",
                h.action,
                f"{h.k}/{h.n}",
                f"{h.lift:.2f}",
                f"{h.q_value:.4f}",
                h.statement,
            )
        console.print(table)
    finally:
        conn.close()


@chains_app.command("mine")
def chains_mine(
    as_of: str | None = typer.Option(None, "--as-of", help="Historical cutoff timestamp (ISO)"),
) -> None:
    """Mine cross-tool action sequences within 24-hour windows."""
    from probation.packs.chains.mining import mine_chains

    console.print(f"[bold cyan]Mining action chains from database at:[/] {settings.db_path}")
    conn = get_connection(settings.db_path)
    try:
        chains = mine_chains(conn, as_of=as_of)
        conn.commit()
        table = Table(title=f"Mined Chains (Count: {len(chains)})")
        table.add_column("ID", style="cyan")
        table.add_column("Trigger Class Key", style="magenta")
        table.add_column("Follow Action", style="green")
        table.add_column("k/n", justify="right")
        table.add_column("Base Rate", justify="right")
        table.add_column("Lift", justify="right")
        table.add_column("Status", style="yellow")

        for c in chains:
            table.add_row(
                c.id,
                c.trigger_class_key,
                c.follow_action,
                f"{c.k}/{c.n}",
                f"{c.base_rate:.2f}",
                f"{c.lift:.2f}",
                c.status,
            )
        console.print(table)
    finally:
        conn.close()
