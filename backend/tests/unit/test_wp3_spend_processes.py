"""Real process isolation for the last-unit and killed-dispatch readiness gates."""

import os
import subprocess
import sys
from pathlib import Path

from probation.db.connection import get_connection
from tests.unit.test_wp3_spend_store import BOUND, MODEL, _file_db, _provision, _store

WORKER = """
import sys
from probation.db.connection import get_connection
from probation.db.spend import SpendStore
from probation.llm.budget import BudgetExceeded
c = get_connection(sys.argv[1])
s = SpendStore(c, role="brain", lease_owner=sys.argv[2])
request = s.open_request(s.scope_for(sys.argv[3]), semantic_digest=sys.argv[2],
    prompt_id="reader.mail", prompt_version="v3", model_id=sys.argv[3], cache_key=sys.argv[2])
print("ready", flush=True)
sys.stdin.readline()
try:
    a = s.reserve(request, ordinal=1, stage="structured", estimate_units=int(sys.argv[4]),
                  tokens_in_bound=10, tokens_out_bound=10)
    if sys.argv[5] == "hold":
        s.mark_dispatched(a.attempt_id)
    print("reserved", flush=True)
except BudgetExceeded as exc:
    print(exc.code, flush=True)
if sys.argv[5] == "hold":
    sys.stdin.readline()
c.close()
"""


def _launch(db: Path, owner: str, mode: str = "finish") -> subprocess.Popen[str]:
    script = db.parent / "worker.py"
    script.write_text(WORKER, encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    return subprocess.Popen(
        [sys.executable, "-B", str(script), str(db), owner, MODEL, str(BOUND), mode],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=db.parent,
        env=env,
    )


def test_two_processes_contend_for_one_last_reservation(tmp_path: Path) -> None:
    db = _file_db(tmp_path)
    conn = get_connection(db)
    _provision(conn, cap_units=BOUND)
    conn.close()
    children = [_launch(db, "worker-a"), _launch(db, "worker-b")]
    try:
        for process in children:
            assert process.stdout is not None
            assert process.stdout.readline().strip() == "ready"
        for process in children:
            assert process.stdin is not None
            process.stdin.write("go\n")
            process.stdin.flush()
        results = []
        for process in children:
            output, errors = process.communicate(timeout=30)
            assert process.returncode == 0, errors
            results.append(output.strip())
        assert sorted(results) == ["cap_exceeded", "reserved"]
    finally:
        for process in children:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)


def test_terminated_process_leaves_dispatched_hold_after_restart(tmp_path: Path) -> None:
    db = _file_db(tmp_path)
    conn = get_connection(db)
    _provision(conn, cap_units=BOUND * 2)
    conn.close()
    process = _launch(db, "terminated-worker", "hold")
    try:
        assert process.stdout is not None and process.stdin is not None
        assert process.stdout.readline().strip() == "ready"
        process.stdin.write("go\n")
        process.stdin.flush()
        assert process.stdout.readline().strip() == "reserved"
        process.kill()
        process.communicate(timeout=10)
        conn = get_connection(db)
        try:
            store = _store(conn, owner="restart")
            totals = store.startup_totals(store.scope_for(MODEL))
            assert (totals.spent_units, totals.held_units) == (0, BOUND)
            assert conn.execute("SELECT state FROM llm_attempts").fetchone()[0] == "dispatched"
        finally:
            conn.close()
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
