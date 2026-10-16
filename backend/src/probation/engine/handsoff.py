"""Hard-coded hands-off lists preventing autonomous execution on sensitive targets.

Authority: docs/CONTRACT.md invariant I-10 and docs/ENGINE_SPEC.md section 8.2.
"""

from pathlib import Path
from typing import Final

# Dangerous executable and script file extensions (ENGINE_SPEC.md section 8.2)
BLOCKED_EXTENSIONS: Final[set[str]] = {
    ".exe",
    ".msi",
    ".bat",
    ".cmd",
    ".com",
    ".scr",
    ".js",
    ".jse",
    ".vbs",
    ".vbe",
    ".wsf",
    ".ps1",
    ".jar",
    ".apk",
    ".dmg",
    ".pkg",
    ".app",
    ".lnk",
    ".iso",
    ".img",
    ".dll",
    ".sys",
    ".sh",
    ".pif",
    ".py",
    ".pyw",
}

# Unicode right-to-left override character often used in filename spoofing attacks
RLO_CHAR: Final[str] = "\u202e"


def is_hands_off(
    filename: str | None = None,
    action: str | None = None,
    subject: str | None = None,
) -> str | None:
    """Check if an item matches hardcoded hands-off safety rules.

    Returns:
        A human-readable reason string if blocked, or None if safe.
    """
    if filename:
        if RLO_CHAR in filename:
            return "Unicode right-to-left override detected in filename"

        lower_name = filename.lower()

        # Double extension check first, e.g. financial_report.pdf.exe
        parts = lower_name.split(".")
        if len(parts) > 2 and f".{parts[-1]}" in BLOCKED_EXTENSIONS:
            return f"Dangerous double extension: .{parts[-2]}.{parts[-1]}"

        suffix = Path(lower_name).suffix
        if suffix in BLOCKED_EXTENSIONS:
            return f"Blocked executable or script extension: {suffix}"

    if action:
        act_upper = action.upper()
        if act_upper in ("PERMANENT_DELETE", "SHARE_OUTWARD", "PAYMENT", "PASSWORD_RESET"):
            return f"Action '{action}' is strictly forbidden by hands-off policy"

    return None
