"""Identity, email address normalization, and domain classification.

Authority: docs/PACKS_SPEC.md section 0.1, 0.2, 1.2 and docs/CHANGES_IMPLEMENTATION_PLAN.md section 6.1.3.
"""

from __future__ import annotations

import email.utils
import re
from collections.abc import Sequence
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


def normalize_user_addresses(value: str | Sequence[str] | None) -> list[str]:
    """Coerce any accepted spelling of an address list into exact normalized addresses.

    Authority: docs/PACKS_SPEC.md sections 0.1-0.2 and
    docs/CHANGES_IMPLEMENTATION_PLAN.md section 6.1.3. Accepts a comma-separated RFC 2822
    header, a sequence of them, or None, and is used both for the owner's `USER_ADDRESSES`
    identity and for a message's `To`/`Cc` recipient list.

    Parsing goes through `email.utils.getaddresses` rather than splitting on commas, because
    a quoted display name may itself contain a comma. Blank tokens are dropped instead of
    kept: an empty string is a substring of every address, so retaining one would make the
    owner match every sender. Tokens without an `@` are dropped for the same reason, since
    PACKS_SPEC 0.1 defines these entries as email addresses and a bare fragment could only
    ever produce a false match. Order is preserved and duplicates removed because callers
    compare and hash the result, and a stable order keeps those comparisons reproducible.
    """
    if value is None:
        return []
    headers: list[str] = [value] if isinstance(value, str) else [str(v) for v in value]
    ordered: dict[str, None] = {}
    for _, addr in email.utils.getaddresses(headers):
        normalized = normalize_address(addr)
        if "@" in normalized:
            ordered.setdefault(normalized, None)
    return list(ordered)


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
