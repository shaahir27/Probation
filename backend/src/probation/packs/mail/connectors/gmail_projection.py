"""Temporal projection and outcome provenance for committed Gmail observations.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 1 (C9), 2 and 4, docs/FULL_PRODUCT_SPEC.md
sections 6 and 7.2 steps 5-6, docs/CONTRACT.md invariants I-6 and I-7. Three properties hold by
construction here, not by convention.

1. **Committed rows only.** ``project`` reads ``gmail_observations`` and ``gmail_history_events``
   and nothing else. The read connector is reachable from one live diagnostic, which refuses any
   explicit cut, and projection holds that guard for its whole read: an accidental provider call
   raises instead of answering, so a current answer can never be presented as past state.
2. **Three times stay distinct.** Provider occurrence (``internalDate``), the provider's position in
   its own change stream (``historyId``) and local knowledge time (injected Clock, stored as
   ``observed_at``) are separate fields, and an occurrence is reported only when
   ``occurrence_provenance`` says the provider supplied it. No ``Date`` header is carried at all:
   the store keeps a content hash and a payload reference, never message content.
3. **No invented attribution.** A change either correlates back to a Probation execution attempt and
   its native receipt — then it is ``probation`` and votes nothing — or it stays ``unknown``.
   ``human`` is not a value this module can construct, and no unmatched event supplies agreement,
   correction or a strong negative.

A retrospective import is labelled as such on every record emitted, so FP-D2's existing ledger
exclusion applies; it never claims a live licence.
"""

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Final, Literal, cast

from probation.connectors.types import ConnectorError, TimeProvenance
from probation.core.clock import Clock, format_timestamp, timestamp_key
from probation.core.history import HistoryView
from probation.db.gmail_store import ConnectorAccess
from probation.packs.mail.connectors.gmail_read import GmailReadConnector

AttributionKind = Literal["probation", "unknown"]
KnowledgeCohort = Literal["prospective", "retrospective"]
ChangeKind = Literal["label_added", "label_removed", "sent_observed", "message_deleted"]
_PROVENANCES: Final = frozenset({"provider_occurrence", "observed_locally", "unknown"})
_SNAPSHOTS: Final = frozenset({"message_added", "sent_observed"})
_KIND: Final[Mapping[str, ChangeKind]] = {
    "labelAdded": "label_added",
    "labelRemoved": "label_removed",
}

_SQL_ROWS = """SELECT native_message_id,history_id,event_type,content_hash,occurrence_time,
 occurrence_provenance,thread_id,rfc_message_id,payload_ref,label_ids,is_sent,observed_at
 FROM gmail_observations WHERE connection_id=? AND account_id=?
 AND observed_at COLLATE UTC_TIMESTAMP <= ? ORDER BY history_id,native_message_id"""
_SQL_EVENTS = """SELECT native_message_id,label_id,history_id,event_type,observed_at
 FROM gmail_history_events WHERE connection_id=? AND account_id=?
 AND observed_at COLLATE UTC_TIMESTAMP <= ? ORDER BY history_id,native_message_id,label_id"""
_SQL_CURSOR = """SELECT created_at FROM gmail_sync_cursors WHERE connection_id=?
 AND account_id=? AND resource_key=? AND role='read'
 ORDER BY committed_history_id DESC, filter_revision DESC LIMIT 1"""
_SQL_RECEIPTS = """SELECT operation_id,action_id,operation,anchor_history_id
 FROM gmail_effect_receipts WHERE connection_id=? AND account_id=? AND outcome='confirmed'
 AND verified_no_effect=0 AND anchor_history_id IS NOT NULL ORDER BY anchor_history_id"""
_SQL_ATTEMPT = """SELECT id AS attempt_id,action_id,created_at,before_json FROM execution_attempts
 WHERE state='confirmed' AND operation='execute' AND (id=? OR (action_id=? AND operation=?))
 AND created_at COLLATE UTC_TIMESTAMP <= ? ORDER BY (id=?) DESC LIMIT 1"""


class ProjectionError(ConnectorError):
    """A projection refused rather than guessed. Always fails closed."""


@dataclass(frozen=True)
class ProjectedMessage:
    """One message as it was knowable at a cut, with its three distinct times."""

    native_message_id: str
    thread_id: str | None
    rfc_message_id: str | None
    label_ids: tuple[str, ...]
    is_sent: bool
    has_body: bool
    occurrence_time: str | None
    occurrence_provenance: TimeProvenance
    observed_at: str
    provider_sequence: int
    content_hash: str
    payload_ref: str | None
    knowledge_cohort: KnowledgeCohort

    @property
    def known_at(self) -> str:
        """Local knowledge time: the injected Clock instant this record was committed at."""
        return self.observed_at

    @property
    def occurrence_claimed(self) -> bool:
        """True only when the provider itself supplied the occurrence time."""
        return (
            self.occurrence_provenance == "provider_occurrence" and self.occurrence_time is not None
        )

    @property
    def live_qualified(self) -> bool:
        """FP-D2: only a prospectively watched record may ever count toward live authority."""
        return self.knowledge_cohort == "prospective"

    @property
    def item_kind(self) -> str:
        return "mail_sent" if self.is_sent else "mail_in"

    def as_world_record(self) -> dict[str, Any]:
        """Exactly what was committed. No invented field, and never a body: only a payload reference."""
        return asdict(self)

    def as_raw_item(self) -> dict[str, Any] | None:
        """The ingest-shaped record, or ``None`` when no body was ever committed for it."""
        if not self.has_body:
            return None
        payload = self.as_world_record()
        payload["retrospective"] = not self.live_qualified
        payload["evidence_context"] = "prospective" if self.live_qualified else "backfill"
        return {
            "id": f"gmail:{self.native_message_id}",
            "pack": "mail",
            "item_kind": self.item_kind,
            "source_ref": self.rfc_message_id or self.native_message_id,
            "occurred_at": self.occurrence_time or self.known_at,
            "known_at": self.known_at,
            "created_at": self.known_at,
            "content_hash": self.content_hash,
            "payload_json": json.dumps(payload, sort_keys=True),
        }


@dataclass(frozen=True)
class ProviderChange:
    """A change observed in the provider stream. It names no actor, because Gmail cannot (C9)."""

    native_message_id: str
    kind: ChangeKind
    label_id: str | None
    history_id: int
    observed_at: str
    rfc_message_id: str | None = None


@dataclass(frozen=True)
class AttributedChange:
    """A provider change plus the honest answer to "who did this", which is rarely knowable."""

    change: ProviderChange
    attribution: AttributionKind
    attempt_id: str | None
    receipt_id: str | None
    action_id: str | None
    safe_reason: str
    agreement_votes: int = 0
    correction_votes: int = 0
    strong_negative_votes: int = 0

    def __post_init__(self) -> None:
        if self.attribution not in ("probation", "unknown"):
            raise ProjectionError("attribution_unsupported")
        if (self.agreement_votes, self.correction_votes, self.strong_negative_votes) != (0, 0, 0):
            raise ProjectionError("provider_change_carries_no_agreement")


@dataclass(frozen=True)
class RecordedEffect:
    """One Probation effect: its execution attempt joined to its private native receipt."""

    attempt_id: str
    receipt_id: str
    action_id: str
    resource_ids: tuple[str, ...]
    added_labels: tuple[str, ...]
    removed_labels: tuple[str, ...]
    sent_rfc_message_id: str | None
    anchor_history_id: int
    executed_at: str


@dataclass(frozen=True)
class EvidenceCounts:
    """What a projection may claim about evidence. Every voting field is structurally zero."""

    observed_messages: int
    prospective_messages: int
    retrospective_messages: int
    probation_attributed: int
    unknown_attributed: int
    agreement: int
    correction: int
    strong_negative: int
    human_attributed: int

    def __post_init__(self) -> None:
        if self.agreement or self.correction or self.strong_negative or self.human_attributed:
            raise ProjectionError("provider_change_carries_no_agreement")
        if self.observed_messages != self.prospective_messages + self.retrospective_messages:
            raise ProjectionError("cohort_counts_must_partition")


@dataclass(frozen=True)
class GmailProjection:
    """The complete as-of answer for one connection at one instant."""

    connection_id: str
    account_id: str
    as_of: str
    messages: tuple[ProjectedMessage, ...]
    changes: tuple[ProviderChange, ...]
    issues: tuple[str, ...] = ()

    def incoming(self) -> tuple[ProjectedMessage, ...]:
        return tuple(m for m in self.messages if not m.is_sent)

    def outgoing(self) -> tuple[ProjectedMessage, ...]:
        return tuple(m for m in self.messages if m.is_sent)

    @property
    def live_qualified_messages(self) -> int:
        return sum(1 for m in self.messages if m.live_qualified)

    def situation_candidates(self) -> tuple[dict[str, Any], ...]:
        """Records that may bear a decision situation. A ``SENT`` observation never does."""
        return tuple(row for row in (m.as_raw_item() for m in self.incoming()) if row is not None)


class GmailWorldView:
    """Read-only ``WorldView`` over committed Gmail rows at one cut, built without a provider call.

    Non-mail accessors answer empty rather than estimated: a mailbox is not a calendar, a file tree
    or a link library. ``get_user_actions`` always answers empty, because provider history names no
    actor (C9), and handing out a label event as a "user" action would fabricate exactly the dated
    human footprint that ``workers/resolver_observations.py`` requires before recording an override.
    """

    def __init__(self, projector: "GmailProjector", as_of: str) -> None:
        self._projector = projector
        self._as_of = as_of

    @property
    def as_of(self) -> str:
        return self._as_of

    def _cut(self, as_of: str | None) -> str:
        return self._as_of if as_of is None else format_timestamp(as_of)

    def get_messages(
        self, label: str | None = None, as_of: str | None = None
    ) -> list[dict[str, Any]]:
        rows = [m.as_world_record() for m in self._projector.project(self._cut(as_of)).messages]
        return rows if label is None else [row for row in rows if label in row["label_ids"]]

    def get_message(self, message_id: str, as_of: str | None = None) -> dict[str, Any] | None:
        for message in self._projector.project(self._cut(as_of)).messages:
            if message_id in (message.native_message_id, message.rfc_message_id):
                return message.as_world_record()
        return None

    def get_user_actions(
        self, item_id: str | None = None, as_of: str | None = None, actor: str | None = None
    ) -> list[dict[str, Any]]:
        del item_id, as_of, actor
        return []

    def get_events(self, as_of: str | None = None) -> list[dict[str, Any]]:
        del as_of
        return []

    def get_files(self, as_of: str | None = None) -> list[dict[str, Any]]:
        del as_of
        return []

    def get_tracker_entries(self, status: str | None = None) -> list[dict[str, Any]]:
        del status
        return []

    def get_library_entries(self, collection: str | None = None) -> list[dict[str, Any]]:
        del collection
        return []

    def get_event(self, uid: str, as_of: str | None = None) -> dict[str, Any] | None:
        del uid, as_of
        return None

    def get_tracker_entry(self, entry_id: str) -> dict[str, Any] | None:
        del entry_id
        return None

    def get_library_entry(self, url: str) -> dict[str, Any] | None:
        del url
        return None


class GmailProjector:
    """Projects one Gmail connection at any instant, from committed local rows only."""

    def __init__(
        self,
        *,
        access: ConnectorAccess,
        clock: Clock,
        connection_id: str,
        account_id: str,
        reader: GmailReadConnector | None = None,
        engine: sqlite3.Connection | None = None,
        resource_key: str = "cohort",
    ) -> None:
        self._access, self._clock = access, clock
        self._connection_id, self._account_id = connection_id, account_id
        self._reader, self._engine, self._resource_key = reader, engine, resource_key
        self._guarded = False
        self.provider_calls = 0

    def _use_reader(self) -> GmailReadConnector:
        if self._guarded:
            raise ProjectionError("provider_call_forbidden_during_projection")
        if self._reader is None:
            raise ProjectionError("no_read_connector_provisioned")
        self.provider_calls += 1
        return self._reader

    def read_provider_watermark(self, *, as_of: str | None = None) -> int:
        """The only transport user here: a LIVE diagnostic of where the account is now.

        Refused for any explicit cut, past or future, so polling can never stand in for a
        historical projection.
        """
        if as_of is not None and timestamp_key(as_of) != timestamp_key(self._clock.now_iso()):
            raise ProjectionError("historical_read_never_polls")
        return self._use_reader().bootstrap_anchor()

    def project(self, as_of: str | None = None) -> GmailProjection:
        cut = self._clock.now_iso() if as_of is None else format_timestamp(as_of)
        keys = (self._connection_id, self._account_id)
        self._guarded = True
        try:
            rows = self._access.query(_SQL_ROWS, (*keys, cut))
            events = self._access.query(_SQL_EVENTS, (*keys, cut))
            cursor = self._access.one(_SQL_CURSOR, (*keys, self._resource_key))
        finally:
            self._guarded = False
        issues: list[str] = []
        tracked = "" if cursor is None else str(cursor["created_at"])
        return GmailProjection(
            connection_id=self._connection_id,
            account_id=self._account_id,
            as_of=cut,
            messages=_messages(rows, events, tracked, issues),
            changes=_changes(rows, events),
            issues=tuple(issues),
        )

    def view(self, as_of: str | None = None) -> GmailWorldView:
        cut = self._clock.now_iso() if as_of is None else format_timestamp(as_of)
        return GmailWorldView(self, cut)

    def attributed_changes(self, as_of: str | None = None) -> tuple[AttributedChange, ...]:
        projection = self.project(as_of)
        return self._attribute(projection)

    def evidence_counts(self, as_of: str | None = None) -> EvidenceCounts:
        projection = self.project(as_of)
        return counts_of(projection, self._attribute(projection))

    def _attribute(self, projection: GmailProjection) -> tuple[AttributedChange, ...]:
        if self._engine is None:
            # Nothing to correlate against: fail closed to unknown, which can never vote.
            return tuple(
                AttributedChange(c, "unknown", None, None, None, "attribution_journal_unavailable")
                for c in projection.changes
            )
        return correlate(projection.changes, self._effects(projection.as_of))

    def _effects(self, as_of: str) -> tuple[RecordedEffect, ...]:
        """The attempt-and-receipt journal as at ``as_of``. No journal means no correlation, ever."""
        if self._engine is None:
            return ()
        out: list[RecordedEffect] = []
        receipts = self._access.query(_SQL_RECEIPTS, (self._connection_id, self._account_id))
        for receipt in receipts:
            operation = str(receipt["operation_id"])
            params = (
                operation,
                str(receipt["action_id"]),
                str(receipt["operation"]),
                as_of,
                operation,
            )
            attempt = self._engine.execute(_SQL_ATTEMPT, params).fetchone()
            effect = None if attempt is None else _effect_of(receipt, attempt)
            if effect is not None:
                out.append(effect)
        return tuple(out)

    def permission_alarms(
        self, class_key: str, action: str, family: str, as_of: str | None = None
    ) -> tuple[str, ...]:
        """Alarm history comes from the engine through ``HistoryView``, never from the provider."""
        return tuple(self._history(as_of).permission_alarms(class_key, action, family))

    def permission_evidence(self, as_of: str | None = None, family: str | None = None) -> int:
        return len(self._history(as_of).permission_records(family))

    def _history(self, as_of: str | None) -> HistoryView:
        if self._engine is None:
            raise ProjectionError("engine_view_unavailable")
        cut = self._clock.now_iso() if as_of is None else format_timestamp(as_of)
        return HistoryView(self._engine, cut)


def _messages(
    rows: Sequence[Any], events: Sequence[Any], tracked_from: str, issues: list[str]
) -> tuple[ProjectedMessage, ...]:
    bodies: dict[str, list[Any]] = {}
    label_events: dict[str, list[Any]] = {}
    known: dict[str, str] = {}
    deleted: set[str] = set()
    for row in rows:
        mid = str(row["native_message_id"])
        _earlier(known, mid, str(row["observed_at"]))
        kind = str(row["event_type"])
        if kind == "message_deleted":
            deleted.add(mid)
        elif kind in _SNAPSHOTS:
            bodies.setdefault(mid, []).append(row)
    for event in events:
        mid = str(event["native_message_id"])
        _earlier(known, mid, str(event["observed_at"]))
        label_events.setdefault(mid, []).append(event)
    return tuple(
        _project_one(
            mid,
            bodies.get(mid, []),
            label_events.get(mid, []),
            known[mid],
            tracked_from,
            deleted,
            issues,
        )
        for mid in sorted(known)
    )


def _earlier(seen: dict[str, str], mid: str, when: str) -> None:
    prior = seen.get(mid)
    if prior is None or timestamp_key(when) < timestamp_key(prior):
        seen[mid] = when


def _project_one(
    mid: str,
    bodies: list[Any],
    events: list[Any],
    observed_at: str,
    tracked_from: str,
    deleted: set[str],
    issues: list[str],
) -> ProjectedMessage:
    base = max(bodies, key=lambda row: int(row["history_id"]), default=None)
    sequence = (
        int(base["history_id"]) if base else min((int(e["history_id"]) for e in events), default=0)
    )
    raw = str(base["occurrence_provenance"]) if base else "observed_locally"
    provenance = cast("TimeProvenance", raw if raw in _PROVENANCES else "unknown")
    stored = None if base is None else base["occurrence_time"]
    claimed = provenance == "provider_occurrence" and stored is not None
    if stored is not None and not claimed:
        issues.append(f"occurrence_unverified:{mid}")
    ref = None if base is None else _text(base["payload_ref"])
    cohort = _cohort(str(stored) if claimed else None, tracked_from)
    return ProjectedMessage(
        native_message_id=mid,
        thread_id=None if base is None else _text(base["thread_id"]),
        rfc_message_id=None if base is None else _text(base["rfc_message_id"]),
        label_ids=_label_state(base, events, issues, mid),
        is_sent=base is not None and bool(int(base["is_sent"])),
        has_body=base is not None and ref is not None and mid not in deleted,
        occurrence_time=str(stored) if claimed else None,
        occurrence_provenance=provenance,
        observed_at=observed_at,
        provider_sequence=sequence,
        content_hash="" if base is None else str(base["content_hash"]),
        payload_ref=ref,
        knowledge_cohort=cohort,
    )


def _cohort(occurrence: str | None, tracked_from: str) -> KnowledgeCohort:
    """FP-D2 cohort, decided from committed columns only.

    Prospective only when the provider's own occurrence time falls at or after the instant this
    connection began being tracked. A record whose occurrence predates that, or whose occurrence the
    provider never supplied, fails closed to ``retrospective``: reconstructed past is eligible for
    training and separate retrospective runs, never for live authority.
    """
    if occurrence is None or not tracked_from:
        return "retrospective"
    return (
        "prospective"
        if timestamp_key(occurrence) >= timestamp_key(tracked_from)
        else "retrospective"
    )


def _label_state(base: Any, events: Sequence[Any], issues: list[str], mid: str) -> tuple[str, ...]:
    """The provider snapshot at its own history id, then only label transitions seen after it."""
    if base is None and events:
        issues.append(f"label_state_unanchored:{mid}")
    labels = set(_labels(base["label_ids"]) if base is not None else ())
    anchor = -1 if base is None else int(base["history_id"])
    for event in sorted(events, key=lambda row: int(row["history_id"])):
        if int(event["history_id"]) <= anchor:
            continue
        if str(event["event_type"]) == "labelAdded":
            labels.add(str(event["label_id"]))
        else:
            labels.discard(str(event["label_id"]))
    return tuple(sorted(labels))


def _changes(rows: Sequence[Any], events: Sequence[Any]) -> tuple[ProviderChange, ...]:
    out: list[ProviderChange] = []
    for row in rows:
        kind = str(row["event_type"])
        if kind == "message_added":
            continue  # an arrival is not a change some actor made to an already-known message
        out.append(
            ProviderChange(
                str(row["native_message_id"]),
                cast("ChangeKind", kind),
                None,
                int(row["history_id"]),
                str(row["observed_at"]),
                _text(row["rfc_message_id"]),
            )
        )
    for event in events:
        out.append(
            ProviderChange(
                str(event["native_message_id"]),
                _KIND[str(event["event_type"])],
                str(event["label_id"]),
                int(event["history_id"]),
                str(event["observed_at"]),
            )
        )
    order = lambda c: (c.history_id, c.native_message_id, c.kind, c.label_id or "")  # noqa: E731
    return tuple(sorted(out, key=order))


def _effect_of(receipt: Any, attempt: Any) -> RecordedEffect | None:
    try:
        before = json.loads(str(attempt["before_json"]))
    except json.JSONDecodeError:
        return None
    if not isinstance(before, Mapping):
        return None
    payload = before.get("payload")
    if not isinstance(payload, Mapping):
        return None
    snapshot: Mapping[str, Any] = before.get("snapshot") or {}
    inner: Mapping[str, Any] = payload.get("message") or {}
    resources = {str(payload.get("resource_id") or ""), str(snapshot.get("resource_id") or "")}
    labels = lambda key: tuple(str(x) for x in payload.get(key) or ())  # noqa: E731
    return RecordedEffect(
        attempt_id=str(attempt["attempt_id"]),
        receipt_id=str(receipt["operation_id"]),
        action_id=str(attempt["action_id"]),
        resource_ids=tuple(sorted(x for x in resources if x)),
        added_labels=labels("add_labels"),
        removed_labels=labels("remove_labels"),
        sent_rfc_message_id=_text(inner.get("message_id")),
        anchor_history_id=int(str(receipt["anchor_history_id"])),
        executed_at=str(attempt["created_at"]),
    )


def _matches(change: ProviderChange, effect: RecordedEffect) -> bool:
    """Our resource, after our anchor, in the direction we asked for, seen after we dispatched."""
    if timestamp_key(change.observed_at) < timestamp_key(effect.executed_at):
        return False
    if change.kind == "sent_observed":
        # A reply is a new resource, so the send is correlated by the RFC id our payload named.
        return (
            change.rfc_message_id is not None
            and change.rfc_message_id == effect.sent_rfc_message_id
            and change.history_id > effect.anchor_history_id
        )
    if (
        change.native_message_id not in effect.resource_ids
        or change.history_id <= effect.anchor_history_id
    ):
        return False
    if change.kind == "label_added":
        return change.label_id in effect.added_labels
    return change.kind == "label_removed" and change.label_id in effect.removed_labels


def correlate(
    changes: Iterable[ProviderChange], effects: Iterable[RecordedEffect]
) -> tuple[AttributedChange, ...]:
    """Attribute each change to Probation or to nobody. ``human`` is not producible (C9)."""
    known = tuple(effects)
    out: list[AttributedChange] = []
    for change in changes:
        matches = [effect for effect in known if _matches(change, effect)]
        if len(matches) == 1:
            won = matches[0]
            out.append(
                AttributedChange(
                    change,
                    "probation",
                    won.attempt_id,
                    won.receipt_id,
                    won.action_id,
                    "correlated_effect_attempt_and_native_receipt",
                )
            )
        else:
            reason = "correlation_ambiguous" if matches else "no_matching_effect"
            out.append(AttributedChange(change, "unknown", None, None, None, reason))
    return tuple(out)


def counts_of(
    projection: GmailProjection, attributed: Iterable[AttributedChange]
) -> EvidenceCounts:
    changes = tuple(attributed)
    return EvidenceCounts(
        observed_messages=len(projection.messages),
        prospective_messages=sum(1 for m in projection.messages if m.live_qualified),
        retrospective_messages=sum(1 for m in projection.messages if not m.live_qualified),
        probation_attributed=sum(1 for a in changes if a.attribution == "probation"),
        unknown_attributed=sum(1 for a in changes if a.attribution == "unknown"),
        agreement=0,
        correction=0,
        strong_negative=0,
        human_attributed=0,
    )


def _labels(raw: Any) -> tuple[str, ...]:
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return ()
    return tuple(sorted(str(item) for item in parsed)) if isinstance(parsed, list) else ()


def _text(value: Any) -> str | None:
    return None if value is None else str(value)
