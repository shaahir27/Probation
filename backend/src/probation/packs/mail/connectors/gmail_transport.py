"""Concrete HTTPS transports for Gmail and Google OAuth. One host each, no exceptions.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 5 and 8.1; docs/CONTRACT.md's
network-destination rule. This is the only module through which a Gmail or OAuth request
leaves the process. Hosts are allowlisted, bearer tokens never enter a URL, bodies are
bounded, and provider request ids are hashed before logging.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Final
from urllib.parse import quote, urlencode, urlsplit

import httpx

from probation.connectors.credentials_state import SecretMaterial
from probation.connectors.types import (
    ConnectorError,
    HttpResult,
    HttpTransport,
    ProviderUnavailable,
    TransportFailure,
)
from probation.packs.mail.connectors.gmail_auth import TokenHttpResponse

GMAIL_HOST: Final = "gmail.googleapis.com"
GMAIL_BASE_URL: Final = f"https://{GMAIL_HOST}/gmail/v1/users/me"
OAUTH_HOST: Final = "oauth2.googleapis.com"
OAUTH_TOKEN_URL: Final = f"https://{OAUTH_HOST}/token"
_WRITE_SUFFIXES: Final = ("/trash", "/untrash", "/modify", "/send")
_MAX_RETRY_AFTER: Final = 120.0
_MAX_REQUEST_ID_BYTES: Final = 256
_MAX_TOKEN_BODY_BYTES: Final = 65_536
_TRANSIENT: Final = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)


def quote_native_id(value: str) -> str:
    """Percent-encode an opaque Gmail id so it cannot change the path or add a query."""
    return quote(value, safe="")


def _transport_failure(exc: httpx.HTTPError) -> TransportFailure:
    if isinstance(exc, httpx.RemoteProtocolError):
        return TransportFailure("transport_protocol_error")
    if isinstance(exc, httpx.TimeoutException):
        return TransportFailure("transport_timeout")
    if isinstance(exc, httpx.ConnectError):
        return TransportFailure("transport_connect_failed")
    return TransportFailure("transport_error")


def _query(params: Mapping[str, object] | None) -> dict[str, str] | None:
    if params is None:
        return None
    return {str(key): str(value) for key, value in params.items() if value is not None}


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None or not raw.strip().isdigit():
        return None
    value = float(raw.strip())
    return value if 0 <= value <= _MAX_RETRY_AFTER else None


def _request_id_hash(response: httpx.Response) -> str | None:
    raw = response.headers.get("x-goog-request-id") or response.headers.get("x-request-id")
    if not raw or len(raw.encode("utf-8")) > _MAX_REQUEST_ID_BYTES:
        return None
    return "req-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class GmailHttpTransport:
    """The only Gmail API client: one host, bounded bodies, header-only bearer auth."""

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        client_factory: Callable[[], httpx.Client] | None = None,
        max_body_bytes: int = 4_194_304,
    ) -> None:
        if timeout <= 0 or max_body_bytes < 1:
            raise ConnectorError("invalid_transport_budget")
        self._timeout, self._client_factory = timeout, client_factory
        self._client: httpx.Client | None = None
        self._max_body = max_body_bytes

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = (
                self._client_factory()
                if self._client_factory is not None
                else httpx.Client(timeout=self._timeout, follow_redirects=False)
            )
        return self._client

    @staticmethod
    def _checked(url: str) -> None:
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or parts.netloc != GMAIL_HOST
            or parts.username is not None
            or parts.password is not None
            or parts.fragment
            or parts.query
            or any(ord(char) < 32 for char in parts.path)
        ):
            raise ConnectorError("forbidden_provider_destination")
        if parts.path != "/gmail/v1/users/me/profile" and not parts.path.startswith(
            "/gmail/v1/users/me/"
        ):
            raise ConnectorError("forbidden_provider_endpoint")

    @staticmethod
    def _no_token_in_url(url: str, params: Mapping[str, object] | None, token: str) -> None:
        if not token:
            raise ConnectorError("access_token_absent")
        if token in url or (
            params is not None and any(token in str(value) for value in params.values())
        ):
            raise ConnectorError("credential_in_url")

    def _send(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, object] | None,
        headers: Mapping[str, str],
        content: bytes | None,
    ) -> HttpResult:
        self._checked(url)
        try:
            with self._http().stream(
                method, url, params=_query(params), headers=headers, content=content
            ) as response:
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > self._max_body:
                        raise ProviderUnavailable("provider_response_too_large")
                    chunks.append(chunk)
                return HttpResult(
                    status=response.status_code,
                    body=b"".join(chunks),
                    retry_after_seconds=_retry_after(response),
                    request_id_hash=_request_id_hash(response),
                )
        except (ConnectorError, ProviderUnavailable):
            raise
        except (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
            httpx.RemoteProtocolError,
        ) as exc:
            # Inline the tuple: mypy does not accept a tuple variable as an exception type.
            raise _transport_failure(exc) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("transport_error") from exc

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, object] | None = None,
        access_token: str,
    ) -> HttpResult:
        self._no_token_in_url(url, params, access_token)
        return self._send(
            "GET",
            url,
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
            content=None,
        )

    def post(
        self,
        url: str,
        *,
        json_body: Mapping[str, object] | None = None,
        data: bytes | None = None,
        access_token: str,
    ) -> HttpResult:
        if json_body is not None and data is not None:
            raise ConnectorError("transport_body_ambiguous")
        if not urlsplit(url).path.endswith(_WRITE_SUFFIXES):
            raise ConnectorError("forbidden_provider_endpoint")
        self._no_token_in_url(url, None, access_token)
        headers = {"Authorization": f"Bearer {access_token}"}
        content = data
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            content = json.dumps(dict(json_body), sort_keys=True).encode("utf-8")
        return self._send("POST", url, params=None, headers=headers, content=content)


class GoogleTokenTransport:
    """The only token client: one host, urlencoded form, bounded JSON response."""

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        client_factory: Callable[[], httpx.Client] | None = None,
    ) -> None:
        if timeout <= 0:
            raise ConnectorError("invalid_transport_budget")
        self._timeout, self._client_factory = timeout, client_factory
        self._client: httpx.Client | None = None

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = (
                self._client_factory()
                if self._client_factory is not None
                else httpx.Client(timeout=self._timeout, follow_redirects=False)
            )
        return self._client

    def post_form(self, url: str, form: Mapping[str, str]) -> TokenHttpResponse:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.netloc != OAUTH_HOST or parts.path != "/token":
            raise ConnectorError("forbidden_provider_destination")
        try:
            response = self._http().post(
                url,
                content=urlencode(dict(form)).encode("ascii"),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
            httpx.RemoteProtocolError,
        ) as exc:
            raise _transport_failure(exc) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("transport_error") from exc
        if len(response.content) > _MAX_TOKEN_BODY_BYTES:
            raise ProviderUnavailable("provider_response_too_large")
        try:
            payload = response.json()
        except ValueError:
            return TokenHttpResponse(response.status_code, {})
        if not isinstance(payload, Mapping):
            return TokenHttpResponse(response.status_code, {})
        return TokenHttpResponse(
            response.status_code, {str(key): value for key, value in payload.items()}
        )


class GmailProfileGateway:
    """Account identity via users.getProfile: same host as the API, no extra scope."""

    def __init__(self, transport: HttpTransport) -> None:
        self._transport = transport

    def account_email(self, access: SecretMaterial) -> str:
        result = self._transport.get(
            f"{GMAIL_BASE_URL}/profile",
            params={"fields": "emailAddress"},
            access_token=access.reveal(),
        )
        if not result.ok:
            raise ProviderUnavailable(f"profile_status_{result.status}")
        try:
            payload = json.loads(result.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderUnavailable("profile_payload_invalid") from exc
        email = payload.get("emailAddress") if isinstance(payload, Mapping) else None
        if not isinstance(email, str) or not email.strip() or len(email) > 320:
            raise ProviderUnavailable("profile_identity_unavailable")
        return email.strip().lower()
