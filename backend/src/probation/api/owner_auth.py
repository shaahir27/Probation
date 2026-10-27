"""Shared owner authentication for the private API surface.

Two credentials are accepted, never mixed in one request:

* ``Authorization: Bearer <owner key>`` — used by CLI callers and tests, verified on every call.
* ``Authorization: Bearer <account JWT>`` — issued by the local email/password account routes.
* the HttpOnly owner-session cookie — issued once by ``POST /api/session`` or account login.
  Unsafe cookie-authenticated methods must carry ``X-Probation-CSRF: 1``.

A request that presents an ``Authorization`` header is authenticated by it alone: an invalid
bearer never falls back to a cookie, so the source of authority is always unambiguous.
"""

import os

from fastapi import HTTPException, Request

from probation.api.accounts import AccountError, verify_token
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
        try:
            credential = verify_owner_request(
                authorization=authorization,
                client_host=client_host,
                credential=owner_credential,
            )
            return credential.owner_id
        except OwnerAuthError:
            if not authorization.startswith("Bearer ") or not is_loopback_host(client_host):
                raise
            token = authorization.removeprefix("Bearer ").strip()
            if token.count(".") != 2:
                raise
            try:
                return verify_token(token).owner_id
            except AccountError as exc:
                raise OwnerAuthError() from exc

    if not is_loopback_host(client_host):
        raise OwnerAuthError()
    session_token = request.cookies.get(SESSION_COOKIE)
    manager = getattr(request.app.state, "owner_sessions", None)
    if not session_token or not isinstance(manager, OwnerSessionManager):
        raise OwnerAuthError()
    record = manager.resolve(session_token)
    if record is None:
        raise OwnerAuthError()
    if (
        request.method.upper() not in SAFE_METHODS
        and request.headers.get(CSRF_HEADER) != CSRF_VALUE
    ):
        raise HTTPException(status_code=403, detail="csrf_header_required")
    request.state.owner_session_token = session_token
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
