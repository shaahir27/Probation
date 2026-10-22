"""Pure action-label parsing. Parameters preserve case and never grant authority."""

import re
from dataclasses import dataclass
from typing import Final


class InvalidAction(ValueError):
    """An action is malformed, unsupported, a no-op or outside its pack catalog."""


ACTION_TYPES: Final[frozenset[str]] = frozenset(
    {
        "ARCHIVE",
        "TRASH",
        "REPLY",
        "FORWARD",
        "LEAVE",
        "ACCEPT",
        "DECLINE",
        "TENTATIVE",
        "NO_RESPONSE",
        "MOVE_TO_FOLDER",
        "BLOCK_TIME",
        "CREATE_FOLDER",
        "CREATE_TASK",
        "TRACK",
        "DISMISS",
        "FILE_TO_COLLECTION",
        "ARCHIVE_LINK",
        "ABSTAIN",
        "NONE",
    }
)
NOOP_ACTIONS: Final[frozenset[str]] = frozenset({"LEAVE", "NO_RESPONSE", "ABSTAIN", "NONE"})
PARAMETER_ACTIONS: Final[frozenset[str]] = frozenset({"MOVE_TO_FOLDER", "FILE_TO_COLLECTION"})
FAMILY_ACTIONS: Final[dict[str, frozenset[str]]] = {
    "email_action": frozenset({"ARCHIVE", "TRASH", "REPLY", "FORWARD", "LEAVE"}),
    "invite_rsvp": frozenset({"ACCEPT", "DECLINE", "TENTATIVE", "NO_RESPONSE"}),
    "file_destination": frozenset({"MOVE_TO_FOLDER", "LEAVE"}),
    "chain_followup": frozenset({"REPLY", "BLOCK_TIME", "CREATE_TASK", "NONE"}),
    "opportunity_triage": frozenset({"TRACK", "DISMISS", "LEAVE"}),
    "link_triage": frozenset({"FILE_TO_COLLECTION", "ARCHIVE_LINK", "LEAVE"}),
}


@dataclass(frozen=True, slots=True)
class ParsedAction:
    type: str
    parameter: str | None = None

    @property
    def label(self) -> str:
        return self.type if self.parameter is None else f"{self.type}:{self.parameter}"

    @property
    def is_noop(self) -> bool:
        return self.type in NOOP_ACTIONS


def parse_action(label: str) -> ParsedAction:
    """Parse TYPE[:parameter], rejecting unsupported labels and invisible parameters."""
    if not isinstance(label, str):
        raise InvalidAction("Action label must be a string")
    raw_type, separator, parameter = label.partition(":")
    kind = raw_type.upper()
    if kind not in ACTION_TYPES or re.fullmatch(r"[A-Z][A-Z0-9_]*", kind) is None:
        raise InvalidAction("Unsupported action type")
    if separator:
        if kind not in PARAMETER_ACTIONS or not parameter or parameter != parameter.strip():
            raise InvalidAction("Unsupported or empty action parameter")
        if parameter.startswith(":") or any(
            ord(char) < 32 or ord(char) == 127 for char in parameter
        ):
            raise InvalidAction("Malformed action parameter")
        return ParsedAction(kind, parameter)
    return ParsedAction(kind)
