"""Refuse snapshot replacement when it would erase real spending authority/history."""

import sqlite3
from pathlib import Path

from probation.llm.budget import BudgetExceeded


def ensure_resettable(path: Path) -> None:
    if not path.exists():
        return
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            tables = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            for table in ("budget_scopes", "llm_requests", "llm_attempts"):
                if table in tables and conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                    raise BudgetExceeded(
                        "This demo cannot reset without losing its live model budget records.",
                        code="funded_demo_reset_denied",
                    )
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise BudgetExceeded(
            "Cannot verify demo reset accounting", code="accounting_store_unavailable"
        ) from exc


if __name__ == "__main__":
    import sys

    try:
        ensure_resettable(Path(sys.argv[1]))
    except BudgetExceeded as exc:
        raise SystemExit(str(exc)) from None
