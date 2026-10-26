"""Owner sessions: one key exchange, an HttpOnly cookie, idle expiry and CSRF protection."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from probation.api.app import app
from probation.api.gmail_auth import OwnerApiCredential, hash_owner_token
from probation.api.owner_session import SESSION_COOKIE, OwnerSessionManager
from probation.api.routes.gmail_connector import GmailApiConfig, configure_gmail_api
from probation.config import settings
from probation.core.clock import Clock

OWNER_KEY = "synthetic-owner-key-for-session-tests"
LOOPBACK = ("127.0.0.1", 50000)


@pytest.fixture
def surface(tmp_path, monkeypatch):
    clock = Clock.replay(datetime(2026, 3, 1, 12, tzinfo=UTC))
    manager = OwnerSessionManager(clock=clock)
    monkeypatch.setattr(app.state, "owner_sessions", manager)
    configure_gmail_api(
        GmailApiConfig(
            owner_credential=OwnerApiCredential(
                owner_id="local-owner", token_sha256=hash_owner_token(OWNER_KEY)
            ),
            store_path=tmp_path / "absent-connector-store.db",
        )
    )
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=LOOPBACK)
    yield {"client": client, "clock": clock, "manager": manager}
    configure_gmail_api(None)


def _sign_in(client: TestClient, key: str = OWNER_KEY):
    return client.post("/api/session", headers={"Authorization": f"Bearer {key}"})


def test_key_exchange_sets_an_httponly_strict_cookie_and_no_key_is_echoed(surface):
    response = _sign_in(surface["client"])
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "version": "v1",
        "authenticated": True,
        "owner_id": "local-owner",
        "expires_in": 1800,
    }
    assert OWNER_KEY not in response.text
    cookie = response.headers["set-cookie"]
    assert f"{SESSION_COOKIE}=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/api" in cookie
    assert "Max-Age=1800" in cookie
    assert "Secure" not in cookie
    assert OWNER_KEY not in cookie


def test_cookie_authenticates_private_reads_and_renews_on_session_check(surface):
    _sign_in(surface["client"])
    queue = surface["client"].get("/api/queue")
    assert queue.status_code == 200
    assert queue.json()["items"] == []
    checked = surface["client"].get("/api/session")
    assert checked.status_code == 200
    assert checked.json()["authenticated"] is True
    assert checked.headers["cache-control"] == "no-store"


def test_wrong_key_and_non_loopback_origin_get_the_same_uniform_failure(tmp_path):
    configure_gmail_api(
        GmailApiConfig(
            owner_credential=OwnerApiCredential(
                owner_id="local-owner", token_sha256=hash_owner_token(OWNER_KEY)
            ),
            store_path=tmp_path / "absent-connector-store.db",
        )
    )
    try:
        wrong = TestClient(app, base_url="http://127.0.0.1:8000", client=LOOPBACK)
        response = _sign_in(wrong, "not-the-owner-key")
        assert response.status_code == 401
        assert response.json() == {"error": {"code": "401", "message": "owner_credential_required"}}
        assert "set-cookie" not in response.headers

        remote = TestClient(app, base_url="http://127.0.0.1:8000", client=("10.0.0.9", 50000))
        remote_response = _sign_in(remote)
        assert remote_response.status_code == 401
        assert "set-cookie" not in remote_response.headers
    finally:
        configure_gmail_api(None)


def test_a_invalid_bearer_never_falls_back_to_a_valid_session_cookie(surface):
    assert _sign_in(surface["client"]).status_code == 200
    response = surface["client"].get(
        "/api/queue", headers={"Authorization": "Bearer a-different-key"}
    )
    assert response.status_code == 401
    assert surface["client"].get("/api/session").status_code == 200


def test_unsafe_cookie_requests_need_the_csrf_marker_and_logout_destroys_the_session(surface):
    assert _sign_in(surface["client"]).status_code == 200
    body = {"version": "v2", "response": "leave"}
    refused = surface["client"].post("/api/queue/no-such-proposal/review", json=body)
    assert refused.status_code == 403
    assert refused.json() == {"error": {"code": "403", "message": "csrf_header_required"}}

    header = {"X-Probation-CSRF": "1"}
    accepted = surface["client"].post(
        "/api/queue/no-such-proposal/review", json=body, headers=header
    )
    assert accepted.status_code != 403

    missing_marker = surface["client"].delete("/api/session")
    assert missing_marker.status_code == 403
    assert surface["client"].get("/api/session").status_code == 200

    logout = surface["client"].delete("/api/session", headers=header)
    assert logout.status_code == 204
    cleared = logout.headers["set-cookie"]
    assert f"{SESSION_COOKIE}=" in cleared
    assert "Max-Age=0" in cleared
    signed_out = surface["client"].get("/api/session")
    assert signed_out.status_code == 200
    assert signed_out.json() == {"version": "v1", "authenticated": False}
    assert len(surface["manager"]) == 0


def test_idle_expiry_signs_the_session_out(surface):
    assert _sign_in(surface["client"]).status_code == 200
    surface["clock"].advance_seconds(1801)
    expired = surface["client"].get("/api/session")
    assert expired.status_code == 200
    assert expired.json()["authenticated"] is False
    assert len(surface["manager"]) == 0


def test_a_signed_out_probe_is_a_normal_state_and_not_a_failed_request(surface):
    probe = surface["client"].get("/api/session")
    assert probe.status_code == 200
    assert probe.json() == {"version": "v1", "authenticated": False}
    assert "set-cookie" not in probe.headers
    assert probe.headers["cache-control"] == "no-store"


def test_synthetic_profile_is_a_trusted_loopback_workspace(surface, monkeypatch):
    monkeypatch.setattr(settings, "app_profile", "synthetic")
    bootstrap = surface["client"].get("/api/bootstrap").json()
    assert bootstrap["profile"] == "synthetic"
    assert bootstrap["auth_required"] is False

    assert surface["client"].get("/api/queue").status_code == 200
    refused = surface["client"].post(
        "/api/queue/no-such-proposal/review", json={"version": "v2", "response": "leave"}
    )
    assert refused.status_code == 403
    setup_state = surface["client"].get("/api/gmail/setup/read")
    assert setup_state.status_code == 200
    assert setup_state.json()["reason"] == "private_profile_required"
    assert surface["client"].post(
        "/api/gmail/setup/read", json={"version": "v1", "request_id": "synthetic-1"}
    ).status_code == 403

    remote = TestClient(app, base_url="http://127.0.0.1:8000", client=("10.0.0.9", 50000))
    assert remote.get("/api/queue").status_code == 401


def test_session_manager_rejects_empty_owner_and_unsafe_idle_windows():
    clock = Clock.replay(datetime(2026, 3, 1, 12, tzinfo=UTC))
    with pytest.raises(ValueError):
        OwnerSessionManager(clock=clock, idle_seconds=1)
    with pytest.raises(ValueError):
        OwnerSessionManager(clock=clock, idle_seconds=90_000)
    manager = OwnerSessionManager(clock=clock)
    with pytest.raises(ValueError):
        manager.create("  ")
    token, _ = manager.create("owner")
    assert manager.resolve(token) is not None
    manager.delete(token)
    assert manager.resolve(token) is None
