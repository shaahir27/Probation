"""Atomic additive migration for versioned durable replay control intents."""

import sqlite3


def migrate_replay_commands(conn: sqlite3.Connection) -> bool:
    """Allow the separate replay command schema while preserving immutable v1 rows."""
    if conn.in_transaction or getattr(conn, "bound_role", None) is not None:
        raise ValueError("Replay migration requires a clean bootstrap connection")
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='command_requests'"
    ).fetchone()
    if row is None:
        return False
    ddl = str(row[0] or "").replace(" ", "").lower()
    if "schema_versionin(1,2)" in ddl:
        return False
    if "schema_version=1" not in ddl:
        raise ValueError("Unrecognized command_requests schema; refusing replay migration")

    conn.execute("PRAGMA foreign_keys=OFF")
    legacy = int(conn.execute("PRAGMA legacy_alter_table").fetchone()[0])
    conn.execute("PRAGMA legacy_alter_table=ON")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DROP TRIGGER IF EXISTS d3_commands_immutable_update")
        conn.execute("DROP TRIGGER IF EXISTS d3_commands_immutable_delete")
        conn.execute("ALTER TABLE command_requests RENAME TO command_requests_d6_old")
        conn.execute(
            """CREATE TABLE command_requests(
                id TEXT PRIMARY KEY,
                schema_version INTEGER NOT NULL CHECK(schema_version IN(1,2)),
                owner_id TEXT NOT NULL,
                request_key TEXT NOT NULL,
                type TEXT NOT NULL CHECK(
                    (schema_version=1 AND type IN('pause','resume','revoke')) OR
                    (schema_version=2 AND type IN('replay_start','replay_pause','replay_speed'))
                ),
                scope_json TEXT NOT NULL CHECK(json_valid(scope_json)),
                payload_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(owner_id,request_key)
            )"""
        )
        conn.execute(
            """INSERT INTO command_requests
            (id,schema_version,owner_id,request_key,type,scope_json,payload_hash,created_at)
            SELECT id,schema_version,owner_id,request_key,type,scope_json,payload_hash,created_at
            FROM command_requests_d6_old"""
        )
        conn.execute("DROP TABLE command_requests_d6_old")
        conn.execute(
            "CREATE TRIGGER d3_commands_immutable_update BEFORE UPDATE ON command_requests "
            "BEGIN SELECT RAISE(ABORT,'immutable command'); END"
        )
        conn.execute(
            "CREATE TRIGGER d3_commands_immutable_delete BEFORE DELETE ON command_requests "
            "BEGIN SELECT RAISE(ABORT,'immutable command'); END"
        )
        refs = {
            str(item[2])
            for item in conn.execute("PRAGMA foreign_key_list(command_receipts)").fetchall()
            if item[3] == "command_id"
        }
        if refs != {"command_requests"}:
            raise ValueError("Replay migration changed command receipt foreign keys")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("Replay migration would break foreign keys")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute(f"PRAGMA legacy_alter_table={legacy}")
        conn.execute("PRAGMA foreign_keys=ON")
    return True
