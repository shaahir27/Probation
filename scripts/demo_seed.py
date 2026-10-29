"""Build the shipped synthetic demo snapshot under ``demo/seed/``.

The snapshot is three files: ``engine.db``, ``connector_store.db`` and ``world.db``.
``scripts/demo_boot.py`` copies the first two into the runtime paths on a cold start.
Rebuilding replaces the snapshot; the runtime database is never touched here.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "demo" / "seed").resolve()
    target.mkdir(parents=True, exist_ok=True)
    for name in ("engine.db", "engine.db-wal", "engine.db-shm", "connector_store.db", "world.db"):
        (target / name).unlink(missing_ok=True)
    environment = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "COMSPEC")
        if key in os.environ
    }
    environment.update(
        {
            "PROBATION_WORKER_ROLE": "api",
            "APP_PROFILE": "synthetic",
            "CLOCK_MODE": "live",
            "PROBATION_GMAIL_OWNER_API_KEY": "synthetic-demo-owner-key",
            "PROBATION_GMAIL_OWNER_ID": "local-owner",
            "PROBATION_GMAIL_STORE": str(target / "connector_store.db"),
            "PROBATION_ACCOUNTS_DB": str(target / "accounts.db"),
            "PROBATION_D6_E2E_ITEMS": "3",
            "PYTHONPATH": str(ROOT / "backend" / "src"),
        }
    )
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "d6_e2e_seed.py"), str(target)],
        env=environment,
        check=True,
    )
    print(f"Synthetic demo snapshot ready at {target}")
    print("Cold start copies it to the runtime paths; it never overwrites an existing DB.")
    print("  demo/seed/engine.db          -> DB_PATH")
    print("  demo/seed/connector_store.db -> PROBATION_GMAIL_STORE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
