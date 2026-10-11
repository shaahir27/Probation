"""Idempotent source data importers for mail, calendar, files, and links.

Authority: docs/PACKS_SPEC.md section 6, docs/DATA_MODEL.md sections 1-2, CONTRACT I-19.
Populates sources and raw_items with mathematical idempotency and deterministic IDs.
"""

import email
import email.utils
import hashlib
import json
import mailbox
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from probation.core.hashing import canonical_json, det_id


@dataclass(frozen=True)
class ImportResult:
    """Result of an idempotent import operation."""

    source_id: str
    pack: str
    kind: str
    items_imported: int
    items_skipped: int


def _iso_utc(dt_or_str: Any) -> str:
    """Normalize date representations to ISO-8601 UTC with trailing 'Z'."""
    if isinstance(dt_or_str, datetime):
        if dt_or_str.tzinfo is None:
            dt = dt_or_str.replace(tzinfo=UTC)
        else:
            dt = dt_or_str.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    elif isinstance(dt_or_str, str):
        clean = dt_or_str.strip()
        if clean.endswith("Z"):
            return clean
        try:
            # Parse RFC 2822
            parsed_parsed = email.utils.parsedate_to_datetime(clean)
            return parsed_parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            try:
                dt = datetime.fromisoformat(clean)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_or_create_source(
    conn: sqlite3.Connection,
    pack: str,
    kind: str,
    ref: str,
) -> str:
    """Register origin source record and return deterministic source_id."""
    source_id = det_id("source", pack, kind, str(ref))
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """
        INSERT OR IGNORE INTO sources (id, pack, kind, ref, imported_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (source_id, pack, kind, str(ref), now),
    )
    conn.commit()
    return source_id


def import_mail(
    mbox_path: str | Path,
    conn: sqlite3.Connection,
    user_addresses: list[str] | None = None,
) -> ImportResult:
    """Import an .mbox archive into raw_items idempotently.

    Authority: docs/PACKS_SPEC.md section 6.
    """
    path = Path(mbox_path)
    if not path.exists():
        raise FileNotFoundError(f"Mbox file not found: {path}")

    source_id = _get_or_create_source(conn, "mail", "mbox", str(path))
    user_addrs = [a.lower().strip() for a in (user_addresses or [])]

    mbox = mailbox.mbox(str(path))
    imported = 0
    skipped = 0

    cursor = conn.cursor()

    for msg in mbox:
        msg_id_hdr = msg.get("Message-ID", "")
        msg_ref = msg_id_hdr.strip() if msg_id_hdr else ""
        from_hdr = msg.get("From", "")
        to_hdr = msg.get("To", "")
        subject_hdr = msg.get("Subject", "")
        date_hdr = msg.get("Date", "")
        labels_hdr = msg.get("X-Gmail-Labels", "")
        in_reply_hdr = msg.get("In-Reply-To", "")

        occurred_at = _iso_utc(date_hdr)

        if not msg_ref:
            msg_ref = f"<det-{det_id(from_hdr, to_hdr, subject_hdr, occurred_at)}@local>"

        # Determine if sent by user
        sender_clean = from_hdr.lower()
        is_sent = any(u in sender_clean for u in user_addrs) if user_addrs else False
        item_kind = "mail_sent" if is_sent else "mail_in"

        # Extract body
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        payload_bytes = part.get_payload(decode=True)
                        if isinstance(payload_bytes, bytes):
                            body = payload_bytes.decode(errors="replace")
                            break
                    except Exception:
                        pass
        else:
            try:
                payload_bytes = msg.get_payload(decode=True)
                if isinstance(payload_bytes, bytes):
                    body = payload_bytes.decode(errors="replace")
                else:
                    body = str(msg.get_payload() or "")
            except Exception:
                body = str(msg.get_payload() or "")

        labels = [lbl.strip() for lbl in labels_hdr.split(",") if lbl.strip()] if labels_hdr else []

        payload = {
            "message_id": msg_ref,
            "from": from_hdr,
            "to": to_hdr,
            "subject": subject_hdr,
            "body": body,
            "labels": labels,
            "in_reply_to": in_reply_hdr or None,
            "has_attachment": any(
                part.get_content_disposition() == "attachment"
                for part in (msg.walk() if msg.is_multipart() else [])
            ),
        }
        payload_str = canonical_json(payload)
        content_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
        raw_id = det_id(source_id, msg_ref)

        try:
            cursor.execute(
                """
                INSERT INTO raw_items
                (id, source_id, pack, item_kind, source_ref, occurred_at, known_at, payload_json, content_hash)
                VALUES (?, ?, 'mail', ?, ?, ?, ?, ?, ?)
                """,
                (
                    raw_id,
                    source_id,
                    item_kind,
                    msg_ref,
                    occurred_at,
                    occurred_at,
                    payload_str,
                    content_hash,
                ),
            )
            imported += 1
        except sqlite3.IntegrityError:
            skipped += 1

    conn.commit()
    return ImportResult(source_id, "mail", "mbox", imported, skipped)


def import_calendar(
    ics_path: str | Path,
    conn: sqlite3.Connection,
    user_addresses: list[str] | None = None,
) -> ImportResult:
    """Import an RFC-5545 .ics file into raw_items idempotently.

    Authority: docs/PACKS_SPEC.md section 6.
    """
    path = Path(ics_path)
    if not path.exists():
        raise FileNotFoundError(f"ICS file not found: {path}")

    source_id = _get_or_create_source(conn, "calendar", "ics", str(path))
    user_addrs = [a.lower().strip() for a in (user_addresses or [])]

    imported = 0
    skipped = 0
    cursor = conn.cursor()

    content = path.read_text(encoding="utf-8", errors="replace")

    # Parse VEVENT blocks
    event_blocks = re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", content, re.DOTALL)

    for block in event_blocks:
        fields: dict[str, str] = {}
        for line in block.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            key_part, val = line.split(":", 1)
            key = key_part.split(";")[0].upper()
            fields[key] = val

        uid = fields.get("UID", "")
        if not uid:
            continue

        def parse_ics_date(s: str | None) -> str:
            if not s:
                return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            s = s.strip()
            if len(s) == 16 and s.endswith("Z"):  # YYYYMMDDTHHMMSSZ
                try:
                    dt = datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
                    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    pass
            return _iso_utc(s)

        start_time = parse_ics_date(fields.get("DTSTART"))
        end_time = parse_ics_date(fields.get("DTEND"))
        occurred_at = start_time
        title = fields.get("SUMMARY", "")
        desc = fields.get("DESCRIPTION", "").replace("\\n", "\n")
        organizer = fields.get("ORGANIZER", "").replace("mailto:", "")

        # Extract attendees
        attendees: list[str] = []
        for line in block.splitlines():
            if line.upper().startswith("ATTENDEE"):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    attendees.append(parts[1].replace("mailto:", "").strip())

        is_organizer = any(u in organizer.lower() for u in user_addrs) if user_addrs else False
        item_kind = "cal_event" if is_organizer else "invite"

        payload = {
            "uid": uid,
            "title": title,
            "description": desc,
            "start_time": start_time,
            "end_time": end_time,
            "organizer": organizer,
            "attendees": attendees,
            "status": fields.get("STATUS", "CONFIRMED"),
        }
        payload_str = canonical_json(payload)
        content_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
        raw_id = det_id(source_id, uid)

        try:
            cursor.execute(
                """
                INSERT INTO raw_items
                (id, source_id, pack, item_kind, source_ref, occurred_at, known_at, payload_json, content_hash)
                VALUES (?, ?, 'calendar', ?, ?, ?, ?, ?, ?)
                """,
                (
                    raw_id,
                    source_id,
                    item_kind,
                    uid,
                    occurred_at,
                    occurred_at,
                    payload_str,
                    content_hash,
                ),
            )
            imported += 1
        except sqlite3.IntegrityError:
            skipped += 1

    conn.commit()
    return ImportResult(source_id, "calendar", "ics", imported, skipped)


def import_files(
    manifest_path: str | Path,
    conn: sqlite3.Connection,
) -> ImportResult:
    """Import folder snapshot manifest into raw_items idempotently.

    Authority: docs/PACKS_SPEC.md section 6.
    """
    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")

    source_id = _get_or_create_source(conn, "files", "folder_snapshot", str(path))

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    files_list = data.get("files", [])
    imported = 0
    skipped = 0
    cursor = conn.cursor()

    for f_info in files_list:
        rel_path = f_info["rel_path"]
        occurred_at = _iso_utc(f_info.get("mtime", datetime.now(UTC)))

        payload = {
            "rel_path": rel_path,
            "filename": f_info.get("filename", Path(rel_path).name),
            "ext": f_info.get("ext", Path(rel_path).suffix.lstrip(".")),
            "size_bytes": f_info.get("size_bytes", 0),
            "mtime": occurred_at,
            "sha256": f_info.get("sha256", ""),
            "origin_url": f_info.get("origin_url", ""),
        }
        payload_str = canonical_json(payload)
        content_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
        raw_id = det_id(source_id, rel_path)

        try:
            cursor.execute(
                """
                INSERT INTO raw_items
                (id, source_id, pack, item_kind, source_ref, occurred_at, known_at, payload_json, content_hash)
                VALUES (?, ?, 'files', 'file', ?, ?, ?, ?, ?)
                """,
                (
                    raw_id,
                    source_id,
                    rel_path,
                    occurred_at,
                    occurred_at,
                    payload_str,
                    content_hash,
                ),
            )
            imported += 1
        except sqlite3.IntegrityError:
            skipped += 1

    conn.commit()
    return ImportResult(source_id, "files", "folder_snapshot", imported, skipped)


def import_links(
    links_path: str | Path,
    conn: sqlite3.Connection,
) -> ImportResult:
    """Import saved links into raw_items idempotently.

    Authority: docs/PACKS_SPEC.md section 6.
    """
    path = Path(links_path)
    if not path.exists():
        raise FileNotFoundError(f"Links file not found: {path}")

    source_id = _get_or_create_source(conn, "links", "link_list", str(path))
    imported = 0
    skipped = 0
    cursor = conn.cursor()

    # Supports JSON list or newline-separated URL list
    entries: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8")
    try:
        loaded = json.loads(text)
        if isinstance(loaded, list):
            for item in loaded:
                if isinstance(item, str):
                    entries.append({"url": item})
                elif isinstance(item, dict):
                    entries.append(item)
    except Exception:
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                entries.append({"url": line})

    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    for entry in entries:
        url = entry.get("url", "").strip()
        if not url:
            continue
        occurred_at = _iso_utc(entry.get("saved_at", now_iso))
        payload = {
            "url": url,
            "title": entry.get("title", ""),
            "saved_at": occurred_at,
        }
        payload_str = canonical_json(payload)
        content_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
        raw_id = det_id(source_id, url)

        try:
            cursor.execute(
                """
                INSERT INTO raw_items
                (id, source_id, pack, item_kind, source_ref, occurred_at, known_at, payload_json, content_hash)
                VALUES (?, ?, 'links', 'link_saved', ?, ?, ?, ?, ?)
                """,
                (
                    raw_id,
                    source_id,
                    url,
                    occurred_at,
                    occurred_at,
                    payload_str,
                    content_hash,
                ),
            )
            imported += 1
        except sqlite3.IntegrityError:
            skipped += 1

    conn.commit()
    return ImportResult(source_id, "links", "link_list", imported, skipped)
