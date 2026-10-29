"""Plain-word task labels for API payloads.

A class key is internal vocabulary. The UI may show it only behind the frozen
"Details" disclosure; everywhere else it gets one of these sentences.
"""

from __future__ import annotations

_TOPIC = {
    "fyi": "Notices",
    "newsletter": "Newsletters",
    "request": "Requests",
    "receipt": "Receipts",
    "invite": "Invites",
    "file": "Files",
    "link": "Links",
    "opportunity": "Opportunities",
}
_TIER = {
    "frequent": "recurring senders",
    "known": "known senders",
    "automated": "automated senders",
    "unknown": "unknown senders",
}


def task_title(class_key: str) -> str:
    """A human task sentence; never the words class, gate or ledger."""
    parts = [part for part in class_key.split("|") if part]
    if not parts:
        return "Email task"
    if len(parts) >= 3:
        topic, tier = parts[1], parts[2]
    elif len(parts) == 2 and parts[1] in _TIER:
        topic, tier = "email", parts[1]
    elif len(parts) == 2:
        topic, tier = parts[1], ""
    else:
        topic, tier = "email", ""
    label = _TOPIC.get(topic, topic.replace("_", " ").title())
    if tier:
        return f"{label} from {_TIER.get(tier, 'your senders')}"
    return label
