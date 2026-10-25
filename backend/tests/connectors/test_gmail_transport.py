"""Tests for GmailHttpTransport, GoogleTokenTransport and GmailProfileGateway."""

import hashlib
from typing import Any

import httpx
import pytest

from probation.connectors.credentials_state import SecretMaterial
from probation.connectors.types import (
    ConnectorError,
    ProviderUnavailable,
    TransportFailure,
)
from probation.packs.mail.connectors import gmail_transport, gmail_write
from probation.packs.mail.connectors.gmail_transport import (
    GMAIL_BASE_URL,
    GmailHttpTransport,
    GmailProfileGateway,
    GoogleTokenTransport,
)


def _transport(handler: Any, **kwargs: Any) -> GmailHttpTransport:
    return GmailHttpTransport(
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)), **kwargs
    )


def test_bearer_only_in_authorization_header() -> None:
    recorded_req: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal recorded_req
        recorded_req = request
        return httpx.Response(200, json={"ok": True})

    transport = _transport(handler)
    res = transport.get(f"{GMAIL_BASE_URL}/profile", access_token="tok")
    assert res.ok
    assert recorded_req is not None
    assert recorded_req.headers["authorization"] == "Bearer tok"
    assert "tok" not in str(recorded_req.url)


def test_token_never_in_url_or_params() -> None:
    transport = _transport(lambda req: httpx.Response(200))
    with pytest.raises(ConnectorError) as exc_info:
        transport.get(f"{GMAIL_BASE_URL}/messages/tok", access_token="tok")
    assert exc_info.value.safe_code == "credential_in_url"

    with pytest.raises(ConnectorError) as exc_info2:
        transport.get(f"{GMAIL_BASE_URL}/messages", params={"q": "tok"}, access_token="tok")
    assert exc_info2.value.safe_code == "credential_in_url"


def test_foreign_host_and_http_refused() -> None:
    transport = _transport(lambda req: httpx.Response(200))
    with pytest.raises(ConnectorError) as exc1:
        transport.get("https://evil.test/gmail/v1/users/me/profile", access_token="tok")
    assert exc1.value.safe_code == "forbidden_provider_destination"

    with pytest.raises(ConnectorError) as exc2:
        transport.get("http://gmail.googleapis.com/gmail/v1/users/me/profile", access_token="tok")
    assert exc2.value.safe_code == "forbidden_provider_destination"


def test_post_suffix_allowlist_matches_gmail_write() -> None:
    assert gmail_transport._WRITE_SUFFIXES == gmail_write._ALLOWED_WRITE_SUFFIXES


def test_retry_after_parsed_and_bounded() -> None:
    transport = _transport(lambda req: httpx.Response(429, headers={"retry-after": "7"}))
    res = transport.get(f"{GMAIL_BASE_URL}/profile", access_token="tok")
    assert res.retry_after_seconds == 7.0

    transport_high = _transport(lambda req: httpx.Response(429, headers={"retry-after": "9999"}))
    res_high = transport_high.get(f"{GMAIL_BASE_URL}/profile", access_token="tok")
    assert res_high.retry_after_seconds is None

    transport_bad = _transport(lambda req: httpx.Response(429, headers={"retry-after": "soon"}))
    res_bad = transport_bad.get(f"{GMAIL_BASE_URL}/profile", access_token="tok")
    assert res_bad.retry_after_seconds is None


def test_request_id_hash_is_hashed_and_optional() -> None:
    transport = _transport(lambda req: httpx.Response(200, headers={"x-goog-request-id": "raw-1"}))
    res = transport.get(f"{GMAIL_BASE_URL}/profile", access_token="tok")
    expected = "req-" + hashlib.sha256(b"raw-1").hexdigest()[:16]
    assert res.request_id_hash == expected

    transport_no_hdr = _transport(lambda req: httpx.Response(200))
    res_no_hdr = transport_no_hdr.get(f"{GMAIL_BASE_URL}/profile", access_token="tok")
    assert res_no_hdr.request_id_hash is None


def test_connect_timeout_raises_transport_failure() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    transport = _transport(handler)
    with pytest.raises(TransportFailure) as exc_info:
        transport.get(f"{GMAIL_BASE_URL}/profile", access_token="tok")
    assert exc_info.value.safe_code == "transport_timeout"


def test_read_timeout_raises_transport_failure() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    transport = _transport(handler)
    with pytest.raises(TransportFailure) as exc_info:
        transport.get(f"{GMAIL_BASE_URL}/profile", access_token="tok")
    assert exc_info.value.safe_code == "transport_timeout"


def test_oversized_body_refused() -> None:
    transport = _transport(lambda req: httpx.Response(200, content=b"12345"), max_body_bytes=4)
    with pytest.raises(ProviderUnavailable) as exc_info:
        transport.get(f"{GMAIL_BASE_URL}/profile", access_token="tok")
    assert exc_info.value.safe_code == "provider_response_too_large"


def test_token_form_is_urlencoded() -> None:
    recorded_req: httpx.Request | None = None

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal recorded_req
        recorded_req = req
        return httpx.Response(200, json={"access_token": "new-acc"})

    token_transport = GoogleTokenTransport(
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    res = token_transport.post_form(
        "https://oauth2.googleapis.com/token",
        {"grant_type": "refresh_token", "refresh_token": "ref-tok"},
    )
    assert res.status == 200
    assert recorded_req is not None
    assert recorded_req.headers["content-type"] == "application/x-www-form-urlencoded"
    assert b"grant_type=refresh_token" in recorded_req.content


def test_profile_gateway_identity() -> None:
    transport = _transport(
        lambda req: httpx.Response(200, json={"emailAddress": "Owner@Test.INVALID"})
    )
    gateway = GmailProfileGateway(transport)
    email = gateway.account_email(SecretMaterial("tok", "access"))
    assert email == "owner@test.invalid"

    transport_empty = _transport(lambda req: httpx.Response(200, json={"emailAddress": ""}))
    gateway_empty = GmailProfileGateway(transport_empty)
    with pytest.raises(ProviderUnavailable) as exc_info:
        gateway_empty.account_email(SecretMaterial("tok", "access"))
    assert exc_info.value.safe_code == "profile_identity_unavailable"


def test_repr_never_leaks_secret() -> None:
    from probation.packs.mail.connectors.gmail_auth import OAuthTokenExchange, StateVault
    from probation.workers.gmail_live import LiveOAuthClient

    client = LiveOAuthClient("client-1", "fake-secret", "ref-tok")
    assert "fake-secret" not in repr(client)

    exchange = OAuthTokenExchange(
        client_id="client-1.apps.googleusercontent.com",
        client_secret="fake-secret",
        vault=StateVault(),
        transport=GoogleTokenTransport(),
        userinfo=GmailProfileGateway(GmailHttpTransport()),
    )
    assert "fake-secret" not in repr(exchange)
