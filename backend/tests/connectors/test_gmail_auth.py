"""D4-05 OAuth installed-app flow, offline against fakes: PKCE, state, scopes, loopback.

No real network. The loopback listener test talks only to a 127.0.0.1 socket in this
process. The single live-marked test can never execute offline by construction.
"""

import hashlib
import logging
import threading
import urllib.request
from base64 import urlsafe_b64encode
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from probation.connectors.credentials import SecretMaterial
from probation.connectors.types import ScopeMismatch
from probation.core.clock import Clock
from probation.packs.mail.connectors.gmail_auth import (
    AUTHORIZE_ENDPOINT,
    GMAIL_FULL_SCOPE,
    GMAIL_MODIFY_SCOPE,
    GMAIL_READONLY_SCOPE,
    GMAIL_SEND_SCOPE,
    TOKEN_ENDPOINT,
    AuthorizationFlowError,
    IssuedState,
    LoopbackCallback,
    OAuthTokenExchange,
    PkcePair,
    StateVault,
    TokenHttpResponse,
    build_authorization_url,
    new_pkce,
    parse_callback_query,
    plan_scopes,
    validate_scope_request,
)

OWNER = "owner-1"
ACCOUNT = "owner@example.com"
CLIENT_ID = "fake-installed-app.apps.googleusercontent.com"
NOW = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
CODE_CANARY = "CANARY-code-4f8a2c6e1d3b5a7c9e0f2134abcd"
STATE_SEED = "abcdefghijklmnopqrstuvwxyz012345"


def _bytes_supplier(start: int = 0) -> Callable[[int], bytes]:
    counter = {"n": start}

    def supply(count: int) -> bytes:
        counter["n"] += 1
        base = counter["n"]
        return bytes((base * 31 + index * 7) % 251 + 4 for index in range(count))

    return supply


def _clock() -> Clock:
    return Clock.replay(NOW)


def _vault(clock: Clock | None = None) -> StateVault:
    return StateVault(clock=clock or _clock(), bytes_supplier=_bytes_supplier())


def _issue(
    vault: StateVault,
    redirect: str = "http://127.0.0.1:4411/",
    scopes: tuple[str, ...] = (GMAIL_READONLY_SCOPE,),
    pkce: PkcePair | None = None,
) -> IssuedState:
    return vault.issue(
        owner_id=OWNER,
        role="read",
        account_id=ACCOUNT,
        connection_id="conn-1",
        redirect_uri=redirect,
        required_scopes=scopes,
        pkce=pkce or new_pkce(_bytes_supplier(100)),
    )


class FakeTokenTransport:
    def __init__(self, responses: list[TokenHttpResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def post_form(self, url: str, form: dict) -> TokenHttpResponse:  # type: ignore[assignment]
        self.calls.append((url, dict(form)))
        if not self.responses:
            raise AssertionError("fake token transport exhausted")
        return self.responses.pop(0)


class FakeUserInfo:
    def __init__(self, email: str = ACCOUNT) -> None:
        self.email = email
        self.seen: list[str] = []

    def account_email(self, access: SecretMaterial) -> str:
        assert isinstance(access, SecretMaterial) and access.kind == "access"
        self.seen.append(access.reveal())
        return self.email


def _token_payload(
    access: str = "fake-access-material", scopes: str = GMAIL_READONLY_SCOPE, **extra: object
) -> TokenHttpResponse:
    body: dict[str, object] = {
        "access_token": access,
        "expires_in": 3600,
        "scope": scopes,
        "refresh_token": "fake-refresh-material",
    }
    body.update(extra)
    return TokenHttpResponse(status=200, json_body=body)


def _consume(vault: StateVault, state: IssuedState) -> IssuedState:
    return vault.consume(
        state.token,
        owner_id=OWNER,
        role="read",
        account_id=ACCOUNT,
        redirect_uri=state.redirect_uri,
    )


def _exchange(
    responses: list[TokenHttpResponse], email: str = ACCOUNT
) -> tuple[OAuthTokenExchange, StateVault]:
    vault = _vault()
    exchange = OAuthTokenExchange(
        client_id=CLIENT_ID,
        client_secret="fake-secret",
        vault=vault,
        transport=FakeTokenTransport(responses),
        userinfo=FakeUserInfo(email),
    )
    return exchange, vault


def test_pkce_verifier_fresh_per_attempt_and_s256_challenge() -> None:
    first, second = new_pkce(), new_pkce()
    assert first.verifier.reveal() != second.verifier.reveal()
    expected = (
        urlsafe_b64encode(hashlib.sha256(first.verifier.reveal().encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    assert first.challenge == expected
    # RFC 7636 appendix B vector: the S256 maths itself is pinned.
    vector = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert (
        PkcePair(
            challenge=urlsafe_b64encode(hashlib.sha256(vector.encode()).digest())
            .decode()
            .rstrip("="),
            verifier=SecretMaterial(vector, "verifier"),
        ).challenge
        == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )


def test_authorization_url_is_code_built_and_carries_only_challenge_and_state() -> None:
    pkce = new_pkce(_bytes_supplier(5))
    url = build_authorization_url(
        client_id=CLIENT_ID,
        redirect_uri="http://127.0.0.1:4411/",
        state_token=STATE_SEED,
        pkce=pkce,
        scopes=(GMAIL_READONLY_SCOPE,),
    )
    assert url.startswith(AUTHORIZE_ENDPOINT + "?")
    assert pkce.challenge in url
    assert pkce.verifier.reveal() not in url  # verifier never leaves the process via URL
    for forbidden in ("access_token=", "refresh_token=", "client_secret=", "code="):
        assert forbidden not in url
    with pytest.raises(AuthorizationFlowError) as broad:
        build_authorization_url(
            client_id=CLIENT_ID,
            redirect_uri="http://127.0.0.1:4411/",
            state_token=STATE_SEED,
            pkce=pkce,
            scopes=(GMAIL_FULL_SCOPE,),
        )
    assert broad.value.safe_code == "unapproved_scope_request"
    with pytest.raises(AuthorizationFlowError):
        build_authorization_url(
            client_id=CLIENT_ID,
            redirect_uri="https://evil.example/",
            state_token=STATE_SEED,
            pkce=pkce,
            scopes=(GMAIL_READONLY_SCOPE,),
        )


def test_state_binds_owner_role_account_and_redirect() -> None:
    vault = _vault()
    state = _issue(vault)
    for kwargs in (
        {"owner_id": "mallory"},
        {"role": "write"},
        {"account_id": "other@example.com"},
        {"redirect_uri": "http://127.0.0.1:9999/"},
    ):
        fresh = _vault()
        bound = _issue(fresh)
        args = {
            "owner_id": OWNER,
            "role": "read",
            "account_id": ACCOUNT,
            "redirect_uri": bound.redirect_uri,
        }
        args.update(kwargs)  # type: ignore[typeddict-item]
        with pytest.raises(AuthorizationFlowError) as excinfo:
            fresh.consume(bound.token, **args)  # type: ignore[arg-type]
        assert excinfo.value.safe_code == "state_binding_mismatch"
    assert repr(state).count(state.token) == 0  # token redacted in repr


def test_state_is_single_use_and_replay_is_refused() -> None:
    vault = _vault()
    state = _issue(vault)
    _consume(vault, state)
    with pytest.raises(AuthorizationFlowError) as replay:
        _consume(vault, state)
    assert replay.value.safe_code == "state_replayed"
    with pytest.raises(AuthorizationFlowError) as unknown:
        vault.consume(
            "never-issued-state-token-aaaa",
            owner_id=OWNER,
            role="read",
            account_id=ACCOUNT,
            redirect_uri=state.redirect_uri,
        )
    assert unknown.value.safe_code == "state_unknown"


def test_state_expiry_denies_completion() -> None:
    clock = _clock()
    vault = StateVault(clock=clock, ttl_seconds=120, bytes_supplier=_bytes_supplier())
    state = _issue(vault)
    clock.advance_seconds(121)
    with pytest.raises(AuthorizationFlowError) as expired:
        _consume(vault, state)
    assert expired.value.safe_code == "state_expired"


def test_one_in_flight_attempt_only() -> None:
    vault = _vault()
    _issue(vault)
    with pytest.raises(AuthorizationFlowError) as busy:
        _issue(vault)
    assert busy.value.safe_code == "authorization_already_in_flight"


def test_callback_rejects_cancelled_wrong_state_and_missing_params() -> None:
    for query, code in (
        (f"error=access_denied&state={STATE_SEED}", "consent_cancelled"),
        (f"error=invalid_grant&state={STATE_SEED}", "callback_provider_error"),
        (f"state={STATE_SEED}", "callback_missing_params"),
        (f"code={CODE_CANARY}", "callback_missing_params"),
        (f"code={CODE_CANARY}&state=wrong-state-value-0000000000", "callback_state_mismatch"),
        (f"code=short&state={STATE_SEED}", "callback_code_invalid"),
    ):
        with pytest.raises(AuthorizationFlowError) as excinfo:
            parse_callback_query(query, expected_state=STATE_SEED)
        assert excinfo.value.safe_code == code
    code = parse_callback_query(f"code={CODE_CANARY}&state={STATE_SEED}", expected_state=STATE_SEED)
    assert code.kind == "code"


def _complete(
    transport_responses: list[TokenHttpResponse],
    email: str = ACCOUNT,
    required: tuple[str, ...] = (GMAIL_READONLY_SCOPE,),
) -> None:
    exchange, vault = _exchange(transport_responses, email)
    state = _issue(vault, scopes=required)
    code = SecretMaterial(CODE_CANARY, "code")
    exchange.complete(
        state_token=state.token,
        code=code,
        owner_id=OWNER,
        role="read",
        account_id=ACCOUNT,
        redirect_uri=state.redirect_uri,
    )


def test_token_exchange_posts_form_and_never_puts_secrets_in_urls() -> None:
    transport = FakeTokenTransport([_token_payload()])
    vault = _vault()
    exchange = OAuthTokenExchange(
        client_id=CLIENT_ID,
        client_secret="fake-secret",
        vault=vault,
        transport=transport,
        userinfo=FakeUserInfo(),
    )
    state = _issue(vault)
    bundle = exchange.complete(
        state_token=state.token,
        code=SecretMaterial(CODE_CANARY, "code"),
        owner_id=OWNER,
        role="read",
        account_id=ACCOUNT,
        redirect_uri=state.redirect_uri,
    )
    url, form = transport.calls[0]
    assert url == TOKEN_ENDPOINT and "?" not in url
    assert form["code"] == CODE_CANARY  # body only, never a URL parameter
    assert form["code_verifier"] == state.verifier.reveal()
    assert bundle.granted_scopes == (GMAIL_READONLY_SCOPE,)
    assert bundle.account_id == ACCOUNT


def test_wrong_account_completion_is_refused_before_install() -> None:
    with pytest.raises(AuthorizationFlowError) as wrong:
        _complete([_token_payload()], email="intruder@example.com")
    assert wrong.value.safe_code == "account_mismatch"


def test_narrow_granted_scope_is_refused_before_install() -> None:
    with pytest.raises(ScopeMismatch) as narrow:
        _complete(
            [_token_payload(scopes=GMAIL_READONLY_SCOPE)],
            required=(GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE),
        )
    assert narrow.value.safe_code == "granted_scope_narrowed"
    with pytest.raises(ScopeMismatch):
        _complete([_token_payload(scopes=GMAIL_FULL_SCOPE)])


def test_token_endpoint_failures_fail_closed() -> None:
    for response, code in (
        (
            TokenHttpResponse(status=400, json_body={"error": "invalid_grant"}),
            "token_exchange_rejected",
        ),
        (_token_payload(access=""), "token_payload_invalid"),
        (_token_payload(expires_in="abc"), "token_payload_invalid"),
        (
            TokenHttpResponse(status=200, json_body={"access_token": "x", "expires_in": 3600}),
            "granted_scope_unproven",
        ),
    ):
        with pytest.raises(
            AuthorizationFlowError if "token_" in code else ScopeMismatch
        ) as excinfo:
            _complete([response])
        assert excinfo.value.safe_code == code


def test_scope_planning_grants_exactly_what_operations_need() -> None:
    assert plan_scopes("read", frozenset({"read"})) == (GMAIL_READONLY_SCOPE,)
    assert plan_scopes("write", frozenset({"send"})) == (GMAIL_SEND_SCOPE,)
    assert plan_scopes("write", frozenset({"archive"})) == (GMAIL_MODIFY_SCOPE,)
    assert set(plan_scopes("write", frozenset({"send", "trash"}))) == {
        GMAIL_SEND_SCOPE,
        GMAIL_MODIFY_SCOPE,
    }
    for role, caps, code in (
        ("read", frozenset({"send"}), "read_role_exceeds_scope"),
        ("read", frozenset({"read", "archive"}), "read_role_exceeds_scope"),
        ("write", frozenset(), "empty_capability_set"),
        ("write", frozenset({"nonsense"}), "unknown_capability"),
    ):
        with pytest.raises(AuthorizationFlowError) as excinfo:
            plan_scopes(role, caps)  # type: ignore[arg-type]
        assert excinfo.value.safe_code == code


def test_scope_planner_refuses_broader_bundle_than_operations_need() -> None:
    assert validate_scope_request("write", frozenset({"send"}), (GMAIL_SEND_SCOPE,)) == (
        GMAIL_SEND_SCOPE,
    )
    with pytest.raises(AuthorizationFlowError) as over:
        validate_scope_request("write", frozenset({"send"}), (GMAIL_SEND_SCOPE, GMAIL_MODIFY_SCOPE))
    assert over.value.safe_code == "over_broad_scope_request"
    with pytest.raises(AuthorizationFlowError) as full:
        validate_scope_request("write", frozenset({"send", "archive"}), (GMAIL_FULL_SCOPE,))
    assert full.value.safe_code == "full_mail_scope_forbidden"
    with pytest.raises(AuthorizationFlowError) as thin:
        validate_scope_request("write", frozenset({"send", "archive"}), (GMAIL_SEND_SCOPE,))
    assert thin.value.safe_code == "incomplete_scope_request"


def test_refresh_requires_scope_proof_and_returns_bundle() -> None:
    exchange, _ = _exchange([_token_payload(scopes=f"{GMAIL_READONLY_SCOPE} {GMAIL_SEND_SCOPE}")])
    bundle = exchange.refresh("cred-read-1", SecretMaterial("fake-refresh-material", "refresh"))
    assert set(bundle.granted_scopes) == {GMAIL_READONLY_SCOPE, GMAIL_SEND_SCOPE}
    failing, _ = _exchange(
        [TokenHttpResponse(status=200, json_body={"access_token": "x", "expires_in": 3600})]
    )
    with pytest.raises(ScopeMismatch) as unproven:
        failing.refresh("cred-read-1", SecretMaterial("fake-refresh-material", "refresh"))
    assert unproven.value.safe_code == "granted_scope_unproven"


def test_loopback_listener_roundtrip_suppresses_callback_logging(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    listener = LoopbackCallback()
    vault = _vault()
    state = _issue(vault, redirect=listener.redirect_uri)
    listener.expect(state.token)
    url = f"{listener.redirect_uri}?code={CODE_CANARY}&state={state.token}"
    caplog.set_level(logging.DEBUG)

    def fetch() -> None:
        with urllib.request.urlopen(url, timeout=5) as response:
            assert response.status == 200

    thread = threading.Thread(target=fetch)
    thread.start()
    try:
        code = listener.wait(timeout_seconds=10)
    finally:
        thread.join(5)
    assert code.reveal() == CODE_CANARY
    assert CODE_CANARY not in caplog.text
    assert state.token not in caplog.text
    assert CODE_CANARY not in capsys.readouterr().out


def test_loopback_listener_surfaces_typed_denial_and_timeout() -> None:
    listener = LoopbackCallback()
    vault = _vault()
    state = _issue(vault, redirect=listener.redirect_uri)
    listener.expect(state.token)
    denial = f"{listener.redirect_uri}?error=access_denied&state={state.token}"

    def fetch() -> None:
        try:
            urllib.request.urlopen(denial, timeout=5)
        except OSError:
            pass

    thread = threading.Thread(target=fetch)
    thread.start()
    with pytest.raises(AuthorizationFlowError) as excinfo:
        listener.wait(timeout_seconds=10)
    thread.join(5)
    assert excinfo.value.safe_code == "consent_cancelled"
    silent = LoopbackCallback()
    silent.expect(state.token)
    with pytest.raises(AuthorizationFlowError) as timeout:
        silent.wait(timeout_seconds=0.5)
    assert timeout.value.safe_code == "callback_timeout"


def test_non_loopback_redirect_and_bad_client_id_are_refused() -> None:
    vault = StateVault(clock=_clock(), bytes_supplier=_bytes_supplier())
    with pytest.raises(AuthorizationFlowError) as remote:
        _issue(vault, redirect="https://dashboard.example.com/callback")
    assert remote.value.safe_code == "redirect_must_be_loopback"
    with pytest.raises(AuthorizationFlowError):
        OAuthTokenExchange(
            client_id="'; DROP TABLE gmail_connections; --",
            client_secret="fake-secret",
            vault=vault,
            transport=FakeTokenTransport([]),
            userinfo=FakeUserInfo(),
        )
    with pytest.raises(AuthorizationFlowError) as exc_secret:
        OAuthTokenExchange(
            client_id=CLIENT_ID,
            client_secret="",
            vault=vault,
            transport=FakeTokenTransport([]),
            userinfo=FakeUserInfo(),
        )
    assert exc_secret.value.safe_code == "client_secret_invalid"


def test_repr_never_leaks_secret() -> None:
    exchange = OAuthTokenExchange(
        client_id=CLIENT_ID,
        client_secret="fake-secret",
        vault=_vault(),
        transport=FakeTokenTransport([]),
        userinfo=FakeUserInfo(),
    )
    assert "fake-secret" not in repr(exchange)


@pytest.mark.live
def test_live_gmail_token_refresh_and_identity() -> None:
    """Phase 7 live test. Requires real credentials in environment; deselected by default.

    Opt-in: PROBATION_GMAIL_LIVE_CONSENT=scoped-authorization-granted
    Required env: PROBATION_GMAIL_CLIENT_ID, PROBATION_GMAIL_CLIENT_SECRET,
    PROBATION_GMAIL_REFRESH_TOKEN, PROBATION_GMAIL_ACCOUNT.
    """
    import os

    if os.environ.get("PROBATION_GMAIL_LIVE_CONSENT") != "scoped-authorization-granted":
        pytest.skip("PROBATION_GMAIL_LIVE_CONSENT not granted")
    client_id = os.environ.get("PROBATION_GMAIL_CLIENT_ID", "")
    client_secret = os.environ.get("PROBATION_GMAIL_CLIENT_SECRET", "")
    refresh_token = os.environ.get("PROBATION_GMAIL_REFRESH_TOKEN", "")
    account = os.environ.get("PROBATION_GMAIL_ACCOUNT", "").strip().lower()
    if not (client_id and client_secret and refresh_token and account):
        pytest.skip("live credentials missing")

    from probation.connectors.credentials_state import SecretMaterial
    from probation.packs.mail.connectors.gmail_transport import (
        GmailHttpTransport,
        GmailProfileGateway,
        GoogleTokenTransport,
    )

    api_transport = GmailHttpTransport()
    token_transport = GoogleTokenTransport()
    try:
        exchange = OAuthTokenExchange(
            client_id=client_id,
            client_secret=client_secret,
            vault=StateVault(),
            transport=token_transport,
            userinfo=GmailProfileGateway(api_transport),
        )
        bundle = exchange.refresh("cred-ref-live", SecretMaterial(refresh_token, "refresh"))
        assert bundle.account_id == account
        assert len(bundle.access.reveal()) > 20
    finally:
        api_transport.close()
