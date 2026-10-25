"""D4 private connector store: authority isolation, immutability and migration invariants.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md section 7. Storage-boundary regressions only: no
transport, no credentials. Each authority gets its own connection, mirroring one process per
role, so a shared handle can never carry two authorities.
"""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from probation.db.gmail_store import (
    ConnectorAccess,
    StoreAccessError,
    drop_store_objects,
    migrate_store,
    open_store,
    store_is_current,
)

NOW = "2026-10-24T09:00:00+00:00"
LATER = "2026-10-24T09:01:00+00:00"

_CONNECTION = """INSERT INTO gmail_connections
 (connection_id,account_id,owner_id,state,selection_revision,label_ids,credential_ref,
  granted_scopes,created_at,updated_at)
 VALUES ('conn-1','acct-1','owner-1','AUTHORIZED',1,'["cohort"]','cred-ref-1','["gmail.readonly"]',?,?)"""

_OBSERVATION = """INSERT INTO gmail_observations
 (connection_id,account_id,native_message_id,history_id,event_type,content_hash,version_hash,
  observed_at,occurrence_provenance,label_ids,payload_ref)
 VALUES ('conn-1','acct-1','msg-1',10,'message_added','sha256:aa','sha256:bb',?,
  'provider_occurrence','["INBOX"]','data/private/payload-1')"""

_CURSOR = """INSERT INTO gmail_sync_cursors
 (connection_id,account_id,resource_key,role,filter_revision,committed_history_id,fence,
  created_at,updated_at) VALUES ('conn-1','acct-1','cohort','read',1,0,1,?,?)"""


class _Handles:
    """Opens one connection per authority and closes them all afterwards."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._conns: list[sqlite3.Connection] = []

    def access(self, authority: str) -> ConnectorAccess:  # type: ignore[typescript-safe]
        conn = open_store(self.path)
        self._conns.append(conn)
        return ConnectorAccess(conn, authority)  # type: ignore[arg-type]

    def raw(self) -> sqlite3.Connection:
        """Unbound handle used only to prove a bound authority cannot be re-declared."""
        conn = open_store(self.path)
        self._conns.append(conn)
        return conn

    def close(self) -> None:
        for conn in self._conns:
            conn.close()


@pytest.fixture
def db(tmp_path: Path) -> Iterator[_Handles]:
    path = tmp_path / "gmail_metadata.db"
    boot = open_store(path)
    assert migrate_store(boot) is True
    assert migrate_store(boot) is False
    assert store_is_current(boot) is True
    boot.close()
    handles = _Handles(path)
    yield handles
    handles.close()


def _registered(access: ConnectorAccess) -> None:
    access.write("gmail_connections", _CONNECTION, (NOW, NOW))


def test_migrations_are_rerunnable_and_rollback_restores_prior_shape(tmp_path: Path) -> None:
    conn = open_store(tmp_path / "rerun.db")
    assert migrate_store(conn) is True
    created = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert migrate_store(conn) is False
    assert {row[0] for row in conn.execute("SELECT name FROM sqlite_master")} == created
    drop_store_objects(conn)
    assert store_is_current(conn) is False
    assert not any(
        str(name).startswith(("gmail_", "d4_"))
        for (name,) in conn.execute("SELECT name FROM sqlite_master")
    )
    assert migrate_store(conn) is True
    assert {row[0] for row in conn.execute("SELECT name FROM sqlite_master")} == created
    conn.close()


def test_api_writes_nothing_and_administration_writes_only_registration(db: _Handles) -> None:
    api = db.access("api")
    for table in ("gmail_observations", "gmail_capabilities", "gmail_connections"):
        with pytest.raises(StoreAccessError):
            api.write(table, _CONNECTION, (NOW, NOW))
    ingestor = db.access("ingestor")
    with pytest.raises(StoreAccessError):
        ingestor.write("gmail_connections", _CONNECTION, (NOW, NOW))
    admin = db.access("administration")
    _registered(admin)
    assert admin.one("SELECT count(*) AS n FROM gmail_connections")["n"] == 1  # type: ignore[index]


def test_a_bound_connection_cannot_carry_a_second_authority(db: _Handles) -> None:
    admin = db.access("administration")
    with pytest.raises(StoreAccessError):
        ConnectorAccess(admin.conn, "executor")
    foreign = db.raw()
    ConnectorAccess(foreign, "executor")
    with pytest.raises(StoreAccessError):
        ConnectorAccess(foreign, "ingestor")


def test_write_capabilities_are_disjoint_per_role(db: _Handles) -> None:
    _registered(db.access("administration"))
    executor = db.access("executor")
    with pytest.raises(StoreAccessError):
        executor.write("gmail_observations", _OBSERVATION, (NOW,))
    with pytest.raises(StoreAccessError):
        executor.write("gmail_connections", _CONNECTION, (NOW, NOW))
    ingestor = db.access("ingestor")
    with pytest.raises(StoreAccessError):
        ingestor.write(
            "gmail_effect_receipts",
            "INSERT INTO gmail_effect_receipts VALUES('op-1','conn-1','acct-1','act-1',"
            "'execute','confirmed',NULL,NULL,'sha256:h',NULL,0,?)",
            (NOW,),
        )
    with pytest.raises(StoreAccessError):
        ingestor.write(
            "gmail_credential_state",
            "INSERT INTO gmail_credential_state VALUES('cred-ref-1','conn-1','acct-1','read',"
            "1,'[]',NULL,?,NULL)",
            (NOW,),
        )


def test_observations_and_history_events_are_append_only(db: _Handles) -> None:
    _registered(db.access("administration"))
    ingestor = db.access("ingestor")
    ingestor.write("gmail_observations", _OBSERVATION, (NOW,))
    ingestor.write(
        "gmail_history_events",
        "INSERT INTO gmail_history_events VALUES('conn-1','acct-1',10,'msg-1','INBOX',"
        "'messageAdded',?)",
        (NOW,),
    )
    with pytest.raises(StoreAccessError):
        ingestor.write(
            "gmail_observations",
            "UPDATE gmail_observations SET content_hash='sha256:zz' WHERE 1=1",
            (),
        )
    with pytest.raises(StoreAccessError):
        ingestor.write("gmail_observations", "DELETE FROM gmail_observations WHERE 1=1", ())
    with pytest.raises(StoreAccessError):
        ingestor.write("gmail_history_events", "UPDATE gmail_history_events SET history_id=99", ())
    assert ingestor.one("SELECT content_hash AS h FROM gmail_observations")["h"] == "sha256:aa"  # type: ignore[index]


def test_repeated_page_is_harmless_and_never_duplicates(db: _Handles) -> None:
    _registered(db.access("administration"))
    ingestor = db.access("ingestor")
    with ingestor.transaction() as tx:
        tx.write("gmail_observations", _OBSERVATION, (NOW,))
    assert ingestor.one("SELECT count(*) AS n FROM gmail_observations")["n"] == 1  # type: ignore[index]
    with pytest.raises(StoreAccessError):
        ingestor.write("gmail_observations", _OBSERVATION, (LATER,))
    assert ingestor.one("SELECT count(*) AS n FROM gmail_observations")["n"] == 1  # type: ignore[index]


def test_failed_page_rolls_back_observations_and_cursor_together(db: _Handles) -> None:
    _registered(db.access("administration"))
    ingestor = db.access("ingestor")
    ingestor.write("gmail_sync_cursors", _CURSOR, (NOW, NOW))
    with pytest.raises(StoreAccessError), ingestor.transaction() as tx:
        tx.write("gmail_observations", _OBSERVATION, (NOW,))
        tx.write(
            "gmail_sync_cursors",
            "UPDATE gmail_sync_cursors SET committed_history_id=10,fence=2,updated_at=?",
            (NOW,),
        )
        tx.write("gmail_effect_receipts", "INSERT INTO gmail_effect_receipts VALUES('x')", ())
    assert ingestor.one("SELECT count(*) AS n FROM gmail_observations")["n"] == 0  # type: ignore[index]
    row = ingestor.one("SELECT committed_history_id AS c,fence AS f FROM gmail_sync_cursors")
    assert (row["c"], row["f"]) == (0, 1)  # type: ignore[index]
    assert not ingestor.conn.in_transaction


def test_cursor_watermark_and_fence_never_move_backwards(db: _Handles) -> None:
    _registered(db.access("administration"))
    ingestor = db.access("ingestor")
    ingestor.write("gmail_sync_cursors", _CURSOR, (NOW, NOW))
    ingestor.write(
        "gmail_sync_cursors",
        "UPDATE gmail_sync_cursors SET committed_history_id=50,fence=2,catchup_complete=1,"
        "updated_at=? WHERE resource_key='cohort'",
        (LATER,),
    )
    for statement in (
        "UPDATE gmail_sync_cursors SET committed_history_id=49 WHERE 1=1",
        "UPDATE gmail_sync_cursors SET fence=1 WHERE 1=1",
        "UPDATE gmail_sync_cursors SET catchup_complete=0 WHERE committed_history_id>0",
    ):
        with pytest.raises(StoreAccessError):
            ingestor.write("gmail_sync_cursors", statement, ())
    row = ingestor.one("SELECT committed_history_id AS c,fence AS f FROM gmail_sync_cursors")
    assert (row["c"], row["f"]) == (50, 2)  # type: ignore[index]


def test_cursor_identity_cannot_be_rewritten_into_another_selection(db: _Handles) -> None:
    _registered(db.access("administration"))
    ingestor = db.access("ingestor")
    ingestor.write("gmail_sync_cursors", _CURSOR, (NOW, NOW))
    for statement in (
        "UPDATE gmail_sync_cursors SET filter_revision=2 WHERE 1=1",
        "UPDATE gmail_sync_cursors SET account_id='acct-2' WHERE 1=1",
        "UPDATE gmail_sync_cursors SET role='write' WHERE 1=1",
        "DELETE FROM gmail_sync_cursors WHERE 1=1",
    ):
        with pytest.raises(StoreAccessError):
            ingestor.write("gmail_sync_cursors", statement, ())


def test_lease_fence_must_advance(db: _Handles) -> None:
    _registered(db.access("administration"))
    ingestor = db.access("ingestor")
    ingestor.write(
        "gmail_worker_leases",
        "INSERT INTO gmail_worker_leases VALUES('conn-1','poll','reader-a',1,?,?)",
        (NOW, LATER),
    )
    with pytest.raises(StoreAccessError):
        ingestor.write(
            "gmail_worker_leases", "UPDATE gmail_worker_leases SET fence=1 WHERE 1=1", ()
        )
    with pytest.raises(StoreAccessError):
        ingestor.write(
            "gmail_worker_leases", "UPDATE gmail_worker_leases SET job_key='x' WHERE 1=1", ()
        )
    ingestor.write(
        "gmail_worker_leases",
        "UPDATE gmail_worker_leases SET fence=2,owner='reader-b',expires_at=? WHERE 1=1",
        (LATER,),
    )
    assert ingestor.one("SELECT owner AS o,fence AS f FROM gmail_worker_leases")["f"] == 2  # type: ignore[index]


def test_capability_rows_are_owner_role_scoped_and_honest(db: _Handles) -> None:
    _registered(db.access("administration"))
    read_worker = db.access("read_worker")
    read_worker.write(
        "gmail_capabilities",
        "INSERT INTO gmail_capabilities VALUES('conn-1','acct-1','read','read',1,'supported',"
        "NULL,1,?)",
        (NOW,),
    )
    with pytest.raises(StoreAccessError):
        read_worker.write(
            "gmail_capabilities",
            "UPDATE gmail_capabilities SET owner_role='write' WHERE 1=1",
            (),
        )
    with pytest.raises(StoreAccessError):
        read_worker.write(
            "gmail_capabilities",
            "INSERT INTO gmail_capabilities VALUES('conn-1','acct-1','send','read',1,"
            "'supported',NULL,1,?)",
            (NOW,),
        )
    with pytest.raises(StoreAccessError):
        read_worker.write(
            "gmail_capabilities",
            "INSERT INTO gmail_capabilities VALUES('conn-1','acct-1','archive','read',1,"
            "'supported',NULL,1,?)",
            (NOW,),
        )


def test_write_only_capabilities_and_no_effect_proof_rules(db: _Handles) -> None:
    _registered(db.access("administration"))
    executor = db.access("executor")
    with pytest.raises(StoreAccessError):
        executor.write(
            "gmail_capabilities",
            "INSERT INTO gmail_capabilities VALUES('conn-1','acct-1','read','write',1,"
            "'supported',NULL,1,?)",
            (NOW,),
        )
    executor.write(
        "gmail_capabilities",
        "INSERT INTO gmail_capabilities VALUES('conn-1','acct-1','archive','write',0,"
        "'unsupported','conditional_write_absent',1,?)",
        (NOW,),
    )
    with pytest.raises(StoreAccessError):
        executor.write(
            "gmail_capabilities",
            "INSERT INTO gmail_capabilities VALUES('conn-1','acct-1','send','write',0,"
            "'unsupported',NULL,1,?)",
            (NOW,),
        )

    def receipt(operation: str, outcome: str, proof: int) -> str:
        return (
            "INSERT INTO gmail_effect_receipts VALUES(?,'conn-1','acct-1','act-1','execute',?,"
            "'sha256:native',10,'sha256:h',NULL,?,?)",
            (operation, outcome, proof, NOW),
        )

    with pytest.raises(StoreAccessError):
        executor.write("gmail_effect_receipts", *receipt("op-confirmed-proof", "confirmed", 1))
    with pytest.raises(StoreAccessError):
        executor.write("gmail_effect_receipts", *receipt("op-unknown-proof", "unknown", 1))
    with pytest.raises(StoreAccessError):
        executor.write("gmail_effect_receipts", *receipt("op-bad-outcome", "recalled", 0))
    executor.write("gmail_effect_receipts", *receipt("op-failed-proof", "failed", 1))
    executor.write("gmail_effect_receipts", *receipt("op-confirmed", "confirmed", 0))
    assert executor.one("SELECT count(*) AS n FROM gmail_effect_receipts")["n"] == 2  # type: ignore[index]


def test_credential_generation_never_regresses_and_holds_no_token(db: _Handles) -> None:
    _registered(db.access("administration"))
    executor = db.access("executor")
    executor.write(
        "gmail_credential_state",
        "INSERT INTO gmail_credential_state (credential_ref,connection_id,account_id,role,"
        "generation,granted_scopes,refresh_updated_at) VALUES('cred-ref-1','conn-1','acct-1',"
        "'write',1,'[\"gmail.send\"]',?)",
        (NOW,),
    )
    with pytest.raises(StoreAccessError):
        executor.write(
            "gmail_credential_state", "UPDATE gmail_credential_state SET generation=0 WHERE 1=1", ()
        )
    with pytest.raises(StoreAccessError):
        executor.write(
            "gmail_credential_state",
            "UPDATE gmail_credential_state SET credential_ref='other' WHERE 1=1",
            (),
        )
    executor.write(
        "gmail_credential_state",
        "UPDATE gmail_credential_state SET generation=2,refresh_updated_at=? WHERE 1=1",
        (LATER,),
    )
    assert executor.one("SELECT generation AS g FROM gmail_credential_state")["g"] == 2  # type: ignore[index]
    columns = {
        row[1]
        for row in executor.conn.execute("PRAGMA table_info(gmail_credential_state)").fetchall()
    }
    assert not {"token", "access_token", "refresh_token", "code"} & columns


def test_connection_identity_is_frozen_and_state_moves(db: _Handles) -> None:
    admin = db.access("administration")
    _registered(admin)
    for statement in (
        "UPDATE gmail_connections SET account_id='acct-2' WHERE 1=1",
        "UPDATE gmail_connections SET credential_ref='other' WHERE 1=1",
        "UPDATE gmail_connections SET selection_revision=0 WHERE 1=1",
        "UPDATE gmail_connections SET state='NOT_A_STATE' WHERE 1=1",
        "DELETE FROM gmail_connections WHERE 1=1",
    ):
        with pytest.raises(StoreAccessError):
            admin.write("gmail_connections", statement, ())
    admin.write(
        "gmail_connections", "UPDATE gmail_connections SET state='PAUSED',updated_at=?", (LATER,)
    )
    assert admin.one("SELECT state AS s FROM gmail_connections")["s"] == "PAUSED"  # type: ignore[index]


def test_tombstone_carries_no_payload_and_history_events_are_typed(db: _Handles) -> None:
    _registered(db.access("administration"))
    ingestor = db.access("ingestor")
    with pytest.raises(StoreAccessError):
        ingestor.write(
            "gmail_observations",
            "INSERT INTO gmail_observations (connection_id,account_id,native_message_id,"
            "history_id,event_type,content_hash,version_hash,observed_at,occurrence_provenance,"
            "label_ids,payload_ref) VALUES('conn-1','acct-1','msg-9',11,'message_deleted',"
            "'sha256:cc','sha256:dd',?,'observed_locally','[]','data/private/leak')",
            (NOW,),
        )
    ingestor.write(
        "gmail_observations",
        "INSERT INTO gmail_observations (connection_id,account_id,native_message_id,history_id,"
        "event_type,content_hash,version_hash,observed_at,occurrence_provenance,label_ids)"
        " VALUES('conn-1','acct-1','msg-9',11,'message_deleted','sha256:cc','sha256:dd',?,"
        "'observed_locally','[]')",
        (NOW,),
    )
    with pytest.raises(StoreAccessError):
        ingestor.write(
            "gmail_history_events",
            "INSERT INTO gmail_history_events VALUES('conn-1','acct-1',12,'msg-9','INBOX',"
            "'actorUnknown',?)",
            (NOW,),
        )


def test_engine_database_is_never_touched_by_the_connector_store(tmp_path: Path) -> None:
    from probation.db.connection import apply_schema, get_connection

    engine = get_connection(tmp_path / "engine.db")
    apply_schema(engine)
    engine_tables = {
        row[0] for row in engine.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    engine.close()

    path = tmp_path / "gmail_metadata.db"
    conn = open_store(path)
    migrate_store(conn)
    assert store_is_current(conn) is True
    store_tables = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()
    assert not store_tables & engine_tables
    assert "gmail_observations" in store_tables
