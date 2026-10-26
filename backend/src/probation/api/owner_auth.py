"""Shared owner authentication for the private API surface.

Two credentials are accepted, never mixed in one request:

* ``Authorization: Bearer <owner key>`` — used by CLI callers and tests, verified on every call.
* the HttpOnly owner-session cookie — issued once by ``POST /api/session`` after the key was
  verified. Unsafe cookie-authenticated methods must carry ``X-Probation-CSRF: 1``.

A request that presents an ``Authorization`` header is authenticated by it alone: an invalid
bearer never falls back to a cookie, so the source of authority is always unambiguous.
"""

import os

from fastapi import HTTPException, Request

from probation.api.authority import OwnerContext
from probation.api.gmail_auth import (
    OwnerApiCredential,
    OwnerAuthError,
    is_loopback_host,
    resolve_owner_context,
    verify_owner_request,
)
from probation.api.owner_session import SESSION_COOKIE, OwnerSessionManager
from probation.api.routes.session import CSRF_HEADER, CSRF_VALUE, SAFE_METHODS
from probation.config import settings


def _synthetic_owner_id(request: Request, owner_credential: OwnerApiCredential) -> str:
    """Trusted server profile: one synthetic workspace, still loopback-only and CSRF-marked.

    No credential is accepted in this mode, and the profile cannot be selected by a client.
    Gmail setup routes additionally refuse to run outside the private profile.
    """
    client_host = request.client.host if request.client is not None else None
    if not is_loopback_host(client_host):
        raise OwnerAuthError()
    if (
        request.method.upper() not in SAFE_METHODS
        and request.headers.get(CSRF_HEADER) != CSRF_VALUE
    ):
        raise HTTPException(status_code=403, detail="csrf_header_required")
    return owner_credential.owner_id


def _owner_id_for_request(request: Request, owner_credential: OwnerApiCredential) -> str:
    """Resolve exactly one credential source to a verified owner id."""
    authorization = request.headers.get("Authorization")
    client_host = request.client.host if request.client is not None else None
    if authorization is not None:
        credential = verify_owner_request(
            authorization=authorization,
            client_host=client_host,
            credential=owner_credential,
        )
        return credential.owner_id

    if not is_loopback_host(client_host):
        raise OwnerAuthError()
    token = request.cookies.get(SESSION_COOKIE)
    manager = getattr(request.app.state, "owner_sessions", None)
    if not token or not isinstance(manager, OwnerSessionManager):
        raise OwnerAuthError()
    record = manager.resolve(token)
    if record is None:
        raise OwnerAuthError()
    if (
        request.method.upper() not in SAFE_METHODS
        and request.headers.get(CSRF_HEADER) != CSRF_VALUE
    ):
        raise HTTPException(status_code=403, detail="csrf_header_required")
    request.state.owner_session_token = token
    return record.owner_id


def owner_for_request(request: Request) -> OwnerContext:
    """Authenticate the local owner and load grants from verified connector registrations."""
    # Deferred import avoids a route/authority import cycle.
    from probation.api.routes.gmail_connector import _api_access, current_config

    config = current_config()
    try:
        if settings.app_profile == "synthetic":
            owner_id = _synthetic_owner_id(request, config.owner_credential)
        else:
            owner_id = _owner_id_for_request(request, config.owner_credential)
    except OwnerAuthError as exc:
        raise HTTPException(status_code=401, detail=exc.safe_code) from exc

    forward = tuple(
        dict.fromkeys(
            item.strip().lower()
            for item in os.environ.get("PROBATION_GMAIL_FORWARD_ALLOWLIST", "").split(",")
            if item.strip()
        )
    )

    # Local dashboard authentication is independent of Gmail onboarding. With no registered
    # connector store there are no source grants, so source-scoped routes return empty results.
    if not config.store_path.is_file():
        return OwnerContext(owner_id=owner_id, grants=(), forward_recipients=forward)

    access = _api_access(config.store_path)
    try:
        context = resolve_owner_context(owner_id, access)
        return OwnerContext(
            owner_id=context.owner_id,
            grants=context.grants,
            forward_recipients=forward,
        )
    finally:
        access.conn.close()
