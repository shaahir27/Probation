"""Owner-only launch/status for a separate read-credential setup process.

The API never reads Google credentials, receives an OAuth callback, or contacts Google.
Only the child setup process loads its OAuth client and persists a verified readonly grant.
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal, Protocol
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from probation.api.authority import OwnerContext, require_owner
from probation.api.gmail_auth import is_loopback_host
from probation.api.routes.gmail_connector import current_config
from probation.config import settings
from probation.connectors.acl import verify_owner_only
from probation.connectors.credentials_state import BASE_CHILD_ENV
from probation.connectors.gmail_read_grant import (
    registered_read_grant as find_registered_read_grant,
)
from probation.connectors.gmail_read_grant import (
    registered_write_grant as find_registered_write_grant,
)
from probation.connectors.gmail_read_grant import (
    token_exists,
)
from probation.core.clock import configure_clock_collation
from probation.db.connection import ManagedConnection
from probation.db.gmail_store import ConnectorAccess

router = APIRouter(prefix="/api/gmail/setup", tags=["gmail-setup"])
Owner = Annotated[OwnerContext, Depends(require_owner)]
_ROOT = Path(__file__).resolve().parents[4]
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_INIT_LOCK = Lock()


class SetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal["v1"]
    request_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")

    @field_validator("request_id")
    @classmethod
    def no_traversal(cls, value: str) -> str:
        if ".." in value:
            raise ValueError("request_id must not contain traversal")
        return value


class ConnectionState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal["v1"] = "v1"
    connected: bool
    status: Literal["not_connected", "connected"]
    reason: str | None = None


class SetupState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal["v1"] = "v1"
    request_id: str
    status: Literal["awaiting_consent", "succeeded", "failed", "unknown"]
    status_url: str
    connected: bool = False
    existing: bool = False
    reason: str | None = None


class SetupProcess(Protocol):
    def poll(self) -> int | None: ...


def _launch(owner_id: str, store: Path, kind: str = "read") -> SetupProcess:
    """Fixed script/argv and exact child allowlist; neither a key nor URL crosses this pipe."""
    env = {key: value for key, value in os.environ.items() if key.upper() in BASE_CHILD_ENV}
    env.update(
        PROBATION_WORKER_ROLE="observation",
        PROBATION_GMAIL_OWNER_ID=owner_id,
        PROBATION_GMAIL_STORE=str(store.resolve()),
        PYTHONPATH=str(_ROOT / "backend/src"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    action = "--authorize-write" if kind == "write" else "--authorize-read"
    return subprocess.Popen(
        [sys.executable, "-B", str(_ROOT / "scripts/d6_gmail_setup.py"), action],
        cwd=_ROOT,
        env=env,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def _registered_grant(store: Path, owner_id: str, *, write: bool) -> bool:
    """Read metadata/ACL only; registration means connected, never synced or analysed."""
    if not store.is_file():
        return False
    conn: sqlite3.Connection | None = None
    try:
        verify_owner_only(store.parent)
        verify_owner_only(store)
        conn = sqlite3.connect(
            store.resolve().as_uri() + "?mode=ro", uri=True, factory=ManagedConnection
        )
        conn.row_factory = sqlite3.Row
        configure_clock_collation(conn)
        access = ConnectorAccess(conn, "api")
        finder = find_registered_write_grant if write else find_registered_read_grant
        grant = finder(access, owner_id)
        return grant is not None and token_exists(store, grant)
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return False
    finally:
        if conn is not None:
            conn.close()


def registered_read_grant(store: Path, owner_id: str) -> bool:
    return _registered_grant(store, owner_id, write=False)


def registered_write_grant(store: Path, owner_id: str) -> bool:
    return _registered_grant(store, owner_id, write=True)


@dataclass
class _Job:
    owner_id: str
    request_id: str
    store: Path
    process: SetupProcess | None = None
    status: Literal["awaiting_consent", "succeeded", "failed"] = "awaiting_consent"
    reason: str | None = None


class SetupManager:
    """One active local consent process; explicit requests only, never resume on startup."""

    def __init__(
        self,
        launcher: Callable[[str, Path], SetupProcess] | None = None,
        verifier: Callable[[Path, str], bool] | None = None,
        *,
        kind: str = "read",
    ) -> None:
        self._kind = "write" if kind == "write" else "read"
        self._launcher = launcher or (lambda owner_id, store: _launch(owner_id, store, self._kind))
        self._verifier = verifier or (
            registered_write_grant if self._kind == "write" else registered_read_grant
        )
        self._jobs: dict[tuple[str, str], _Job] = {}
        self._lock = Lock()

    def _state(self, job: _Job, *, existing: bool = False) -> SetupState:
        if job.process is not None:
            code = job.process.poll()
            if code is not None:
                job.process = None
                verified = code == 0 and self._verifier(job.store, job.owner_id)
                job.status = "succeeded" if verified else "failed"
                job.reason = None if verified else "readonly_setup_not_completed"
        connected = job.status == "succeeded" and self._verifier(job.store, job.owner_id)
        if job.status == "succeeded" and not connected:
            job.status, job.reason = "failed", "readonly_registration_unavailable"
        return SetupState(
            request_id=job.request_id,
            status=job.status,
            connected=connected,
            existing=existing,
            status_url=f"/api/gmail/setup/{self._kind}/{job.request_id}",
            reason=job.reason,
        )

    def start(self, owner_id: str, request_id: str, store: Path) -> SetupState:
        with self._lock:
            key = (owner_id, request_id)
            if key in self._jobs:
                return self._state(self._jobs[key], existing=True)
            for job in self._jobs.values():
                if self._state(job).status == "awaiting_consent":
                    raise HTTPException(409, "readonly_setup_already_running")
            job = _Job(owner_id, request_id, store.resolve())
            self._jobs[key] = job
            if self._verifier(job.store, owner_id):
                job.status = "succeeded"
            else:
                try:
                    job.process = self._launcher(owner_id, job.store)
                except OSError:
                    job.status, job.reason = "failed", "readonly_setup_launch_failed"
            return self._state(job)

    def state(self, owner_id: str, request_id: str) -> SetupState:
        with self._lock:
            job = self._jobs.get((owner_id, request_id))
            if job is not None:
                return self._state(job)
            if any(key[1] == request_id for key in self._jobs):
                raise HTTPException(404, "setup_request_not_found")
            return SetupState(
                request_id=request_id,
                status="unknown",
                connected=False,
                status_url=f"/api/gmail/setup/{self._kind}/{request_id}",
                reason="setup_status_unavailable",
            )


def _manager(request: Request, kind: str = "read") -> SetupManager:
    with _INIT_LOCK:
        attribute = "gmail_write_setup" if kind == "write" else "gmail_read_setup"
        manager = getattr(request.app.state, attribute, None)
        if not isinstance(manager, SetupManager):
            manager = SetupManager(kind=kind)
            setattr(request.app.state, attribute, manager)
        return manager


def _local_control(request: Request) -> None:
    client_host = request.client.host if request.client is not None else None
    if not is_loopback_host(client_host) or request.url.hostname not in _LOCAL_HOSTS:
        raise HTTPException(403, "local_setup_only")
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        raise HTTPException(403, "setup_origin_refused")
    origin = request.headers.get("Origin")
    if origin is not None:
        try:
            parsed = urlsplit(origin)
            _ = parsed.port
        except ValueError as exc:
            raise HTTPException(403, "setup_origin_refused") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in _LOCAL_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise HTTPException(403, "setup_origin_refused")


@router.get("/read", response_model=ConnectionState)
def connection_state(owner: Owner) -> ConnectionState:
    if settings.app_profile != "private":
        return ConnectionState(
            connected=False, status="not_connected", reason="private_profile_required"
        )
    connected = registered_read_grant(current_config().store_path, owner.owner_id)
    return ConnectionState(
        connected=connected,
        status="connected" if connected else "not_connected",
        reason=None if connected else "readonly_grant_not_configured",
    )


@router.post("/read", status_code=202, response_model=SetupState)
def start_read_setup(body: SetupRequest, request: Request, owner: Owner) -> SetupState:
    if settings.app_profile != "private":
        raise HTTPException(403, "private_profile_required")
    _local_control(request)
    return _manager(request).start(owner.owner_id, body.request_id, current_config().store_path)


@router.get("/read/{request_id}", response_model=SetupState)
def read_setup_status(request_id: str, request: Request, owner: Owner) -> SetupState:
    if settings.app_profile != "private":
        raise HTTPException(403, "private_profile_required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}", request_id) or ".." in request_id:
        raise HTTPException(404, "setup_request_not_found")
    return _manager(request).state(owner.owner_id, request_id)


@router.get("/write", response_model=ConnectionState)
def write_connection_state(owner: Owner) -> ConnectionState:
    if settings.app_profile != "private":
        return ConnectionState(
            connected=False, status="not_connected", reason="private_profile_required"
        )
    connected = registered_write_grant(current_config().store_path, owner.owner_id)
    return ConnectionState(
        connected=connected,
        status="connected" if connected else "not_connected",
        reason=None if connected else "write_grant_not_configured",
    )


@router.post("/write", status_code=202, response_model=SetupState)
def start_write_setup(body: SetupRequest, request: Request, owner: Owner) -> SetupState:
    if settings.app_profile != "private":
        raise HTTPException(403, "private_profile_required")
    _local_control(request)
    return _manager(request, "write").start(
        owner.owner_id, body.request_id, current_config().store_path
    )


@router.get("/write/{request_id}", response_model=SetupState)
def write_setup_status(request_id: str, request: Request, owner: Owner) -> SetupState:
    if settings.app_profile != "private":
        raise HTTPException(403, "private_profile_required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}", request_id) or ".." in request_id:
        raise HTTPException(404, "setup_request_not_found")
    return _manager(request, "write").state(owner.owner_id, request_id)
