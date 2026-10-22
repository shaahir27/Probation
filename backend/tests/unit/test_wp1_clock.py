"""WP1: UTC/microsecond chronology, alias-aware clock checks and semantic IDs."""

import ast
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from probation.core.clock import Clock
from probation.core.history import HistoryView
from probation.core.types import Situation


def test_clock_normalizes_offsets_and_preserves_microseconds() -> None:
    local = datetime(2026, 1, 1, 10, 0, 0, 123456, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    clock = Clock.replay(local)
    assert clock.now().tzinfo == UTC
    assert clock.now_iso() == "2026-01-01T04:30:00.123456Z"


def test_live_clock_rejects_backwards_system_time(monkeypatch: pytest.MonkeyPatch) -> None:
    import probation.core.clock as clock_module

    clock = Clock.live()
    readings = iter([datetime(2026, 1, 1, 10, tzinfo=UTC), datetime(2026, 1, 1, 9, tzinfo=UTC)])

    class WallClock:
        @staticmethod
        def now(tz: object) -> datetime:
            return next(readings)

    monkeypatch.setattr(clock_module, "datetime", WallClock)
    assert clock.now().hour == 10
    with pytest.raises(ValueError):
        clock.now()


def test_history_compares_instants_not_timestamp_spellings(
    memory_db: sqlite3.Connection, basic_situation: Situation
) -> None:
    for name, known in [
        ("before", "2026-01-01T10:00:00.500000Z"),
        ("equal", "2026-01-01T10:00:00Z"),
        ("after", "2026-01-01T10:00:00.750000Z"),
    ]:
        memory_db.execute(
            "INSERT INTO raw_items VALUES (?, 'wp1-source', 'mail', 'mail_in', ?, '2026-01-01T10:00:00Z', ?, '{}', 'synthetic')",
            (name, name, known),
        )
    history = HistoryView(memory_db, as_of=datetime(2026, 1, 1, 10, 0, 0, 600000, tzinfo=UTC))
    rows = history.get_raw_items()
    assert {row["id"] for row in rows} == {"before", "equal", "wp1-raw"}
    assert rows[-1]["id"] == "before"


def _clock_violations(source: str) -> list[str]:
    tree = ast.parse(source)
    aliases = {"datetime": "datetime", "date": "date", "time": "time"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases.update({alias.asname or alias.name: alias.name for alias in node.names})
        elif isinstance(node, ast.ImportFrom) and node.module:
            aliases.update(
                {alias.asname or alias.name: f"{node.module}.{alias.name}" for alias in node.names}
            )

    def qualified(node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return qualified(node.value) + "." + node.attr
        if isinstance(node, ast.Call):
            name = qualified(node.func)
            if name in {"__import__", "importlib.import_module"} and node.args:
                module = node.args[0]
                if isinstance(module, ast.Constant) and isinstance(module.value, str):
                    return module.value
            if name == "getattr" and len(node.args) >= 2:
                attribute = node.args[1]
                if isinstance(attribute, ast.Constant) and isinstance(attribute.value, str):
                    return qualified(node.args[0]) + "." + attribute.value
        return ""

    # Resolve aliases to functions/modules as well as aliases declared by imports.
    for _ in range(len(list(ast.walk(tree)))):
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            resolved = qualified(value)
            for target in targets:
                if isinstance(target, ast.Name) and resolved and aliases.get(target.id) != resolved:
                    aliases[target.id] = resolved
                    changed = True
        if not changed:
            break

    forbidden = {
        "datetime.now",
        "datetime.utcnow",
        "datetime.today",
        "date.today",
        "datetime.datetime.now",
        "datetime.datetime.utcnow",
        "datetime.datetime.today",
        "datetime.date.today",
        "time.time",
        "time.time_ns",
        "time.monotonic",
        "time.monotonic_ns",
        "time.perf_counter",
        "time.perf_counter_ns",
    }
    return [
        qualified(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and qualified(node.func) in forbidden
    ]


@pytest.mark.parametrize(
    "source",
    [
        "from datetime import datetime as D\nD.utcnow()",
        "import datetime as d\nd.datetime.now()",
        "from time import time as seconds\nseconds()",
        "from datetime import date as d\nd.today()",
        "from datetime import datetime as D\nnow = D.now\nnow()",
        "import time as t\nfirst = t.time\nsecond = first\nsecond()",
        "import datetime as d\ngetattr(d.datetime, 'utcnow')()",
        "__import__('time').time()",
        "from importlib import import_module as load\nload('datetime').datetime.now()",
        "import importlib as i\nm = i.import_module('time')\nm.perf_counter()",
    ],
)
def test_clock_scan_detects_aliases_and_utcnow(source: str) -> None:
    assert _clock_violations(source)


def test_all_application_modules_use_clock_boundary() -> None:
    root = Path(__file__).resolve().parents[2] / "src/probation"
    violations = {
        str(path.relative_to(root)): _clock_violations(path.read_text(encoding="utf-8"))
        for path in root.rglob("*.py")
        if path != root / "core/clock.py"
    }
    assert {name: calls for name, calls in violations.items() if calls} == {}


def test_same_exam_request_has_a_stable_id(memory_db: sqlite3.Connection) -> None:
    from probation.engine.exam import run_exam

    kwargs = {
        "class_key": "mail|request|known",
        "action": "ARCHIVE",
        "as_of": "2026-01-01T10:00:00Z",
        "seed": 7,
    }
    first = run_exam(memory_db, **kwargs)
    second = run_exam(memory_db, **kwargs)
    assert first.run_id == second.run_id
    assert memory_db.execute("SELECT count(*) FROM exam_runs").fetchone()[0] == 1
    assert memory_db.execute("SELECT count(*) FROM ledger WHERE kind='exam_run'").fetchone()[0] == 1


def test_deliberate_exam_attempt_has_explicit_stable_ordinal(memory_db: sqlite3.Connection) -> None:
    from probation.engine.exam import run_exam

    kwargs = {
        "class_key": "mail|request|known",
        "action": "ARCHIVE",
        "as_of": "2026-06-01T10:00:00Z",
    }
    first = run_exam(memory_db, **kwargs, attempt_ordinal=0)
    second = run_exam(memory_db, **kwargs, attempt_ordinal=1)
    retry = run_exam(memory_db, **kwargs, attempt_ordinal=1)
    assert first.run_id != second.run_id == retry.run_id
    with pytest.raises(ValueError):
        run_exam(memory_db, **kwargs, attempt_ordinal=-1)


def test_replay_rejects_events_before_its_injected_clock(
    memory_db: sqlite3.Connection,
    basic_situation: Situation,
) -> None:
    from probation.engine.replay import run_replay

    clock = Clock.replay(datetime(2026, 6, 1, tzinfo=UTC))
    with pytest.raises(ValueError):
        run_replay(memory_db, clock=clock)
    assert memory_db.execute("SELECT count(*) FROM actions").fetchone()[0] == 0
