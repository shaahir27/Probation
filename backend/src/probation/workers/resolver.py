"""Resolver worker: Resolves outcomes from user footprints and responses.

Authority: docs/CONTRACT.md section 3, invariant I-7, and docs/PACKS_SPEC.md.
Enforces Role.RESOLVER database write boundaries.
"""

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any, Literal, cast

from probation.core.clock import Clock, get_clock
from probation.core.enums import LedgerKind
from probation.core.hashing import canonical_json
from probation.core.identity import normalize_user_addresses
from probation.core.types import Situation
from probation.db.access import Role, RoleAccess
from probation.db.ledger import append_ledger
from probation.packs.base import WorldView
from probation.packs.calendar.resolver import resolve_calendar_outcome
from probation.packs.identity import persisted_or_configured_owner, world_user_addresses
from probation.packs.mail.resolver import MailResolverIndex, resolve_mail_outcome
from probation.packs.registry import registry


def resolve_outcomes(
    conn: sqlite3.Connection,
    world: WorldView,
    as_of: datetime | str | None = None,
    user_addresses: list[str] | str | None = None,
    clock: Clock | None = None,
) -> int:
    """Resolve and record outcomes for unresolved situations up to as_of.

    Authority: docs/CONTRACT.md section 3, invariant I-7, and docs/ENGINE_SPEC.md section 1.1.
    """
    if as_of is None:
        as_of_dt = (clock or get_clock()).now()
    elif isinstance(as_of, str):
        as_of_dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        if as_of_dt.tzinfo is None:
            as_of_dt = as_of_dt.replace(tzinfo=UTC)
        else:
            as_of_dt = as_of_dt.astimezone(UTC)
    else:
        as_of_dt = as_of if as_of.tzinfo is not None else as_of.replace(tzinfo=UTC)

    access_conn = RoleAccess(conn, Role.RESOLVER)
    from probation.workers.response_resolver import resolve_responses

    explicit_count = resolve_responses(conn, as_of=as_of_dt.isoformat().replace("+00:00", "Z"))
    from probation.workers.resolver_observations import (
        automation_message_ids,
        is_system_footprint,
        observe_manual_overrides,
    )

    cutoff = as_of_dt.isoformat().replace("+00:00", "Z")
    override_count = observe_manual_overrides(conn, world, cutoff)
    cur = access_conn.conn.cursor()

    # Determine user addresses explicitly. Normalization is centralized in core.identity so a
    # world, an import and a resolver cannot disagree about spelling; splitting on commas here
    # would mis-parse a quoted display name that contains one (plan section 6.1.3).
    if user_addresses is not None:
        effective_user_addrs = normalize_user_addresses(user_addresses)
    elif (world_addrs := world_user_addresses(world)) is not None:
        effective_user_addrs = world_addrs
    else:
        effective_user_addrs = persisted_or_configured_owner(cur)

    # Pre-index messages once for O(1) resolution across the batch
    mail_index: MailResolverIndex | None = None
    try:
        system_ids = automation_message_ids(conn, cutoff)
        messages = [
            message
            for message in world.get_messages(as_of=cutoff)
            if message.get("message_id") not in system_ids
        ]
        mail_index = MailResolverIndex(effective_user_addrs, messages)
    except Exception:
        mail_index = None

    cur.execute(
        """
        SELECT s.*, r.payload_json
        FROM situations s
        LEFT JOIN outcomes o ON s.id = o.situation_id
        LEFT JOIN raw_items r ON s.raw_item_id = r.id
        WHERE o.situation_id IS NULL
          AND s.occurred_at COLLATE UTC_TIMESTAMP <= ?
          AND r.known_at COLLATE UTC_TIMESTAMP <= ?
        ORDER BY s.occurred_at COLLATE UTC_TIMESTAMP ASC;
        """,
        (cutoff, cutoff),
    )
    rows = cur.fetchall()
    count = explicit_count + override_count

    for row in rows:
        sit = Situation(
            id=row["id"],
            raw_item_id=row["raw_item_id"],
            pack=row["pack"],
            family=row["family"],
            variant=row["variant"],
            occurred_at=row["occurred_at"],
            sender_key=row["sender_key"],
            content_hash=row["content_hash"],
            redacted_text=row["redacted_text"],
            hands_off_reason=row["hands_off_reason"],
            created_at=row["created_at"],
        )

        raw_payload: dict[str, Any] | None = None
        if row["payload_json"]:
            try:
                raw_payload = json.loads(row["payload_json"])
            except Exception:
                raw_payload = None

        outcome = None
        if sit.pack == "mail":
            outcome = resolve_mail_outcome(
                sit,
                world,
                as_of_dt,
                raw_payload=raw_payload,
                user_addresses=effective_user_addrs,
                index=mail_index,
            )
        elif sit.pack == "calendar":
            outcome = resolve_calendar_outcome(
                sit, world, as_of_dt, raw_payload=raw_payload, user_addresses=effective_user_addrs
            )
        else:
            try:
                pack = registry.get_descriptor(sit.pack)
                # The situation carries hashes and redacted text only, so the source identity a
                # resolver needs (a file's rel_path, a link's url) must come from the payload
                # already parsed above. Dropping it degrades every such outcome to a WEAK default.
                outcome = pack.resolve_observed_outcome(sit, world, as_of_dt, raw_payload)
            except KeyError:
                continue

        if outcome is None:
            continue
        if sit.pack == "mail" and is_system_footprint(conn, sit.raw_item_id, outcome):
            continue

        proposal = access_conn.conn.execute(
            """SELECT id,proposed_at FROM proposals WHERE situation_id=?
            AND proposed_at COLLATE UTC_TIMESTAMP < ? ORDER BY proposed_at COLLATE UTC_TIMESTAMP,id LIMIT 1""",
            (sit.id, outcome.known_at),
        ).fetchone()
        if proposal is not None:
            from probation.core.hashing import det_id
            from probation.core.lifecycle import OutcomeEvent
            from probation.db.lifecycle_events import EventStore

            source_key = det_id(
                "observed-v2", sit.id, outcome.source, outcome.known_at, outcome.observed_action
            )
            with access_conn.transaction():
                saved = EventStore(access_conn).append(
                    OutcomeEvent(
                        event_id="footprint-" + source_key,
                        situation_id=sit.id,
                        proposal_id=proposal["id"],
                        kind="footprint",
                        source=cast(Literal["footprint", "window_close"], outcome.source),
                        source_key=source_key,
                        strength=cast(Literal["STRONG", "WEAK"], str(outcome.strength)),
                        observed_at=outcome.observed_at,
                        known_at=outcome.known_at,
                        observed_action=outcome.observed_action,
                        actor="human",
                        details=outcome.details,
                    )
                )
                access_conn.execute_write(
                    "outcomes",
                    """INSERT OR IGNORE INTO outcomes
                    (situation_id,observed_action,strength,source,observed_at,known_at,details_json,ledger_seq)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        sit.id,
                        outcome.observed_action,
                        str(outcome.strength),
                        outcome.source,
                        outcome.observed_at,
                        outcome.known_at,
                        canonical_json(outcome.details),
                        saved.ledger_seq,
                    ),
                )
            count += 1
            continue

        # Append to hash-chained ledger first (Contract I-7)
        seq = append_ledger(
            conn,
            kind=LedgerKind.OUTCOME,
            ref_id=outcome.situation_id,
            payload={
                "situation_id": outcome.situation_id,
                "observed_action": outcome.observed_action,
                "strength": str(outcome.strength),
                "source": outcome.source,
                "known_at": outcome.known_at,
            },
            created_at=outcome.known_at,
        )

        # Write to outcomes table
        access_conn.execute_write(
            "outcomes",
            """
            INSERT OR IGNORE INTO outcomes
            (situation_id, observed_action, strength, source, observed_at, known_at, details_json, ledger_seq)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                outcome.situation_id,
                outcome.observed_action,
                str(outcome.strength),
                outcome.source,
                outcome.observed_at,
                outcome.known_at,
                canonical_json(outcome.details),
                seq,
            ),
        )
        count += 1

    return count
