"""Resolver worker: Resolves outcomes from user footprints and responses.

Authority: docs/CONTRACT.md section 3, invariant I-7, and docs/PACKS_SPEC.md.
Enforces Role.RESOLVER database write boundaries.
"""

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from probation.core.clock import Clock, get_clock
from probation.core.enums import LedgerKind
from probation.core.hashing import canonical_json
from probation.core.types import Situation
from probation.db.access import Role, RoleAccess
from probation.db.ledger import append_ledger
from probation.packs.base import WorldView
from probation.packs.calendar.resolver import resolve_calendar_outcome
from probation.packs.identity import world_user_addresses
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
    cur = access_conn.conn.cursor()

    # Determine user addresses explicitly
    if user_addresses is not None:
        if isinstance(user_addresses, str):
            effective_user_addrs = [a.strip() for a in user_addresses.split(",") if a.strip()]
        else:
            effective_user_addrs = [a.strip() for a in user_addresses if a.strip()]
    elif (world_addrs := world_user_addresses(world)) is not None:
        effective_user_addrs = world_addrs
    else:
        try:
            cur.execute("SELECT value FROM meta WHERE key = 'user_addresses';")
            meta_row = cur.fetchone()
            if meta_row and meta_row[0]:
                effective_user_addrs = [a.strip() for a in str(meta_row[0]).split(",") if a.strip()]
            else:
                from probation.config import settings

                effective_user_addrs = [
                    a.strip() for a in settings.user_addresses.split(",") if a.strip()
                ]
        except Exception:
            from probation.config import settings

            effective_user_addrs = [
                a.strip() for a in settings.user_addresses.split(",") if a.strip()
            ]

    # Pre-index messages once for O(1) resolution across the batch
    mail_index: MailResolverIndex | None = None
    try:
        messages = world.get_messages()
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
        ORDER BY s.occurred_at COLLATE UTC_TIMESTAMP ASC;
        """
    )
    rows = cur.fetchall()
    count = 0

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
                outcome = pack.resolve_outcome(sit, world, as_of_dt)
            except KeyError:
                continue

        if outcome is None:
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
