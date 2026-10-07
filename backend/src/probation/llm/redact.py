"""Local deterministic redaction pipeline.

Authority: docs/CONTRACT.md invariant I-14 and docs/PROMPTS.md section 1.
Raw private data is replaced by numbered placeholders before sending to an LLM.
The restore map is kept strictly local and never sent to external services.
"""

import re

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
PHONE_PATTERN = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
CARD_PATTERN = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")


def redact(raw_text: str) -> tuple[str, dict[str, str], dict[str, int]]:
    """Redact sensitive patterns in raw text.

    Returns:
        redacted_text: Text with sensitive entities replaced by <TYPE_N> placeholders.
        restore_map: Local mapping from placeholder back to original value (MUST NOT leave process).
        counts: Summary count of redacted items per category.
    """
    restore_map: dict[str, str] = {}
    counts: dict[str, int] = {"email": 0, "phone": 0, "card": 0}

    # Redact emails
    def email_sub(match: re.Match[str]) -> str:
        orig = match.group(0)
        counts["email"] += 1
        tag = f"<EMAIL_{counts['email']}>"
        restore_map[tag] = orig
        return tag

    redacted = EMAIL_PATTERN.sub(email_sub, raw_text)

    # Redact phones
    def phone_sub(match: re.Match[str]) -> str:
        orig = match.group(0)
        counts["phone"] += 1
        tag = f"<PHONE_{counts['phone']}>"
        restore_map[tag] = orig
        return tag

    redacted = PHONE_PATTERN.sub(phone_sub, redacted)

    # Redact cards
    def card_sub(match: re.Match[str]) -> str:
        orig = match.group(0)
        counts["card"] += 1
        tag = f"<CARD_{counts['card']}>"
        restore_map[tag] = orig
        return tag

    redacted = CARD_PATTERN.sub(card_sub, redacted)

    return redacted, restore_map, counts
