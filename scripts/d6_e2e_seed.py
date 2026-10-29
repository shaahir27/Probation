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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

WORKTREE = Path(__file__).resolve().parents[1]
CONNECTION_ID = "d6-e2e-connection"
ACCOUNT_ID = "e2e-owner@example.test"
SOURCE_ID = f"gmail-source:{CONNECTION_ID}"
NOW = "2026-10-01T01:00:00Z"
FUTURE = "2027-01-01T00:00:00Z"
PAST_DEADLINE = "2026-10-02T00:00:00Z"
CITATION_URL = "https://www.example.org/renewal-notice"

# The first item keeps the fixture summary the private-workspace journey asserts on.
EXTRA_ASKS = (
    (
        "e2e-ask-2",
        (
            "Subject: Your renewal window closed on 30 September\n\n"
            "Hello,\n\n"
            "Our records show that the renewal for your club membership closed on 30 September.\n\n"
            "If you still want the current rate, reply before Friday and we will reopen the order. "
            "Nothing has been charged on your account.\n\n"
            "— Membership desk"
        ),
        "<ask2@test.local>",
    ),
    (
        "e2e-ask-3",
        (
            "Subject: Committee vote on the autumn schedule\n\n"
            "Hi,\n\n"
            "We need a decision on the autumn schedule before the room booking lapses on Monday.\n\n"
            "The proposal is to move the Thursday session to 19:00 and keep the Saturday one "
            "unchanged. If you do not reply, we will assume you are abstaining and book the "
            "original slot.\n\n"
            "— Scheduling"
        ),
        "<ask3@test.local>",
    ),
)
SHADOW_ITEM = (
    "e2e-shadow-1",
    (
        "Subject: Newsletter 42 — what changed this month\n\n"
        "This month: a new scheduling rule, two bug fixes, and a note on the September outage.\n\n"
        "You are receiving this because you subscribed last year. Unsubscribe at any time.\n\n"
        "— The digest"
    ),
    "<shadow@test.local>",
)
VERIFIED_ITEM = (
    "e2e-verified-1",
    (
        "Subject: Renewal notice — payment due 5 November\n\n"
        "Hello,\n\n"
        "This is a reminder that your subscription renews on 5 November. The amount is unchanged "
        "from last year and no action is needed if you have already paid.\n\n"
        "The fee schedule is published on our site.\n\n"
        "— Billing"
    ),
    "<verified@test.local>",
)

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
        "provenance": {"synthetic": True, "source": "demo_seed"},
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
        "similar_cases": [
            {
                "situation_id": "sit-lic-0",
                "similarity": 0.94,
                "action_taken": "ARCHIVE",
                "summary": "Subject: Weekly club notice\n\nHello,\n\nNo action is needed this week.",
            },
            {
                "situation_id": "sit-grad-0",
                "similarity": 0.91,
                "action_taken": "ARCHIVE",
                "summary": "Subject: Monthly statement\n\nHello,\n\nYour statement is ready.",
            },
            {
                "situation_id": "sit-obs-0",
                "similarity": 0.88,
                "action_taken": "LEAVE",
                "summary": "Subject: Weekly digest\n\nThis week's digest is below.",
            },
        ],
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


def _owner_id() -> str:
    """The one owner this workspace serves, read from trusted settings."""
    from probation.config import settings

    return settings.probation_gmail_owner_id


def _binding_json(conn, proposal_id: str, action: str) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    """A real ApprovalBinding for the seeded item, hashed exactly like the Executor would."""
    import hashlib

    from probation.core.hashing import canonical_json
    from probation.core.lifecycle import ApprovalBinding, binding_hash

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
        owner_id=_owner_id(),
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


LICENCE_CLASS_KEY = "mail|fyi|frequent"
LICENCE_GRADIENT_CLASS_KEY = "mail|fyi|known"
LICENCE_ACTION = "ARCHIVE"
LICENCE_HISTORY = 72
LICENCE_GRADIENT = 27
OBSERVED_CLASS_KEY = "mail|newsletter|known"
OBSERVED_HISTORY = 57
WATCH_CLASS_KEY = "mail|request|known"
WATCH_HISTORY = 12
LICENCE_BASE = datetime(2026, 10, 20, 10, 0, 0, tzinfo=UTC)
EXAM_RUN_ID = "exam-synthetic-demo-v1"


def _append_licence_history(
    conn,  # type: ignore[no-untyped-def]
    *,
    class_key: str,
    action: str,
    clue: str,
    count: int,
    base: datetime,
    prefix: str,
    sender: str,
    subject: str,
    body: str,
) -> list[str]:
    """Write one synthetic decision history the Resolver itself would write."""
    from probation.db.ledger import append_ledger
    from probation.llm.feature_identity import semantic_feature_version

    redacted = f"Subject: {subject}\n\n{body}"
    situation_ids: list[str] = []
    for index in range(count):
        proposed = base + timedelta(minutes=index)
        known = proposed + timedelta(hours=1)
        proposed_at = proposed.strftime("%Y-%m-%dT%H:%M:%SZ")
        known_at = known.strftime("%Y-%m-%dT%H:%M:%SZ")
        situation_id = f"sit-{prefix}-{index}"
        raw_id = f"raw-{prefix}-{index}"
        proposal_id = f"prop-{prefix}-{index}"
        source_ref = f"<{prefix}-{index}@test.local>"
        content_hash = f"hash-{prefix}-{index}"
        payload = {
            "message_id": source_ref,
            "thread_id": f"thread-{prefix}-{index}",
            "from": sender,
            "subject": subject,
            "body": body,
        }
        conn.execute(
            """INSERT INTO raw_items (id,source_id,pack,item_kind,source_ref,occurred_at,
            known_at,payload_json,content_hash) VALUES (?,?,'mail','mail_in',?,?,?,?,?)""",
            (raw_id, SOURCE_ID, source_ref, proposed_at, proposed_at, json.dumps(payload), content_hash),
        )
        conn.execute(
            """INSERT INTO situations (id,raw_item_id,pack,family,occurred_at,sender_key,
            content_hash,redacted_text,created_at) VALUES (?,?,'mail','email_action',?,?,?,?,?)""",
            (situation_id, raw_id, proposed_at, sender, content_hash, redacted, proposed_at),
        )
        proposal_seq = append_ledger(
            conn,
            "proposal",
            proposal_id,
            {
                "situation_id": situation_id,
                "action": action,
                "class_key": class_key,
                "gate": "SUGGEST",
                "proposed_at": proposed_at,
                "retrospective": False,
                "evidence_context": "prospective_synthetic",
            },
            proposed_at,
        )
        conn.execute(
            """INSERT INTO proposals (id,situation_id,family,class_key,action,probs_json,
            p_max,novelty,novel,licence_level,cap,gate,reasons_json,policy_version,
            features_hash,audit_holdout,proposed_at,ledger_seq,params_json,explanation_json,web_json)
            VALUES (?,?,'email_action',?,?,?,0.99,0,0,2,3,'SUGGEST','[]','synthetic-demo',
            'features',0,?,?,'{}','{}','{}')""",
            (
                proposal_id,
                situation_id,
                class_key,
                action,
                json.dumps({action: 0.99}),
                proposed_at,
                proposal_seq,
            ),
        )
        conn.execute(
            """INSERT INTO features (situation_id,deterministic_json,reader_json,reader_ok,
            featurizer_version,model_id,prompt_version,features_hash,created_at,provenance_json)
            VALUES (?,?,NULL,1,?,NULL,NULL,?,?,NULL)""",
            (
                situation_id,
                json.dumps({"intent": clue}),
                semantic_feature_version(),
                content_hash,
                proposed_at,
            ),
        )
        outcome_seq = append_ledger(
            conn,
            "outcome",
            proposal_id,
            {
                "situation_id": situation_id,
                "proposal_id": proposal_id,
                "observed_action": action,
                "strength": "STRONG",
                "source": "footprint",
                "known_at": known_at,
                "retrospective": False,
                "evidence_context": "prospective_synthetic",
            },
            known_at,
        )
        conn.execute(
            """INSERT INTO outcomes (situation_id,observed_action,strength,source,observed_at,
            known_at,details_json,ledger_seq) VALUES (?,?,'STRONG','footprint',?,?,
            '{"synthetic_demo":true}',?)""",
            (situation_id, action, known_at, known_at, outcome_seq),
        )
        situation_ids.append(situation_id)
    return situation_ids


def _seed_earned_licence(conn) -> None:  # type: ignore[no-untyped-def]
    """A synthetic history the engine can license, plus one labelled exam fixture.

    The outcomes below are written exactly as the Resolver writes them — a committed
    proposal, a matching outcome ledger entry and an ``outcomes`` row — so the licence
    on screen is derived by ``derive_licences``, never copied from a constant. The exam
    row is a fixture because running the board needs a fitted policy and a model edit
    provider; it is marked ``synthetic_demo`` and its details satisfy ``meaningful_exam``.
    """
    from probation.config import settings
    from probation.db.ledger import append_ledger
    from probation.engine.exam_catalogue import operators_for_class
    from probation.llm.feature_identity import semantic_feature_version

    base_ids = _append_licence_history(
        conn,
        class_key=LICENCE_CLASS_KEY,
        action=LICENCE_ACTION,
        clue="fyi",
        count=LICENCE_HISTORY,
        base=LICENCE_BASE,
        prefix="lic",
        sender="club@test.local",
        subject="Weekly club notice",
        body=(
            "Hello,\n\nThis is the weekly club notice. No action is needed; the schedule is "
            "unchanged.\n\n— Club desk"
        ),
    )
    _append_licence_history(
        conn,
        class_key=LICENCE_GRADIENT_CLASS_KEY,
        action=LICENCE_ACTION,
        clue="fyi",
        count=LICENCE_GRADIENT,
        base=LICENCE_BASE + timedelta(hours=3),
        prefix="grad",
        sender="alerts@test.local",
        subject="Monthly statement",
        body="Hello,\n\nYour monthly statement is ready. No action is needed.\n\n— Accounts",
    )
    # A minority action gives the habit miner a real association to find; LEAVE is a noop
    # for licences, so this never changes the earned rows above.
    _append_licence_history(
        conn,
        class_key=OBSERVED_CLASS_KEY,
        action="LEAVE",
        clue="newsletter",
        count=OBSERVED_HISTORY,
        base=LICENCE_BASE + timedelta(hours=6),
        prefix="obs",
        sender="digest@test.local",
        subject="Weekly digest",
        body="Hello,\n\nThis week's digest is below. No action is needed.\n\n— The digest",
    )
    _append_licence_history(
        conn,
        class_key=WATCH_CLASS_KEY,
        action=LICENCE_ACTION,
        clue="request",
        count=WATCH_HISTORY,
        base=LICENCE_BASE + timedelta(hours=9),
        prefix="watch",
        sender="requests@test.local",
        subject="Request from the club",
        body="Hello,\n\nPlease review the attached proposal when you have a moment.\n\n— Club desk",
    )
    # A recorded web check that matches the seeded renewal card, so Access & privacy
    # and the card do not contradict each other. It is explicitly synthetic.
    conn.execute(
        """INSERT INTO tavily_calls (id, endpoint, purpose, query_text, params_json,
        credits, ok, latency_ms, situation_id, created_at, accounting_version,
        account_label, run_id, request_id, attempt_ordinal, state, reserved_units,
        charged_units, run_cap_units, request_hash, usage_provenance, dispatched_at,
        reconciled_at) VALUES
        ('tavily-demo-1','search','find_official','example.org official renewal page',
        '{}',1.0,1,120,'sit','2026-10-01T00:30:00Z',1,
        'demo','demo-run-1','demo-request-1',1,'reserved',1000,0,800000,
        'demo-request-hash',NULL,NULL,NULL)"""
    )
    conn.execute(
        """UPDATE tavily_calls SET state='dispatched', dispatched_at='2026-10-01T00:30:00Z'
        WHERE id='tavily-demo-1'"""
    )
    conn.execute(
        """UPDATE tavily_calls SET state='reconciled', charged_units=1000,
        usage_provenance='provider', reconciled_at='2026-10-01T00:30:01Z'
        WHERE id='tavily-demo-1'"""
    )
    conn.execute(
        """INSERT INTO web_facts (entity_key,status,facts_json,sources_json,origin,
        fetched_at,ttl_until) VALUES
        ('example.org','confirmed_official','{"domain_in_results":true}',
        '["https://www.example.org/renewal-notice"]','tavily',
        '2026-10-01T00:30:00Z','2027-01-01T00:00:00Z')"""
    )
    from probation.engine.habits import mine_habits

    mine_habits(conn, as_of="2026-10-29T12:00:00Z")

    operators = operators_for_class(LICENCE_CLASS_KEY)
    started_at = "2026-10-20T12:00:00Z"
    finished_at = "2026-10-20T12:10:00Z"
    exam_bases = base_ids[:20]
    details = {
        "schema": "wp5-exam-details-v1",
        "synthetic_demo": True,
        "reason": "synthetic_demo_fixture",
        "snapshot_version": "wp5-frozen-v1",
        "snapshot": {
            "policy_digest": "synthetic-demo-policy-digest",
            "history_digest": "synthetic-demo-history-digest",
            "feature_version": semantic_feature_version(),
            "configured_models": [settings.model_reader, settings.model_exam_edits],
            "model_cutoff": "2026-10-13T12:00:00Z",
            "history_cutoff": started_at,
        },
        "required_operators": [op.name for op in operators],
        "operator_coverage": {op.name: len(exam_bases) for op in operators},
        "base_ids": exam_bases,
        "valid_base_cases": len(exam_bases),
        "pipeline_failures": 0,
        "missing_operators": [],
    }
    conn.execute(
        """INSERT INTO exam_runs (id,class_key,action,level_tested,started_at,finished_at,
        n_cases,invariance_flip_rate,directional_violations_critical,
        directional_violation_rate_other,passed,edit_model_id,details_json)
        VALUES (?,?,?,2,?,?,?,0.0,0,0.0,1,?,?)""",
        (
            EXAM_RUN_ID,
            LICENCE_CLASS_KEY,
            LICENCE_ACTION,
            started_at,
            finished_at,
            len(exam_bases),
            settings.model_exam_edits,
            json.dumps(details),
        ),
    )
    for base_index, base_id in enumerate(exam_bases):
        for op_index, op in enumerate(operators):
            conn.execute(
                """INSERT INTO exam_cases (id,exam_run_id,base_situation_id,operator,
                expectation,edit_valid,decision_before,decision_after,violated,critical)
                VALUES (?,?,?,?,?,1,'DO_WITH_UNDO','DO_WITH_UNDO',0,?)""",
                (
                    f"case-{EXAM_RUN_ID}-{base_index}-{op_index}",
                    EXAM_RUN_ID,
                    base_id,
                    op.name,
                    op.expectation,
                    int(op.critical),
                ),
            )
    append_ledger(
        conn,
        "exam_run",
        EXAM_RUN_ID,
        {
            "exam_run_id": EXAM_RUN_ID,
            "class_key": LICENCE_CLASS_KEY,
            "action": LICENCE_ACTION,
            "level_tested": 2,
            "passed": True,
            "n_cases": len(exam_bases),
            "invariance_flip_rate": 0.0,
            "critical_violations": 0,
            "finished_at": finished_at,
            "synthetic_demo": True,
        },
        finished_at,
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
    from wp6_mail_fixture import NOW as FIXTURE_NOW
    from wp6_mail_fixture import seed

    conn, _world = seed(temp_root, action="ARCHIVE")
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("UPDATE raw_items SET source_id = ? WHERE source_id = 'source'", (SOURCE_ID,))
    conn.execute("UPDATE sources SET id = ? WHERE id = 'source'", (SOURCE_ID,))
    conn.execute(
        "UPDATE situations SET redacted_text = ? WHERE id = 'sit'",
        (
            (
                "Subject: Notice of renewal — payment due 5 November\n\n"
                "Hello,\n\n"
                "Your subscription renews on 5 November. The amount is unchanged from last year, "
                "and no action is needed if you have already paid.\n\n"
                "If you would rather stop the renewal, reply before 1 November.\n\n"
                "— Billing"
            ),
        ),
    )
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
    if items >= 3:
        _seed_earned_licence(conn)
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
            _owner_id(),
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
