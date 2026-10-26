"""Real child-process proofs that a scrubbed worker cannot reach a dotenv file.

Everything here is synthetic: the canary dotenv is created inside a pytest temporary directory,
the repository's own ``.env`` is never read, opened or copied, and no provider is contacted. The
child is launched for real through ``workers/bootstrap.py`` with a scrubbed environment, so the
verdict comes from a process the parent does not control.
"""

import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from probation.core.clock import Clock
from probation.workers.gmail_runtime import GmailRuntime, RuntimeRole

CANARY = "synthetic-canary-key-must-never-reach-a-worker"
_SRC = Path(__file__).resolve().parents[2] / "src"

#: Reports, and never prints, the value it was given: whether Settings read a dotenv, whether a
#: dotenv path is still configured, and which worker marker the child carries.
_PROBE = f"""\
import os
import sys
from probation.config import settings

verdict = "LEAK" if settings.llm_api_key == {CANARY!r} else "CLEAN"
dotenv = "file" if os.environ.get("PROBATION_ENV_FILE") else "no-file"
role = os.environ.get("PROBATION_WORKER_ROLE", "unmarked")
print(f"{{verdict}}|{{dotenv}}|{{role}}")
"""


def _child_env(probe_dir: Path, extra: dict[str, str]) -> dict[str, str]:
    """A scrubbed child environment: OS essentials plus the import path, nothing else."""
    base = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"),
        "COMSPEC": os.environ.get("COMSPEC", "cmd.exe"),
        "TEMP": os.environ.get("TEMP", "."),
        "TMP": os.environ.get("TMP", "."),
        "PYTHONHASHSEED": "0",
        "PYTHONPATH": os.pathsep.join((str(_SRC), str(probe_dir))),
    }
    return {**base, **extra}


def _run(directory: Path, argv: list[str], env: dict[str, str]) -> str:
    result = subprocess.run(
        [sys.executable, *argv],
        cwd=str(directory),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout.strip()


@pytest.fixture
def canary_home(tmp_path: Path) -> Path:
    """A temporary directory holding a synthetic canary dotenv and the settings probe."""
    directory = tmp_path / "canary-home"
    directory.mkdir()
    (directory / ".env").write_text(f"LLM_API_KEY={CANARY}\n", encoding="utf-8")
    directory.joinpath("d6_env_probe.py").write_text(textwrap.dedent(_PROBE), encoding="utf-8")
    return directory


def test_the_canary_dotenv_is_reachable_for_an_unprotected_import(canary_home: Path) -> None:
    """Control: the canary really would load, so the worker result below means something."""
    verdict = _run(
        canary_home,
        [str(canary_home / "d6_env_probe.py")],
        _child_env(canary_home, {"PROBATION_ENV_FILE": ".env"}),
    )
    assert verdict.startswith("LEAK|file|unmarked")


@pytest.mark.parametrize("role", ["api", "brain", "webfacts", "executor"])
def test_scrubbed_bootstrap_child_cannot_load_the_dotenv(canary_home: Path, role: str) -> None:
    """The marker is installed before any application import, so no dotenv is consulted."""
    bootstrap = _SRC / "probation" / "workers" / "bootstrap.py"
    verdict = _run(
        canary_home,
        [
            str(bootstrap),
            "--role",
            role,
            "--db",
            str(canary_home / "engine.db"),
            "--module",
            "d6_env_probe",
        ],
        _child_env(canary_home, {"PROBATION_ENV_FILE": str(canary_home / ".env")}),
    )
    assert verdict == f"CLEAN|no-file|{role}"


def test_worker_settings_treat_one_mapping_as_the_whole_authority() -> None:
    """The role and the values come from the same mapping, so they can never disagree."""
    from probation.config import load_settings

    scrubbed = {"PROBATION_WORKER_ROLE": "api"}
    assert load_settings(scrubbed).llm_api_key == ""
    assert load_settings({**scrubbed, "LLM_API_KEY": CANARY}).llm_api_key == CANARY
    assert load_settings({**scrubbed, "LLM_API_KEY": ""}).llm_api_key == ""


def test_runtime_child_environments_are_built_without_touching_the_parent(
    tmp_path: Path,
) -> None:
    """No role is ever launched through a temporarily rewritten ``os.environ``."""
    before = dict(os.environ)
    parent = {"PATH": os.environ.get("PATH", ""), "LLM_API_KEY": CANARY}
    runtime = GmailRuntime(
        db_path=tmp_path / "engine.db",
        private_store_path=tmp_path / "private" / "gmail.db",
        env=parent,
        clock=Clock.replay(),
    )
    launched: list[dict[str, str]] = []

    def launch(_command: object, env: dict[str, str]) -> _NullProcess:
        launched.append(env)
        return _NullProcess()

    stop = threading.Event()
    stop.set()
    runtime._launcher = launch  # type: ignore[assignment]
    runtime.run(stop, join_timeout=0.01)
    assert dict(os.environ) == before
    assert len(launched) == len(RuntimeRole)
    assert all(child is not parent for child in launched)
    api = runtime._child_env(RuntimeRole.API, None)
    assert "LLM_API_KEY" not in api and CANARY not in api.values()


class _NullProcess:
    def __init__(self) -> None:
        self.returncode: int | None = 0

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0

    def terminate(self) -> None:
        return None

    def kill(self) -> None:
        return None
