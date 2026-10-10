"""Unit tests for security boundaries, temporal clock isolation, and actor permissions.

Authority: docs/TEST_PLAN.md (T-CLOCK, T-SEC) and docs/CONTRACT.md section 3, invariants I-2, I-9, I-19.
"""

import ast
import sqlite3
from pathlib import Path

import pytest

from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.db.access import AccessError, Role, get_role_access


def test_t_clock_no_wall_clock_in_engine_modules() -> None:
    """T-CLOCK: Static AST check verifies no direct datetime.now() or time.time() calls in engine."""
    engine_dir = Path(__file__).resolve().parent.parent.parent / "src" / "probation" / "engine"
    core_dir = Path(__file__).resolve().parent.parent.parent / "src" / "probation" / "core"

    # Scan all files under engine/ and core/ (except core/clock.py)
    files_to_check = list(engine_dir.glob("**/*.py")) + [
        p for p in core_dir.glob("*.py") if p.name != "clock.py"
    ]

    violations: list[str] = []
    for py_file in files_to_check:
        with open(py_file, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(py_file))

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check for datetime.now()
                if isinstance(node.func, ast.Attribute) and node.func.attr == "now":
                    violations.append(f"{py_file.name}:{node.lineno} - direct datetime.now() call")
                # Check for time.time()
                elif isinstance(node.func, ast.Attribute) and node.func.attr == "time":
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == "time":
                        violations.append(f"{py_file.name}:{node.lineno} - direct time.time() call")

    assert violations == [], (
        f"Found disallowed system clock calls in engine/core modules: {violations}"
    )


def test_t_clock_monotonicity() -> None:
    """T-CLOCK: Clock advances forward monotonically and forbids backward movement."""
    from datetime import UTC, datetime

    clock = Clock(mode=ClockMode.REPLAY, initial_time=datetime(2026, 6, 1, 10, 0, tzinfo=UTC))
    clock.advance_seconds(120)
    assert clock.now_iso() == "2026-06-01T10:02:00Z"

    # Attempt to move backward
    earlier = datetime(2026, 6, 1, 9, 59, tzinfo=UTC)
    with pytest.raises(ValueError):
        clock.set_time(earlier)


def test_t_sec_role_access_boundaries(memory_db: sqlite3.Connection) -> None:
    """T-SEC: RoleAccess enforces per-process table write boundaries (CONTRACT section 3)."""
    brain = get_role_access(memory_db, Role.BRAIN)
    ingestor = get_role_access(memory_db, Role.INGESTOR)
    executor = get_role_access(memory_db, Role.EXECUTOR)

    # Brain is permitted to write to proposals
    brain.verify_write("proposals")
    brain.verify_write("llm_cache")
    brain.verify_write("exposure_log")

    # Brain is PROHIBITED from writing to actions or sources
    with pytest.raises(AccessError):
        brain.verify_write("actions")
    with pytest.raises(AccessError):
        brain.verify_write("sources")

    # Ingestor is permitted to write to raw_items, but NOT proposals or actions
    ingestor.verify_write("raw_items")
    with pytest.raises(AccessError):
        ingestor.verify_write("proposals")
    with pytest.raises(AccessError):
        ingestor.verify_write("actions")

    # Executor is permitted to write to actions, but NOT proposals
    executor.verify_write("actions")
    with pytest.raises(AccessError):
        executor.verify_write("proposals")
