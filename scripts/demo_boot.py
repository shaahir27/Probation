"""Cold-start boot for the shipped synthetic demo.

If the runtime database or connector store is absent, copy the committed snapshot from
``demo/seed/``. An existing database is never overwritten: a restart keeps the workspace
the judge already saw, and ``scripts/demo_reset.sh`` is the only thing that restores it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "demo" / "seed"


def _copy_if_absent(source: Path, target: Path) -> None:
    if target.exists():
        return
    if not source.is_file():
        raise SystemExit(f"demo snapshot is missing: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def main() -> int:
    db_path = Path(os.environ.get("DB_PATH", "/data/db/probation.db"))
    store = os.environ.get("PROBATION_GMAIL_STORE", "").strip()
    store_path = (
        Path(store)
        if store
        else db_path.parent.parent / "private" / "connectors" / "gmail_metadata.db"
    )
    _copy_if_absent(SEED / "engine.db", db_path)
    _copy_if_absent(SEED / "connector_store.db", store_path)
    if shutil.which("cron"):
        subprocess.Popen(
            ["cron"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True
        )
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "probation.api.app:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
