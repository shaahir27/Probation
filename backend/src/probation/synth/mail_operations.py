"""Persistent synthetic target operations; same capability used by the Executor.

The target journal and its effect share one transaction, independently of engine DB.
"""

import hashlib
import json
import sqlite3
from dataclasses import asdict
from typing import Any

from probation.core.hashing import canonical_json
from probation.packs.mail.lifecycle_io import MailConflict, MailReceipt, MailSnapshot

SCHEMA = """
CREATE TABLE IF NOT EXISTS mail_label_versions (
    message_id TEXT NOT NULL,label TEXT NOT NULL,version INTEGER NOT NULL CHECK(version>=1),
    PRIMARY KEY(message_id,label)
);
CREATE TABLE IF NOT EXISTS mail_operations (
    operation_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL, receipt_json TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS mail_operations_no_update BEFORE UPDATE ON mail_operations
BEGIN SELECT RAISE(ABORT,'mail operation immutable'); END;
CREATE TRIGGER IF NOT EXISTS mail_operations_no_delete BEFORE DELETE ON mail_operations
BEGIN SELECT RAISE(ABORT,'mail operation immutable'); END;
"""


def snapshot(conn: sqlite3.Connection, resource_id: str) -> MailSnapshot:
    row = conn.execute(
        "SELECT * FROM messages WHERE message_id=? OR id=?", (resource_id, resource_id)
    ).fetchone()
    if row is None:
        raise MailConflict("mail_resource_missing")
    state = dict(row)
    labels = tuple(sorted(json.loads(state["labels"])))
    state["labels"] = labels
    versions = {
        str(r["label"]): int(r["version"])
        for r in conn.execute(
            "SELECT label,version FROM mail_label_versions WHERE message_id=?", (row["message_id"],)
        ).fetchall()
    }
    state["label_versions"] = versions
    return MailSnapshot(
        resource_id,
        str(row["message_id"]),
        str(row["thread_id"]),
        labels,
        hashlib.sha256(canonical_json(state).encode()).hexdigest(),
        versions,
    )


def record_label_changes(
    conn: sqlite3.Connection, message_id: str, before: set[str], after: set[str]
) -> None:
    """Track touched labels independently so undo preserves unrelated changes and ABA edits."""
    for label in sorted(before ^ after):
        conn.execute(
            """INSERT INTO mail_label_versions(message_id,label,version) VALUES (?,?,1)
            ON CONFLICT(message_id,label) DO UPDATE SET version=version+1""",
            (message_id, label),
        )


def reconcile(conn: sqlite3.Connection, operation_id: str, payload_hash: str) -> MailReceipt:
    row = conn.execute(
        "SELECT payload_hash,receipt_json FROM mail_operations WHERE operation_id=?",
        (operation_id,),
    ).fetchone()
    if row is None:
        return MailReceipt("unknown", safe_code="receipt_not_found")
    if row["payload_hash"] != payload_hash:
        raise MailConflict("operation_payload_conflict")
    return MailReceipt(**json.loads(row["receipt_json"]))


def apply(
    conn: sqlite3.Connection,
    operation_id: str,
    payload_hash: str,
    payload: dict[str, Any],
    expected_revision: str,
) -> MailReceipt:
    if conn.in_transaction:
        raise ValueError("Target operation requires a clean transaction")
    if hashlib.sha256(canonical_json(payload).encode()).hexdigest() != payload_hash:
        raise MailConflict("operation_payload_hash_mismatch")
    conn.execute("BEGIN IMMEDIATE")
    try:
        prior = conn.execute(
            "SELECT * FROM mail_operations WHERE operation_id=?", (operation_id,)
        ).fetchone()
        if prior is not None:
            if prior["payload_hash"] != payload_hash or prior["payload_json"] != canonical_json(
                payload
            ):
                raise MailConflict("operation_payload_conflict")
            result = reconcile(conn, operation_id, payload_hash)
            conn.commit()
            return result
        before = snapshot(conn, str(payload["resource_id"]))
        if before.revision != expected_revision:
            result = MailReceipt(
                "failed", safe_code="mail_revision_conflict", confirmed_no_effect=True
            )
        elif payload["type"] == "labels":
            labels = (set(before.labels) | set(payload["add_labels"])) - set(
                payload["remove_labels"]
            )
            conn.execute(
                "UPDATE messages SET labels=? WHERE message_id=?",
                (canonical_json(sorted(labels)), before.native_message_id),
            )
            record_label_changes(conn, before.native_message_id, set(before.labels), labels)
            after = snapshot(conn, before.resource_id)
            result = MailReceipt(
                "confirmed",
                before.native_message_id,
                after_state={
                    "labels": list(after.labels),
                    "revision": after.revision,
                    "executed_at": payload.get("performed_at"),
                },
            )
        elif payload["type"] == "send":
            values = payload["message"]
            conn.execute(
                """INSERT INTO messages (id,message_id,thread_id,from_addr,to_addr,
                subject,body,labels,received_at,in_reply_to,has_attachment)
                VALUES (?,?,?,?,?,?,?,'["SENT"]',?,?,0)""",
                (
                    operation_id,
                    values["message_id"],
                    values["thread_id"],
                    values["from_addr"],
                    values["to_addr"],
                    values["subject"],
                    values["body"],
                    values["sent_at"],
                    values.get("in_reply_to"),
                ),
            )
            result = MailReceipt(
                "confirmed",
                str(values["message_id"]),
                after_state={"executed_at": values["sent_at"]},
            )
        else:
            raise MailConflict("unsupported_mail_operation")
        conn.execute(
            "INSERT INTO mail_operations VALUES (?,?,?,?)",
            (operation_id, payload_hash, canonical_json(payload), canonical_json(asdict(result))),
        )
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise
