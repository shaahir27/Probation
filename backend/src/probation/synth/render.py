"""Renderers for synthetic events: .mbox, .ics, filesystem directories, and manifest.

Authority: docs/EVALUATION_PLAN.md section 2.5 and docs/PACKS_SPEC.md sections 0.5, 6.
Generates RFC-compliant file formats matching real data sources.
"""

import email.utils
import hashlib
import json
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any


def render_mbox(messages: list[dict[str, Any]], output_path: str | Path) -> None:
    """Render a list of messages into a standard RFC-822 .mbox file.

    Authority: docs/PACKS_SPEC.md section 6.
    """
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    with open(out_file, "wb") as f:
        for msg_data in messages:
            msg = EmailMessage()
            msg["From"] = msg_data["from_addr"]
            msg["To"] = msg_data["to_addr"]
            msg["Subject"] = msg_data["subject"]
            msg["Message-ID"] = msg_data["message_id"]

            # Parse date string to RFC 2822 format
            date_str = msg_data["occurred_at"]
            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                msg["Date"] = email.utils.format_datetime(dt)
            except Exception:
                msg["Date"] = date_str

            if msg_data.get("in_reply_to"):
                msg["In-Reply-To"] = msg_data["in_reply_to"]
                msg["References"] = msg_data["in_reply_to"]

            if msg_data.get("labels"):
                msg["X-Gmail-Labels"] = ", ".join(msg_data["labels"])

            if msg_data.get("is_automated"):
                msg["Precedence"] = "bulk"
                msg["List-Unsubscribe"] = "<mailto:unsubscribe@example.com>"

            msg.set_content(msg_data["body"])

            # Write standard mbox 'From ' envelope header followed by message bytes
            envelope_from = msg_data["from_addr"].split()[-1].strip("<>")
            f.write(f"From {envelope_from} {msg['Date']}\n".encode())
            f.write(msg.as_bytes())
            f.write(b"\n\n")


def render_ics(events: list[dict[str, Any]], output_path: str | Path) -> None:
    """Render a list of calendar events into a standard RFC-5545 .ics file.

    Authority: docs/PACKS_SPEC.md section 6.
    """
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Probation//Synthetic World Generator//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    for ev in events:
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{ev['uid']}")

        # Format timestamps to iCalendar UTC compact format (YYYYMMDDTHHMMSSZ)
        def to_ics_ts(ts_str: str) -> str:
            clean = ts_str.replace("-", "").replace(":", "").replace(".000", "")
            if not clean.endswith("Z"):
                clean += "Z"
            return clean

        dtstamp = to_ics_ts(ev.get("created_at", ev["start_time"]))
        dtstart = to_ics_ts(ev["start_time"])
        dtend = to_ics_ts(ev["end_time"])

        lines.append(f"DTSTAMP:{dtstamp}")
        lines.append(f"DTSTART:{dtstart}")
        lines.append(f"DTEND:{dtend}")
        lines.append(f"SUMMARY:{ev['title']}")

        desc = ev.get("description", "").replace("\n", "\\n")
        lines.append(f"DESCRIPTION:{desc}")

        lines.append(f"ORGANIZER;CN={ev['organizer'].split('@')[0]}:mailto:{ev['organizer']}")

        for att in ev.get("attendees", []):
            partstat = ev.get("attendee_status", "NEEDS-ACTION")
            lines.append(
                f"ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;PARTSTAT={partstat};CN={att.split('@')[0]}:mailto:{att}"
            )

        lines.append(f"STATUS:{ev.get('status', 'CONFIRMED')}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    lines.append("")

    with open(out_file, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\r\n".join(lines))


def render_files(
    files: list[dict[str, Any]],
    base_dir: str | Path,
    snapshot_at: str,
) -> dict[str, Any]:
    """Render a directory tree and return folder manifest.

    Authority: docs/PACKS_SPEC.md section 6 and scripts/snapshot_folder.py.
    """
    root_path = Path(base_dir) / "fs"
    root_path.mkdir(parents=True, exist_ok=True)

    manifest_entries: list[dict[str, Any]] = []

    for file_info in files:
        initial_rel_path = file_info["rel_path"].replace("\\", "/").strip("/")
        final_action = file_info.get("final_action", "LEAVE")
        is_censored = file_info.get("is_censored", False)

        # If user moved the file and action is uncensored, place it in destination folder
        if final_action.startswith("MOVE_TO_FOLDER:") and not is_censored:
            dest_folder = final_action.split(":", 1)[1].strip().strip("/")
            rendered_rel_path = f"{dest_folder}/{file_info['filename']}".replace("\\", "/")
        else:
            rendered_rel_path = initial_rel_path

        target_path = root_path / rendered_rel_path
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Write deterministic dummy content
        if target_path.suffix == ".py":
            content = (
                f"# Probation Synthetic Document\n"
                f"# Filename: {file_info['filename']}\n"
                f"# Origin: {file_info.get('origin_url', 'local')}\n"
                f"# Created: {file_info['downloaded_at']}\n"
                f"pass\n"
            ).encode()
        else:
            content = (
                f"Probation Synthetic Document\n"
                f"Filename: {file_info['filename']}\n"
                f"Origin: {file_info.get('origin_url', 'local')}\n"
                f"Created: {file_info['downloaded_at']}\n"
            ).encode()

        target_path.write_bytes(content)
        sha = hashlib.sha256(content).hexdigest()

        manifest_entries.append(
            {
                "rel_path": initial_rel_path,
                "rendered_path": rendered_rel_path,
                "filename": file_info["filename"],
                "ext": file_info.get("ext", target_path.suffix.lstrip(".")),
                "size_bytes": len(content),
                "mtime": file_info["downloaded_at"],
                "sha256": sha,
                "origin_url": file_info.get("origin_url", ""),
            }
        )

    manifest = {
        "snapshot_at": snapshot_at,
        "root": "fs",
        "files": manifest_entries,
    }

    manifest_file = Path(base_dir) / "files_manifest.json"
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest
