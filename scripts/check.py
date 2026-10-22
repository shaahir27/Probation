"""Portable `make check`: verify a secret-free snapshot without changing published data.

Run with the selected project interpreter: python scripts/check.py.
Only the standard library is imported before invoking the installed checking tools.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = ("backend/tests/fixtures", "docs/results")


def protected_hashes(root: Path) -> dict[str, str]:
    """Hash synthetic fixtures and published results, never environment/private files."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for relative in PROTECTED
        for path in (root / relative).rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def snapshot(workspace: Path) -> None:
    """Copy tracked and unignored working files, excluding credentials/local records."""
    names = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
        )
        .decode("utf-8")
        .split("\0")
    )
    excluded = {
        ".git",
        ".aws",
        ".codex",
        ".agents",
        "build_history",
        "graphify-out",
        "data",
    }
    for name in names:
        relative = Path(name)
        if not name or any(part in excluded for part in relative.parts):
            continue
        if relative.name.startswith(".env") or relative.suffix in {".pem", ".key"}:
            continue
        source = ROOT / relative
        if source.is_symlink() or not source.resolve().is_relative_to(ROOT):
            raise RuntimeError(f"Refusing linked/out-of-tree check input: {relative}")
        if source.is_file():
            dest = workspace / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)


def command(args: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> int:
    """Run a checker with the exact interpreter that launched this script."""
    print("+", sys.executable, "-m", *args, flush=True)
    return subprocess.call([sys.executable, "-m", *args], cwd=cwd, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests-only", action="store_true")
    parser.add_argument("--coverage", action="store_true")
    args = parser.parse_args()
    before = protected_hashes(ROOT)
    if not args.tests_only:
        commands = [
            ["ruff", "check", "backend", "scripts/check.py"],
            ["ruff", "format", "--check", "backend", "scripts/check.py"],
            [
                "mypy",
                "--config-file",
                "backend/pyproject.toml",
                "backend/src/probation",
            ],
            [
                "mypy",
                "--strict",
                "--config-file",
                "backend/pyproject.toml",
                "backend/src/probation/core",
                "backend/src/probation/engine",
            ],
        ]
        for args_list in commands:
            code = command(args_list, cwd=ROOT)
            if code:
                return code
    parent = (ROOT / "data/checks").resolve()
    if not parent.is_relative_to(ROOT):
        raise RuntimeError(
            "Check workspaces must stay inside the project data directory."
        )
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="run-", dir=parent, ignore_cleanup_errors=True
    ) as name:
        workspace = Path(name).resolve()
        if not workspace.is_relative_to(parent):
            raise RuntimeError("Invalid check workspace.")
        snapshot(workspace)
        (workspace / "data").mkdir(exist_ok=True)
        snapshot_before = protected_hashes(workspace)
        env = os.environ.copy()
        for key in ("LLM_API_KEY", "TAVILY_API_KEY"):
            env.pop(key, None)
        env.update(
            PYTHONPATH=str(workspace / "backend/src"),
            DB_PATH=str(workspace / "data/db/checks.db"),
            WORLD_DB_PATH=str(workspace / "data/synth/world.db"),
            PRICE_TABLE_PATH=str(workspace / "config/prices.json"),
            USER_ADDRESSES="meena@example.test",
            USER_NAME_TOKENS="",
            FILES_WATCH_DIRS=str(workspace / "data/synth/1/fs/Downloads"),
            FILES_ALLOWED_ROOTS=str(workspace / "data/synth/1/fs"),
            HF_HUB_OFFLINE="1",
        )
        tests = [
            "pytest",
            "-q",
            "-c",
            "backend/pyproject.toml",
            "backend/tests",
            "-m",
            "not live",
            "--basetemp",
            str(workspace / "data/pytest"),
            "--tb=short",
        ]
        if args.coverage:
            tests.extend(["--cov=probation", "--cov-report=term-missing"])
        code = command(tests, cwd=workspace, env=env)
        if protected_hashes(workspace) != snapshot_before:
            print(
                "FAIL: tests modified synthetic fixtures or published results in the snapshot."
            )
            code = 1
        if protected_hashes(ROOT) != before:
            print("FAIL: original synthetic fixtures or published results changed.")
            code = 1
        if not code:
            print(
                "Checks passed; fixture/result hashes unchanged in source and test snapshot."
            )
        return code


if __name__ == "__main__":
    raise SystemExit(main())
