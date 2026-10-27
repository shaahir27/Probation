"""Local user accounts for the dashboard.

This is deliberately not an engine table. Accounts live in their own owner-only SQLite file
under the private directory, with scrypt password hashes and short-lived HS256 JWTs signed by a
key derived from the existing owner API key. The browser keeps the HttpOnly session cookie;
the JWT is available to local API clients. No password, token or hash is logged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from probation.config import settings
from probation.connectors.acl import IS_WINDOWS, apply_owner_only, verify_owner_only
from probation.core.clock import operational_clock

ACCOUNT_TTL_SECONDS: Final = 1800
_SCRYPT_N: Final = 2**14
_SCRYPT_R: Final = 8
_SCRYPT_P: Final = 1
_SCRYPT_MAXMEM: Final = 64 * 1024 * 1024
_EMAIL = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
_SAFE_EMAIL = re.compile(r"^[^\x00-\x1f\x7f]{3,254}$")


class AccountError(Exception):
    """Typed account failure with a safe code and no credential material."""

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


@dataclass(frozen=True, slots=True)
class Account:
    id: str
    email: str
    owner_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class AccountClaims:
    owner_id: str
    email: str
    expires_at: int


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _now() -> datetime:
    return operational_clock().now(UTC)


def _normalise_email(email: str) -> str:
    value = email.strip().lower()
    if not _SAFE_EMAIL.fullmatch(value) or not _EMAIL.fullmatch(value):
        raise AccountError("invalid_email")
    return value


def _password_hash(password: str) -> str:
    if not 8 <= len(password) <= 200 or not password.strip():
        raise AccountError("invalid_password")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=32,
        maxmem=_SCRYPT_MAXMEM,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64encode(salt)}${_b64encode(digest)}"


def _verify_hash(password: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt, digest = stored.split("$", 5)
        if algorithm != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(_b64decode(digest)),
            maxmem=_SCRYPT_MAXMEM,
        )
        return hmac.compare_digest(derived, _b64decode(digest))
    except (ValueError, TypeError):
        return False


def _protect(path: Path, *, is_dir: bool) -> None:
    if IS_WINDOWS:
        apply_owner_only(path, is_dir=is_dir)
    else:
        os.chmod(path, 0o700 if is_dir else 0o600)


def _verify(path: Path) -> None:
    if IS_WINDOWS:
        verify_owner_only(path)
    elif not path.exists():
        raise AccountError("accounts_unavailable")


def _connect(path: Path) -> sqlite3.Connection:
    parent = path.parent
    try:
        if not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
            _protect(parent, is_dir=True)
        else:
            _verify(parent)
        conn = sqlite3.connect(path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        conn.commit()
        if not IS_WINDOWS:
            _protect(path, is_dir=False)
        else:
            if not path.stat().st_size:
                raise AccountError("accounts_unavailable")
            try:
                verify_owner_only(path)
            except Exception:
                _protect(path, is_dir=False)
                verify_owner_only(path)
        return conn
    except AccountError:
        raise
    except Exception as exc:
        raise AccountError("accounts_unavailable") from exc


def _account(row: sqlite3.Row) -> Account:
    return Account(
        id=str(row["id"]),
        email=str(row["email"]),
        owner_id=str(row["owner_id"]),
        created_at=str(row["created_at"]),
    )


def create_account(path: Path, *, email: str, password: str, owner_id: str) -> Account:
    normalised = _normalise_email(email)
    if not owner_id.strip():
        raise AccountError("invalid_owner")
    conn = _connect(path)
    try:
        account_id = uuid.uuid4().hex
        created = _now().isoformat(timespec="seconds").replace("+00:00", "Z")
        try:
            conn.execute(
                "INSERT INTO accounts(id,email,password_hash,owner_id,created_at) VALUES(?,?,?,?,?)",
                (account_id, normalised, _password_hash(password), owner_id.strip(), created),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise AccountError("account_exists") from exc
        row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        return _account(row)
    finally:
        conn.close()


def authenticate(path: Path, *, email: str, password: str) -> Account | None:
    normalised = _normalise_email(email)
    conn = _connect(path)
    try:
        row = conn.execute("SELECT * FROM accounts WHERE email=?", (normalised,)).fetchone()
        if row is None or not _verify_hash(password, str(row["password_hash"])):
            return None
        return _account(row)
    finally:
        conn.close()


def account_for_owner(path: Path, owner_id: str) -> Account | None:
    conn = _connect(path)
    try:
        row = conn.execute(
            "SELECT * FROM accounts WHERE owner_id=? ORDER BY created_at LIMIT 1", (owner_id,)
        ).fetchone()
        return None if row is None else _account(row)
    finally:
        conn.close()


def _signing_key() -> bytes:
    owner_key = settings.probation_gmail_owner_api_key.strip()
    if not owner_key:
        raise AccountError("auth_not_configured")
    return hashlib.sha256(f"probation-account-jwt:{owner_key}".encode()).digest()


def issue_token(account: Account, *, ttl_seconds: int = ACCOUNT_TTL_SECONDS) -> str:
    now = int(_now().timestamp())
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64encode(
        json.dumps(
            {
                "sub": account.owner_id,
                "email": account.email,
                "iat": now,
                "exp": now + ttl_seconds,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = _b64encode(hmac.new(_signing_key(), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def verify_token(token: str) -> AccountClaims:
    try:
        header_part, payload_part, signature_part = token.split(".")
        signing_input = f"{header_part}.{payload_part}".encode("ascii")
        expected = hmac.new(_signing_key(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(signature_part)):
            raise AccountError("invalid_token")
        header = json.loads(_b64decode(header_part))
        payload = json.loads(_b64decode(payload_part))
        if header.get("alg") != "HS256" or header.get("typ") != "JWT":
            raise AccountError("invalid_token")
        owner_id = payload.get("sub")
        email = payload.get("email")
        issued = int(payload.get("iat"))
        expires = int(payload.get("exp"))
        now = int(_now().timestamp())
        if (
            not isinstance(owner_id, str)
            or not owner_id.strip()
            or not isinstance(email, str)
            or not _SAFE_EMAIL.fullmatch(email)
            or issued > now + 60
            or expires <= now
        ):
            raise AccountError("invalid_token")
        return AccountClaims(owner_id=owner_id, email=email, expires_at=expires)
    except AccountError:
        raise
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise AccountError("invalid_token") from exc


__all__ = [
    "ACCOUNT_TTL_SECONDS",
    "Account",
    "AccountClaims",
    "AccountError",
    "account_for_owner",
    "authenticate",
    "create_account",
    "issue_token",
    "verify_token",
]
