"""Email/password account authentication for the local workspace.

Accounts are stored in a separate owner-only SQLite file. Passwords are scrypt hashes and
successful sign-in returns a short-lived HS256 JWT. The browser also receives the existing
HttpOnly owner session cookie, so a refresh does not require the password again. The owner API
key remains supported for local CLI callers and is never exposed here.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from probation.api.accounts import (
    ACCOUNT_TTL_SECONDS,
    Account,
    AccountError,
    authenticate,
    create_account,
    issue_token,
)
from probation.api.gmail_auth import is_loopback_host
from probation.api.owner_session import OwnerSessionManager
from probation.api.routes.session import _set_session_cookie
from probation.config import settings

router = APIRouter(prefix="/api/auth", tags=["account-auth"])


class AccountBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


def _require_loopback(request: Request) -> None:
    if not is_loopback_host(request.client.host if request.client is not None else None):
        raise HTTPException(status_code=401, detail="owner_credential_required")


def _manager(request: Request) -> OwnerSessionManager:
    manager = getattr(request.app.state, "owner_sessions", None)
    if not isinstance(manager, OwnerSessionManager):
        raise HTTPException(status_code=503, detail="owner_session_unavailable")
    return manager


def _account_error(exc: AccountError) -> HTTPException:
    code = exc.safe_code
    if code == "account_exists":
        return HTTPException(status_code=409, detail=code)
    if code == "invalid_credentials":
        return HTTPException(status_code=401, detail=code)
    if code in {"invalid_email", "invalid_password", "invalid_owner"}:
        return HTTPException(status_code=400, detail="invalid_account_input")
    return HTTPException(status_code=503, detail="accounts_unavailable")


def _session_response(
    request: Request, response: Response, account: Account, *, status_code: int
) -> dict[str, Any]:
    token, _record = _manager(request).create(account.owner_id, email=account.email)
    _set_session_cookie(response, token)
    response.headers["Cache-Control"] = "no-store"
    response.status_code = status_code
    return {
        "version": "v1",
        "access_token": issue_token(account),
        "token_type": "bearer",
        "expires_in": ACCOUNT_TTL_SECONDS,
        "user": {"email": account.email, "owner_id": account.owner_id},
    }


@router.post("/register", status_code=201)
def register(body: AccountBody, request: Request, response: Response) -> dict[str, Any]:
    """Create a local account and sign it in. It has no source grants until it connects one."""
    _require_loopback(request)
    if settings.app_profile != "private":
        raise HTTPException(status_code=403, detail="private_profile_required")
    try:
        account = create_account(
            settings.probation_accounts_db,
            email=body.email,
            password=body.password,
            owner_id=f"user-{uuid.uuid4().hex}",
        )
    except AccountError as exc:
        raise _account_error(exc) from exc
    return _session_response(request, response, account, status_code=201)


@router.post("/login", status_code=200)
def login(body: AccountBody, request: Request, response: Response) -> dict[str, Any]:
    """Verify an account password and issue a JWT plus the HttpOnly owner session."""
    _require_loopback(request)
    if settings.app_profile != "private":
        raise HTTPException(status_code=403, detail="private_profile_required")
    try:
        account = authenticate(
            settings.probation_accounts_db, email=body.email, password=body.password
        )
    except AccountError as exc:
        raise _account_error(exc) from exc
    if account is None:
        raise HTTPException(status_code=401, detail="invalid_credentials")
    return _session_response(request, response, account, status_code=200)


__all__ = ["router"]
