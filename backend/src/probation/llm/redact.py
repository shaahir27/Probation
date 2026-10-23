"""Local deterministic redaction pipeline.

Authority: docs/CONTRACT.md invariant I-14 and docs/PROMPTS.md section 1.
Runs before every LLM call. Raw private data is replaced by numbered placeholders.
The restore map is kept strictly local and never sent to external services.

Two things a caller must not be able to do with the result: treat a column named
`redacted_text` as an egress guarantee, and restore a placeholder that was never earned.
So counts report replacements actually performed, only PERSON tokens are ever restorable,
and a placeholder-shaped token that arrived in the source text is excluded from the
restorable set instead of being honoured.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse

from probation.core.types import RedactionResult

READER_MAX_INPUT_CHARS = 4800

TYPES = (
    "email",
    "upi",
    "phone",
    "aadhaar",
    "pan",
    "card",
    "otp",
    "ifsc",
    "url",
    "person",
)

# History stripping
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

# Sensitive entities
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
EMAIL_UPI_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+)\b")
OTP_CONTEXT_PATTERN = re.compile(
    r"(?i)\b(?:otp|code|verification code)\b.{0,20}?\b(\d{4,8})\b|\b(\d{4,8})\b.{0,20}?\b(?:otp|code|verification code)\b"
)

# Any token that looks like one of ours, however it got there.
TOKEN_PATTERN = re.compile(
    r"<(?:PERSON|EMAIL|UPI|PHONE|AADHAAR|PAN|CARD|OTP|IFSC)_\d+>|<URL:[a-z]+>"
)
PERSON_TOKEN = re.compile(r"<PERSON_\d+>")
RESTORABLE_PREFIX = "<PERSON_"

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


def domain_class_of(address: str) -> str:
    """Classify the domain of an email address with the same scale a URL gets."""
    handle, _, host = address.rpartition("@")
    if not handle:
        return "other"
    return _classify_url_domain(host)


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


class RedactionLedger:
    """One request's numbering and maps, shared so documents of a request cannot collide.

    PROMPTS.md numbers placeholders per document. A reply request carries the incoming mail
    plus up to three historical examples, and two documents numbering `<PERSON_1>` for
    different people would let one identity be restored in place of another. Sharing one
    namespace per request makes a token mean exactly one value, and restoration authority is
    still granted per document.
    """

    def __init__(self) -> None:
        self._val_to_token: dict[str, str] = {}
        self._reserved: set[str] = set()
        self.token_to_val: dict[str, str] = {}
        self.counters: dict[str, int] = dict.fromkeys(TYPES, 0)

    def reserve(self, tokens: Iterable[str]) -> None:
        """Mark token text as already present in the data, so numbering must skip it.

        Without this, a sender who writes a literal `<PERSON_1>` into their own mail would
        occupy the token the real display name is about to earn, and one value would then
        stand for two different strings in the same document.
        """
        self._reserved.update(tokens)

    def token_for(self, tag_type: str, raw_val: str) -> str:
        key = f"{tag_type.lower()}:{raw_val}"
        existing = self._val_to_token.get(key)
        if existing is not None:
            return existing
        kind = tag_type.lower()
        while True:
            self.counters[kind] += 1
            token = f"<{tag_type.upper()}_{self.counters[kind]}>"
            if token not in self._reserved:
                break
        self._val_to_token[key] = token
        self._reserved.add(token)
        self.token_to_val[token] = raw_val
        return token


def _kind_of(token: str) -> str:
    """The type a placeholder belongs to, read from the token itself.

    Tallies are derived from the tokens in the sent text rather than from a numbering counter,
    so a class-collapsed token such as `<URL:corp>`, which is never numbered, is still counted.
    """
    header = token[1:-1]
    return header.partition("_")[0].partition(":")[0].lower()


def _positive(tally: dict[str, int]) -> dict[str, int]:
    return {kind: value for kind, value in tally.items() if value > 0}


@dataclass(frozen=True, slots=True)
class RequestRedaction:
    """Every document that went out in one request, with its own restoration authority."""

    documents: Mapping[str, RedactionResult]
    ledger: RedactionLedger = field(repr=False)
    current: str
    truncated: bool

    @property
    def counts(self) -> dict[str, int]:
        merged: dict[str, int] = dict.fromkeys(TYPES, 0)
        for result in self.documents.values():
            for kind, value in result.counts.items():
                merged[kind] = merged.get(kind, 0) + int(value)
        return _positive(merged)

    def text(self, label: str) -> str:
        return self.documents[label].text

    @property
    def current_text(self) -> str:
        return self.documents[self.current].text

    def restorable(self, label: str | None = None) -> dict[str, str]:
        """Placeholder to value, limited to tokens this document legitimately earned."""
        label = label if label is not None else self.current
        allowed = self.documents[label].restorable
        return {
            token: self.ledger.token_to_val[token]
            for token in sorted(allowed)
            if token in self.ledger.token_to_val
        }


def restore_person(text: str, restorable: Mapping[str, str]) -> tuple[str, tuple[str, ...]]:
    """Restore only PERSON placeholders this document earned; report what stayed unresolved."""
    unresolved: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        value = restorable.get(token)
        if value is None:
            unresolved.append(token)
            return token
        return value

    return PERSON_TOKEN.sub(_replace, text), tuple(dict.fromkeys(unresolved))


def redact(
    text: str,
    *,
    display_names: Iterable[str] | None = None,
    profile: str = "mail",
    ledger: RedactionLedger | None = None,
    limit: int = READER_MAX_INPUT_CHARS,
) -> RedactionResult:
    """Execute local deterministic redaction pipeline per docs/PROMPTS.md section 1.

    Counts and maps describe this document only, even when the numbering namespace is shared
    with the other documents of the same request.
    """
    scope = ledger or RedactionLedger()
    if profile == "mail":
        text = _strip_quoted_history(text)
        text = _strip_signature(text)

    # Any token that looks like ours and arrived in the source text is hostile, not earned.
    # Reserving it first means the real values can never be numbered into a collision with it.
    forged = {match.group(0) for match in TOKEN_PATTERN.finditer(text)}
    scope.reserve(forged)
    # Token -> local value, or None when the placeholder is lossy by design and cannot be
    # restored. Insertion-ordered, so a document's map is reproducible.
    earned: dict[str, str | None] = {}

    def _tag(tag_type: str, raw_val: str) -> str:
        token = scope.token_for(tag_type, raw_val)
        earned.setdefault(token, raw_val)
        return token

    def url_sub(match: re.Match[str]) -> str:
        # Same-class URLs collapse to one token, so no single value could be honestly restored.
        token = f"<URL:{_classify_url_domain(match.group(0))}>"
        earned.setdefault(token, None)
        return token

    text = URL_PATTERN.sub(url_sub, text)
    text = PAN_PATTERN.sub(lambda m: _tag("PAN", m.group(0)), text)
    text = IFSC_PATTERN.sub(lambda m: _tag("IFSC", m.group(0)), text)

    def card_sub(match: re.Match[str]) -> str:
        raw_val = match.group(0)
        return _tag("CARD", raw_val) if _luhn_valid(raw_val) else raw_val

    text = CARD_CANDIDATE_PATTERN.sub(card_sub, text)
    text = AADHAAR_PATTERN.sub(lambda m: _tag("AADHAAR", m.group(0)), text)

    def email_or_upi_sub(match: re.Match[str]) -> str:
        raw_val = match.group(0)
        has_domain_dot = "." in match.group(1)
        return _tag("EMAIL" if has_domain_dot else "UPI", raw_val)

    text = EMAIL_UPI_PATTERN.sub(email_or_upi_sub, text)

    def otp_sub(match: re.Match[str]) -> str:
        otp_val = match.group(1) or match.group(2)
        return match.group(0).replace(otp_val, _tag("OTP", otp_val), 1)

    text = OTP_CONTEXT_PATTERN.sub(otp_sub, text)

    def phone_sub(match: re.Match[str]) -> str:
        raw_val = match.group(0)
        if "<" in raw_val or ">" in raw_val:
            return raw_val
        return _tag("PHONE", raw_val)

    text = PHONE_PATTERN.sub(phone_sub, text)

    # Names go last: an address or URL that contains a person's name is already a typed
    # placeholder by now, so a name pattern can never cut a private token in half.
    for name in display_names or ():
        name_clean = name.strip()
        if len(name_clean) >= 2:
            pattern = re.compile(rf"\b{re.escape(name_clean)}\b", re.IGNORECASE)
            text = pattern.sub(lambda m: _tag("PERSON", m.group(0)), text)

    truncated = len(text) > limit
    if truncated:
        text = _safe_clip(text, limit)

    # Tallies are read off the text that is actually about to leave, so a clipped placeholder
    # cannot be reported as an exposure that never happened, and a hostile literal that merely
    # looks like one of ours is never credited as our own replacement.
    sent_occ: dict[str, int] = dict.fromkeys(TYPES, 0)
    sent_uni: dict[str, int] = dict.fromkeys(TYPES, 0)
    live: set[str] = set()
    for match in TOKEN_PATTERN.finditer(text):
        token = match.group(0)
        if token not in earned:
            continue
        live.add(token)
        kind = _kind_of(token)
        sent_occ[kind] += 1
    for token in live:
        sent_uni[_kind_of(token)] += 1

    # Reservation makes a forged literal unnumberable, so every token earned here is genuinely
    # ours; only PERSON carries a value worth putting back.
    restorable = frozenset(
        token for token in live if earned[token] is not None and token.startswith(RESTORABLE_PREFIX)
    )

    return RedactionResult(
        text=text,
        counts=_positive(sent_occ),
        restore_map={
            token: value for token, value in earned.items() if value is not None and token in live
        },
        unique=_positive(sent_uni),
        restorable=restorable,
        truncated=truncated,
    )


def _safe_clip(text: str, limit: int) -> str:
    """Clip at the limit without cutting a placeholder or tag in half."""
    clipped = text[:limit]
    open_token = re.search(r"<[A-Za-z_:0-9]*$", clipped)
    if open_token:
        clipped = clipped[: open_token.start()]
    dangling = clipped.rfind("<")
    if dangling != -1 and clipped.find(">", dangling) == -1:
        clipped = clipped[:dangling]
    return clipped


def redact_request(
    documents: Mapping[str, str],
    *,
    current: str,
    display_names: Iterable[str] | None = None,
    profile: str = "mail",
    limit: int = READER_MAX_INPUT_CHARS,
) -> RequestRedaction:
    """Redact every document of one outbound request through one namespace."""
    scope = RedactionLedger()
    results: dict[str, RedactionResult] = {}
    for label, raw in documents.items():
        results[label] = redact(
            raw, display_names=display_names, profile=profile, ledger=scope, limit=limit
        )
    return RequestRedaction(
        documents=results,
        ledger=scope,
        current=current,
        truncated=any(result.truncated for result in results.values()),
    )


# Alias for convenience
redact_text = redact
