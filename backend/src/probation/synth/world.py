"""Simulated world state database and manager (SimWorld).

Authority: docs/PACKS_SPEC.md section 0.5 and docs/CONTRACT.md section 8 (I-17).
Provides SQLite-backed mailbox, calendar, files catalog, and task lists
completely decoupled from the engine database.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

from probation.core.clock import timestamp_key
from probation.core.identity import normalize_user_addresses


def _exists_at(value: str, bound: str) -> bool:
    """True when an item's own timestamp is at or before `bound`.

    Compares instants rather than spellings, matching the `UTC_TIMESTAMP` collation the engine
    database uses. An unparseable timestamp fails closed: an item whose arrival cannot be placed
    in time is treated as not yet present instead of being shown to an earlier observer.
    """
    try:
        return timestamp_key(value) <= timestamp_key(bound)
    except ValueError:
        return False


WORLD_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    message_id TEXT UNIQUE NOT NULL,
    thread_id TEXT NOT NULL,
    from_addr TEXT NOT NULL,
    to_addr TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    labels TEXT NOT NULL DEFAULT '["INBOX"]',
    received_at TEXT NOT NULL,
    in_reply_to TEXT,
    has_attachment INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_msg_thread ON messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_msg_received ON messages(received_at);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    organizer TEXT NOT NULL,
    attendees TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'CONFIRMED',
    my_status TEXT NOT NULL DEFAULT 'NEEDS_ACTION'
);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_time);

CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    ext TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    origin_url TEXT NOT NULL DEFAULT '',
    downloaded_at TEXT NOT NULL,
    sha256 TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'TODO',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tracker (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    organizer TEXT NOT NULL,
    opp_type TEXT NOT NULL DEFAULT 'other',
    deadline_date TEXT,
    official_url TEXT,
    status TEXT NOT NULL DEFAULT 'TRACKED',
    fee_flag INTEGER NOT NULL DEFAULT 0,
    sources_json TEXT NOT NULL DEFAULT '[]',
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tracker_status ON tracker(status);

CREATE TABLE IF NOT EXISTS library (
    id TEXT PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    title TEXT,
    collection TEXT NOT NULL DEFAULT 'inbox',
    topic TEXT,
    content_type TEXT,
    saved_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_library_col ON library(collection);

CREATE TABLE IF NOT EXISTS user_actions (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    acted_at TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'user',
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_actions_acted ON user_actions(acted_at);
CREATE INDEX IF NOT EXISTS idx_actions_item ON user_actions(item_id);

CREATE TABLE IF NOT EXISTS world_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class SimWorld:
    """Manages the simulated environment state in world.db."""

    def __init__(
        self,
        db_path: str | Path,
        user_addresses: list[str] | str | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        # Whose world this is. `None` means "not told", so callers fall back to the persisted
        # or configured owner rather than concluding the mailbox has no owner. Supplying it
        # here is what lets a resolver attribute a sent message or an RSVP to the owner
        # instead of reading every record as someone else's (plan section 6.1.3).
        self.user_addresses: list[str] | None = (
            None if user_addresses is None else normalize_user_addresses(user_addresses)
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_db()
        if self.user_addresses is None:
            # Reopening a world must not lose whose world it is: a resolver that cannot name the
            # owner attributes no sent message and no RSVP to them, so every outcome collapses to
            # its WEAK default (plan section 6.1.3).
            stored = self._get_meta("user_addresses")
            if stored:
                self.user_addresses = normalize_user_addresses(json.loads(stored))
        else:
            self._set_meta("user_addresses", json.dumps(self.user_addresses))

    def _init_db(self) -> None:
        """Apply world schema."""
        self.conn.executescript(WORLD_SCHEMA)
        self.conn.commit()

    def _get_meta(self, key: str) -> str | None:
        """Read one world metadata value.

        The table is `world_meta`, not `meta`: the engine schema owns `meta` and the two schemas
        must stay independent even when a caller applies both to one connection (CONTRACT I-17).
        """
        row = self.conn.execute("SELECT value FROM world_meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def _set_meta(self, key: str, value: str) -> None:
        """Write one world metadata value."""
        self.conn.execute(
            "INSERT OR REPLACE INTO world_meta (key, value) VALUES (?, ?)",
            (key, value),
        )
        self.conn.commit()

    def declare_initial_state(self) -> None:
        """Record that stored labels and RSVP status are the state at world creation.

        Only the writer may declare this. A world that baked the *final* state into those columns
        has no footprints to replay, so projecting them at an earlier `as_of` would hand a resolver
        an outcome that has not happened yet (CONTRACT I-6). Undeclared worlds are therefore read
        conservatively by `_project_message_labels` and `_project_event_status`.
        """
        self._set_meta("state_model", "initial")

    @property
    def stores_initial_state(self) -> bool:
        """Whether the stored columns may be trusted as the pre-footprint state."""
        return self._get_meta("state_model") == "initial"

    def close(self) -> None:
        """Close connection."""
        self.conn.close()

    def __enter__(self) -> "SimWorld":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    # --- Mailbox Operations ---

    def add_message(
        self,
        msg_id: str,
        message_id: str,
        thread_id: str,
        from_addr: str,
        to_addr: str,
        subject: str,
        body: str,
        labels: list[str],
        received_at: str,
        in_reply_to: str | None = None,
        has_attachment: bool = False,
    ) -> None:
        """Insert or replace a message in world.db."""
        self.conn.execute(
            """
            INSERT OR REPLACE INTO messages
            (id, message_id, thread_id, from_addr, to_addr, subject, body, labels, received_at, in_reply_to, has_attachment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                msg_id,
                message_id,
                thread_id,
                from_addr,
                to_addr,
                subject,
                body,
                json.dumps(labels),
                received_at,
                in_reply_to,
                1 if has_attachment else 0,
            ),
        )
        self.conn.commit()

    def get_messages(
        self, label: str | None = None, as_of: str | None = None
    ) -> list[dict[str, Any]]:
        """Retrieve messages, optionally filtering by label and projecting state as of a timestamp."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM messages ORDER BY received_at ASC")
        rows = cur.fetchall()
        results: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            if as_of is not None and not _exists_at(str(d["received_at"]), as_of):
                continue
            labels = list(json.loads(d["labels"]))
            if as_of is not None:
                labels = self._project_message_labels(d["message_id"], labels, as_of)
            d["labels"] = labels
            if label is None or label in labels:
                results.append(d)
        return results

    def get_message(self, message_id: str, as_of: str | None = None) -> dict[str, Any] | None:
        """Retrieve single message by Message-ID, optionally projected as of a timestamp."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM messages WHERE message_id = ?", (message_id,))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        if as_of is not None and not _exists_at(str(d["received_at"]), as_of):
            return None
        labels = list(json.loads(d["labels"]))
        if as_of is not None:
            labels = self._project_message_labels(message_id, labels, as_of)
        d["labels"] = labels
        return d

    def _project_message_labels(
        self, message_id: str, current_labels: list[str], as_of: str
    ) -> list[str]:
        """Project message labels as of a specific timestamp based on recorded actions."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT action_type, acted_at FROM user_actions WHERE item_id = ? AND acted_at <= ? ORDER BY acted_at ASC",
            (message_id, as_of),
        )
        actions = cur.fetchall()
        if not self.stores_initial_state:
            # Undeclared world: the stored labels may already be the final state, so only a dated
            # footprint can prove a label existed at `as_of`. Starting from INBOX is the one state
            # that is true of every message before the owner has done anything to it.
            if not actions:
                return ["INBOX"]
            labels = {"INBOX"}
        else:
            labels = set(current_labels)
        for act in actions:
            atype = act["action_type"]
            if atype == "TRASH":
                labels.discard("INBOX")
                labels.add("TRASH")
            elif atype == "ARCHIVE":
                labels.discard("INBOX")
                labels.add("ARCHIVED")
        return sorted(labels)

    def update_message_labels(
        self,
        message_id: str,
        add_labels: list[str] | None = None,
        remove_labels: list[str] | None = None,
    ) -> None:
        """Update label set for a message."""
        msg = self.get_message(message_id)
        if not msg:
            return
        labels = set(msg["labels"])
        if add_labels:
            labels.update(add_labels)
        if remove_labels:
            labels.difference_update(remove_labels)
        self.conn.execute(
            "UPDATE messages SET labels = ? WHERE message_id = ?",
            (json.dumps(sorted(labels)), message_id),
        )
        self.conn.commit()

    # --- Calendar Operations ---

    def add_event(
        self,
        event_id: str,
        uid: str,
        title: str,
        description: str,
        start_time: str,
        end_time: str,
        organizer: str,
        attendees: list[str],
        status: str = "CONFIRMED",
        my_status: str = "NEEDS_ACTION",
    ) -> None:
        """Insert or replace a calendar event in world.db."""
        self.conn.execute(
            """
            INSERT OR REPLACE INTO events
            (id, uid, title, description, start_time, end_time, organizer, attendees, status, my_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                uid,
                title,
                description,
                start_time,
                end_time,
                organizer,
                json.dumps(attendees),
                status,
                my_status,
            ),
        )
        self.conn.commit()

    def get_events(self, as_of: str | None = None) -> list[dict[str, Any]]:
        """Retrieve all calendar events, optionally projected as of timestamp.

        Events are not existence-bounded by `as_of`: the table records only when an event *starts*,
        and an invite must be visible before it starts or its RSVP window could never be observed.
        Only the response status is projected.
        """
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM events ORDER BY start_time ASC")
        rows = cur.fetchall()
        results: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["attendees"] = json.loads(d["attendees"])
            if as_of is not None:
                d["my_status"] = self._project_event_status(
                    d["uid"], d.get("my_status", "NEEDS_ACTION"), as_of
                )
            results.append(d)
        return results

    def get_event(self, uid: str, as_of: str | None = None) -> dict[str, Any] | None:
        """Get event by UID, optionally projected as of timestamp."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM events WHERE uid = ?", (uid,))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        d["attendees"] = json.loads(d["attendees"])
        if as_of is not None:
            d["my_status"] = self._project_event_status(
                uid, d.get("my_status", "NEEDS_ACTION"), as_of
            )
        return d

    def _project_event_status(self, uid: str, current_status: str, as_of: str) -> str:
        """Project attendee response status as of timestamp."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT action_type FROM user_actions WHERE item_id = ? AND acted_at <= ? ORDER BY acted_at ASC",
            (uid, as_of),
        )
        actions = cur.fetchall()
        # An undeclared world may already hold the final RSVP in `my_status`, so without a dated
        # footprint the only safe reading is that the owner has not responded yet.
        fallback = current_status if self.stores_initial_state else "NEEDS_ACTION"
        if not actions:
            return fallback
        last_action = actions[-1]["action_type"]
        if last_action in ("ACCEPT", "DECLINE", "TENTATIVE"):
            return f"{last_action}ED" if last_action != "TENTATIVE" else "TENTATIVE"
        return fallback

    def update_rsvp(self, uid: str, rsvp_status: str) -> None:
        """Update user attendee response status (ACCEPTED, DECLINED, TENTATIVE)."""
        self.conn.execute(
            "UPDATE events SET my_status = ? WHERE uid = ?",
            (rsvp_status.upper(), uid),
        )
        self.conn.commit()

    def delete_event(self, uid: str) -> None:
        """Delete an event (used for undo)."""
        self.conn.execute("DELETE FROM events WHERE uid = ?", (uid,))
        self.conn.commit()

    # --- File Catalog Operations ---

    def add_file(
        self,
        file_id: str,
        path: str,
        filename: str,
        ext: str,
        size_bytes: int,
        origin_url: str,
        downloaded_at: str,
        sha256: str,
    ) -> None:
        """Add record of downloaded file."""
        self.conn.execute(
            """
            INSERT OR REPLACE INTO files
            (id, path, filename, ext, size_bytes, origin_url, downloaded_at, sha256)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (file_id, path, filename, ext, size_bytes, origin_url, downloaded_at, sha256),
        )
        self.conn.commit()

    def get_files(self, as_of: str | None = None) -> list[dict[str, Any]]:
        """Retrieve all file catalog entries, optionally projected as of timestamp."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM files ORDER BY downloaded_at ASC")
        rows = cur.fetchall()
        results: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            if as_of is not None:
                if not _exists_at(str(d["downloaded_at"]), as_of):
                    continue
                acts = self.conn.cursor()
                acts.execute(
                    "SELECT details_json FROM user_actions WHERE item_id = ? AND acted_at <= ? ORDER BY acted_at ASC",
                    (d["path"], as_of),
                )
                # The last move before `as_of` decides where the file is; taking the first would
                # report a stale destination for anything relocated more than once.
                dest = ""
                for act in acts.fetchall():
                    try:
                        candidate = json.loads(act["details_json"]).get("destination_path")
                    except (ValueError, TypeError, AttributeError):
                        continue
                    if candidate:
                        dest = str(candidate)
                if dest:
                    d["path"] = dest
            results.append(d)
        return results

    # --- User and System Action Stream ---

    def record_user_action(
        self,
        action_id: str,
        item_id: str,
        action_type: str,
        acted_at: str,
        actor: str = "user",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record a dated user or system action in world.db.

        Authority: docs/CHANGES_IMPLEMENTATION_PLAN.md section 6.2.1, 6.2.5.
        """
        details_str = json.dumps(details or {})
        self.conn.execute(
            """
            INSERT OR REPLACE INTO user_actions
            (id, item_id, action_type, acted_at, actor, details_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (action_id, item_id, action_type, acted_at, actor, details_str),
        )
        self.conn.commit()

    def get_user_actions(
        self,
        item_id: str | None = None,
        as_of: str | None = None,
        actor: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve recorded actions with optional filtering."""
        query = "SELECT * FROM user_actions WHERE 1=1"
        params: list[Any] = []
        if item_id:
            query += " AND item_id = ?"
            params.append(item_id)
        if as_of:
            query += " AND acted_at <= ?"
            params.append(as_of)
        if actor:
            query += " AND actor = ?"
            params.append(actor)
        query += " ORDER BY acted_at ASC"
        cur = self.conn.cursor()
        cur.execute(query, tuple(params))
        res: list[dict[str, Any]] = []
        for r in cur.fetchall():
            d = dict(r)
            try:
                d["details"] = json.loads(d["details_json"])
            except Exception:
                d["details"] = {}
            res.append(d)
        return res

    # --- Task Operations ---

    def add_task(
        self,
        task_id: str,
        title: str,
        due_date: str | None,
        created_at: str,
        status: str = "TODO",
    ) -> None:
        """Insert or replace a task."""
        self.conn.execute(
            """
            INSERT OR REPLACE INTO tasks (id, title, due_date, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (task_id, title, due_date, status, created_at),
        )
        self.conn.commit()

    def get_tasks(self) -> list[dict[str, Any]]:
        """Retrieve all tasks."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM tasks ORDER BY created_at ASC")
        return [dict(r) for r in cur.fetchall()]

    def delete_task(self, task_id: str) -> None:
        """Delete task by ID."""
        self.conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.conn.commit()

    # --- Opportunity Radar Tracker Operations ---

    def add_tracker_entry(
        self,
        entry_id: str,
        title: str,
        organizer: str,
        opp_type: str = "other",
        deadline_date: str | None = None,
        official_url: str | None = None,
        status: str = "TRACKED",
        fee_flag: bool = False,
        sources: list[dict[str, Any]] | None = None,
        details: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> None:
        """Insert or replace an opportunity in the Radar tracker."""
        now_iso = created_at or "2026-10-20T12:00:00Z"
        sources_json = json.dumps(sources or [])
        details_json = json.dumps(details or {})
        self.conn.execute(
            """
            INSERT OR REPLACE INTO tracker
            (id, title, organizer, opp_type, deadline_date, official_url, status, fee_flag, sources_json, details_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                title,
                organizer,
                opp_type,
                deadline_date,
                official_url,
                status,
                1 if fee_flag else 0,
                sources_json,
                details_json,
                now_iso,
                now_iso,
            ),
        )
        self.conn.commit()

    def get_tracker_entries(self, status: str | None = None) -> list[dict[str, Any]]:
        """Retrieve all tracker entries, optionally filtering by status."""
        cur = self.conn.cursor()
        if status is not None:
            cur.execute(
                "SELECT * FROM tracker WHERE status = ? ORDER BY updated_at DESC", (status,)
            )
        else:
            cur.execute("SELECT * FROM tracker ORDER BY updated_at DESC")
        results: list[dict[str, Any]] = []
        for r in cur.fetchall():
            d = dict(r)
            try:
                d["sources"] = json.loads(d["sources_json"])
            except Exception:
                d["sources"] = []
            try:
                d["details"] = json.loads(d["details_json"])
            except Exception:
                d["details"] = {}
            results.append(d)
        return results

    def get_tracker_entry(self, entry_id: str) -> dict[str, Any] | None:
        """Retrieve single tracker entry by ID."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM tracker WHERE id = ?", (entry_id,))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["sources"] = json.loads(d["sources_json"])
        except Exception:
            d["sources"] = []
        try:
            d["details"] = json.loads(d["details_json"])
        except Exception:
            d["details"] = {}
        return d

    def update_tracker_status(self, entry_id: str, status: str) -> None:
        """Update tracker entry status (e.g. DISMISSED, TRACKED, APPLIED)."""
        self.conn.execute(
            "UPDATE tracker SET status = ? WHERE id = ?",
            (status, entry_id),
        )
        self.conn.commit()

    def delete_tracker_entry(self, entry_id: str) -> None:
        """Delete tracker entry by ID (used for undo)."""
        self.conn.execute("DELETE FROM tracker WHERE id = ?", (entry_id,))
        self.conn.commit()

    # --- Reading Triage Library Operations ---

    def add_library_entry(
        self,
        entry_id: str,
        url: str,
        title: str = "",
        collection: str = "inbox",
        topic: str = "other",
        content_type: str = "article",
        saved_at: str | None = None,
    ) -> None:
        """Insert or replace a saved link in the Reading library."""
        now_iso = saved_at or "2026-10-20T12:00:00Z"
        self.conn.execute(
            """
            INSERT OR REPLACE INTO library
            (id, url, title, collection, topic, content_type, saved_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (entry_id, url, title, collection, topic, content_type, now_iso, now_iso),
        )
        self.conn.commit()

    def get_library_entries(self, collection: str | None = None) -> list[dict[str, Any]]:
        """Retrieve library entries, optionally filtering by collection."""
        cur = self.conn.cursor()
        if collection is not None:
            cur.execute(
                "SELECT * FROM library WHERE collection = ? ORDER BY updated_at DESC", (collection,)
            )
        else:
            cur.execute("SELECT * FROM library ORDER BY updated_at DESC")
        return [dict(r) for r in cur.fetchall()]

    def get_library_entry(self, url: str) -> dict[str, Any] | None:
        """Retrieve single library entry by URL."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM library WHERE url = ?", (url,))
        row = cur.fetchone()
        return dict(row) if row else None

    def update_library_collection(self, url: str, collection: str) -> None:
        """Update collection category for a saved link."""
        self.conn.execute(
            "UPDATE library SET collection = ? WHERE url = ?",
            (collection, url),
        )
        self.conn.commit()

    def delete_library_entry(self, url: str) -> None:
        """Delete library entry by URL."""
        self.conn.execute("DELETE FROM library WHERE url = ?", (url,))
        self.conn.commit()
