"""Bootstrap then incremental Gmail sync with durable, fenced, atomic page commits.

Authority: docs/WP12_D4_GMAIL_CONTRACT.md sections 2, 4, 7 and docs/FULL_PRODUCT_SPEC.md
sections 5.1, 6 and 7.2. Every read goes through ``GmailReadConnector`` (so the injected
transport); every write goes through the ``ingestor`` ``ConnectorAccess`` on the private store. A
page of observations and its cursor advance commit in ONE ``StoreTransaction``: a crash before
commit leaves nothing and repeats safely; a crash after commit is harmless via the observation
primary key. Out-of-cohort history records are discarded in memory — no row, id, label or
payload — and a stale ``startHistoryId`` (HTTP 404) is never an empty poll: ``incremental``
re-bootstraps through ``resync`` (new anchor, bounded re-enumeration reconciled by the observation
primary key, full catch-up, one atomic cursor replacement) and records a content-free marker row
for every attempt.

Cursor, lease, marker, cohort-seed and page-row persistence live in ``gmail_sync_state``; this
module owns orchestration only.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from probation.connectors.types import (
    ConnectorError,
    CursorRejected,
    HistoryStale,
    LabelTransition,
    LabelVersionEvidence,
    NativeRef,
    PayloadWriter,
    ProviderUnavailable,
    SourceObservation,
    SourceSelection,
    SyncCursor,
    advance_versions,
)
from probation.core.clock import Clock
from probation.db.gmail_store import ConnectorAccess
from probation.packs.mail.connectors.gmail_payloads import GmailPayloadStore
from probation.packs.mail.connectors.gmail_read import GmailReadConnector
from probation.packs.mail.connectors.gmail_sync_state import (
    _RESYNC_COMPLETE,
    DEFAULT_LEASE_SECONDS,
    ResyncMarker,
    ResyncStatus,
    SyncStateMixin,
)

__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "POLL_INTERVAL_SECONDS",
    "GmailSync",
    "ResyncMarker",
    "ResyncStatus",
    "SyncResult",
]

POLL_INTERVAL_SECONDS = 30
_RESYNC = "resync_required"


@dataclass(frozen=True)
class SyncResult:
    """Outcome of one sync run, safe to log: counts and flags, never message content."""

    pages_committed: int
    observations_written: int
    committed_history_id: int
    catchup_complete: bool
    resync_required: bool = False


class GmailSync(SyncStateMixin):
    """One ingestor worker driving cohort bootstrap and fenced incremental catch-up."""

    def __init__(
        self,
        *,
        access: ConnectorAccess,
        connector: GmailReadConnector,
        clock: Clock,
        connection_id: str,
        account_id: str,
        resource_key: str = "cohort",
        owner_label: str | None = None,
        payloads: PayloadWriter | None = None,
    ) -> None:
        self._access = access
        self._connector = connector
        self._clock = clock
        self._connection_id = connection_id
        self._account_id = account_id
        self._resource_key = resource_key
        self._owner_label = owner_label
        self._payloads = payloads if payloads is not None else self._private_payloads()

    def _private_payloads(self) -> PayloadWriter:
        """Contract section 12 root: ``<private_root>/connectors/payloads``, beside the store.

        Deriving it from the injected private store keeps one private root for both the metadata
        database and payload files, so the worker needs no new wiring and a test store under a
        temporary directory gets a temporary payload root.
        """
        row = self._access.conn.execute("PRAGMA database_list").fetchone()
        database = "" if row is None else str(row["file"])
        if not database or database == ":memory:":
            raise ConnectorError("payload_root_unavailable")
        return GmailPayloadStore(Path(database).parent / "payloads", self._connection_id)

    # -- bootstrap --------------------------------------------------------------------------
    def bootstrap(
        self, selection: SourceSelection, *, owner: str, page_size: int = 100
    ) -> SyncResult:
        if selection.selection_revision < 1:
            raise ConnectorError("invalid_selection_revision")
        fence = self.claim(owner, selection)
        anchor = self._connector.bootstrap_anchor()
        now = self._clock.now_iso()
        self._access.write(
            "gmail_sync_cursors",
            "UPDATE gmail_sync_cursors SET bootstrap_history_id=?,committed_history_id=?,"
            "updated_at=? WHERE connection_id=? AND resource_key=? AND role='read'"
            " AND filter_revision=? AND claim_owner=? AND fence=?",
            (
                anchor,
                anchor,
                now,
                self._connection_id,
                self._resource_key,
                selection.selection_revision,
                owner,
                fence,
            ),
        )
        written = 0
        committed = anchor
        pages = 0
        for ref in self._connector.enumerate_cohort(selection):
            observation = self._connector.observe(ref, observed_at=now, payloads=self._payloads)
            with self._access.transaction() as tx:
                written += self._write_observation(tx, observation)
                committed = max(committed, observation.history_id)
                self._advance(tx, selection, owner, fence, committed=committed, complete=False)
            pages += 1
        catchup = self._catch_up(
            selection,
            from_history_id=anchor,
            owner=owner,
            fence=fence,
            page_size=page_size,
            refresh_cohort=True,
        )
        written += catchup.observations_written
        committed = max(committed, catchup.committed_history_id)
        if catchup.resync_required:
            # A provider 404 during the bootstrap interval means the gap cannot be covered.
            # Installing a "complete" watermark here would present stale history as a clean
            # bootstrap, so the cursor stays incomplete and the caller must resync.
            with self._access.transaction() as tx:
                self._advance(tx, selection, owner, fence, committed=committed, complete=False)
            return SyncResult(
                pages + catchup.pages_committed, written, committed, False, resync_required=True
            )
        with self._access.transaction() as tx:
            self._advance(tx, selection, owner, fence, committed=committed, complete=True)
        return SyncResult(pages + catchup.pages_committed, written, committed, True)

    # -- incremental ------------------------------------------------------------------------
    def incremental(
        self, selection: SourceSelection, *, owner: str, page_size: int = 100
    ) -> SyncResult:
        row = self._cursor_row(selection)
        if row is None:
            raise CursorRejected("cursor_missing_run_bootstrap_first")
        if not int(row["catchup_complete"]):
            raise HistoryStale(_RESYNC)
        cursor = SyncCursor(
            connection_id=self._connection_id,
            account_id=self._account_id,
            resource_key=self._resource_key,
            role="read",
            filter_revision=selection.selection_revision,
            history_id=int(row["committed_history_id"]),
        )
        if not cursor.matches_selection(selection, self._resource_key):
            raise CursorRejected("cursor_selection_mismatch")
        fence = self.claim(owner, selection)
        result = self._catch_up(
            selection,
            from_history_id=cursor.history_id,
            owner=owner,
            fence=fence,
            page_size=page_size,
            refresh_cohort=True,
        )
        if not result.resync_required:
            return result
        # C3: a 404 is not "no changes". Re-bootstrap under the same fenced lease instead of
        # leaving the connection degraded until a human intervenes. Only a complete, committed
        # catch-up returns with ``resync_required`` cleared.
        return self.resync(selection, owner=owner, page_size=page_size)

    # -- resync -----------------------------------------------------------------------------
    def resync(self, selection: SourceSelection, *, owner: str, page_size: int = 100) -> SyncResult:
        """Re-bootstrap after stale provider history, replacing the cursor only on full success.

        The old watermark stays installed for the whole run: the cohort is re-enumerated and the
        new bootstrap interval is caught up with observations committed page by page, but nothing
        advances the cursor until one final transaction installs the new bootstrap anchor, the
        caught-up watermark and the completed marker together. A crash at any point therefore
        repeats safely — the observation primary key dedupes the replay and the untouched cursor
        never points past data that was not committed.
        """
        row = self._cursor_row(selection)
        if row is None:
            raise CursorRejected("cursor_missing_run_bootstrap_first")
        prior = int(row["committed_history_id"])
        fence = self.claim(owner, selection)
        anchor = self._connector.bootstrap_anchor()
        attempted_at = self._clock.now_iso()
        marker_key = self._begin_resync(selection, owner, fence, anchor, attempted_at)
        if anchor < prior:
            # Provider history ids are monotonic; a lower anchor means a different account or a
            # provider reset. Never move the cursor backwards.
            self._fail_resync(marker_key, fence, "resync_anchor_behind_cursor")
            return SyncResult(0, 0, prior, False, resync_required=True)
        pages = 0
        written = 0
        for ref in self._connector.enumerate_cohort(selection):
            try:
                observation = self._connector.observe(
                    ref, observed_at=attempted_at, payloads=self._payloads
                )
            except ProviderUnavailable as exc:
                if exc.safe_code == "provider_status_404":
                    # Gone between the id-only listing and the body fetch. Store no row and no
                    # tombstone fiction; a real deletion is only recorded from provider history.
                    continue
                raise
            with self._access.transaction() as tx:
                self._touch(tx, selection, owner, fence)
                written += self._write_observation(tx, observation)
            pages += 1
        # Cohort membership stays durable, so history for an already-selected message that has
        # since left the owner label is still applied rather than discarded as a stranger.
        cohort = set(self._connector.proven()) | self._stored_cohort()
        self._connector.prove(cohort)
        catchup = self._catch_up(
            selection,
            from_history_id=anchor,
            owner=owner,
            fence=fence,
            page_size=page_size,
            refresh_cohort=True,
            advance_cursor=False,
        )
        pages += catchup.pages_committed
        written += catchup.observations_written
        if catchup.resync_required:
            self._fail_resync(marker_key, fence, "provider_status_404")
            return SyncResult(pages, written, prior, False, resync_required=True)
        committed = max(anchor, catchup.committed_history_id)
        with self._access.transaction() as tx:
            self._install_cursor(tx, selection, owner, fence, anchor=anchor, committed=committed)
            self._finish_marker(tx, marker_key, fence, _RESYNC_COMPLETE, None, committed)
        return SyncResult(pages, written, committed, True)

    # -- shared history processing ----------------------------------------------------------
    def _catch_up(
        self,
        selection: SourceSelection,
        *,
        from_history_id: int,
        owner: str,
        fence: int,
        page_size: int,
        refresh_cohort: bool = False,
        advance_cursor: bool = True,
    ) -> SyncResult:
        # Cohort membership is durable, not connector-instance memory: a restarted worker holds
        # an empty proven set, and without the store-seeded tracking set every history record for
        # an already-selected message would be silently discarded as out-of-cohort. That would
        # break contract section 4 ("a selected message stays tracked after INBOX removal") and
        # the C2 label-transition honesty the undo guard depends on. Every id here was selected
        # and committed earlier, so no out-of-cohort identifier is read, proved or retained.
        cohort = set(self._connector.proven()) | self._stored_cohort()
        self._connector.prove(cohort)
        refreshed = not refresh_cohort
        committed = from_history_id
        written = 0
        pages = 0
        token: str | None = None
        while True:
            params: dict[str, object] = {"startHistoryId": from_history_id, "maxResults": page_size}
            if token is not None:
                params["pageToken"] = token
            try:
                payload = self._connector.history_page(params)
            except ProviderUnavailable as exc:
                if exc.safe_code == "provider_status_404":
                    return SyncResult(pages, written, committed, False, resync_required=True)
                raise
            records = payload.get("history", [])
            page = (
                [item for item in records if isinstance(item, dict)]
                if isinstance(records, list)
                else []
            )
            if not refreshed and _unknown_addition(page, cohort):
                # A post-bootstrap arrival carries no label list in ``messagesAdded``. One
                # id-only provider enumeration (never a body) proves which unknown ids are
                # inside the owner-approved selection; a stranger is never fetched.
                self._connector.enumerate_cohort(selection)
                cohort |= set(self._connector.proven())
                self._connector.prove(cohort)
                refreshed = True
            next_raw = payload.get("nextPageToken")
            next_token = str(next_raw) if next_raw else None
            now = self._clock.now_iso()
            # Provider body fetches happen before the write lock is taken: no network call may
            # hold the private store's ``BEGIN IMMEDIATE`` transaction open (fail-closed on a
            # slow provider, not on a stuck write lock).
            prefetched = [self._prefetch(entry, cohort, now) for entry in page]
            with self._access.transaction() as tx:
                max_id = 0
                for entry, observations in zip(page, prefetched, strict=True):
                    history_id = int(str(entry.get("id", "0") or "0"))
                    max_id = max(max_id, history_id)
                    written += self._apply_entry(
                        tx, selection, entry, history_id, cohort, observations, now
                    )
                committed = max(committed, max_id)
                if advance_cursor:
                    self._advance(
                        tx,
                        selection,
                        owner,
                        fence,
                        committed=committed,
                        complete=False,
                        page_token=next_token,
                    )
                else:
                    # A resync commits its observations per page but keeps the previous, truthful
                    # watermark until the whole interval has been caught up.
                    self._touch(tx, selection, owner, fence)
            pages += 1
            if next_token is None:
                return SyncResult(pages, written, committed, False)
            token = next_token

    def _prefetch(
        self, entry: dict[str, object], cohort: set[str], now: str
    ) -> dict[str, SourceObservation]:
        """Body fetches for one page's in-cohort arrivals, performed before any lock is taken.

        The owner-label additions this entry itself applies grow the cohort before ``messagesAdded``
        is written, so a same-entry ``labelAdded``+``messagesAdded`` arrival is fetched exactly as
        ``_apply_entry`` will later treat it: in-cohort.
        """
        grown = {
            str(message.get("id", ""))
            for record in _records(entry, "labelAdded")
            if self._owner_label is not None and str(record.get("labelId", "")) == self._owner_label
            for message in _messages(record)
        }
        observations: dict[str, SourceObservation] = {}
        for message in _records(entry, "messagesAdded"):
            mid = str(message.get("id", ""))
            if mid in cohort or mid in grown:
                ref = NativeRef(self._connection_id, self._account_id, mid)
                observations[mid] = self._connector.observe(
                    ref, observed_at=now, payloads=self._payloads
                )
        return observations

    def _apply_entry(
        self,
        tx: ConnectorAccess,
        selection: SourceSelection,
        entry: dict[str, object],
        history_id: int,
        cohort: set[str],
        observations: dict[str, SourceObservation],
        now: str,
    ) -> int:
        written = 0
        grown: set[str] = set()
        shrunk: set[str] = set()
        for label_event, added in (("labelAdded", True), ("labelRemoved", False)):
            for record in _records(entry, label_event):
                label_id = str(record.get("labelId", ""))
                is_owner = self._owner_label is not None and label_id == self._owner_label
                for message in _messages(record):
                    mid = str(message.get("id", ""))
                    if is_owner and added:
                        grown.add(mid)
                        cohort.add(mid)  # the owner label defines the cohort
                    if mid not in cohort:
                        continue  # out-of-cohort: no row, no id, no label name, no payload
                    written += self._write_label_event(
                        tx,
                        history_id=history_id,
                        native_message_id=mid,
                        label_id=label_id,
                        label_event=label_event,
                        now=now,
                    )
                    if is_owner and not added:
                        shrunk.add(mid)
        self._connector.prove(grown)
        for message in _records(entry, "messagesAdded"):
            mid = str(message.get("id", ""))
            observation = observations.get(mid)
            if observation is not None:
                written += self._write_observation(tx, observation)
        for message in _records(entry, "messagesDeleted"):
            mid = str(message.get("id", ""))
            if mid in cohort:
                written += self._write_tombstone(
                    tx, native_message_id=mid, history_id=history_id, now=now
                )
                shrunk.add(mid)
        cohort.difference_update(shrunk)
        return written

    # -- label version evidence (Executor undo honesty) -------------------------------------
    def build_label_evidence(
        self,
        selection: SourceSelection,
        native_message_id: str,
        *,
        anchor_history_id: int,
        resync_required: bool = False,
    ) -> LabelVersionEvidence:
        row = self._cursor_row(selection)
        transitions: list[LabelTransition] = []
        for event in self._access.query(
            "SELECT label_id,event_type,history_id FROM gmail_history_events WHERE connection_id=?"
            " AND native_message_id=? AND history_id> ? AND event_type IN ('labelAdded','labelRemoved')"
            " ORDER BY history_id ASC",
            (self._connection_id, native_message_id, anchor_history_id),
        ):
            transitions.append(
                LabelTransition(
                    native_message_id=native_message_id,
                    label_id=str(event["label_id"]),
                    history_id=int(event["history_id"]),
                    added=str(event["event_type"]) == "labelAdded",
                )
            )
        continuous = (
            not resync_required
            and row is not None
            and _window_is_continuous(row, anchor_history_id)
        )
        return LabelVersionEvidence(
            native_message_id=native_message_id,
            versions=advance_versions({}, tuple(transitions), native_message_id),
            continuous=continuous,
            anchor_history_id=anchor_history_id,
        )


def _window_is_continuous(row: sqlite3.Row, anchor_history_id: int) -> bool:
    bootstrap = row["bootstrap_history_id"]
    if bootstrap is None or not bool(row["catchup_complete"]):
        return False
    return anchor_history_id >= int(bootstrap)


def _records(entry: dict[str, object], key: str) -> list[dict[str, object]]:
    value = entry.get(key, [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _unknown_addition(entries: list[dict[str, object]], cohort: set[str]) -> bool:
    """True when a page names a ``messagesAdded`` id the durable cohort cannot vouch for."""
    for entry in entries:
        for message in _records(entry, "messagesAdded"):
            if str(message.get("id", "")) not in cohort:
                return True
    return False


def _messages(record: dict[str, object]) -> list[dict[str, object]]:
    value = record.get("messages", [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
