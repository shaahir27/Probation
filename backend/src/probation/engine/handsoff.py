"""Hard-coded hands-off lists preventing autonomous execution on sensitive targets.

Authority: docs/CONTRACT.md invariant I-10 and docs/ENGINE_SPEC.md section 8.2.
"""

from pathlib import Path
from typing import Final

# Dangerous and executable file extensions that must NEVER be autonomously acted upon
BLOCKED_EXTENSIONS: Final[set[str]] = {
    ".exe",
    ".bat",
    ".cmd",
    ".sh",
    ".ps1",
    ".vbs",
    ".msi",
    ".dll",
    ".sys",
    ".scr",
    ".pif",
    ".com",
    ".jar",
    ".py",
    ".pyw",
}

# Unicode right-to-left override character often used in spoofing attacks
RLO_CHAR: Final[str] = "\u202e"


def is_hands_off(
    filename: str | None = None,
    sender_domain: str | None = None,
) -> str | None:
    """Check if an item matches hardcoded hands-off safety rules.

    Returns:
        A human-readable reason string if blocked, or None if safe.
    """
    if filename:
        if RLO_CHAR in filename:
            return "Unicode right-to-left override detected in filename"

        lower_name = filename.lower()
        suffix = Path(lower_name).suffix
        if suffix in BLOCKED_EXTENSIONS:
            return f"Blocked executable extension: {suffix}"

        # Double extension check, e.g. document.pdf.exe
        parts = lower_name.split(".")
        if len(parts) > 2 and f".{parts[-1]}" in BLOCKED_EXTENSIONS:
            return f"Dangerous double extension: .{parts[-2]}.{parts[-1]}"

    return None
