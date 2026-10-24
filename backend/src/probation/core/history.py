"""HistoryView: Temporal isolation preventing access to future state.

Authority: docs/CONTRACT.md section 2, invariant I-6, and section 5.
History access goes ONLY through HistoryView(as_of=t).
It exposes only outcomes and raw items with known_at <= as_of.
It has no method that can return later data.
"""

import json
import sqlite3
from datetime import datetime
from typing import Any, cast

from probation.core.clock import format_timestamp
from probation.core.identity import normalize_address, normalize_user_addresses
from probation.db.guards import ReadConnection


class HistoryView:
    """Read-only database view bounded temporally by timestamp cutoff `as_of`."""

    def __init__(self, conn: sqlite3.Connection | ReadConnection, as_of: str | datetime) -> None:
        self._conn = conn
        self._as_of = format_timestamp(as_of)
        self._current_override: tuple[str, dict[str, Any]] | None = None

    @property
    def as_of(self) -> str:
        return self._as_of

    def frozen(self) -> "HistoryView":
        reader = (
            self._conn if isinstance(self._conn, ReadConnection) else ReadConnection(self._conn)
        )
        return HistoryView(reader.frozen(self.as_of), self.as_of)

    def shift_populations(
        self, family: str, semantic_version: str | None = None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        from probation.core.history_shift import shift_populations

        return shift_populations(self._conn, self.as_of, family, semantic_version)

    def control_records(self) -> list[dict[str, Any]]:
        from probation.core.history_controls import control_records

        return control_records(self._conn, self.as_of)

    def followup_records(self, limit: int = 32) -> list[dict[str, Any]]:
        from probation.core.history_followups import followup_records

        return followup_records(self._conn, self.as_of, limit)

    def get_execution_features(self, proposal_id: str) -> dict[str, Any] | None:
        """Current known source/feature inputs, never authoritative stored caps."""
        row = self._conn.execute(
            """SELECT s.*,f.deterministic_json,f.reader_json,f.reader_ok,
            f.featurizer_version,f.features_hash,f.created_at AS features_created_at,
            p.class_key,p.id AS proposal_id
            FROM proposals p JOIN situations s ON s.id=p.situation_id
            JOIN raw_items r ON r.id=s.raw_item_id
            JOIN features f ON f.situation_id=s.id WHERE p.id=?
            AND p.proposed_at COLLATE UTC_TIMESTAMP <= ?
            AND s.occurred_at COLLATE UTC_TIMESTAMP <= ?
            AND r.known_at COLLATE UTC_TIMESTAMP <= ?
            AND f.created_at COLLATE UTC_TIMESTAMP <= ?""",
            (proposal_id, self.as_of, self.as_of, self.as_of, self.as_of),
        ).fetchone()
        return dict(row) if row is not None else None

    def permission_history_digest(self) -> str:
        """Hash only knowable immutable events and observations for exam provenance."""
        from probation.core.hashing import canonical_json, det_id

        raw = self._conn.execute(
            """SELECT id,content_hash,payload_json FROM raw_items
               WHERE known_at COLLATE UTC_TIMESTAMP <= ? ORDER BY id""",
            (self.as_of,),
        ).fetchall()
        events = self._conn.execute(
            """SELECT seq,hash FROM ledger WHERE created_at COLLATE UTC_TIMESTAMP <= ?
               AND kind IN ('proposal','outcome','drift_alarm') ORDER BY seq""",
            (self.as_of,),
        ).fetchall()
        return det_id(
            canonical_json(
                {"raw": [tuple(row) for row in raw], "events": [tuple(row) for row in events]}
            )
        )

    def get_decision_projection(self) -> dict[str, dict[str, Any]]:
        """As-of immutable legacy events; never current outcome overwrite truth."""
        from probation.core.history_wp4 import decision_projection

        return decision_projection(self._conn, self.as_of)

    def get_training_records(self, family: str) -> list[dict[str, Any]]:
        from probation.core.history_wp4 import training_records

        return training_records(self._conn, self.as_of, family)

    def permission_records(self, family: str | None = None) -> list[dict[str, Any]]:
        from probation.core.permission_history import permission_records

        return permission_records(self._conn, self.as_of, family)

    def permission_alarms(self, class_key: str, action: str, family: str) -> list[str]:
        from probation.core.permission_history import alarm_times

        return alarm_times(self._conn, self.as_of, class_key, action, family)

    def permission_pairs(self) -> list[tuple[str, str]]:
        rows = self._conn.execute(
            """SELECT class_key,action FROM proposals WHERE proposed_at COLLATE UTC_TIMESTAMP <= ?
               UNION SELECT class_key,action FROM licence_cache WHERE computed_at COLLATE UTC_TIMESTAMP <= ?
               ORDER BY class_key,action""",
            (self.as_of, self.as_of),
        ).fetchall()
        return [(str(row[0]), str(row[1])) for row in rows]

    def sender_statistics(
        self, sender: str, exclude_situation_id: str | None = None
    ) -> dict[str, Any]:
        from probation.core.history_statistics import sender_statistics

        return sender_statistics(self._conn, self.as_of, sender, exclude_situation_id)

    def file_statistics(
        self, origin: str, exclude_situation_id: str | None = None
    ) -> dict[str, Any]:
        from probation.core.history_statistics import file_statistics

        return file_statistics(self._conn, self.as_of, origin, exclude_situation_id)

    def calendar_statistics(
        self, organizer: str, current_id: str, start: str, end: str, timezone: str
    ) -> dict[str, Any]:
        from probation.core.history_statistics import calendar_statistics

        return calendar_statistics(
            self._conn, self.as_of, organizer, current_id, start, end, timezone
        )

    def with_current_payload(self, raw_item_id: str, payload: dict[str, Any]) -> "HistoryView":
        """Counterfactual current-item data only; no future rows or historical mutation."""
        if self.get_raw_item(raw_item_id) is None:
            raise ValueError("Current item is not known at this cutoff")
        view = HistoryView(self._conn, self.as_of)
        view._current_override = (raw_item_id, dict(payload))
        return view

    def get_raw_item(self, raw_item_id: str) -> dict[str, Any] | None:
        """Fetch a single item only if it was knowable at this cut."""
        row = cast(
            sqlite3.Row | None,
            self._conn.execute(
                "SELECT * FROM raw_items WHERE id=? AND known_at COLLATE UTC_TIMESTAMP <= ?",
                (raw_item_id, self.as_of),
            ).fetchone(),
        )
        if row is None:
            return None
        result = dict(row)
        if self._current_override is not None and self._current_override[0] == raw_item_id:
            result["payload_json"] = json.dumps(self._current_override[1], allow_nan=False)
        return result

    def get_raw_items(
        self,
        pack: str | None = None,
        source_id: str | None = None,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        """Fetch raw items with known_at <= as_of."""
        query = "SELECT * FROM raw_items WHERE known_at COLLATE UTC_TIMESTAMP <= ?"
        params: list[Any] = [self.as_of]

        if pack is not None:
            query += " AND pack = ?"
            params.append(pack)
        if source_id is not None:
            query += " AND source_id = ?"
            params.append(source_id)

        query += " ORDER BY known_at COLLATE UTC_TIMESTAMP ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        cursor = self._conn.cursor()
        cursor.execute(query, tuple(params))
        return list(cursor.fetchall())

    def get_situations(
        self,
        pack: str | None = None,
        family: str | None = None,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        """Fetch situations with occurred_at <= as_of."""
        query = "SELECT * FROM situations WHERE occurred_at COLLATE UTC_TIMESTAMP <= ?"
        params: list[Any] = [self.as_of]

        if pack is not None:
            query += " AND pack = ?"
            params.append(pack)
        if family is not None:
            query += " AND family = ?"
            params.append(family)

        query += " ORDER BY occurred_at COLLATE UTC_TIMESTAMP ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        cursor = self._conn.cursor()
        cursor.execute(query, tuple(params))
        return list(cursor.fetchall())

    def get_outcomes(
        self,
        situation_ids: list[str] | None = None,
    ) -> list[sqlite3.Row]:
        """Fetch outcomes with known_at <= as_of."""
        query = "SELECT * FROM outcomes WHERE known_at COLLATE UTC_TIMESTAMP <= ?"
        params: list[Any] = [self.as_of]

        if situation_ids is not None:
            if not situation_ids:
                return []
            placeholders = ",".join("?" for _ in situation_ids)
            query += f" AND situation_id IN ({placeholders})"
            params.extend(situation_ids)

        query += " ORDER BY known_at COLLATE UTC_TIMESTAMP ASC"
        cursor = self._conn.cursor()
        cursor.execute(query, tuple(params))
        return list(cursor.fetchall())

    def get_proposals(
        self,
        class_key: str | None = None,
        action: str | None = None,
    ) -> list[sqlite3.Row]:
        """Fetch proposals with proposed_at <= as_of."""
        query = "SELECT * FROM proposals WHERE proposed_at COLLATE UTC_TIMESTAMP <= ?"
        params: list[Any] = [self.as_of]

        if class_key is not None:
            query += " AND class_key = ?"
            params.append(class_key)
        if action is not None:
            query += " AND action = ?"
            params.append(action)

        query += " ORDER BY proposed_at COLLATE UTC_TIMESTAMP ASC"
        cursor = self._conn.cursor()
        cursor.execute(query, tuple(params))
        return list(cursor.fetchall())

    def get_unreviewed_outcome_events(self) -> list[sqlite3.Row]:
        """Immutable operational outcome events, bounded by event and proposal time."""
        return list(
            self._conn.execute(
                """SELECT l.seq,l.payload_json,l.created_at,p.class_key,p.action,
                       p.proposed_at,p.ledger_seq AS proposal_ledger_seq
            FROM ledger l JOIN proposals p
              ON p.situation_id=json_extract(l.payload_json,'$.situation_id')
              AND (json_extract(l.payload_json,'$.proposal_id') IS NULL
                   OR p.id=json_extract(l.payload_json,'$.proposal_id'))
              AND (json_extract(l.payload_json,'$.proposal_id') IS NOT NULL OR p.id=(
                  SELECT p0.id FROM proposals p0 WHERE p0.situation_id=p.situation_id
                  AND p0.proposed_at COLLATE UTC_TIMESTAMP <
                    COALESCE(json_extract(l.payload_json,'$.known_at'),l.created_at)
                  ORDER BY p0.proposed_at COLLATE UTC_TIMESTAMP,p0.id LIMIT 1))
            WHERE l.kind='outcome' AND l.created_at COLLATE UTC_TIMESTAMP <= ?
              AND COALESCE(json_extract(l.payload_json,'$.known_at'),
                  json_extract(l.payload_json,'$.undone_at'),l.created_at) COLLATE UTC_TIMESTAMP <= ?
              AND p.proposed_at COLLATE UTC_TIMESTAMP <= ?
              AND NOT EXISTS (SELECT 1 FROM drift_receipts r WHERE r.event_seq=l.seq)
            ORDER BY l.created_at COLLATE UTC_TIMESTAMP,l.seq""",
                (self.as_of, self.as_of, self.as_of),
            ).fetchall()
        )

    def count_prior_sender_messages(
        self, sender: str, exclude_situation_id: str | None = None
    ) -> int:
        """Count prior situations from this sender with occurred_at <= as_of."""
        query = "SELECT COUNT(*) FROM situations WHERE sender_key = ? AND occurred_at COLLATE UTC_TIMESTAMP <= ?"
        params: list[Any] = [sender, self.as_of]
        if exclude_situation_id:
            query += " AND id != ?"
            params.append(exclude_situation_id)
        cur = self._conn.cursor()
        cur.execute(query, tuple(params))
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def count_prior_sender_replies(
        self, sender: str, exclude_situation_id: str | None = None
    ) -> int:
        """Count prior situations from sender that have a known REPLY outcome at <= as_of."""
        query = """
            SELECT COUNT(*)
            FROM situations s
            JOIN outcomes o ON s.id = o.situation_id
            WHERE s.sender_key = ?
              AND s.occurred_at COLLATE UTC_TIMESTAMP <= ?
              AND o.known_at COLLATE UTC_TIMESTAMP <= ?
              AND o.observed_action = 'REPLY'
        """
        params: list[Any] = [sender, self.as_of, self.as_of]
        if exclude_situation_id:
            query += " AND s.id != ?"
            params.append(exclude_situation_id)
        cur = self._conn.cursor()
        cur.execute(query, tuple(params))
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def get_prior_sender_reply_deltas(
        self, sender: str, exclude_situation_id: str | None = None
    ) -> list[float]:
        """Compute reply response deltas (in hours) for prior replied situations from sender."""
        query = """
            SELECT s.occurred_at, o.known_at
            FROM situations s
            JOIN outcomes o ON s.id = o.situation_id
            WHERE s.sender_key = ?
              AND s.occurred_at COLLATE UTC_TIMESTAMP <= ?
              AND o.known_at COLLATE UTC_TIMESTAMP <= ?
              AND o.observed_action = 'REPLY'
        """
        params: list[Any] = [sender, self.as_of, self.as_of]
        if exclude_situation_id:
            query += " AND s.id != ?"
            params.append(exclude_situation_id)
        query += " ORDER BY s.occurred_at COLLATE UTC_TIMESTAMP ASC"
        cur = self._conn.cursor()
        cur.execute(query, tuple(params))
        deltas: list[float] = []
        for r in cur.fetchall():
            try:
                t_occ = datetime.fromisoformat(str(r["occurred_at"]).replace("Z", "+00:00"))
                t_res = datetime.fromisoformat(str(r["known_at"]).replace("Z", "+00:00"))
                hours = (t_res - t_occ).total_seconds() / 3600.0
                if hours >= 0:
                    deltas.append(hours)
            except Exception:
                pass
        return deltas

    def count_prior_sent_to_recipient(self, recipient_email: str) -> int:
        """Count prior user sent messages directed to a recipient with known_at <= as_of.

        The LIKE clause is only a coarse prefilter that keeps this off a full scan of sent
        mail; it cannot decide membership. A raw `To` header holds display names and several
        comma-separated addresses, so `'%a@x.com%'` also matches `ba@x.com` and
        `a@x.com.attacker.test`. The decision is made by parsing each candidate header and
        comparing normalized addresses exactly (docs/PACKS_SPEC.md section 0.2).
        """
        recipient = normalize_address(recipient_email)
        if not recipient:
            return 0
        query = """
            SELECT json_extract(payload_json, '$.to') FROM raw_items
            WHERE pack = 'mail'
              AND item_kind = 'mail_sent'
              AND known_at COLLATE UTC_TIMESTAMP <= ?
              AND json_extract(payload_json, '$.to') LIKE ?
        """
        cur = self._conn.cursor()
        cur.execute(query, (self.as_of, f"%{recipient}%"))
        count = 0
        for (to_header,) in cur.fetchall():
            recipients = normalize_user_addresses("" if to_header is None else str(to_header))
            if recipient in recipients:
                count += 1
        return count

    def get_prior_thread_stats(
        self,
        msg_id: str,
        in_reply_to: str,
        user_addresses: list[str],
        current_raw_item_id: str | None = None,
    ) -> tuple[int, bool]:
        """Compute thread message count and whether user sent in thread prior to as_of."""
        if not msg_id and not in_reply_to:
            return 0, False
        query = """
            SELECT id, item_kind, payload_json FROM raw_items
            WHERE pack = 'mail'
              AND known_at COLLATE UTC_TIMESTAMP <= ?
              AND (
                source_ref = ?
                OR json_extract(payload_json, '$.in_reply_to') = ?
                OR (json_extract(payload_json, '$.message_id') = ? AND ? != '')
                OR (json_extract(payload_json, '$.in_reply_to') = ? AND ? != '')
              )
        """
        cur = self._conn.cursor()
        cur.execute(
            query,
            (
                self.as_of,
                in_reply_to or "__none__",
                msg_id or "__none__",
                in_reply_to or "",
                in_reply_to or "",
                in_reply_to or "",
                in_reply_to or "",
            ),
        )
        thread_msgs = 0
        user_sent = False
        # Exact membership, never substring: an owner token such as "me" is contained in most
        # addresses, so `token in from_addr` would credit unrelated senders as the owner and
        # inflate n_prior_sent / thread participation (plan section 6.1.3).
        owner = set(normalize_user_addresses(user_addresses))
        for r in cur.fetchall():
            if current_raw_item_id and r["id"] == current_raw_item_id:
                continue
            thread_msgs += 1
            if r["item_kind"] == "mail_sent":
                user_sent = True
            else:
                try:
                    p = json.loads(r["payload_json"])
                    from_addr = str(p.get("from") or p.get("from_addr") or "")
                    if owner and normalize_address(from_addr) in owner:
                        user_sent = True
                except Exception:
                    pass
        return thread_msgs, user_sent

    def get_prior_files_in_folder(self, folder: str) -> int:
        """Count prior files moved to or located in folder known at <= as_of."""
        query = """
            SELECT COUNT(*) FROM raw_items
            WHERE pack = 'files'
              AND known_at COLLATE UTC_TIMESTAMP <= ?
              AND json_extract(payload_json, '$.rel_path') LIKE ?
        """
        cur = self._conn.cursor()
        cur.execute(query, (self.as_of, f"{folder}/%"))
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def get_prior_outcomes(self, family: str | None = None) -> list[sqlite3.Row]:
        """Fetch prior outcomes known at <= as_of, optionally filtered by family."""
        query = """
            SELECT o.*, s.family, s.occurred_at
            FROM outcomes o
            JOIN situations s ON o.situation_id = s.id
            WHERE o.known_at COLLATE UTC_TIMESTAMP <= ?
        """
        params: list[Any] = [self.as_of]
        if family is not None:
            query += " AND s.family = ?"
            params.append(family)
        query += " ORDER BY o.known_at COLLATE UTC_TIMESTAMP ASC"
        cur = self._conn.cursor()
        cur.execute(query, tuple(params))
        return list(cur.fetchall())
