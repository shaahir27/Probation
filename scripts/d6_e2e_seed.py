"""Seed one isolated synthetic D6 workspace: items, connector capabilities, action lifecycle.

Everything here is generated. Nothing is read from a real account. The counts are
driven by PROBATION_D6_E2E_ITEMS so each Playwright project gets exactly the state its
specs assert on:

  1 -> only the original ASK item (the private-workspace journey)
  2 -> the original ASK item plus a second one (the durable-mutation journey)
  3+ -> both plus a third ASK item, a SHADOW item and the action lifecycle fixtures

The row shapes are the ones the engine itself writes: proposals joined to their own
situation and raw item, an ACTIVE connection row in the private store, and committed
write capabilities so the server derives its own supported actions.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

WORKTREE = Path(__file__).resolve().parents[1]
CONNECTION_ID = "d6-e2e-connection"
OWNER_ID = "d6-e2e-owner"
ACCOUNT_ID = "e2e-owner@example.test"
SOURCE_ID = f"gmail-source:{CONNECTION_ID}"
NOW = "2026-10-01T01:00:00Z"
FUTURE = "2027-01-01T00:00:00Z"
PAST_DEADLINE = "2026-10-02T00:00:00Z"
CITATION_URL = "https://www.example.org/renewal-notice"

# The first item keeps the fixture summary the private-workspace journey asserts on.
EXTRA_ASKS = (
    ("e2e-ask-2", "Second synthetic notice: the renewal window closed.", "<ask2@test.local>"),
    ("e2e-ask-3", "Third synthetic notice: the club is asking for a decision.", "<ask3@test.local>"),
)
SHADOW_ITEM = ("e2e-shadow-1", "Synthetic notice Probation is only observing.", "<shadow@test.local>")
VERIFIED_ITEM = ("e2e-verified-1", "Synthetic notice with a cited web check.", "<verified@test.local>")

FIELDS = {"title": "Renewal notice", "deadline_date": "2026-11-05"}
CITATIONS = [{"title": "Synthetic renewal page", "url": CITATION_URL}]
REASONS = ["deadline_in_subject", "recurring_sender"]


def _card(availability: str, fee_status: str, fields: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "version": "d5.v1",
        "availability": availability,
        "fields": fields or {},
        "fee_status": fee_status,
        "citations": CITATIONS if (fields or fee_status != "unknown") else [],
        "reasons": REASONS,
        "fetched_at": "2026-09-30T09:00:00Z",
        "ttl_until": FUTURE,
    }


def _web(card: dict[str, Any] | None) -> str:
    payload: dict[str, Any] = {
        "status": "not_checked" if card is None else card["availability"],
        "cap": 3,
        "source_ids": [],
        "decision_cutoff": "2026-10-01T00:30:00Z",
    }
    if card is not None:
        payload["verification_card"] = card
        payload["source_ids"] = [CITATION_URL]
    return json.dumps(payload)


EXPLANATION = json.dumps(
    {
        "top_clues": ["The sender recurs in your own history", "The subject names a deadline"],
        "summary_reason": "You archived a very similar notice from this sender last time.",
    }
)


def _proposal(
    conn,  # type: ignore[no-untyped-def]
    *,
    proposal_id: str,
    situation_id: str,
    raw_id: str,
    source_ref: str,
    summary: str,
    gate: str,
    action: str = "ARCHIVE",
    web_json: str = "{}",
    ledger_seq: int = 1,
) -> None:
    payload = {
        "message_id": source_ref,
        "thread_id": f"thread-{proposal_id}",
        "from": "sender@test.local",
        "subject": "Notice",
        "body": summary,
    }
    conn.execute(
        """INSERT INTO raw_items (id,source_id,pack,item_kind,source_ref,occurred_at,known_at,
        payload_json,content_hash) VALUES (?,?,'mail','mail_in',?,
        '2026-10-01T00:00:00Z','2026-10-01T00:00:00Z',?,?)""",
        (raw_id, SOURCE_ID, source_ref, json.dumps(payload), f"hash-{proposal_id}"),
    )
    conn.execute(
        """INSERT INTO situations (id,raw_item_id,pack,family,occurred_at,sender_key,content_hash,
        redacted_text,created_at) VALUES (?,?,'mail','email_action','2026-10-01T00:00:00Z',?,?,?,
        '2026-10-01T00:00:00Z')""",
        (situation_id, raw_id, "sender@test.local", f"hash-{proposal_id}", summary),
    )
    conn.execute(
        """INSERT INTO proposals (id,situation_id,family,class_key,action,probs_json,p_max,novelty,
        novel,licence_level,cap,gate,reasons_json,policy_version,features_hash,audit_holdout,
        proposed_at,ledger_seq,params_json,explanation_json,web_json)
        VALUES (?,?,'email_action','mail|fyi|frequent',?,?,1,0,0,2,3,?,
        '[]','policy','features',0,?,?, '{}',?,?)""",
        (proposal_id, situation_id, action, json.dumps({action: 1}), gate, NOW, ledger_seq, EXPLANATION, web_json),
    )
    conn.commit()


def _binding_json(conn, proposal_id: str, action: str) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    """A real ApprovalBinding for the seeded item, hashed exactly like the Executor would."""
    from probation.core.hashing import canonical_json
    from probation.core.lifecycle import ApprovalBinding, binding_hash
    import hashlib

    row = conn.execute(
        """SELECT r.source_ref,r.payload_json,r.content_hash FROM proposals p
        JOIN situations s ON s.id=p.situation_id JOIN raw_items r ON r.id=s.raw_item_id WHERE p.id=?""",
        (proposal_id,),
    ).fetchone()
    source_hash = hashlib.sha256(
        canonical_json(
            {
                "payload": json.loads(row["payload_json"]),
                "source_ref": row["source_ref"],
                "content_hash": row["content_hash"],
            }
        ).encode()
    ).hexdigest()
    binding = ApprovalBinding(
        owner_id=OWNER_ID,
        connection_id=CONNECTION_ID,
        account_id=ACCOUNT_ID,
        resource_id=str(row["source_ref"]),
        source_hash=source_hash,
        action=action,
        restriction_revision="0",
        params={"proposal_id": proposal_id, "review_response": "accept", "message_id": row["source_ref"]},
        pack="mail",
    )
    return binding.model_dump_json(), binding_hash(binding)


def _action(
    conn,  # type: ignore[no-untyped-def]
    *,
    action_id: str,
    proposal_id: str,
    status: str,
    recallable: int,
    undo_deadline: str | None,
    hold_until: str | None = None,
    attempt_state: str | None = None,
) -> None:
    binding_json, hash_value = _binding_json(conn, proposal_id, "ARCHIVE")
    conn.execute(
        """INSERT INTO actions (id,proposal_id,pack,type,params_json,level_required,recallable,status,
        hold_until,undo_json,created_at,updated_at,executed_at,authority_kind,approval_response_id,
        binding_json,binding_hash,undo_deadline) VALUES (?,?,'mail','ARCHIVE','{}',2,?,?,?,NULL,
        '2026-10-01T02:00:00Z','2026-10-01T02:00:00Z',?,'explicit_user',NULL,?,?,?)""",
        (
            action_id,
            proposal_id,
            recallable,
            status,
            hold_until,
            "2026-10-01T02:00:00Z" if status in {"DONE", "FAILED"} else None,
            binding_json,
            hash_value,
            undo_deadline,
        ),
    )
    if attempt_state is not None:
        conn.execute(
            """INSERT INTO execution_attempts (id,action_id,operation,binding_hash,state,claim_owner,
            fence,lease_until,before_json,created_at,updated_at) VALUES (?,?, 'execute',?,?,
            'synthetic-executor',1,?, '{}', '2026-10-01T02:00:00Z','2026-10-01T02:00:00Z')""",
            (
                f"attempt-{action_id}",
                action_id,
                hash_value,
                attempt_state,
                FUTURE,
            ),
        )
    conn.commit()


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    temp_root = Path(sys.argv[1]).resolve()
    items = int(os.environ.get("PROBATION_D6_E2E_ITEMS", "1") or "1")
    os.environ["PROBATION_WORKER_ROLE"] = "api"
    sys.path.insert(0, str(WORKTREE / "backend" / "src"))
    sys.path.insert(0, str(WORKTREE / "backend" / "tests" / "unit"))

    from probation.db.gmail_store import ConnectorAccess, migrate_store, open_store
    from wp6_mail_fixture import NOW as FIXTURE_NOW, seed

    conn, _world = seed(temp_root, action="ARCHIVE")
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("UPDATE raw_items SET source_id = ? WHERE source_id = 'source'", (SOURCE_ID,))
    conn.execute("UPDATE sources SET id = ? WHERE id = 'source'", (SOURCE_ID,))
    conn.execute("UPDATE situations SET redacted_text = ? WHERE id = 'sit'", ("Some information.",))
    # The engine asked the owner here, so Home may count it as needing a decision.
    conn.execute("UPDATE proposals SET gate='ASK', web_json=?, explanation_json=? WHERE id='proposal'", (_web(None), EXPLANATION))
    conn.commit()

    for index, (proposal_id, summary, source_ref) in enumerate(EXTRA_ASKS[: max(0, items - 1)]):
        _proposal(
            conn,
            proposal_id=proposal_id,
            situation_id=f"sit-{proposal_id}",
            raw_id=f"raw-{proposal_id}",
            source_ref=source_ref,
            summary=summary,
            gate="ASK",
            web_json=_web(_card("partial", "unknown", FIELDS))
            if proposal_id == "e2e-ask-2"
            else _web(_card("not_checked", "unknown", None)),
            ledger_seq=index + 2,
        )
    for gate_group, count in (("shadow", items), ("verified", items)):
        if count < 3:
            continue
        if gate_group == "shadow":
            proposal_id, summary, source_ref = SHADOW_ITEM
            gate, web_json, seq = "SHADOW", _web(None), 8
        else:
            proposal_id, summary, source_ref = VERIFIED_ITEM
            gate, web_json, seq = "ASK", _web(_card("validated", "explicit_free", FIELDS)), 9
        _proposal(
            conn,
            proposal_id=proposal_id,
            situation_id=f"sit-{proposal_id}",
            raw_id=f"raw-{proposal_id}",
            source_ref=source_ref,
            summary=summary,
            gate=gate,
            web_json=web_json,
            ledger_seq=seq,
        )

    # The lifecycle states the Actions screen must render truthfully.
    _action(
        conn,
        action_id="e2e-action-held",
        proposal_id="e2e-ask-2" if items > 1 else "proposal",
        status="HELD",
        recallable=1,
        undo_deadline=FUTURE,
        hold_until=FUTURE,
    )
    _action(
        conn,
        action_id="e2e-action-expired",
        proposal_id="e2e-ask-3" if items > 2 else "proposal",
        status="DONE",
        recallable=1,
        undo_deadline=PAST_DEADLINE,
    )
    if items > 2:
        # The unconfirmed and failed effects live on their own items, so each Actions
        # row stays addressable by the email it belongs to.
        _action(
            conn,
            action_id="e2e-action-unknown",
            proposal_id="e2e-verified-1",
            status="DONE",
            recallable=0,
            undo_deadline=None,
            attempt_state="unknown",
        )
    if items > 2:
        # A failed effect on its own item, so the unconfirmed row stays unambiguous.
        _action(
            conn,
            action_id="e2e-action-failed",
            proposal_id="e2e-shadow-1",
            status="FAILED",
            recallable=0,
            undo_deadline=None,
            attempt_state="failed",
        )
    conn.close()

    store_path = Path(os.environ["PROBATION_GMAIL_STORE"])
    boot = open_store(store_path)
    migrate_store(boot)
    boot.close()
    access = ConnectorAccess(open_store(store_path), "administration")
    access.write(
        "gmail_connections",
        """INSERT INTO gmail_connections
        (connection_id,account_id,owner_id,state,selection_revision,label_ids,credential_ref,
         granted_scopes,created_at,updated_at)
        VALUES (?,? ,?,'ACTIVE',1,'[]','synthetic-only','[]',?,?)""",
        (
            CONNECTION_ID,
            ACCOUNT_ID,
            OWNER_ID,
            FIXTURE_NOW,
            FIXTURE_NOW,
        ),
    )
    # Committed write capabilities are the only reason the server offers Archive/Trash
    # as supported actions; the UI never decides that for itself. Capability rows are
    # committed by the executor authority, exactly as the real connector does.
    capability_access = ConnectorAccess(open_store(store_path), "executor")
    for name in ("archive", "trash"):
        capability_access.write(
            "gmail_capabilities",
            """INSERT INTO gmail_capabilities
            (connection_id,account_id,name,owner_role,supported,evidence,reason,manifest_version,verified_at)
            VALUES (?,?,?,'write',1,'supported',NULL,1,?)""",
            (CONNECTION_ID, ACCOUNT_ID, name, FIXTURE_NOW),
        )
    capability_access.write(
        "gmail_capabilities",
        """INSERT INTO gmail_capabilities
        (connection_id,account_id,name,owner_role,supported,evidence,reason,manifest_version,verified_at)
        VALUES (?,?,'read','read',1,'supported',NULL,1,?)""",
        (CONNECTION_ID, ACCOUNT_ID, FIXTURE_NOW),
    )
    capability_access.conn.close()
    access.conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
