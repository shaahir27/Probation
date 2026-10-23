"""Existing CLI workflows, split into focused registration modules."""

from pathlib import Path

import typer
from rich.table import Table

from probation.cli_apps import (
    app,
    console,
    exam_app,
)
from probation.config import settings
from probation.db.connection import get_connection


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
    attempt: int = typer.Option(
        0, "--attempt", min=0, help="Stable ordinal for a deliberate new exam attempt"
    ),
) -> None:
    """Run examination board on candidate policies.

    Authority: docs/ENGINE_SPEC.md section 15.
    """
    from probation.core.clock import get_clock
    from probation.engine.licence import find_exam_candidates
    from probation.workers.examiner import run_examiner_job

    conn = get_connection(settings.db_path)
    try:
        now_iso = get_clock().now_iso()
        results = []
        console.print("[bold cyan]Running examination board (Phase 7)...[/]")

        if class_key and action:
            console.print(
                f"[bold cyan]Running diagnostic exam for ({class_key}, {action}) at Level {level}...[/]"
            )
            res = run_examiner_job(
                conn,
                class_key=class_key,
                action=action,
                level=level,
                seed=seed,
                as_of=now_iso,
                attempt_ordinal=attempt,
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
                    attempt_ordinal=attempt,
                )
                results.append(res)
            else:
                console.print(
                    f"[bold cyan]Found {len(candidates)} candidate(s) qualifying numerically. Running exams...[/]"
                )
                for c_key, act, lvl in candidates:
                    res = run_examiner_job(
                        conn,
                        class_key=c_key,
                        action=act,
                        level=lvl,
                        seed=seed,
                        as_of=now_iso,
                        attempt_ordinal=attempt,
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
    allow_live_llm: bool = typer.Option(
        False,
        "--allow-live-llm",
        help="Spend against the reader model; off by default so replay stays reproducible",
    ),
) -> None:
    """Run event-sourced replay backtest (Phase 4)."""
    from probation.core.clock import Clock
    from probation.core.enums import ClockMode
    from probation.engine.replay import run_replay

    db_path = Path(db) if db else settings.db_path
    console.print(
        f"[bold cyan]Running event-sourced replay backtest (Phase 4) for family: {family}...[/]"
    )

    from probation.db.connection import ensure_schema

    conn = get_connection(db_path)
    try:
        ensure_schema(conn)

        clock = Clock(mode=ClockMode.REPLAY)
        if allow_live_llm:
            console.print(
                "[bold yellow]Live LLM reader enabled: this replay will spend against the "
                "reader model and its features are not reproducible.[/]"
            )
        report = run_replay(
            conn,
            clock=clock,
            family=family,
            until=until,
            allow_live_llm=allow_live_llm,
        )

        table = Table(title=f"Probation Report Card — {family} (Phase 4)")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Total Proposals Emitted", str(report.get("total_proposals", 0)))
        table.add_row("Total Evaluated (Strong)", str(report.get("total_evaluated", 0)))
        table.add_row("Same (Agreement)", str(report.get("same", 0)))
        table.add_row("Different (Disagreement)", str(report.get("different", 0)))
        table.add_row("Would Ask (Abstain / Ask)", str(report.get("would_ask", 0)))
        table.add_row("Censored / Weak", str(report.get("censored", 0)))
        for label, key in (
            ("Probation Agreement Rate", "accuracy"),
            ("Baseline B0 (Majority) Rate", "b0_accuracy"),
            ("Baseline B2 (Generic Rules) Rate", "b2_accuracy"),
        ):
            value = report.get(key)
            table.add_row(
                label, "Unavailable (no evaluated cohort)" if value is None else f"{value:.2%}"
            )
        console.print(table)
        acc, b0_acc = report.get("accuracy"), report.get("b0_accuracy")
        baseline = report.get("baselines", {}).get("b0", {})
        if acc is None or b0_acc is None or baseline.get("missing", 0):
            console.print("Comparison unavailable: missing or unmatched evaluation cohorts.")
        elif acc >= b0_acc:
            console.print(f"Probation agreement ({acc:.2%}) >= Baseline B0 ({b0_acc:.2%})")
        else:
            console.print(f"Probation agreement ({acc:.2%}) < Baseline B0 ({b0_acc:.2%})")
    finally:
        conn.close()
