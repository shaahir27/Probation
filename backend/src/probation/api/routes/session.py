"""Owner session exchange for the loopback dashboard.

The owner key is verified once and exchanged for an opaque, server-side session id. Only an
HttpOnly ``SameSite=Strict`` cookie carries that id; the key never enters browser storage and is
never returned by this API. Sessions live in process memory, expire after a fixed idle period,
and are destroyed on sign-out. Unsafe cookie-authenticated requests must also carry the
``X-Probation-CSRF: 1`` header, which a cross-site form cannot set and a cross-site fetch cannot
send without a CORS preflight that this app never grants.

Authority: docs/CONTRACT.md section 9; docs/wp9/D6_API_CONTRACT.md "Profiles and authentication".
"""

from typing import Any, Final

from fastapi import APIRouter, HTTPException, Request, Response

from probation.api.gmail_auth import (
    OwnerAuthError,
    is_loopback_host,
    verify_owner_request,
)
from probation.api.owner_session import (
    SESSION_COOKIE,
    SESSION_COOKIE_PATH,
    SESSION_IDLE_SECONDS,
    OwnerSessionManager,
    OwnerSessionRecord,
)

router = APIRouter(prefix="/api/session", tags=["owner-session"])

CSRF_HEADER: Final = "X-Probation-CSRF"
CSRF_VALUE: Final = "1"
SAFE_METHODS: Final[frozenset[str]] = frozenset({"GET", "HEAD", "OPTIONS"})

SESSION_REQUIRED: Final = "owner_session_required"
SESSION_UNAVAILABLE: Final = "owner_session_unavailable"
# A loopback request with no session is a state, not an error; only a non-loopback client is
# refused outright by `read_session`.


def _manager(request: Request) -> OwnerSessionManager:
    manager = getattr(request.app.state, "owner_sessions", None)
    if not isinstance(manager, OwnerSessionManager):
        raise HTTPException(status_code=503, detail=SESSION_UNAVAILABLE)
    return manager


def _client_is_loopback(request: Request) -> bool:
    return is_loopback_host(request.client.host if request.client is not None else None)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_IDLE_SECONDS,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        samesite="strict",
        secure=False,
    )


def _session_body(record: OwnerSessionRecord, remaining: int) -> dict[str, Any]:
    return {
        "version": "v1",
        "authenticated": True,
        "owner_id": record.owner_id,
        "expires_in": remaining,
    }


def _signed_out_body() -> dict[str, Any]:
    """A signed-out probe is a normal state, not a failed request a browser would log."""
    return {"version": "v1", "authenticated": False}


def require_cookie_csrf(request: Request) -> None:
    """Reject unsafe cookie-authenticated requests without the same-origin marker header."""
    if request.method.upper() in SAFE_METHODS:
        return
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(status_code=403, detail="csrf_header_required")


@router.post("", status_code=200)
def create_session(request: Request, response: Response) -> dict[str, Any]:
    """Verify the owner key once and exchange it for a short-lived HttpOnly session cookie."""
    from probation.api.routes.gmail_connector import current_config

    config = current_config()
    try:
        credential = verify_owner_request(
            authorization=request.headers.get("Authorization"),
            client_host=request.client.host if request.client is not None else None,
            credential=config.owner_credential,
        )
    except OwnerAuthError as exc:
        raise HTTPException(status_code=401, detail=exc.safe_code) from exc

    manager = _manager(request)
    token, record = manager.create(credential.owner_id)
    response.headers["Cache-Control"] = "no-store"
    _set_session_cookie(response, token)
    return _session_body(record, manager.remaining_seconds(record))


@router.get("")
def read_session(request: Request, response: Response) -> dict[str, Any]:
    """Report the current session, renewing its idle window and cookie lifetime."""
    if not _client_is_loopback(request):
        raise HTTPException(status_code=401, detail=SESSION_REQUIRED)
    manager = _manager(request)
    token = request.cookies.get(SESSION_COOKIE)
    record = manager.resolve(token)
    response.headers["Cache-Control"] = "no-store"
    if record is None or token is None:
        if token is not None:
            response.delete_cookie(
                key=SESSION_COOKIE,
                path=SESSION_COOKIE_PATH,
                httponly=True,
                samesite="strict",
                secure=False,
            )
        return _signed_out_body()
    request.state.owner_session_token = token
    _set_session_cookie(response, token)
    return _session_body(record, manager.remaining_seconds(record))


@router.delete("", status_code=204)
def delete_session(request: Request) -> Response:
    """Destroy the server-side session and expire the cookie. Safe to repeat."""
    if not _client_is_loopback(request):
        raise HTTPException(status_code=401, detail=SESSION_REQUIRED)
    require_cookie_csrf(request)
    manager = _manager(request)
    token = request.cookies.get(SESSION_COOKIE)
    manager.delete(token)
    response = Response(status_code=204)
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(
        key=SESSION_COOKIE,
        path=SESSION_COOKIE_PATH,
        httponly=True,
        samesite="strict",
        secure=False,
    )
    return response


__all__ = [
    "CSRF_HEADER",
    "CSRF_VALUE",
    "SAFE_METHODS",
    "require_cookie_csrf",
    "router",
]
