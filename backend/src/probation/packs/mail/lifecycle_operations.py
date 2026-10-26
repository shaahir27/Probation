"""Pure construction of precise mail effects and inverse label operations."""

import hashlib
from dataclasses import asdict
from typing import Any

from probation.core.hashing import canonical_json
from probation.core.types import Action
from probation.packs.mail.lifecycle_io import MailConflict, MailSnapshot


def payload_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def prepare_effect(action: Action, snapshot: MailSnapshot, now: str) -> dict[str, Any]:
    """Persist this entire description before marking dispatch."""
    undo: dict[str, Any] | None = None
    if action.type in {"ARCHIVE", "TRASH"}:
        added = ["TRASH"] if action.type == "TRASH" and "TRASH" not in snapshot.labels else []
        removed = ["INBOX"] if action.type == "ARCHIVE" and "INBOX" in snapshot.labels else []
        payload: dict[str, Any] = {
            "type": "labels",
            "resource_id": snapshot.resource_id,
            "add_labels": added,
            "remove_labels": removed,
            "performed_at": now,
        }
        undo = {
            "version": "mail-labels-v2",
            "resource_id": snapshot.resource_id,
            "added": added,
            "removed": removed,
            "touched_versions": {
                label: snapshot.label_versions.get(label, 0) + 1 for label in added + removed
            },
            # The provider history point and label baselines the undo equality check was
            # computed from. Kept in the durable proof so it survives the cursor moving on.
            "anchor_history_id": snapshot.message_history_id,
            "before_revision": snapshot.revision,
            "baseline": dict(snapshot.label_versions),
        }
    elif action.type in {"REPLY", "FORWARD"}:
        params = action.params
        required = ("from_addr", "to_addr", "subject", "body")
        if any(not isinstance(params.get(key), str) or not params[key].strip() for key in required):
            raise MailConflict("send_binding_incomplete")
        payload = {
            "type": "send",
            "resource_id": snapshot.resource_id,
            "message": {
                "message_id": f"<{action.id}@probation.local>",
                "thread_id": snapshot.thread_id if action.type == "REPLY" else action.id,
                "from_addr": params["from_addr"],
                "to_addr": params["to_addr"],
                "subject": params["subject"],
                "body": params["body"],
                "sent_at": now,
                "in_reply_to": snapshot.native_message_id if action.type == "REPLY" else None,
            },
        }
    else:
        raise MailConflict("unsupported_mail_action")
    return {
        "snapshot": asdict(snapshot),
        "payload": payload,
        "payload_hash": payload_digest(payload),
        "undo": undo,
    }


def prepare_undo(action: Action, snapshot: MailSnapshot) -> dict[str, Any]:
    undo = action.undo or {}
    if undo.get("version") != "mail-labels-v2" or undo.get("resource_id") != snapshot.resource_id:
        raise MailConflict("undo_provenance_missing")
    added, removed = set(undo["added"]), set(undo["removed"])
    labels = set(snapshot.labels)
    if not added <= labels or removed & labels:
        raise MailConflict("undo_state_conflict")
    expected = undo.get("touched_versions")
    if (
        not isinstance(expected, dict)
        or any(
            snapshot.label_versions.get(label, 0) != version for label, version in expected.items()
        )
        or set(expected) != added | removed
    ):
        raise MailConflict("undo_label_history_conflict")
    payload = {
        "type": "labels",
        "resource_id": snapshot.resource_id,
        "add_labels": sorted(removed),
        "remove_labels": sorted(added),
    }
    return {
        "snapshot": asdict(snapshot),
        "payload": payload,
        "payload_hash": payload_digest(payload),
        "undo": None,
    }
