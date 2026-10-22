"""Shared CLI command groups; importing this module performs no application I/O."""

import typer
from rich.console import Console

app = typer.Typer(help="Probation: Earned autonomy personal AI engine.")
db_app = typer.Typer(help="Database operations.")
ledger_app = typer.Typer(help="Ledger operations.")
budget_app = typer.Typer(help="Budget inspection.")
synth_app = typer.Typer(help="Synthetic world generation.")
import_app = typer.Typer(help="Source data importers.")
exam_app = typer.Typer(help="Examination board.")
webfacts_app = typer.Typer(help="Web facts and Tavily vetting operations.")
habits_app = typer.Typer(help="Habit mining operations.")
chains_app = typer.Typer(help="Chain sequence mining operations.")
eval_app = typer.Typer(help="Evaluation and benchmark suite.")

app.add_typer(db_app, name="db")
app.add_typer(ledger_app, name="ledger")
app.add_typer(budget_app, name="budget")
app.add_typer(synth_app, name="synth")
app.add_typer(import_app, name="import")
app.add_typer(exam_app, name="exam")
app.add_typer(webfacts_app, name="webfacts")
app.add_typer(habits_app, name="habits")
app.add_typer(chains_app, name="chains")
app.add_typer(eval_app, name="eval")

console = Console()
