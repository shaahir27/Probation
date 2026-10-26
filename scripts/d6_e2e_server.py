"""Start an isolated, synthetic D6 API plus the BUILT frontend for Playwright.

One run namespace = one ephemeral loopback pair + one throwaway synthetic workspace.
The principal proof never touches the Vite dev server: this script builds the React
app into the run's own directory and serves that output with `vite preview`.

Required environment (set by frontend/playwright.config.ts):
  PROBATION_D6_E2E_NAMESPACE   run-scoped id; names the workspace, dist and stop file
  PROBATION_D6_E2E_API_PORT    free loopback port for the API
  PROBATION_D6_E2E_WEB_PORT    free loopback port for the built frontend
Optional:
  PROBATION_D6_E2E_ITEMS       how many unanswered ASK items to seed (default 1)
  PROBATION_D6_E2E_STOP_FILE   file whose creation ends the run
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[1]
FRONTEND = WORKTREE / "frontend"
API_HOST = "127.0.0.1"
WEB_HOST = "127.0.0.1"
OWNER_ID = "d6-e2e-owner"
CONNECTION_ID = "d6-e2e-connection"
OWNER_KEY = "d6-e2e-synthetic-owner-key-only-never-for-private-use"
SOURCE_ID = f"gmail-source:{CONNECTION_ID}"


def _required_int(name: str) -> int:
    raw = os.environ.get(name, "")
    if not raw.isdigit() or not (1024 <= int(raw) <= 65535):
        raise RuntimeError(f"{name} must be a free loopback port between 1024 and 65535.")
    return int(raw)


def _minimal_environment(temp_root: Path, api_port: int, namespace: str, items: int) -> dict[str, str]:
    """Pass only runtime necessities and synthetic test configuration to child processes."""
    environment = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "COMSPEC", "USERPROFILE", "LOCALAPPDATA")
        if key in os.environ
    }
    environment.update(
        {
            "PROBATION_WORKER_ROLE": "api",
            "DB_PATH": str(temp_root / "engine.db"),
            "WORLD_DB_PATH": str(temp_root / "world.db"),
            "CLOCK_MODE": "live",
            "LLM_API_KEY": "",
            "TAVILY_API_KEY": "",
            "PROBATION_GMAIL_OWNER_API_KEY": OWNER_KEY,
            "PROBATION_GMAIL_OWNER_ID": OWNER_ID,
            "PROBATION_GMAIL_STORE": str(temp_root / "private" / "gmail_metadata.db"),
            "PROBATION_GMAIL_BIND_HOST": "127.0.0.1",
            "PYTHONPATH": str(WORKTREE / "backend" / "src"),
            "PYTHONUNBUFFERED": "1",
            "PROBATION_D6_E2E_API_TARGET": f"http://{API_HOST}:{api_port}",
            "PROBATION_D6_E2E_NAMESPACE": namespace,
            "PROBATION_D6_E2E_STOP_FILE": os.environ.get("PROBATION_D6_E2E_STOP_FILE", ""),
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    environment["PROBATION_D6_E2E_ITEMS"] = str(items)
    return environment


def _backend_python(original_path: str) -> str:
    """Use the installed backend interpreter when the launcher Python is too bare."""
    uvicorn = shutil.which("uvicorn", path=original_path)
    if uvicorn:
        candidate = Path(uvicorn).resolve().parent.parent / "python.exe"
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def _node_binary(path: str) -> str:
    node = shutil.which("node.exe", path=path) or shutil.which("node", path=path)
    if node is None:
        raise RuntimeError("Node.js was not found on PATH for the D6 E2E web server.")
    return node


def _wait_for(url: str, process: subprocess.Popen[bytes], label: str) -> None:
    for _attempt in range(240):
        if process.poll() is not None:
            raise RuntimeError(f"D6 E2E {label} server exited during startup.")
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.25)
    raise RuntimeError(f"D6 E2E {label} server did not become ready in time.")


def _stop(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _run_checked(command: list[str], cwd: Path, log, label: str) -> None:
    """Run a build step to completion; a failed build must stop the harness loudly."""
    result = subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, check=False)
    log.flush()
    if result.returncode != 0:
        raise RuntimeError(f"D6 E2E could not {label} (exit {result.returncode}). See the run log for details.")


def main() -> int:
    namespace = os.environ.get("PROBATION_D6_E2E_NAMESPACE", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", namespace):
        raise RuntimeError("PROBATION_D6_E2E_NAMESPACE is missing or invalid.")
    api_port = _required_int("PROBATION_D6_E2E_API_PORT")
    web_port = _required_int("PROBATION_D6_E2E_WEB_PORT")
    items = int(os.environ.get("PROBATION_D6_E2E_ITEMS", "1") or "1")

    with tempfile.TemporaryDirectory(
        prefix=f"probation-d6-e2e-{namespace}-", ignore_cleanup_errors=True
    ) as temp_name:
        temp_root = Path(temp_name)
        dist_root = temp_root / "dist"
        original_path = os.environ.get("PATH", "")
        python = _backend_python(original_path)
        node = _node_binary(original_path)
        environment = _minimal_environment(temp_root, api_port, namespace, items)
        os.environ.clear()
        os.environ.update(environment)

        seed = subprocess.run(
            [python, str(WORKTREE / "scripts" / "d6_e2e_seed.py"), str(temp_root)],
            cwd=temp_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if seed.returncode:
            sys.stderr.write(seed.stderr or seed.stdout)
            raise RuntimeError("Could not prepare the isolated synthetic D6 data store.")

        build_log = (temp_root / "build.log").open("wb")
        api_log = (temp_root / "api.log").open("wb")
        web_log = (temp_root / "web.log").open("wb")
        api: subprocess.Popen[bytes] | None = None
        web: subprocess.Popen[bytes] | None = None
        try:
            # The principal proof runs the production bundle, never the dev server.
            _run_checked(
                [
                    node,
                    str(FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"),
                    "build",
                    "--outDir",
                    str(dist_root),
                    "--emptyOutDir",
                    "--logLevel",
                    "warn",
                ],
                FRONTEND,
                build_log,
                "build the frontend",
            )
            if not (dist_root / "index.html").is_file():
                raise RuntimeError("The D6 E2E frontend build produced no index.html.")
            api = subprocess.Popen(
                [
                    python,
                    "-m",
                    "uvicorn",
                    "probation.api.app:app",
                    "--host",
                    API_HOST,
                    "--port",
                    str(api_port),
                ],
                cwd=temp_root,
                env=environment,
                stdout=api_log,
                stderr=subprocess.STDOUT,
            )
            _wait_for(f"http://{API_HOST}:{api_port}/api/health", api, "API")
            web = subprocess.Popen(
                [
                    node,
                    str(FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"),
                    "preview",
                    "--host",
                    WEB_HOST,
                    "--port",
                    str(web_port),
                    "--strictPort",
                    "--outDir",
                    str(dist_root),
                ],
                cwd=FRONTEND,
                env=environment,
                stdout=web_log,
                stderr=subprocess.STDOUT,
            )
            _wait_for(f"http://{WEB_HOST}:{web_port}/", web, "web")
            print("Synthetic D6 E2E servers are ready on loopback.")
            stop_path = environment["PROBATION_D6_E2E_STOP_FILE"]
            stop_file = Path(stop_path) if stop_path else None
            if stop_file is not None and (
                stop_file.parent.resolve() != Path(tempfile.gettempdir()).resolve()
                or not re.fullmatch(rf"probation-d6-e2e-stop-{re.escape(namespace)}-\d+", stop_file.name)
            ):
                raise RuntimeError("The D6 E2E stop marker path is invalid.")
            while api.poll() is None and web.poll() is None and not (stop_file and stop_file.exists()):
                time.sleep(0.5)
            if stop_file and stop_file.exists():
                stop_file.unlink(missing_ok=True)
                return 0
            raise RuntimeError("A D6 E2E server stopped unexpectedly.")
        except KeyboardInterrupt:
            return 0
        finally:
            _stop(web)
            _stop(api)
            build_log.close()
            api_log.close()
            web_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
