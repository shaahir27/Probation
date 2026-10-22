"""Identity, email address normalization, and domain classification.

Authority: docs/PACKS_SPEC.md section 0.1, 0.2, 1.2 and docs/CHANGES_IMPLEMENTATION_PLAN.md section 6.1.3.
"""

from __future__ import annotations

import email.utils
import re
from typing import Any

FREEMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "yahoo.com",
        "hotmail.com",
        "outlook.com",
        "live.com",
        "icloud.com",
        "proton.me",
        "protonmail.com",
        "zoho.com",
        "aol.com",
        "gmx.com",
        "mail.com",
        "yandex.com",
    }
)

AUTOMATED_LOCAL_PARTS = frozenset(
    {
        "noreply",
        "no-reply",
        "donotreply",
        "do-not-reply",
        "notifications",
        "notification",
        "newsletter",
        "mailer-daemon",
        "postmaster",
    }
)


def normalize_address(addr: str) -> str:
    """Normalize email address per docs/PACKS_SPEC.md section 0.2.

    Lower-case, strip display names, and strip +tag from local part.
    """
    if not addr:
        return ""
    _, clean_addr = email.utils.parseaddr(addr)
    if not clean_addr:
        clean_addr = addr.strip()
    clean_addr = clean_addr.lower().strip()
    if "@" in clean_addr:
        local, domain = clean_addr.split("@", 1)
        local_base = local.split("+", 1)[0]
        return f"{local_base}@{domain}"
    return clean_addr


def extract_domain(addr: str) -> str:
    """Extract domain from an address string."""
    norm = normalize_address(addr)
    if "@" in norm:
        return norm.split("@", 1)[1]
    return ""


def classify_domain(domain: str) -> str:
    """Classify domain into edu, freemail, corp, or other per docs/PACKS_SPEC.md section 0.2."""
    d = domain.lower().strip()
    if not d:
        return "other"
    if d in FREEMAIL_DOMAINS:
        return "freemail"
    if (
        d.endswith(".edu")
        or re.search(r"\.edu\.[a-z]{2,3}$", d)
        or re.search(r"\.ac\.[a-z]{2,3}$", d)
    ):
        return "edu"
    if "." in d:
        return "corp"
    return "other"


def is_automated_sender(
    from_addr: str,
    headers: dict[str, Any] | None = None,
) -> bool:
    """Check if sender is automated per docs/PACKS_SPEC.md section 1.2."""
    norm = normalize_address(from_addr)
    local_part = norm.split("@", 1)[0] if "@" in norm else norm
    if local_part in AUTOMATED_LOCAL_PARTS:
        return True

    if headers:
        if headers.get("List-Unsubscribe") or headers.get("List-Id"):
            return True
        prec = str(headers.get("Precedence", "")).lower()
        if prec in ("bulk", "list"):
            return True

    return False
