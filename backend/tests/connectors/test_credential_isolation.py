"""Role-bound credential isolation: a reader can never resolve the write grant (D4-05).

Offline only. Every value is an obviously fake constant; no real account, network or
secret. The canary sweep proves no token-shaped material reaches a log, an exception,
a repr, a persisted store row or a URL.
"""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from probation.connectors.credentials import (
    CredentialStateRow,
    EnvCredentialSource,
    InMemoryCredentialStateRepository,
    ProvisionedGrant,
    RoleCredentialProvider,
    SecretMaterial,
    StaleRefreshRejected,
    StoreCredentialStateRepository,
    TokenBundle,
    build_child_env,
    default_state_repository,
    grant_env_name,
)
from probation.connectors.types import CredentialUnavailable, ScopeMismatch
from probation.core.clock import Clock
from probation.db.gmail_store import ConnectorAccess, migrate_store, open_store
from probation.packs.mail.connectors.gmail_auth import (
    GMAIL_MODIFY_SCOPE,
    GMAIL_READONLY_SCOPE,
    GMAIL_SEND_SCOPE,
    PkcePair,
    build_authorization_url,
    new_pkce,
)

ACCESS_CANARY = "CANARY-acc-3j2k4h5g6f7d8s9a0s1d2f3g"
REFRESH_CANARY = "CANARY-ref-9z8x7c6v5b4n3m2q1w0e9r8t"
VERIFIER_CANARY = "CANARY-verifier-kjhgfdsa1234567890abcdef"
WRONG_ACCESS = "CANARY-write-acc-5t6y7u8i9o0p1a2s3d4f5g6h"
OWNER = "owner-1"
ACCOUNT = "owner@example.com"
NOW = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)

READ_GRANT = ProvisionedGrant(
    role="read", connection_id="conn-1", account_id=ACCOUNT, credential_ref="cred-read-1"
)
WRITE_GRANT = ProvisionedGrant(
    role="write", connection_id="conn-1", account_id=ACCOUNT, credential_ref="cred-write-1"
)


def _clock() -> Clock:
    return Clock.replay(NOW)


def _bundle(access: str, scopes: tuple[str, ...], account: str = ACCOUNT) -> TokenBundle:
    return TokenBundle(
        account_id=account,
        granted_scopes=scopes,
        expires_in_seconds=3600,
        access=SecretMaterial(access, "access"),
        refresh=SecretMaterial(REFRESH_CANARY, "refresh"),
    )


class RecordingSource:
    """Spy source: records every (role, ref) request so denial can be proven absolute."""

    def __init__(self, env: dict[str, str], grant: ProvisionedGrant) -> None:
        self._inner = EnvCredentialSource(env, grant)
        self.requested: list[tuple[str, str]] = []

    def fetch(self, role: str, credential_ref: str) -> SecretMaterial:  # type: ignore[assignment]
        self.requested.append((role, credential_ref))
        return self._inner.fetch(role, credential_ref)  # type: ignore[arg-type]


class FakeRefresher:
    def __init__(self, bundle: TokenBundle, block: threading.Event | None = None) -> None:
        self.bundle = bundle
        self.calls = 0
        self.entered = threading.Event()
        self._block = block

    def refresh(self, credential_ref: str, refresh_material: SecretMaterial) -> TokenBundle:
        self.calls += 1
        if self._block is not None:
            self.entered.set()
            self._block.wait(5)
        return self.bundle


def _parent_env() -> dict[str, str]:
    return {
        "SystemRoot": "C:/Windows",
        "PATH": "/usr/bin",
        READ_GRANT.env_name: REFRESH_CANARY,
        WRITE_GRANT.env_name: "writer-refresh-material",
    }


def _reader(
    source_out: list[RecordingSource] | None = None, clock: Clock | None = None
) -> RoleCredentialProvider:
    env = build_child_env(_parent_env(), READ_GRANT)
    source = RecordingSource(env, READ_GRANT)
    if source_out is not None:
        source_out.append(source)
    return RoleCredentialProvider(grant=READ_GRANT, source=source, clock=clock or _clock())


def test_read_worker_denies_write_credential() -> None:
    """D4-05 gate id (WP12_D4_GMAIL_CONTRACT.md section 9)."""
    sources: list[RecordingSource] = []
    reader = _reader(sources)
    with pytest.raises(CredentialUnavailable) as excinfo:
        reader.resolve_for_role("write", "send", (GMAIL_SEND_SCOPE,))
    assert excinfo.value.safe_code == "role_not_provisioned_to_process"
    # The proof: the reader's source was never even consulted for the write role, and the
    # only grant this process can name is its own read grant.
    assert sources[0].requested == []
    assert reader.is_disabled("send") == "role_not_provisioned_to_process"
    assert reader.role == "read"


def test_reader_cannot_enumerate_inherit_or_guess_the_write_grant() -> None:
    env = build_child_env(_parent_env(), READ_GRANT)
    source = RecordingSource(env, READ_GRANT)
    for ref in (WRITE_GRANT.credential_ref, "any-string-at-all"):
        with pytest.raises(CredentialUnavailable) as excinfo:
            source.fetch("write", ref)
        # Same safe code for wrong role and wrong reference: nothing is enumerable.
        assert excinfo.value.safe_code == "grant_not_provisioned_to_process"
    reader = _reader()
    text = f"{reader!r} {WRITE_GRANT.env_name in env} {WRITE_GRANT.credential_ref in repr(reader)}"
    assert WRITE_GRANT.env_name not in text
    assert "writer-refresh-material" not in "".join(env.values())


def test_child_env_allowlist_never_inherits_both_grants() -> None:
    parent = _parent_env()
    assert grant_env_name("read", "cred-read-1") == READ_GRANT.env_name
    child = build_child_env(parent, READ_GRANT)
    grant_vars = [key for key in child if key.startswith("PROBATION_GMAIL_GRANT_")]
    assert grant_vars == [READ_GRANT.env_name]  # exactly one, despite the parent holding two
    assert child[READ_GRANT.env_name] == REFRESH_CANARY
    with pytest.raises(Exception) as bad:
        build_child_env(parent, READ_GRANT, extra_allow=(WRITE_GRANT.env_name,))
    assert "foreign_grant" in str(bad.value)


def _provider_with_bundle(scopes: tuple[str, ...]) -> RoleCredentialProvider:
    provider = _reader()
    provider.install_bundle(_bundle(ACCESS_CANARY, scopes))
    return provider


def test_missing_grant_disables_affected_capability_only() -> None:
    provider = _reader()
    with pytest.raises(CredentialUnavailable) as excinfo:
        provider.resolve_access("read", (GMAIL_READONLY_SCOPE,))
    assert excinfo.value.safe_code == "grant_not_installed"
    assert provider.is_disabled("read") == "grant_not_installed"
    assert provider.is_disabled("undo_history_proof") is None


def test_expired_grant_without_refresher_fails_closed() -> None:
    clock = _clock()
    provider = _reader(clock=clock)
    provider.install_bundle(_bundle(ACCESS_CANARY, (GMAIL_READONLY_SCOPE,)))
    clock.advance_seconds(3700)
    with pytest.raises(CredentialUnavailable) as excinfo:
        provider.resolve_access("read", (GMAIL_READONLY_SCOPE,))
    assert excinfo.value.safe_code == "grant_expired_no_refresher"


def test_refresh_installs_new_generation_and_serializes_callers() -> None:
    clock = _clock()
    env = build_child_env(_parent_env(), READ_GRANT)
    gate = threading.Event()
    refresher = FakeRefresher(_bundle(ACCESS_CANARY, (GMAIL_READONLY_SCOPE,)), block=gate)
    provider = RoleCredentialProvider(
        grant=READ_GRANT,
        source=EnvCredentialSource(env, READ_GRANT),
        refresher=refresher,
        clock=clock,
    )
    provider.install_bundle(_bundle(ACCESS_CANARY, (GMAIL_READONLY_SCOPE,)))
    clock.advance_seconds(3600)  # inside margin now, expired for the second call
    results: list[SecretMaterial] = []

    def fetch() -> None:
        results.append(provider.resolve_access("read", (GMAIL_READONLY_SCOPE,)))

    first = threading.Thread(target=fetch)
    first.start()
    assert refresher.entered.wait(2)
    second = threading.Thread(target=fetch)
    second.start()
    gate.set()
    first.join(5)
    second.join(5)
    assert refresher.calls == 1  # serialized: the waiter reuses the fresh result
    assert len(results) == 2
    state = provider._state.load(READ_GRANT.credential_ref)
    assert state is not None and state.generation == 2  # one install, one refresh


def test_stale_generation_cannot_overwrite_newer_state() -> None:
    repo = InMemoryCredentialStateRepository()
    newer = CredentialStateRow("cred-read-1", "conn-1", ACCOUNT, "read", 5, (GMAIL_READONLY_SCOPE,))
    stale = CredentialStateRow("cred-read-1", "conn-1", ACCOUNT, "read", 3, (GMAIL_SEND_SCOPE,))
    assert repo.commit(newer) is True
    assert repo.commit(stale) is False
    stored = repo.load("cred-read-1")
    assert (
        stored is not None
        and stored.generation == 5
        and stored.granted_scopes == (GMAIL_READONLY_SCOPE,)
    )


def test_provider_loses_generation_guard_race_refuses_to_serve() -> None:
    repo = _RejectingRepo()  # simulates a newer writer winning the race first
    provider = _reader()
    provider._state = repo  # test seam: inject the adversarial repository
    with pytest.raises(StaleRefreshRejected):
        provider.install_bundle(_bundle(ACCESS_CANARY, (GMAIL_READONLY_SCOPE,)))
    assert provider.granted_scopes() == ()


class _RejectingRepo:
    def load(self, credential_ref: str) -> CredentialStateRow | None:
        del credential_ref
        return CredentialStateRow(
            "cred-read-1", "conn-1", ACCOUNT, "read", 9, (GMAIL_READONLY_SCOPE,)
        )

    def commit(self, row: CredentialStateRow) -> bool:
        del row
        return False


def _executor_access(tmp_path: Path) -> ConnectorAccess:
    conn = open_store(tmp_path / "gmail_metadata.db")
    assert migrate_store(conn) is True
    return ConnectorAccess(conn, "executor")


def test_executor_state_persists_scopes_expiry_never_token(tmp_path: Path) -> None:
    access = _executor_access(tmp_path)
    repo = StoreCredentialStateRepository(access)
    provider = RoleCredentialProvider(
        grant=WRITE_GRANT,
        source=EnvCredentialSource(_parent_env(), WRITE_GRANT),
        state=repo,
        clock=_clock(),
    )
    provider.install_bundle(_bundle(WRONG_ACCESS, (GMAIL_SEND_SCOPE, GMAIL_MODIFY_SCOPE)))
    row = repo.load(WRITE_GRANT.credential_ref)
    assert row is not None
    assert row.role == "write" and row.generation == 1
    assert json.loads(json.dumps(row.granted_scopes)) == [GMAIL_SEND_SCOPE, GMAIL_MODIFY_SCOPE]
    assert row.access_expires_at is not None
    assert (
        repo.commit(
            CredentialStateRow(
                WRITE_GRANT.credential_ref, "conn-1", ACCOUNT, "write", 1, (GMAIL_SEND_SCOPE,)
            )
        )
        is False
    )  # same generation cannot clobber: strictly monotonic
    assert (
        repo.commit(
            CredentialStateRow(
                WRITE_GRANT.credential_ref, "conn-1", ACCOUNT, "write", 2, (GMAIL_SEND_SCOPE,)
            )
        )
        is True
    )


def test_read_role_state_stays_in_memory_when_store_denies(tmp_path: Path) -> None:
    conn = open_store(tmp_path / "gmail_metadata.db")
    migrate_store(conn)
    read_worker = ConnectorAccess(conn, "read_worker")
    repo = default_state_repository(read_worker)  # denied by the authority matrix, in-memory
    assert isinstance(repo, InMemoryCredentialStateRepository)
    with pytest.raises(ScopeMismatch) as excinfo:
        _provider_with_bundle((GMAIL_READONLY_SCOPE,)).resolve_access(
            "undo_history_proof", (GMAIL_MODIFY_SCOPE,)
        )
    assert excinfo.value.safe_code.startswith("scope_missing")
    assert read_worker.one("SELECT count(*) AS n FROM gmail_credential_state")["n"] == 0  # type: ignore[index]


def test_narrow_scope_disables_dependent_capability_only() -> None:
    provider = _provider_with_bundle((GMAIL_READONLY_SCOPE,))
    assert provider.resolve_access("read", (GMAIL_READONLY_SCOPE,)).kind == "access"
    with pytest.raises(ScopeMismatch):
        provider.resolve_access("send", (GMAIL_SEND_SCOPE,))
    assert provider.is_disabled("send") == "scope_missing_gmail.send"
    assert provider.is_disabled("read") is None  # only the affected capability


def test_revoked_grant_never_resolves_again() -> None:
    provider = _provider_with_bundle((GMAIL_READONLY_SCOPE,))
    provider.revoke()
    with pytest.raises(CredentialUnavailable) as excinfo:
        provider.resolve_access("read", (GMAIL_READONLY_SCOPE,))
    assert excinfo.value.safe_code == "grant_revoked"
    with pytest.raises(CredentialUnavailable):
        provider.install_bundle(_bundle(ACCESS_CANARY, (GMAIL_READONLY_SCOPE,)))


def test_wrong_account_bundle_is_refused_never_falls_back() -> None:
    provider = _reader()
    with pytest.raises(CredentialUnavailable) as excinfo:
        provider.install_bundle(
            _bundle(ACCESS_CANARY, (GMAIL_READONLY_SCOPE,), account="other@example.com")
        )
    assert excinfo.value.safe_code == "account_binding_mismatch"
    assert provider.granted_scopes() == ()


def test_canary_never_persisted_logged_repr_exception_or_url(
    caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    canary = ACCESS_CANARY
    provider = _provider_with_bundle((GMAIL_READONLY_SCOPE,))
    # 1. reprs and strings.
    material = provider.resolve_access("read", (GMAIL_READONLY_SCOPE,))
    swept = [repr(material), str(material), repr(provider)]
    # 2. exception paths: typed failures carry safe codes only.
    with pytest.raises(CredentialUnavailable) as excinfo:
        provider.resolve_for_role("write", "send")
    swept += [str(excinfo.value), repr(excinfo.value)]
    with pytest.raises(ScopeMismatch) as narrow:
        provider.resolve_access("send", (GMAIL_MODIFY_SCOPE,))
    swept += [str(narrow.value), repr(narrow.value)]
    # 3. logs: everything the provider did above.
    with caplog.at_level("DEBUG"):
        provider.revoke()
        with pytest.raises(CredentialUnavailable):
            provider.resolve_access("read")
    swept.append(caplog.text)
    # 4. store rows: executor state for a different canary token.
    access = _executor_access(tmp_path)
    StoreCredentialStateRepository(access)  # construction alone must not write tokens
    swept.append(json.dumps([dict(r) for r in access.query("SELECT * FROM gmail_connections")]))
    # 5. URLs: the verifier half of PKCE must never ride in a URL either.
    url = build_authorization_url(
        client_id="fake-client.apps.googleusercontent.com",
        redirect_uri="http://127.0.0.1:4321/",
        state_token=new_pkce().challenge,
        pkce=PkcePair(
            challenge=new_pkce().challenge, verifier=SecretMaterial(VERIFIER_CANARY, "verifier")
        ),
        scopes=(GMAIL_READONLY_SCOPE,),
    )
    swept.append(url)
    joined = "\n".join(swept)
    assert canary not in joined
    assert VERIFIER_CANARY not in url
    # 6. persisted files: the whole database byte stream from a clean install.
    provider2 = RoleCredentialProvider(
        grant=WRITE_GRANT,
        source=EnvCredentialSource(_parent_env(), WRITE_GRANT),
        state=StoreCredentialStateRepository(access),
        clock=_clock(),
    )
    provider2.install_bundle(_bundle(canary, (GMAIL_SEND_SCOPE,)))
    access.conn.commit()
    access.conn.close()
    blob = b"".join(p.read_bytes() for p in sorted(tmp_path.glob("gmail_metadata.db*")))
    assert canary.encode() not in blob
    assert REFRESH_CANARY.encode() not in blob
