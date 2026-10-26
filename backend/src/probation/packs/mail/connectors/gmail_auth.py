"""Installed-app OAuth for Gmail: authorization-code flow with PKCE and a loopback redirect.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md section 5. Fully offline: every endpoint call
goes through an injected transport and the fake lives in tests only. The OAuth token
endpoint is NOT the Gmail REST ``HttpTransport``; ``TokenTransport`` below is a separate,
form-posting seam so no token or code can ever ride in a URL. Bearer material stays in
process memory; persisted state (see ``connectors.credentials``) is scopes and expiry only.
"""

import base64
import hashlib
import logging
import re
import secrets
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar, Final, Protocol
from urllib.parse import parse_qs, urlencode, urlsplit

from probation.connectors.credentials import SecretMaterial, TokenBundle
from probation.connectors.types import ConnectorError, CredentialRole, ScopeMismatch
from probation.core.clock import Clock, get_clock

AUTHORIZE_ENDPOINT: Final = "https://accounts.google.com/o/oauth2/auth"
TOKEN_ENDPOINT: Final = "https://oauth2.googleapis.com/token"
GMAIL_READONLY_SCOPE: Final = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND_SCOPE: Final = "https://www.googleapis.com/auth/gmail.send"
GMAIL_MODIFY_SCOPE: Final = "https://www.googleapis.com/auth/gmail.modify"
GMAIL_FULL_SCOPE: Final = "https://mail.google.com/"
REQUESTABLE_SCOPES: Final = (GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE, GMAIL_MODIFY_SCOPE)
_STATE_TTL_SECONDS: Final = 120

_SEND_CAPS: Final = frozenset({"send", "forward"})
_MODIFY_CAPS: Final = frozenset(
    {"archive", "trash", "reconciliation", "undo_history_proof", "conditional_write"}
)
_KNOWN_CAPS: Final = frozenset({"read"}) | _SEND_CAPS | _MODIFY_CAPS

_SECRET_PARAM_RE = re.compile(r"(?:code|access_token|refresh_token|client_secret)$", re.IGNORECASE)
_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{6,128}$")
_LOOPBACK_RE = re.compile(r"^http://127\.0\.0\.1(?::[0-9]{1,5})?/?$")

BytesSupplier = Callable[[int], bytes]
_CALLBACK_LOG = logging.getLogger("probation.connectors.gmail_auth.callback")


class AuthorizationFlowError(ConnectorError):
    """The authorization flow must halt; each variant is a distinct safe code."""


def _offline_random(count: int) -> bytes:
    return secrets.token_bytes(count)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


@dataclass(frozen=True)
class PkcePair:
    challenge: str
    verifier: SecretMaterial


def new_pkce(bytes_supplier: BytesSupplier = _offline_random) -> PkcePair:
    """Fresh 256-bit verifier per attempt; the S256 challenge is the only published half."""
    verifier = _b64url(bytes_supplier(32))
    if not _B64URL_RE.match(verifier):
        raise AuthorizationFlowError("pkce_verifier_invalid")
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return PkcePair(challenge=challenge, verifier=SecretMaterial(verifier, "verifier"))


@dataclass(frozen=True, repr=False)
class IssuedState:
    """One single-use authorization attempt bound to owner, role, account, redirect, expiry."""

    token: str
    owner_id: str
    role: CredentialRole
    account_id: str
    connection_id: str
    redirect_uri: str
    required_scopes: tuple[str, ...]
    challenge: str
    verifier: SecretMaterial
    issued_at: str
    expires_at: str

    def __repr__(self) -> str:
        return f"IssuedState(role={self.role!r}, token='<redacted>')"


class StateVault:
    """Issues and consumes OAuth state exactly once, with expiry from the injected clock."""

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        ttl_seconds: int = _STATE_TTL_SECONDS,
        bytes_supplier: BytesSupplier = _offline_random,
    ) -> None:
        self._clock = clock or get_clock()
        self._ttl = ttl_seconds
        self._bytes = bytes_supplier
        self._pending: dict[str, IssuedState] = {}
        self._consumed: set[str] = set()

    def issue(
        self,
        *,
        owner_id: str,
        role: CredentialRole,
        account_id: str,
        connection_id: str,
        redirect_uri: str,
        required_scopes: Sequence[str],
        pkce: PkcePair,
    ) -> IssuedState:
        if self._pending:
            raise AuthorizationFlowError("authorization_already_in_flight")
        if not redirect_uri.startswith("http://127.0.0.1"):
            raise AuthorizationFlowError("redirect_must_be_loopback")
        issued_at = self._clock.now(UTC)
        state = IssuedState(
            token=_b64url(self._bytes(24)),
            owner_id=owner_id,
            role=role,
            account_id=account_id,
            connection_id=connection_id,
            redirect_uri=redirect_uri,
            required_scopes=tuple(required_scopes),
            challenge=pkce.challenge,
            verifier=pkce.verifier,
            issued_at=issued_at.isoformat(),
            expires_at=(issued_at + timedelta(seconds=self._ttl)).isoformat(),
        )
        self._pending[state.token] = state
        return state

    def consume(
        self,
        token: str,
        *,
        owner_id: str,
        role: CredentialRole,
        account_id: str,
        redirect_uri: str,
    ) -> IssuedState:
        state = self._pending.get(token)
        if state is None:
            raise AuthorizationFlowError(
                "state_replayed" if token in self._consumed else "state_unknown"
            )
        if self._clock.now(UTC) >= datetime.fromisoformat(state.expires_at):
            self._pending.pop(token, None)
            raise AuthorizationFlowError("state_expired")
        if (
            state.owner_id != owner_id
            or state.role != role
            or state.account_id != account_id
            or state.redirect_uri != redirect_uri
        ):
            raise AuthorizationFlowError("state_binding_mismatch")
        self._consumed.add(token)
        self._pending.pop(token)
        return state


def build_authorization_url(
    *, client_id: str, redirect_uri: str, state_token: str, pkce: PkcePair, scopes: Sequence[str]
) -> str:
    """URL assembled only from code-built constants; never from user-supplied text."""
    if not _CLIENT_ID_RE.match(client_id):
        raise AuthorizationFlowError("client_id_invalid")
    if not _LOOPBACK_RE.match(redirect_uri):
        raise AuthorizationFlowError("redirect_must_be_loopback")
    if not _B64URL_RE.match(state_token) or not _B64URL_RE.match(pkce.challenge):
        raise AuthorizationFlowError("state_or_challenge_invalid")
    for scope in scopes:
        if scope not in REQUESTABLE_SCOPES:
            raise AuthorizationFlowError("unapproved_scope_request")
    url = (
        AUTHORIZE_ENDPOINT
        + "?"
        + urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(scopes),
                "state": state_token,
                "code_challenge": pkce.challenge,
                "code_challenge_method": "S256",
                "access_type": "offline",
                "prompt": "consent",
            }
        )
    )
    if pkce.verifier.reveal() in url:
        raise AuthorizationFlowError("verifier_leaked_to_url")
    if any(_SECRET_PARAM_RE.match(key) for key in parse_qs(urlsplit(url).query)):
        raise AuthorizationFlowError("secret_bearing_param_in_url")
    return url


def parse_callback_query(query: str, *, expected_state: str) -> SecretMaterial:
    """Extract the authorization code from a loopback callback query. Logs nothing, ever."""
    params = parse_qs(query, keep_blank_values=False)
    error = params.get("error", [""])[0]
    if error in ("access_denied", "consent_required", "login_required"):
        raise AuthorizationFlowError("consent_cancelled")
    if error:
        raise AuthorizationFlowError("callback_provider_error")
    states = params.get("state", [])
    codes = params.get("code", [])
    if not states or not codes:
        raise AuthorizationFlowError("callback_missing_params")
    if states[0] != expected_state:
        raise AuthorizationFlowError("callback_state_mismatch")
    code = codes[0]
    if (
        not 20 <= len(code) <= 4096
        or not code.isprintable()
        or any(char.isspace() for char in code)
    ):
        raise AuthorizationFlowError("callback_code_invalid")
    return SecretMaterial(code, "code")


@dataclass(frozen=True, repr=False)
class TokenHttpResponse:
    status: int
    json_body: Mapping[str, object]

    def __repr__(self) -> str:
        return f"TokenHttpResponse(status={self.status}, keys={sorted(self.json_body)})"


class TokenTransport(Protocol):
    """POST of an application/x-www-form-urlencoded body to the OAuth token endpoint."""

    def post_form(self, url: str, form: Mapping[str, str]) -> TokenHttpResponse: ...


class UserInfoGateway(Protocol):
    """Injected account verification; returns the account email for a fresh access token."""

    def account_email(self, access: SecretMaterial) -> str: ...


def plan_scopes(role: CredentialRole, capabilities: frozenset[str]) -> tuple[str, ...]:
    """Minimal scope tuple for an operation set. Broader bundles are refused by the gate."""
    if not capabilities:
        raise AuthorizationFlowError("empty_capability_set")
    if capabilities - _KNOWN_CAPS:
        raise AuthorizationFlowError("unknown_capability")
    if role == "read":
        if capabilities != frozenset({"read"}):
            raise AuthorizationFlowError("read_role_exceeds_scope")
        return (GMAIL_READONLY_SCOPE,)
    scopes: list[str] = []
    if capabilities & _SEND_CAPS:
        scopes.append(GMAIL_SEND_SCOPE)
    if capabilities & _MODIFY_CAPS:
        scopes.append(GMAIL_MODIFY_SCOPE)
    if not scopes:
        raise AuthorizationFlowError("write_role_needs_operations")
    return tuple(scopes)


def validate_scope_request(
    role: CredentialRole, capabilities: frozenset[str], requested: Sequence[str]
) -> tuple[str, ...]:
    """Refuse any requested bundle that is not exactly what the operations need."""
    planned = plan_scopes(role, capabilities)
    requested_set = set(requested)
    if GMAIL_FULL_SCOPE in requested_set:
        raise AuthorizationFlowError("full_mail_scope_forbidden")
    if requested_set - set(planned):
        raise AuthorizationFlowError("over_broad_scope_request")
    if set(planned) - requested_set:
        raise AuthorizationFlowError("incomplete_scope_request")
    return planned


class OAuthTokenExchange:
    """Code exchange and refresh. Account and granted scopes are verified before any bundle."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        vault: StateVault,
        transport: TokenTransport,
        userinfo: UserInfoGateway,
        clock: Clock | None = None,
    ) -> None:
        if not _CLIENT_ID_RE.match(client_id):
            raise AuthorizationFlowError("client_id_invalid")
        if (
            not client_secret
            or len(client_secret) > 256
            or any(ord(char) < 32 for char in client_secret)
        ):
            raise AuthorizationFlowError("client_secret_invalid")
        self._client_id = client_id
        self._client_secret = client_secret
        self._vault = vault
        self._transport = transport
        self._userinfo = userinfo
        self._clock = clock or get_clock()

    def __repr__(self) -> str:
        cid = getattr(self, "_client_id", None)
        trans = getattr(self, "_transport", None)
        trans_name = type(trans).__name__ if trans is not None else "None"
        return f"OAuthTokenExchange(client_id={cid!r}, transport={trans_name})"

    def complete(
        self,
        *,
        state_token: str,
        code: SecretMaterial,
        owner_id: str,
        role: CredentialRole,
        account_id: str,
        redirect_uri: str,
    ) -> TokenBundle:
        issued = self._vault.consume(
            state_token,
            owner_id=owner_id,
            role=role,
            account_id=account_id,
            redirect_uri=redirect_uri,
        )
        bundle = self._post_and_verify(
            {
                "code": code.reveal(),
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "redirect_uri": issued.redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": issued.verifier.reveal(),
            },
            issued.required_scopes,
        )
        if bundle.account_id != issued.account_id:
            # Refuse before installing: never fall back to another account.
            raise AuthorizationFlowError("account_mismatch")
        return bundle

    def refresh(self, credential_ref: str, refresh_material: SecretMaterial) -> TokenBundle:
        """TokenRefresher seam for ``RoleCredentialProvider``; serialized by the provider."""
        del credential_ref  # opaque correlation id; the endpoint only needs the material.
        return self._post_and_verify(
            {
                "refresh_token": refresh_material.reveal(),
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
            },
            (),
        )

    def _post_and_verify(
        self, form: Mapping[str, str], required_scopes: tuple[str, ...]
    ) -> TokenBundle:
        if urlsplit(TOKEN_ENDPOINT).netloc != "oauth2.googleapis.com":
            raise AuthorizationFlowError("token_endpoint_constant_drift")
        response = self._transport.post_form(TOKEN_ENDPOINT, form)
        if response.status != 200:
            raise AuthorizationFlowError("token_exchange_rejected")
        access = self._text_field(response.json_body, "access_token")
        expires_in = self._int_field(response.json_body, "expires_in")
        scope_field = response.json_body.get("scope")
        if not isinstance(scope_field, str):
            # Fail closed: an unproven granted-scope set cannot install a grant.
            raise ScopeMismatch("granted_scope_unproven")
        granted = tuple(scope_field.split())
        if GMAIL_FULL_SCOPE in granted or not set(required_scopes) <= set(granted):
            raise ScopeMismatch("granted_scope_narrowed")
        access_material = SecretMaterial(access, "access")
        email = self._userinfo.account_email(access_material)
        raw_refresh = response.json_body.get("refresh_token")
        refresh = SecretMaterial(str(raw_refresh), "refresh") if raw_refresh else None
        return TokenBundle(
            account_id=email.strip().lower(),
            granted_scopes=granted,
            expires_in_seconds=expires_in,
            access=access_material,
            refresh=refresh,
        )

    def _text_field(self, body: Mapping[str, object], name: str) -> str:
        value = body.get(name)
        if not isinstance(value, str) or not value or len(value) > 4096:
            raise AuthorizationFlowError("token_payload_invalid")
        return value

    def _int_field(self, body: Mapping[str, object], name: str) -> int:
        value = body.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise AuthorizationFlowError("token_payload_invalid")
        try:
            seconds = int(str(value))
        except ValueError as exc:
            raise AuthorizationFlowError("token_payload_invalid") from exc
        if not 0 < seconds <= 3600:
            raise AuthorizationFlowError("token_payload_invalid")
        return seconds


@dataclass(frozen=True)
class _Outcome:
    code: SecretMaterial | None = None
    error: ConnectorError | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    holder: ClassVar[dict[str, object] | None] = None

    def do_GET(self) -> None:
        holder = type(self).holder
        assert holder is not None
        try:
            code: SecretMaterial | None = parse_callback_query(
                urlsplit(self.path).query, expected_state=str(holder["expected"])
            )
            outcome: _Outcome = _Outcome(code=code)
        except ConnectorError as exc:
            outcome = _Outcome(error=exc)
        if holder["outcome"] is None:
            holder["outcome"] = outcome
        self.send_response(200 if outcome.code is not None else 400)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Authorization received. You may close this window.")
        event = holder.get("done")
        if isinstance(event, threading.Event):
            event.set()

    def log_message(self, fmt: str, *args: object) -> None:
        """Suppress access logging entirely: the request line carries the callback query."""


class LoopbackCallback:
    """Single-shot loopback listener owned by the credential boundary, not the dashboard API."""

    def __init__(self, port: int = 0) -> None:
        if not 0 <= port <= 65535:
            raise AuthorizationFlowError("loopback_port_invalid")
        self._holder: dict[str, object] = {"expected": "", "outcome": None}
        self._done = threading.Event()
        self._holder["done"] = self._done
        handler = type("_BoundCallbackHandler", (_CallbackHandler,), {"holder": self._holder})
        try:
            self._server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        except OSError as exc:
            raise AuthorizationFlowError("loopback_bind_failed") from exc
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/"

    def expect(self, state_token: str) -> None:
        if not _B64URL_RE.match(state_token):
            raise AuthorizationFlowError("state_or_challenge_invalid")
        self._holder["expected"] = state_token

    def wait(self, timeout_seconds: float = 10.0) -> SecretMaterial:
        try:
            if not self._done.wait(timeout_seconds):
                raise AuthorizationFlowError("callback_timeout")
            outcome = self._holder["outcome"]
            assert isinstance(outcome, _Outcome)
            # Only a safe code is ever logged; query values stay in memory.
            _CALLBACK_LOG.info(
                "gmail_oauth_callback",
                extra={"safe_code": outcome.error.safe_code if outcome.error else "ok"},
            )
            if outcome.error is not None:
                raise outcome.error
            assert outcome.code is not None
            return outcome.code
        finally:
            self._server.shutdown()
            self._server.server_close()


@contextmanager
def loopback_callback(state_token: str) -> Iterator[LoopbackCallback]:
    listener = LoopbackCallback()
    listener.expect(state_token)
    try:
        yield listener
    finally:
        listener._server.shutdown()
        listener._server.server_close()
