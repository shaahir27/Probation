"""Existing CLI workflows, split into focused registration modules."""

from pathlib import Path

import typer
from rich.table import Table

from probation.cli_apps import (
    console,
    eval_app,
)


@eval_app.callback(invoke_without_command=True)
def eval_callback(
    ctx: typer.Context,
    suite: str = typer.Option(
        "main", "--suite", "-s", help="Evaluation suite name (main, fast, ablations)"
    ),
) -> None:
    """Evaluation operations and benchmark runner."""
    if ctx.invoked_subcommand is None:
        eval_run_cmd(suite=suite, db=None, truth=None, out=None, seed=1)


@eval_app.command("run")
def eval_run_cmd(
    suite: str = typer.Option(
        "main", "--suite", "-s", help="Evaluation suite name (main, fast, ablations)"
    ),
    db: str | None = typer.Option(None, "--db", help="Path to database"),
    truth: str | None = typer.Option(None, "--truth", help="Path to counterfactual truth.json"),
    out: str | None = typer.Option(None, "--out", "-o", help="Output path for results JSON"),
    seed: int = typer.Option(1, "--seed", help="Random seed for sampling"),
) -> None:
    """Execute evaluation suite across Probation and baselines B0-B3 (Phase 10)."""
    from probation.eval.run_eval import export_evaluation_results, run_evaluation

    actual_suite = suite if isinstance(suite, str) else "main"
    actual_db = db if isinstance(db, str) else None
    actual_truth = truth if isinstance(truth, str) else None
    actual_out = out if isinstance(out, str) else None
    actual_seed = seed if isinstance(seed, int) else 1

    console.print(
        f"[bold cyan]Running evaluation suite '{actual_suite}' (Phase 10, seed={actual_seed})...[/]"
    )
    db_path = Path(actual_db) if actual_db else None
    truth_path = Path(actual_truth) if actual_truth else None

    results = run_evaluation(
        db_path=db_path, truth_path=truth_path, suite=actual_suite, seed=actual_seed
    )

    out_json = Path(actual_out) if actual_out else Path("data/results") / f"{actual_suite}.json"
    out_md = out_json.with_suffix(".md")

    export_evaluation_results(results, json_path=out_json, markdown_path=out_md)

    meta = results.get("metadata", {})
    comp = results.get("main_comparison", {})
    pro = comp.get("probation", {})
    b0 = comp.get("b0_majority", {})
    b1 = comp.get("b1_ask_always", {})
    b2 = comp.get("b2_generic_rules", {})
    b3 = comp.get("b3_llm_confidence_sweeps", {})
    eff = results.get("resource_efficiency", {})

    table = Table(
        title=f"Probation Benchmark Results — Suite: {suite} (N={meta.get('total_situations')})"
    )
    table.add_column("System / Model", style="cyan")
    table.add_column("Agreement", justify="right")
    table.add_column("Attention/100", justify="right")
    table.add_column("Auto Err Rate", justify="right")
    table.add_column("Harm Loss", justify="right")
    table.add_column("Coverage", justify="right")

    table.add_row(
        "[bold green]Probation (Ours)[/]",
        f"{pro.get('agreement_all', 0.0):.1%}",
        f"{pro.get('attention_units_per_100', 0.0):.1f}",
        f"{pro.get('autonomous_error_rate', 0.0):.1%}",
        f"{pro.get('harm_weighted_error', 0.0):.1%}",
        f"{pro.get('autonomous_coverage', 0.0):.1%}",
    )
    table.add_row(
        "B0 (Majority)",
        f"{b0.get('agreement', 0.0):.1%}",
        "100.0",
        "N/A",
        "N/A",
        "0.0%",
    )
    table.add_row(
        "B1 (Ask Always)",
        "N/A",
        f"{b1.get('attention_units_per_100', 100.0):.1f}",
        "0.0%",
        "0.0%",
        "0.0%",
    )
    table.add_row(
        "B2 (Generic Heuristics)",
        "N/A",
        f"{b2.get('attention_units_per_100', 0.0):.1f}",
        f"{b2.get('autonomous_error_rate', 0.0):.1%}",
        f"{b2.get('harm_weighted_error', 0.0):.1%}",
        "N/A",
    )
    for tau, vals in sorted(b3.items()):
        table.add_row(
            f"B3 (LLM Conf tau={tau})",
            "N/A",
            f"{vals.get('attention_units_per_100', 0.0):.1f}",
            f"{vals.get('autonomous_error_rate', 0.0):.1%}",
            "N/A",
            "N/A",
        )

    console.print(table)
    console.print(
        f"[bold green]Evaluation complete.[/] "
        f"Exported JSON: [yellow]{out_json}[/] | Markdown: [yellow]{out_md}[/] | LLM Spend: [cyan]${eff.get('spend_usd', 0.0):.4f}[/]"
    )


@eval_app.command("report")
def eval_report_cmd(
    results_path: str = typer.Option(
        "docs/results/main.json", "--results", "-r", help="Path to evaluation results JSON"
    ),
) -> None:
    """Display benchmark evaluation report from results JSON."""
    import json

    from probation.eval.run_eval import format_results_markdown

    path = Path(results_path)
    if not path.exists():
        console.print(f"[bold red]Results file not found at:[/] {path}")
        raise typer.Exit(code=1)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    md = format_results_markdown(data)
    console.print(md)
