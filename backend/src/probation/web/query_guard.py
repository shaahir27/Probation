"""Tavily query guard ensuring strict safety and privacy constraints before outbound queries.

Authority: docs/CONTRACT.md invariant I-23 and docs/TAVILY_AND_NEW_PACKS.md section 4.
Queries are built by code from public-entity strings only. Never fetches user private info.
"""

import re

DISALLOWED_CHARS = re.compile(r"[@<>]|https?://")
SIX_DIGIT_RUN = re.compile(r"\b\d{6,}\b")
PERSON_TAG = re.compile(r"<PERSON_\d+>")


def validate_tavily_query(
    query: str,
    user_name_tokens: list[str] | None = None,
) -> tuple[bool, str | None]:
    """Validate query string before sending to Tavily API.

    Returns:
        (True, None) if safe.
        (False, reason) if rejected.
    """
    if not query or len(query.strip()) < 2:
        return False, "Query is empty or too short."

    if len(query) > 200:
        return False, "Query exceeds maximum allowed length of 200 characters."

    if DISALLOWED_CHARS.search(query):
        return False, "Query contains disallowed characters or URLs (@, <, >, http)."

    if SIX_DIGIT_RUN.search(query):
        return False, "Query contains long numeric sequence (potential private identifier)."

    if PERSON_TAG.search(query):
        return False, "Query contains redacted person token."

    if user_name_tokens:
        lower_q = query.lower()
        for token in user_name_tokens:
            if token and token.lower() in lower_q:
                return False, f"Query contains blocked user name token: {token}"

    return True, None
