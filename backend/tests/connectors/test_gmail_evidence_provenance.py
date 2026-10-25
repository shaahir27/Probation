"""D4 outcome provenance: attribution, cohort and re-sync honesty for committed Gmail events.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md section 1 (C9 attribution unsupported), section 4 (cohort,
three times, ``SENT`` is an observation, backfill never grants live authority) and
docs/FULL_PRODUCT_SPEC.md sections 6 and 7.2 steps 5-6. ``docs/CONTRACT.md`` I-7 requires a proposal
to precede its outcome and keeps retrospective provenance separate, which is exactly what a
correlated provider change is: retrospective provenance, never a fresh vote.
"""

import inspect
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fake_gmail_read import FakeGmailTransport, _Message

from probation.core.clock import Clock, format_timestamp
from probation.core.enums import ClockMode, LedgerKind
from probation.db.access import Role, RoleAccess
from probation.db.connection import apply_schema, get_connection
from probation.db.gmail_store import ConnectorAccess, migrate_store, open_store
from probation.db.proposals import persist_proposal
from probation.engine.evidence import aggregate_evidence
from probation.engine.licence import derive_licences
from probation.packs.mail import MailPack
from probation.packs.mail.connectors.gmail_projection import (
    AttributedChange,
    EvidenceCounts,
    GmailProjector,
    ProjectionError,
    ProviderChange,
    RecordedEffect,
    correlate,
)
from probation.packs.mail.connectors.gmail_read import GmailReadConnector
from probation.packs.mail.connectors.gmail_sync import GmailSync

CONNECTION = "conn-1"
ACCOUNT = "acct@test.invalid"
TOKEN = "read-token"
OWNER_LABEL = "COHORT"
BASE = datetime(2026, 10, 24, 9, 0, 0, tzinfo=UTC)
PAIR = ("mail|request|known", "ARCHIVE")
PROPOSED = "2026-05-31T10:00:00.123456Z"
KNOWN = "2026-05-31T11:00:00Z"
LATER = "2026-06-01T00:00:00Z"
# One fixed Gmail-store cut for the re-sync comparison. The injected clock legitimately advances
# between the two snapshots, and an answer's ``as_of`` is the cut it was asked for, so pinning the
# cut keeps the comparison about what the re-sync did to the store, not about clock movement. The
# cut is after every knowledge time the re-sync can commit at, so a duplicated or restored row
# still shows up in the second answer and only in the second answer.
RESYNC_CUT = "2026-10-24T09:30:00Z"


def _clock(at: datetime = BASE) -> Clock:
    return Clock(mode=ClockMode.REPLAY, initial_time=at)


def _selection() -> Any:
    from probation.connectors.types import SourceSelection

    return SourceSelection(
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        selection_revision=1,
        label_ids=(OWNER_LABEL,),
    )


def _message(
    native_id: str,
    *,
    labels: set[str],
    rfc: str | None = None,
    internal: datetime = datetime(2026, 10, 24, 8, 30, tzinfo=UTC),
) -> _Message:
    return _Message(
        native_id,
        thread_id=f"thread-{native_id}",
        from_addr="alice@sender.test",
        to_addr="bob@owner.test",
        subject=f"subject {native_id}",
        date="Tue, 14 Nov 2023 22:13:20 +0000",
        message_id=rfc or f"<{native_id}@sender.test>",
        internal_date_ms=int(internal.timestamp() * 1000),
        labels=labels,
        text=f"body of {native_id}",
    )


def _ingestor(path: Path) -> ConnectorAccess:
    return ConnectorAccess(open_store(path), "ingestor")


def _executor(path: Path) -> ConnectorAccess:
    return ConnectorAccess(open_store(path), "executor")


def _reader(path: Path) -> ConnectorAccess:
    return ConnectorAccess(open_store(path), "api")


def _migrate(path: Path) -> ConnectorAccess:
    boot = open_store(path)
    assert migrate_store(boot) is True
    boot.close()
    return _ingestor(path)


def _sync(fake: FakeGmailTransport, access: ConnectorAccess, clock: Clock) -> GmailSync:
    connector = GmailReadConnector(
        fake,
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        access_token=TOKEN,
        clock=clock,
        owner_label=OWNER_LABEL,
    )
    return GmailSync(
        access=access,
        connector=connector,
        clock=clock,
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        owner_label=OWNER_LABEL,
    )


def _projector(
    access: ConnectorAccess, clock: Clock, engine: sqlite3.Connection | None = None
) -> GmailProjector:
    return GmailProjector(
        access=access,
        clock=clock,
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        engine=engine,
    )


def _bootstrap(tmp_path: Path, *messages: _Message) -> tuple[Path, Clock, FakeGmailTransport]:
    path = tmp_path / "store.db"
    access = _migrate(path)
    clock = _clock()
    fake = FakeGmailTransport(expected_token=TOKEN)
    for message in messages:
        fake.add_message(message)
    _sync(fake, access, clock).bootstrap(_selection(), owner="reader-a")
    return path, clock, fake


def _engine() -> sqlite3.Connection:
    conn = get_connection(":memory:")
    apply_schema(conn)
    return conn


def _commit_proposal(
    conn: sqlite3.Connection,
    *,
    situation_id: str,
    proposal_id: str,
    class_key: str = PAIR[0],
    at: str = PROPOSED,
    extra: dict[str, Any] | None = None,
) -> int:
    """One immutable prospective commitment, shaped exactly like ``db.proposals`` writes it."""
    conn.execute(
        "INSERT INTO sources VALUES(?,?,?,?,?)",
        (f"src-{situation_id}", "mail", "gmail_live", "cohort", at),
    )
    conn.execute(
        """INSERT INTO raw_items(id,source_id,pack,item_kind,source_ref,occurred_at,known_at,
           payload_json,content_hash) VALUES(?,?,?,?,?,?,?,?,?)""",
        (
            f"raw-{situation_id}",
            f"src-{situation_id}",
            "mail",
            "mail_in",
            f"<{situation_id}@sender.test>",
            at,
            at,
            "{}",
            "hash",
        ),
    )
    conn.execute(
        """INSERT INTO situations(id,raw_item_id,pack,family,occurred_at,content_hash,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (situation_id, f"raw-{situation_id}", "mail", "email_action", at, "hash", at),
    )
    payload: dict[str, Any] = {
        "situation_id": situation_id,
        "class_key": class_key,
        "action": PAIR[1],
        "gate": "SUGGEST",
        "policy_version": "fitted",
        **(extra or {}),
    }
    seq = RoleAccess(conn, Role.BRAIN).append_ledger(
        LedgerKind.PROPOSAL, proposal_id, payload, created_at=at
    )
    conn.execute(
        """INSERT INTO proposals(id,situation_id,family,class_key,action,probs_json,p_max,novelty,
           novel,licence_level,cap,gate,reasons_json,policy_version,features_hash,proposed_at,
           ledger_seq) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            proposal_id,
            situation_id,
            "email_action",
            class_key,
            PAIR[1],
            "{}",
            0.99,
            0.0,
            0,
            1,
            3,
            "SUGGEST",
            "[]",
            "fitted",
            "hash",
            at,
            seq,
        ),
    )
    conn.commit()
    return seq


def _outcome_event(
    conn: sqlite3.Connection,
    *,
    situation_id: str,
    proposal_id: str,
    action: str = "ARCHIVE",
    actor: str | None = None,
    source: str = "footprint",
    at: str = KNOWN,
) -> None:
    event: dict[str, Any] = {
        "situation_id": situation_id,
        "proposal_id": proposal_id,
        "observed_action": action,
        "strength": "STRONG",
        "source": source,
        "known_at": at,
    }
    if actor is not None:
        event["actor"] = actor
    RoleAccess(conn, Role.RESOLVER).append_ledger(
        LedgerKind.OUTCOME, situation_id, event, created_at=at
    )
    conn.commit()


def _record_effect(
    path: Path,
    engine: sqlite3.Connection,
    *,
    attempt_id: str,
    action_id: str,
    resource_id: str,
    added: tuple[str, ...] = (),
    removed: tuple[str, ...] = (),
    anchor: int,
    sent_rfc: str | None = None,
    receipt_id: str | None = None,
    at: str = "2026-10-24T09:00:00Z",
) -> None:
    """The two halves of one Probation effect: the engine attempt and the native receipt."""
    engine.execute(
        """INSERT INTO actions(id,proposal_id,pack,type,params_json,level_required,recallable,
           status,created_at,updated_at,executed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            action_id,
            "prop-1",
            "mail",
            "ARCHIVE",
            "{}",
            1,
            1,
            "DONE",
            at,
            at,
            at,
        ),
    )
    payload: dict[str, Any] = {"type": "labels" if sent_rfc is None else "send"}
    payload["resource_id"] = resource_id
    if sent_rfc is None:
        payload["add_labels"] = list(added)
        payload["remove_labels"] = list(removed)
    else:
        payload["message"] = {"message_id": sent_rfc}
    engine.execute(
        """INSERT INTO execution_attempts(id,action_id,operation,binding_hash,state,claim_owner,
           fence,lease_until,before_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            attempt_id,
            action_id,
            "execute",
            "0" * 64,
            "confirmed",
            "executor-1",
            1,
            at,
            json.dumps({"payload": payload, "snapshot": {"resource_id": resource_id}}),
            at,
            at,
        ),
    )
    engine.commit()
    executor = _executor(path)
    executor.write(
        "gmail_effect_receipts",
        """INSERT INTO gmail_effect_receipts
           (operation_id,connection_id,account_id,action_id,operation,outcome,native_ref_hash,
            anchor_history_id,payload_hash,safe_code,verified_no_effect,created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            receipt_id or attempt_id,
            CONNECTION,
            ACCOUNT,
            action_id,
            "execute",
            "confirmed",
            f"sha256:{resource_id}",
            anchor,
            "0" * 64,
            None,
            0,
            at,
        ),
    )
    executor.conn.close()


def test_sent_observation_never_becomes_decision_situation(tmp_path: Path) -> None:
    """``SENT`` is an observation of the world, not something Probation should act on (section 4)."""
    path, clock, _ = _bootstrap(
        tmp_path,
        _message("m-in", labels={OWNER_LABEL, "INBOX"}),
        # Even a sent item that still carries INBOX must not be read as an incoming request.
        _message("m-out", labels={OWNER_LABEL, "INBOX", "SENT"}),
    )
    projection = _projector(_reader(path), clock).project()

    outgoing = projection.outgoing()
    assert [message.native_message_id for message in outgoing] == ["m-out"]
    assert outgoing[0].is_sent is True
    assert outgoing[0].item_kind == "mail_sent"
    assert [message.native_message_id for message in projection.incoming()] == ["m-in"]

    candidates = projection.situation_candidates()
    assert [row["id"] for row in candidates] == [projection.incoming()[0].as_raw_item()["id"]]
    assert all(row["item_kind"] != "mail_sent" for row in candidates)

    pack = MailPack(user_addresses=["bob@owner.test"])
    situations = [sit for row in candidates for sit in pack.iter_situations(row)]
    assert len(situations) == 1, "an incoming observation must still yield its decision situation"
    assert all(pack.iter_situations(message.as_raw_item()) == [] for message in outgoing)
    assert situations[0].raw_item_id != outgoing[0].as_raw_item()["id"]


def test_probation_label_change_adds_no_agreement(tmp_path: Path) -> None:
    """A correlated effect is Probation's own; it can never be counted as the owner agreeing."""
    path, clock, fake = _bootstrap(tmp_path, _message("m1", labels={OWNER_LABEL, "INBOX"}))
    anchor = int(
        _reader(path).query(
            "SELECT history_id FROM gmail_observations WHERE native_message_id='m1'"
        )[0]["history_id"]
    )
    engine = _engine()
    _commit_proposal(engine, situation_id="x1", proposal_id="prop-1")
    _outcome_event(engine, situation_id="x1", proposal_id="prop-1")
    _record_effect(
        path,
        engine,
        attempt_id="att-1",
        action_id="act-1",
        receipt_id="act-1:execute",
        resource_id="m1",
        removed=("INBOX",),
        anchor=anchor,
    )
    fake.modify_labels("m1", remove=("INBOX",))
    clock.advance_seconds(120)
    _sync(fake, _ingestor(path), clock).incremental(_selection(), owner="reader-a")

    projector = _projector(_reader(path), clock, engine)
    changes = projector.attributed_changes()
    label_changes = [c for c in changes if c.change.label_id == "INBOX"]
    assert len(label_changes) == 1
    assert label_changes[0].attribution == "probation"
    assert label_changes[0].attempt_id == "att-1"
    assert label_changes[0].receipt_id == "act-1:execute"
    assert label_changes[0].action_id == "act-1"
    assert label_changes[0].change.kind == "label_removed"

    # A sent item we caused is correlated the same way and still votes nothing. A cohort re-scan
    # (the documented route for a stale anchor) is what brings a labelled-but-not-yet-seen resource
    # into the tracked set, so this re-enumerates rather than pretending incremental history saw it.
    fake.add_message(_message("m-reply", labels={OWNER_LABEL, "SENT"}, rfc="<act-2@invalid>"))
    _record_effect(
        path,
        engine,
        attempt_id="att-2",
        action_id="act-2",
        resource_id="m1",
        sent_rfc="<act-2@invalid>",
        anchor=anchor,
    )
    clock.advance_seconds(60)
    _sync(fake, _ingestor(path), clock).bootstrap(_selection(), owner="reader-a")
    sends = [c for c in projector.attributed_changes() if c.change.kind == "sent_observed"]
    assert [c.attribution for c in sends] == ["probation"]
    assert sends[0].attempt_id == "att-2" and sends[0].action_id == "act-2"

    before = projector.evidence_counts()
    assert before.agreement == 0
    assert before.correction == 0
    assert before.strong_negative == 0
    assert before.human_attributed == 0
    assert before.probation_attributed == 2

    # Re-ingesting the identical change cannot move a single count.
    fake.modify_labels("m1", add=("INBOX",), remove=("INBOX",))
    clock.advance_seconds(60)
    _sync(fake, _ingestor(path), clock).incremental(_selection(), owner="reader-a")
    after = projector.evidence_counts()
    assert (after.agreement, after.correction, after.strong_negative) == (0, 0, 0)
    assert after.human_attributed == before.human_attributed

    # Engine side: the same change recorded as a Probation outcome cannot earn a vote.
    baseline = aggregate_evidence(engine, LATER, persist=False)
    _outcome_event(
        engine,
        situation_id="x1",
        proposal_id="prop-1",
        action="ARCHIVE",
        actor="probation",
        at="2026-05-31T12:00:00Z",
    )
    _commit_proposal(
        engine, situation_id="x2", proposal_id="prop-2", class_key="mail|request|newcomer"
    )
    _outcome_event(engine, situation_id="x2", proposal_id="prop-2", actor="probation")
    later = aggregate_evidence(engine, LATER, persist=False)
    assert {k: (v.n_all, v.k_all) for k, v in later.items()} == {
        k: (v.n_all, v.k_all) for k, v in baseline.items()
    }
    assert ("mail|request|newcomer", PAIR[1]) not in later


def test_unknown_attribution_adds_no_evidence(tmp_path: Path) -> None:
    """Unmatched provider changes stay unknown: never human, never a vote, never a negative (C9)."""
    path, clock, fake = _bootstrap(tmp_path, _message("m1", labels={OWNER_LABEL, "INBOX"}))
    engine = _engine()
    fake.modify_labels("m1", add=("STARRED",))
    clock.advance_seconds(120)
    _sync(fake, _ingestor(path), clock).incremental(_selection(), owner="reader-a")

    projector = _projector(_reader(path), clock, engine)
    changes = projector.attributed_changes()
    assert [c.attribution for c in changes] == ["unknown"] * len(changes)
    assert all(c.safe_reason and c.attempt_id is None for c in changes)
    assert all(c.attribution != "human" for c in changes)
    counts = projector.evidence_counts()
    assert (counts.agreement, counts.correction, counts.strong_negative) == (0, 0, 0)
    assert counts.human_attributed == 0
    assert counts.unknown_attributed == len(changes)

    # The type itself refuses to carry a human attribution or a vote.
    change = ProviderChange(
        native_message_id="m1",
        kind="label_added",
        label_id="STARRED",
        history_id=9,
        observed_at=format_timestamp(clock.now()),
    )
    with pytest.raises(ProjectionError, match="attribution_unsupported"):
        AttributedChange(
            change=change,
            attribution="human",  # type: ignore[arg-type]
            attempt_id=None,
            receipt_id=None,
            action_id=None,
            safe_reason="never",
        )
    with pytest.raises(ProjectionError, match="carries_no_agreement"):
        AttributedChange(
            change=change,
            attribution="unknown",
            attempt_id=None,
            receipt_id=None,
            action_id=None,
            safe_reason="no_matching_effect",
            agreement_votes=1,
        )
    with pytest.raises(ProjectionError, match="carries_no_agreement"):
        EvidenceCounts(
            observed_messages=1,
            prospective_messages=1,
            retrospective_messages=0,
            probation_attributed=0,
            unknown_attributed=0,
            agreement=1,
            correction=0,
            strong_negative=0,
            human_attributed=0,
        )
    # Two competing effects cannot be told apart, so the change stays unknown.
    effect = RecordedEffect(
        attempt_id="att-1",
        receipt_id="att-1",
        action_id="act-1",
        resource_ids=("m1",),
        added_labels=("STARRED",),
        removed_labels=(),
        sent_rfc_message_id=None,
        anchor_history_id=1,
        executed_at="2026-10-24T09:00:00Z",
    )
    single = correlate((change,), (effect,))
    assert [c.attribution for c in single] == ["probation"]
    assert single[0].attempt_id == "att-1" and single[0].action_id == "act-1"
    both = correlate((change,), (effect, effect))
    assert [c.attribution for c in both] == ["unknown"]
    assert both[0].safe_reason == "correlation_ambiguous"
    # A change before our anchor is not ours: it predates the effect entirely.
    early = ProviderChange(
        native_message_id="m1",
        kind="label_added",
        label_id="STARRED",
        history_id=1,
        observed_at=format_timestamp(clock.now()),
    )
    assert [c.safe_reason for c in correlate((early,), (effect,))] == ["no_matching_effect"]


def test_backfill_cannot_grant_live_authority(tmp_path: Path) -> None:
    """A retrospective import is labelled as such and moves no derived authority (FP-D2)."""
    path, clock, fake = _bootstrap(
        tmp_path, *[_message(f"m-old-{i}", labels={OWNER_LABEL, "INBOX"}) for i in range(4)]
    )
    projection = _projector(_reader(path), clock).project()
    assert len(projection.messages) == 4
    assert all(m.knowledge_cohort == "retrospective" for m in projection.messages)
    assert all(m.live_qualified is False for m in projection.messages)
    assert projection.live_qualified_messages == 0

    # One message that arrives after the anchor was watched happening: prospective. A cohort
    # re-scan is the documented route that brings a labelled-but-not-yet-seen resource into the
    # tracked set (see test_probation_label_change_adds_no_agreement), and "watched happening"
    # must be true at the provider: its occurrence (internalDate) falls inside the tracking
    # window that began at BASE, not before it. An occurrence predating tracking is backfill and
    # stays retrospective, which is exactly what the first four messages above prove.
    fake.add_message(
        _message(
            "m-live",
            labels={OWNER_LABEL, "INBOX"},
            internal=datetime(2026, 10, 24, 9, 1, tzinfo=UTC),
        )
    )
    clock.advance_seconds(120)
    _sync(fake, _ingestor(path), clock).bootstrap(_selection(), owner="reader-a")
    after = _projector(_reader(path), clock).project()
    fresh = [m for m in after.messages if m.native_message_id == "m-live"]
    assert [m.knowledge_cohort for m in fresh] == ["prospective"]
    assert [m.live_qualified for m in fresh] == [True]
    assert after.live_qualified_messages == 1

    # The flag rides on every record the projection emits, so the writer can honour it.
    payload = json.loads(projection.messages[0].as_raw_item()["payload_json"])
    assert payload["retrospective"] is True
    assert payload["evidence_context"] == "backfill"

    engine = _engine()
    _commit_proposal(engine, situation_id="xb", proposal_id="prop-b", extra={"retrospective": True})
    _outcome_event(engine, situation_id="xb", proposal_id="prop-b")
    backfilled = aggregate_evidence(engine, LATER, persist=False)
    assert PAIR not in backfilled
    assert derive_licences(engine, LATER, pair=PAIR)[PAIR].level == 0
    assert "no_eligible_evidence" in derive_licences(engine, LATER, pair=PAIR)[PAIR].reasons

    _commit_proposal(engine, situation_id="xp", proposal_id="prop-p")
    _outcome_event(engine, situation_id="xp", proposal_id="prop-p")
    prospective = aggregate_evidence(engine, LATER, persist=False)
    assert prospective[PAIR].n_all == 1
    # Even one prospective record does not buy authority: licence maths is unchanged by cohorting.
    assert derive_licences(engine, LATER, pair=PAIR)[PAIR].level == 0


def test_backfill_label_is_not_yet_carried_by_the_writer() -> None:
    """DOCUMENTED GAP, interface request IR-D4-1: nothing stamps the cohort onto a commitment.

    ``core/permission_history.py`` honours ``retrospective``/``evidence_context`` and drops such a
    record from qualifying evidence, and the test above proves the exclusion works. The released
    projection emits the flag on every record it hands to the ingest path. But the only writer of
    proposal commitments, ``db/proposals.persist_proposal``, builds its ledger payload from a fixed
    field list that contains neither key, so a Gmail backfill imported through the ordinary path is
    committed as ordinary prospective evidence. D4 does not change a shared file to close it; this
    test keeps the gap visible instead of reporting it closed.
    """
    source = inspect.getsource(persist_proposal)
    assert "append_ledger" in source, "the commitment writer moved, re-read this test"
    assert "retrospective" not in source
    assert "evidence_context" not in source


def test_resync_does_not_duplicate_or_restore(tmp_path: Path) -> None:
    """Replaying the same provider history twice changes nothing the engine already decided."""
    path, clock, fake = _bootstrap(
        tmp_path,
        _message("m1", labels={OWNER_LABEL, "INBOX"}),
        _message("m2", labels={OWNER_LABEL, "INBOX"}),
    )
    engine = _engine()
    _commit_proposal(engine, situation_id="x1", proposal_id="prop-1")
    _outcome_event(engine, situation_id="x1", proposal_id="prop-1")
    RoleAccess(engine, Role.EXAMINER).append_ledger(
        LedgerKind.DRIFT_ALARM,
        "pair-1",
        {"class_key": PAIR[0], "action": PAIR[1], "alarm_at": KNOWN},
        created_at=KNOWN,
    )
    engine.commit()

    def snapshot() -> dict[str, Any]:
        projector = _projector(_reader(path), clock, engine)
        stats = aggregate_evidence(engine, LATER, persist=False)
        return {
            "projection": _answer_of(projector.project(as_of=RESYNC_CUT)),
            "counts": projector.evidence_counts(as_of=RESYNC_CUT),
            "alarms": projector.permission_alarms(PAIR[0], PAIR[1], "email_action", as_of=LATER),
            "records": projector.permission_evidence(as_of=LATER),
            "licence": derive_licences(engine, LATER, pair=PAIR)[PAIR].level,
            "evidence": {k: (v.n_all, v.k_all, v.n_strong, v.k_strong) for k, v in stats.items()},
        }

    before = snapshot()
    sync = _sync(fake, _ingestor(path), clock)
    sync.bootstrap(_selection(), owner="reader-a")
    sync.incremental(_selection(), owner="reader-a")
    sync.incremental(_selection(), owner="reader-a")
    clock.advance_seconds(60)
    after = snapshot()

    assert before["projection"] == after["projection"]
    assert before["counts"] == after["counts"]
    assert before["alarms"] == after["alarms"], "a re-sync erased a drift alarm"
    assert before["records"] == after["records"], "a re-sync duplicated evidence"
    assert before["licence"] == after["licence"] == 0, "a re-sync restored authority"
    assert before["evidence"] == after["evidence"]
    rows = _reader(path).query("SELECT count(*) AS n FROM gmail_observations")
    assert int(rows[0]["n"]) == 2, "a re-sync duplicated committed observations"


def _answer_of(projection: Any) -> tuple[Any, ...]:
    return (
        projection.as_of,
        tuple(message.as_world_record() for message in projection.messages),
        tuple(
            (c.native_message_id, c.kind, c.label_id, c.history_id, c.observed_at)
            for c in projection.changes
        ),
        sorted(projection.issues),
    )
