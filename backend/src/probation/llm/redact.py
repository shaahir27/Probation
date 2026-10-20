"""Local deterministic redaction pipeline.

Authority: docs/CONTRACT.md invariant I-14 and docs/PROMPTS.md section 1.
Runs before every LLM call. Raw private data is replaced by numbered placeholders.
The restore map is kept strictly local and never sent to external services.
"""

import re
from collections.abc import Iterable
from urllib.parse import urlparse

from probation.core.types import RedactionResult

READER_MAX_INPUT_CHARS = 4800

# Regex patterns for history stripping
QUOTED_HEADER_PATTERNS = [
    re.compile(r"^On .{0,120} wrote:\s*$", re.MULTILINE),
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^From: .+ Sent: \s*", re.MULTILINE),
]
SIGNATURE_LINE_PATTERN = re.compile(r"^-- \s*$", re.MULTILINE)
TRAILING_SIG_PATTERN = re.compile(
    r"\n\s*(?:Sent from my|Get Outlook for|Sent from Yahoo Mail).*",
    re.DOTALL | re.IGNORECASE,
)

# Regex patterns for sensitive entities
PAN_PATTERN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
IFSC_PATTERN = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
CARD_CANDIDATE_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
AADHAAR_PATTERN = re.compile(
    r"(?<!\d)(?<!\d\s)(?<!\d-)(?:\d{4}\s\d{4}\s\d{4}|\d{12})(?!\s*\d)(?!-\d)(?!\d)"
)

PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)|(?<!\d)\+\d{1,3}[\s-]?(?:\(\d{2,4}\)[\s-]?)?\d{3,4}[\s-]?\d{3,4}(?!\d)"
)
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+")

FREEMAIL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "icloud.com",
    "protonmail.com",
    "aol.com",
}
EDU_SUFFIXES = (".edu", ".ac.in", ".edu.in", ".ac.uk", ".edu.au")


def _luhn_valid(num_str: str) -> bool:
    """Validate numeric string using the Luhn checksum algorithm."""
    digits = [int(c) for c in num_str if c.isdigit()]
    if not (13 <= len(digits) <= 19):
        return False
    checksum = 0
    reverse_digits = digits[::-1]
    for i, d in enumerate(reverse_digits):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _classify_url_domain(url_str: str) -> str:
    """Classify domain into 'edu', 'corp', 'freemail', or 'other'."""
    try:
        if not url_str.startswith(("http://", "https://")):
            url_str = "http://" + url_str
        parsed = urlparse(url_str)
        host = (parsed.hostname or "").lower()
        if not host:
            return "other"
        if any(host.endswith(sfx) for sfx in EDU_SUFFIXES):
            return "edu"
        if host in FREEMAIL_DOMAINS:
            return "freemail"
        if any(host.endswith(tld) for tld in (".com", ".org", ".net", ".io", ".co", ".in", ".ai")):
            return "corp"
        return "other"
    except Exception:
        return "other"


def _strip_quoted_history(text: str) -> str:
    """Strip email quoted history (lines starting with > or header cuts)."""
    earliest_idx = len(text)
    for pat in QUOTED_HEADER_PATTERNS:
        match = pat.search(text)
        if match and match.start() < earliest_idx:
            earliest_idx = match.start()

    trimmed = text[:earliest_idx]

    lines = trimmed.splitlines()
    filtered_lines = [line for line in lines if not line.strip().startswith(">")]
    return "\n".join(filtered_lines)


def _strip_signature(text: str) -> str:
    """Strip signatures starting with '-- ' or trailing device notices."""
    match = SIGNATURE_LINE_PATTERN.search(text)
    if match:
        text = text[: match.start()]

    text = TRAILING_SIG_PATTERN.sub("", text)
    return text


def redact(
    text: str,
    *,
    display_names: Iterable[str] | None = None,
    profile: str = "mail",
) -> RedactionResult:
    """Execute local deterministic redaction pipeline per docs/PROMPTS.md section 1."""
    if profile == "mail":
        text = _strip_quoted_history(text)
        text = _strip_signature(text)

    val_to_placeholder: dict[str, str] = {}
    restore_map: dict[str, str] = {}
    counts: dict[str, int] = {
        "email": 0,
        "upi": 0,
        "phone": 0,
        "aadhaar": 0,
        "pan": 0,
        "card": 0,
        "otp": 0,
        "ifsc": 0,
        "url": 0,
        "person": 0,
    }

    def _get_or_create_placeholder(tag_type: str, raw_val: str) -> str:
        if raw_val in val_to_placeholder:
            return val_to_placeholder[raw_val]
        counts[tag_type.lower()] += 1
        placeholder = f"<{tag_type.upper()}_{counts[tag_type.lower()]}>"
        val_to_placeholder[raw_val] = placeholder
        restore_map[placeholder] = raw_val
        return placeholder

    # 1. Person names
    if display_names:
        for name in display_names:
            name_clean = name.strip()
            if len(name_clean) >= 2:
                pattern = re.compile(rf"\b{re.escape(name_clean)}\b", re.IGNORECASE)
                for match in pattern.finditer(text):
                    _get_or_create_placeholder("PERSON", match.group(0))
                text = pattern.sub(lambda m: _get_or_create_placeholder("PERSON", m.group(0)), text)

    # 2. URLs
    def url_sub(match: re.Match[str]) -> str:
        raw_val = match.group(0)
        domain_class = _classify_url_domain(raw_val)
        counts["url"] += 1
        tag = f"<URL:{domain_class}>"
        restore_map[tag] = raw_val
        return tag

    text = URL_PATTERN.sub(url_sub, text)

    # 3. PAN
    def pan_sub(match: re.Match[str]) -> str:
        return _get_or_create_placeholder("PAN", match.group(0))

    text = PAN_PATTERN.sub(pan_sub, text)

    # 4. IFSC
    def ifsc_sub(match: re.Match[str]) -> str:
        return _get_or_create_placeholder("IFSC", match.group(0))

    text = IFSC_PATTERN.sub(ifsc_sub, text)

    # 5. Card check (Checked before Aadhaar so 16-digit cards are not eaten by 12-digit Aadhaar)
    def card_sub(match: re.Match[str]) -> str:
        raw_val = match.group(0)
        if _luhn_valid(raw_val):
            return _get_or_create_placeholder("CARD", raw_val)
        return raw_val

    text = CARD_CANDIDATE_PATTERN.sub(card_sub, text)

    # 6. Aadhaar (12 digits, strictly not followed by another digit run)
    def aadhaar_sub(match: re.Match[str]) -> str:
        return _get_or_create_placeholder("AADHAAR", match.group(0))

    text = AADHAAR_PATTERN.sub(aadhaar_sub, text)

    # 7. Emails and UPI IDs
    email_or_upi_pattern = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+)\b")

    def email_or_upi_sub(match: re.Match[str]) -> str:
        raw_val = match.group(0)
        domain_part = match.group(1)
        if "." in domain_part:
            return _get_or_create_placeholder("EMAIL", raw_val)
        else:
            return _get_or_create_placeholder("UPI", raw_val)

    text = email_or_upi_pattern.sub(email_or_upi_sub, text)

    # 8. OTPs (4-8 digits near OTP/code keywords)
    otp_context_pattern = re.compile(
        r"(?i)\b(?:otp|code|verification code)\b.{0,20}?\b(\d{4,8})\b|\b(\d{4,8})\b.{0,20}?\b(?:otp|code|verification code)\b"
    )

    def otp_sub(match: re.Match[str]) -> str:
        otp_val = match.group(1) or match.group(2)
        placeholder = _get_or_create_placeholder("OTP", otp_val)
        return match.group(0).replace(otp_val, placeholder, 1)

    text = otp_context_pattern.sub(otp_sub, text)

    # 9. Phones
    def phone_sub(match: re.Match[str]) -> str:
        raw_val = match.group(0)
        if "<" in raw_val or ">" in raw_val:
            return raw_val
        return _get_or_create_placeholder("PHONE", raw_val)

    text = PHONE_PATTERN.sub(phone_sub, text)

    if len(text) > READER_MAX_INPUT_CHARS:
        text = text[:READER_MAX_INPUT_CHARS]

    clean_counts = {k: v for k, v in counts.items() if v > 0}

    return RedactionResult(
        text=text,
        counts=clean_counts,
        restore_map=restore_map,
    )


# Alias for convenience
redact_text = redact
