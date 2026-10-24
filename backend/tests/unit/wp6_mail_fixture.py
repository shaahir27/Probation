"""Genuine immutable synthetic source/approval fixtures, without account access."""

import json
from pathlib import Path

from probation.core.lifecycle import SourceGrant
from probation.db.connection import apply_schema, get_connection
from probation.db.ledger import append_ledger
from probation.llm.draft_validation import body_hash
from probation.synth.world import SimWorld

NOW = "2026-10-01T01:00:00Z"
GRANT = SourceGrant("source", "connection", "account", "owner@test.local")


def seed(
    tmp_path: Path,
    action: str = "ARCHIVE",
    labels: list[str] | None = None,
    *,
    autonomous: bool = False,
    audit_holdout: bool = False,
):  # type: ignore[no-untyped-def]
    conn = get_connection(tmp_path / "engine.db")
    apply_schema(conn)
    payload = {
        "message_id": "<m@test.local>",
        "thread_id": "thread",
        "from": "sender@test.local",
        "subject": "Notice",
        "body": "Some information.",
    }
    conn.execute("INSERT INTO sources VALUES ('source','mail','mbox','fixture',?)", (NOW,))
    conn.execute(
        """INSERT INTO raw_items (id,source_id,pack,item_kind,source_ref,occurred_at,
        known_at,payload_json,content_hash) VALUES ('raw','source','mail','mail_in','<m@test.local>',
        '2026-10-01T00:00:00Z','2026-10-01T00:00:00Z',?,'source-hash')""",
        (json.dumps(payload),),
    )
    conn.execute("""INSERT INTO situations (id,raw_item_id,pack,family,occurred_at,content_hash,created_at)
        VALUES ('sit','raw','mail','email_action','2026-10-01T00:00:00Z','source-hash','2026-10-01T00:00:00Z')""")
    reply_body = "Thank you for the information."
    params = (
        {
            "draft_proposal_id": "proposal",
            "to_addr": "sender@test.local",
            "draft_body_hash": body_hash(reply_body),
        }
        if action == "REPLY"
        else {}
    )
    gate = (
        ("HOLD_THEN_EXECUTE" if action in {"REPLY", "FORWARD"} else "EXECUTE_UNDO")
        if autonomous
        else "SUGGEST"
    )
    seq = append_ledger(
        conn,
        "proposal",
        "proposal",
        {
            "situation_id": "sit",
            "action": action,
            "class_key": "mail|fyi|frequent",
            "gate": gate,
            "proposed_at": NOW,
        },
        NOW,
    )
    conn.execute(
        """INSERT INTO proposals (id,situation_id,family,class_key,action,probs_json,p_max,
        novelty,novel,licence_level,cap,gate,reasons_json,policy_version,features_hash,audit_holdout,
        proposed_at,ledger_seq,params_json) VALUES ('proposal','sit','email_action','mail|fyi|frequent',?,
        ?,1,0,0,?,3,?,'[]','policy','features',?,?,?,?)""",
        (
            action,
            json.dumps({action: 1}),
            2 if autonomous else 1,
            gate,
            int(audit_holdout),
            NOW,
            seq,
            json.dumps(params),
        ),
    )
    if action == "REPLY":
        conn.execute(
            "INSERT INTO drafts VALUES ('proposal',?,0,1,'fake-writer','v1',?)", (reply_body, NOW)
        )
    conn.commit()
    world = SimWorld(tmp_path / "world.db", user_addresses=[GRANT.from_addr])
    world.add_message(
        "m",
        payload["message_id"],
        "thread",
        payload["from"],
        GRANT.from_addr,
        payload["subject"],
        payload["body"],
        ["INBOX"] if labels is None else labels,
        "2026-10-01T00:00:00Z",
    )
    return conn, world
