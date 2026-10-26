"""Shared owner authentication for the private API surface."""

from fastapi import HTTPException, Request

from probation.api.authority import OwnerContext
from probation.api.gmail_auth import (
    OwnerAuthError,
    resolve_owner_context,
    verify_owner_request,
)


def owner_for_request(request: Request) -> OwnerContext:
    """Authenticate the local owner and load grants from verified connector registrations."""
    # Deferred import avoids a route/authority import cycle.
    from probation.api.routes.gmail_connector import _api_access, current_config

    config = current_config()
    try:
        credential = verify_owner_request(
            authorization=request.headers.get("Authorization"),
            client_host=request.client.host if request.client is not None else None,
            credential=config.owner_credential,
        )
    except OwnerAuthError as exc:
        raise HTTPException(status_code=401, detail=exc.safe_code) from exc

    # Local dashboard authentication is independent of Gmail onboarding. With no registered
    # connector store there are no source grants, so source-scoped routes return empty results.
    if not config.store_path.is_file():
        return OwnerContext(owner_id=credential.owner_id, grants=())

    access = _api_access(config.store_path)
    try:
        return resolve_owner_context(credential.owner_id, access)
    finally:
        access.conn.close()
