"""Durable sync state for the Gmail syncer: fenced cursor, lease, markers and cohort seed.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 4 and 11 rows 13-15. This module owns every
write that defines where the connection stands: the fenced cursor advance, the worker lease,
content-free resync markers, the durable cohort seed and the observation rows a page commits.
``gmail_sync`` mixes it into ``GmailSync`` and owns orchestration only. Nothing here talks to the
provider.
"""

import json
import sqlite3
from dataclasses import dataclass
from typing import Final, Literal

from probation.connectors.readiness import ResyncFreshness
from probation.connectors.types import CursorRejected, SourceObservation, SourceSelection
from probation.core.clock import Clock
from probation.db.gmail_store import ConnectorAccess

DEFAULT_LEASE_SECONDS = 60
ResyncStatus = Literal["in_progress", "complete", "failed"]
_RESYNC_IN_PROGRESS: ResyncStatus = "in_progress"
_RESYNC_COMPLETE: ResyncStatus = "complete"
_RESYNC_FAILED: ResyncStatus = "failed"
_MARKER_PREFIX = "resync:"
_MAX_SAFE_CODE = 64
RESYNC_STATUS_UNAVAILABLE: Final = "resync_status_unavailable"

_INSERT_OBSERVATION = """INSERT OR IGNORE INTO gmail_observations
 (connection_id,account_id,native_message_id,history_id,event_type,content_hash,version_hash,
  observed_at,occurrence_time,occurrence_provenance,thread_id,rfc_message_id,payload_ref,
  label_ids,is_sent) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""

_INSERT_HISTORY_EVENT = """INSERT OR IGNORE INTO gmail_history_events
 (connection_id,account_id,history_id,native_message_id,label_id,event_type,observed_at)
 VALUES(?,?,?,?,?,?,?)"""

_INSERT_CURSOR = """INSERT OR IGNORE INTO gmail_sync_cursors
 (connection_id,account_id,resource_key,role,filter_revision,committed_history_id,
  bootstrap_history_id,fence,created_at,updated_at) VALUES(?,?,?,'read',?,?,?,?,?,?)"""

_HISTORY_TYPES = {
    "labelAdded": "labelAdded",
    "labelRemoved": "labelRemoved",
    "messagesAdded": "messageAdded",
    "messagesDeleted": "messageDeleted",
}


@dataclass(frozen=True)
class ResyncMarker:
    """One explicit resync attempt, safe to log or publish: times, counters and safe codes only.

    ``finished_at`` is set when the attempt reaches a terminal state; a marker that never
    finished names a crash mid-resync and is safe to repeat.
    """

    status: ResyncStatus
    safe_code: str | None
    attempted_at: str
    finished_at: str | None
    anchor_history_id: int | None
    committed_history_id: int | None


class SyncStateMixin:
    """Cursor, lease, marker, cohort-seed and page-row persistence for one selection.

    Attributes are declared by the composing engine (``GmailSync``); this half only writes state.
    """

    _access: ConnectorAccess
    _clock: Clock
    _connection_id: str
    _account_id: str
    _resource_key: str

    def _job_key(self) -> str:
        return f"sync:{self._resource_key}"

    # -- fencing ----------------------------------------------------------------------------
    def claim(
        self, owner: str, selection: SourceSelection, *, lease_seconds: int = DEFAULT_LEASE_SECONDS
    ) -> int:
        now = self._clock.now_iso()
        self._ensure_cursor(selection, now)
        held = self._access.one(
            "SELECT owner FROM gmail_worker_leases WHERE connection_id=? AND job_key=?"
            " AND expires_at COLLATE UTC_TIMESTAMP > ?",
            (self._connection_id, self._job_key(), now),
        )
        if held is not None and str(held["owner"]) != owner:
            raise CursorRejected("lease_held_by_active_worker")
        prior = self._access.one(
            "SELECT fence FROM gmail_worker_leases WHERE connection_id=? AND job_key=?",
            (self._connection_id, self._job_key()),
        )
        new_fence = 1 if prior is None else int(prior["fence"]) + 1
        expires = _plus_seconds(now, lease_seconds)
        if prior is None:
            self._access.write(
                "gmail_worker_leases",
                "INSERT INTO gmail_worker_leases VALUES(?,?,?,?,?,?)",
                (self._connection_id, self._job_key(), owner, new_fence, now, expires),
            )
        else:
            self._access.write(
                "gmail_worker_leases",
                "UPDATE gmail_worker_leases SET owner=?,fence=?,expires_at=?"
                " WHERE connection_id=? AND job_key=?",
                (owner, new_fence, expires, self._connection_id, self._job_key()),
            )
        self._access.write(
            "gmail_sync_cursors",
            "UPDATE gmail_sync_cursors SET claim_owner=?,fence=?,lease_until=?,updated_at=?"
            " WHERE connection_id=? AND resource_key=? AND role='read' AND filter_revision=?",
            (
                owner,
                new_fence,
                expires,
                now,
                self._connection_id,
                self._resource_key,
                selection.selection_revision,
            ),
        )
        return new_fence

    def _ensure_cursor(self, selection: SourceSelection, now: str) -> None:
        self._access.write(
            "gmail_sync_cursors",
            _INSERT_CURSOR,
            (
                self._connection_id,
                self._account_id,
                self._resource_key,
                selection.selection_revision,
                0,
                None,
                0,
                now,
                now,
            ),
        )

    # -- cursor advance ---------------------------------------------------------------------
    def _advance(
        self,
        tx: ConnectorAccess,
        selection: SourceSelection,
        owner: str,
        fence: int,
        *,
        committed: int,
        complete: bool,
        page_token: str | None = None,
    ) -> None:
        now = self._clock.now_iso()
        catchup_sql = ",catchup_complete=1" if complete else ""
        rowcount = tx.write(
            "gmail_sync_cursors",
            "UPDATE gmail_sync_cursors SET committed_history_id=?,page_token=?,watermark_at=?,updated_at=?"
            + catchup_sql
            + " WHERE connection_id=? AND resource_key=? AND role='read'"
            " AND filter_revision=? AND claim_owner=? AND fence=?",
            (
                committed,
                page_token,
                now,
                now,
                self._connection_id,
                self._resource_key,
                selection.selection_revision,
                owner,
                fence,
            ),
        )
        if rowcount != 1:
            raise CursorRejected("fenced_out_by_second_worker")

    def _touch(
        self, tx: ConnectorAccess, selection: SourceSelection, owner: str, fence: int
    ) -> None:
        """Assert the fenced claim without moving the watermark, inside the page transaction.

        ``UPDATE ... SET updated_at=updated_at`` still reports one matched row in SQLite, so a
        stale worker whose lease was taken over is refused before any observation it holds is
        committed.
        """
        rowcount = tx.write(
            "gmail_sync_cursors",
            "UPDATE gmail_sync_cursors SET updated_at=updated_at WHERE connection_id=?"
            " AND resource_key=? AND role='read' AND filter_revision=? AND claim_owner=? AND fence=?",
            (
                self._connection_id,
                self._resource_key,
                selection.selection_revision,
                owner,
                fence,
            ),
        )
        if rowcount != 1:
            raise CursorRejected("fenced_out_by_second_worker")

    def _install_cursor(
        self,
        tx: ConnectorAccess,
        selection: SourceSelection,
        owner: str,
        fence: int,
        *,
        anchor: int,
        committed: int,
    ) -> None:
        """Install the new bootstrap anchor and watermark in one monotonic, fenced update."""
        now = self._clock.now_iso()
        rowcount = tx.write(
            "gmail_sync_cursors",
            "UPDATE gmail_sync_cursors SET bootstrap_history_id=?,committed_history_id=?,"
            "page_token=NULL,watermark_at=?,updated_at=?,catchup_complete=1"
            " WHERE connection_id=? AND resource_key=? AND role='read' AND filter_revision=?"
            " AND claim_owner=? AND fence=?",
            (
                anchor,
                committed,
                now,
                now,
                self._connection_id,
                self._resource_key,
                selection.selection_revision,
                owner,
                fence,
            ),
        )
        if rowcount != 1:
            raise CursorRejected("fenced_out_by_second_worker")

    def _cursor_row(self, selection: SourceSelection) -> sqlite3.Row | None:
        return self._access.one(
            "SELECT committed_history_id,catchup_complete,bootstrap_history_id FROM gmail_sync_cursors"
            " WHERE connection_id=? AND resource_key=? AND role='read' AND filter_revision=?",
            (self._connection_id, self._resource_key, selection.selection_revision),
        )

    # -- resync marker ----------------------------------------------------------------------
    def _marker_prefix(self) -> str:
        return f"{_MARKER_PREFIX}{self._resource_key}:"

    def _next_marker_key(self) -> str:
        row = self._access.one(
            "SELECT count(*) AS n FROM gmail_sync_cursors WHERE connection_id=? AND role='read'"
            " AND resource_key LIKE ? ESCAPE '\\'",
            (self._connection_id, _like_prefix(self._marker_prefix())),
        )
        sequence = 1 if row is None else int(row["n"]) + 1
        return f"{self._marker_prefix()}{sequence}"

    def _begin_resync(
        self, selection: SourceSelection, owner: str, fence: int, anchor: int, now: str
    ) -> str:
        """Record the attempt before any provider work: a crash leaves it visible as unfinished.

        The marker is an ordinary cursor row with its own reserved ``resource_key`` and a zero
        watermark, so no readiness or projection reader can mistake it for the connection's
        committed position.
        """
        marker_key = self._next_marker_key()
        self._access.write(
            "gmail_sync_cursors",
            "INSERT INTO gmail_sync_cursors (connection_id,account_id,resource_key,role,"
            "filter_revision,committed_history_id,bootstrap_history_id,watermark_at,page_token,"
            "catchup_complete,claim_owner,fence,lease_until,created_at,updated_at)"
            " VALUES(?,?,?,'read',?,0,?,NULL,?,0,?,?,NULL,?,?)",
            (
                self._connection_id,
                self._account_id,
                marker_key,
                selection.selection_revision,
                anchor,
                _RESYNC_IN_PROGRESS,
                owner,
                fence,
                now,
                now,
            ),
        )
        return marker_key

    def _fail_resync(self, marker_key: str, fence: int, code: str) -> None:
        with self._access.transaction() as tx:
            self._finish_marker(tx, marker_key, fence, _RESYNC_FAILED, code, 0, required=False)

    def _finish_marker(
        self,
        tx: ConnectorAccess,
        marker_key: str,
        fence: int,
        status: ResyncStatus,
        code: str | None,
        committed: int,
        *,
        required: bool = True,
    ) -> None:
        now = self._clock.now_iso()
        token = status if code is None else f"{status}:{_safe_code(code)}"
        rowcount = tx.write(
            "gmail_sync_cursors",
            "UPDATE gmail_sync_cursors SET page_token=?,catchup_complete=?,committed_history_id=?,"
            "watermark_at=?,updated_at=? WHERE connection_id=? AND resource_key=? AND role='read'"
            " AND fence=?",
            (
                token,
                1 if status == _RESYNC_COMPLETE else 0,
                committed,
                now,
                now,
                self._connection_id,
                marker_key,
                fence,
            ),
        )
        if required and rowcount != 1:
            raise CursorRejected("fenced_out_by_second_worker")

    def resync_markers(self, selection: SourceSelection) -> tuple[ResyncMarker, ...]:
        """Every recorded resync attempt for this selection, oldest first. Safe codes only."""
        rows = self._access.query(
            "SELECT page_token,created_at,watermark_at,bootstrap_history_id,"
            "committed_history_id FROM gmail_sync_cursors WHERE connection_id=? AND role='read'"
            " AND filter_revision=? AND resource_key LIKE ? ESCAPE '\\' ORDER BY rowid ASC",
            (
                self._connection_id,
                selection.selection_revision,
                _like_prefix(self._marker_prefix()),
            ),
        )
        return tuple(_marker_of(row) for row in rows)

    # -- cohort seed ------------------------------------------------------------------------
    def _stored_cohort(self) -> set[str]:
        """The durable tracking set: every resource already selected into the private store.

        Only ids this connection previously committed are read back, so seeding the cohort from
        the store can never widen it to an out-of-cohort resource. A tombstoned (permanently
        removed) id stays tracked: its identifier is already durable, and dropping later records
        for it would fabricate a gap in the honest label-transition history.
        """
        rows = self._access.query(
            "SELECT DISTINCT native_message_id FROM gmail_observations"
            " WHERE connection_id=? AND account_id=?",
            (self._connection_id, self._account_id),
        )
        return {str(row["native_message_id"]) for row in rows}

    # -- page rows --------------------------------------------------------------------------
    def _write_observation(self, tx: ConnectorAccess, observation: SourceObservation) -> int:
        return tx.write("gmail_observations", _INSERT_OBSERVATION, _observation_params(observation))

    def _write_label_event(
        self,
        tx: ConnectorAccess,
        *,
        history_id: int,
        native_message_id: str,
        label_id: str,
        label_event: str,
        now: str,
    ) -> int:
        return tx.write(
            "gmail_history_events",
            _INSERT_HISTORY_EVENT,
            (
                self._connection_id,
                self._account_id,
                history_id,
                native_message_id,
                label_id,
                _HISTORY_TYPES[label_event],
                now,
            ),
        )

    def _write_tombstone(
        self, tx: ConnectorAccess, *, native_message_id: str, history_id: int, now: str
    ) -> int:
        digest = _sha(f"tombstone:{native_message_id}:{history_id}")
        tombstone = (
            self._connection_id,
            self._account_id,
            native_message_id,
            history_id,
            "message_deleted",
            digest,
            digest,
            now,
            None,
            "observed_locally",
            None,
            None,
            None,
            "[]",
            0,
        )
        return tx.write("gmail_observations", _INSERT_OBSERVATION, tombstone)


def _marker_of(row: sqlite3.Row) -> ResyncMarker:
    """Decode a marker row without ever surfacing anything but status, times and safe codes."""
    raw = str(row["page_token"] or "")
    status_raw, _, code = raw.partition(":")
    if status_raw == _RESYNC_COMPLETE:
        status: ResyncStatus = "complete"
    elif status_raw == _RESYNC_FAILED:
        status = "failed"
    else:
        status = "in_progress"
    finished = row["watermark_at"]
    anchor = row["bootstrap_history_id"]
    committed = row["committed_history_id"]
    return ResyncMarker(
        status=status,
        safe_code=code or None,
        attempted_at=str(row["created_at"]),
        finished_at=None if finished is None else str(finished),
        anchor_history_id=None if anchor is None else int(anchor),
        committed_history_id=None if committed is None else int(committed),
    )


def _like_prefix(prefix: str) -> str:
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped + "%"


def resync_freshness(markers: tuple[ResyncMarker, ...]) -> ResyncFreshness:
    """Resync attempt state from decoded markers, shared by worker and API readers.

    An unfinished attempt (live or crashed) counts as in progress, and only a later completed
    attempt clears it; a completed attempt clears any earlier failure code.
    """
    if not markers:
        return ResyncFreshness()
    latest = markers[-1]
    # The newest terminal attempt decides the failure code: a completed attempt clears an
    # earlier failure, and only a later in-progress retry keeps it relevant.
    terminal = next(
        (marker for marker in reversed(markers) if marker.status != "in_progress"), None
    )
    return ResyncFreshness(
        in_progress=latest.status == "in_progress",
        last_successful_at=next(
            (
                marker.finished_at
                for marker in reversed(markers)
                if marker.status == "complete" and marker.finished_at is not None
            ),
            None,
        ),
        last_failure_code=(
            None if terminal is None or terminal.status != "failed" else terminal.safe_code
        ),
    )


def committed_resync_freshness(
    access: ConnectorAccess, connection_id: str, resource_key: str = "cohort"
) -> ResyncFreshness:
    """Resync attempt state read from committed marker rows only; unreadable state fails closed."""
    try:
        rows = access.query(
            "SELECT page_token,created_at,watermark_at,bootstrap_history_id,committed_history_id"
            " FROM gmail_sync_cursors WHERE connection_id=? AND role='read'"
            " AND filter_revision=(SELECT MAX(filter_revision) FROM gmail_sync_cursors"
            "  WHERE connection_id=? AND role='read')"
            " AND resource_key LIKE ? ESCAPE '\\' ORDER BY rowid ASC",
            (
                connection_id,
                connection_id,
                _like_prefix(f"{_MARKER_PREFIX}{resource_key}:"),
            ),
        )
        return resync_freshness(tuple(_marker_of(row) for row in rows))
    except Exception:  # any doubt about resync history holds dependence, never permits it
        return ResyncFreshness(in_progress=True, last_failure_code=RESYNC_STATUS_UNAVAILABLE)


def _safe_code(code: str) -> str:
    cleaned = "".join(
        char if ("a" <= char <= "z" or "0" <= char <= "9" or char == "_") else "_"
        for char in code.lower()
    )
    return cleaned[:_MAX_SAFE_CODE] or "unknown"


def _observation_params(observation: SourceObservation) -> tuple[object, ...]:
    obs = observation
    return (
        str(obs.connection_id),
        str(obs.account_id),
        str(obs.native_message_id),
        int(obs.history_id),
        str(obs.event_type),
        str(obs.content_hash),
        str(obs.version_hash),
        str(obs.observed_at),
        obs.occurrence_time,
        str(obs.provenance),
        obs.thread_id,
        obs.rfc_message_id,
        obs.payload_ref,
        json.dumps(list(obs.label_ids)),
        1 if str(obs.event_type) == "sent_observed" else 0,
    )


def _plus_seconds(now: str, seconds: int) -> str:
    from datetime import UTC, datetime, timedelta

    parsed = datetime.fromisoformat(now.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (parsed + timedelta(seconds=seconds)).astimezone(UTC).isoformat().replace("+00:00", "Z")


def _sha(text: str) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
