"""Local account sign-up/login, scrypt passwords, JWT bearer and owner session."""

import json

import pytest
from fastapi.testclient import TestClient

from probation.api.accounts import create_account, verify_token
from probation.api.app import app
from probation.api.gmail_auth import OwnerApiCredential, hash_owner_token
from probation.api.routes.gmail_connector import GmailApiConfig, configure_gmail_api
from probation.config import settings

OWNER_KEY = "synthetic-owner-key-for-account-tests"
LOOPBACK = ("127.0.0.1", 50000)


@pytest.fixture
def surface(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "probation_gmail_owner_api_key", OWNER_KEY)
    monkeypatch.setattr(settings, "probation_accounts_db", tmp_path / "private" / "accounts.db")
    configure_gmail_api(
        GmailApiConfig(
            owner_credential=OwnerApiCredential(
                owner_id="local-owner", token_sha256=hash_owner_token(OWNER_KEY)
            ),
            store_path=tmp_path / "absent-connector-store.db",
        )
    )
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=LOOPBACK)
    yield client
    configure_gmail_api(None)


def _register(client, email="person@example.test", password="correct-horse-battery"):
    return client.post("/api/auth/register", json={"email": email, "password": password})


def test_register_issues_a_jwt_and_an_httponly_session(surface):
    response = _register(surface)
    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"].split(".")) == 3
    assert body["user"]["email"] == "person@example.test"
    assert body["user"]["owner_id"].startswith("user-")
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert verify_token(body["access_token"]).owner_id == body["user"]["owner_id"]

    checked = surface.get("/api/session")
    assert checked.status_code == 200
    assert checked.json()["authenticated"] is True
    assert checked.json()["email"] == "person@example.test"


def test_login_is_uniform_for_wrong_password_and_duplicate_signup_is_typed(surface):
    assert _register(surface).status_code == 201
    wrong = surface.post(
        "/api/auth/login",
        json={"email": "person@example.test", "password": "not-the-password"},
    )
    assert wrong.status_code == 401
    assert wrong.json() == {"error": {"code": "401", "message": "invalid_credentials"}}
    duplicate = _register(surface)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["message"] == "account_exists"
    assert "correct-horse-battery" not in duplicate.text


def test_account_input_errors_do_not_echo_values(surface):
    bad_email = _register(surface, email="not-an-email", password="long-enough-password")
    assert bad_email.status_code == 400
    assert bad_email.json()["error"]["message"] == "invalid_account_input"
    assert "not-an-email" not in bad_email.text
    short = _register(surface, password="short")
    assert short.status_code == 400
    assert "short" not in short.text


def test_jwt_bearer_authenticates_private_reads(surface):
    account = create_account(
        settings.probation_accounts_db,
        email="demo@example.test",
        password="correct-horse-battery",
        owner_id="local-owner",
    )
    assert account.owner_id == "local-owner"
    login = surface.post(
        "/api/auth/login",
        json={"email": "demo@example.test", "password": "correct-horse-battery"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    read = surface.get("/api/queue", headers={"Authorization": f"Bearer {token}"})
    assert read.status_code == 200
    assert read.json()["items"] == []
    bad = surface.get("/api/queue", headers={"Authorization": "Bearer not-a-jwt"})
    assert bad.status_code == 401
    assert json.loads(bad.text)["error"]["message"] == "owner_credential_required"
