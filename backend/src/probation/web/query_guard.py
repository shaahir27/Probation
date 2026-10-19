"""Tavily query guard ensuring strict safety and privacy constraints before outbound queries.

Authority: docs/CONTRACT.md invariant I-23 and docs/TAVILY_AND_NEW_PACKS.md section 4.
Queries are built by code from public-entity strings only. Never fetches user private info.
"""

import re

ALLOWED_CHARS = re.compile(r"^[a-zA-Z0-9\s.\-&']+$")
DISALLOWED_SUBSTRINGS = re.compile(r"[@<>]|https?://|http", re.IGNORECASE)
SIX_DIGIT_RUN = re.compile(r"\d{6,}")
PERSON_TAG = re.compile(r"<PERSON_\d+>", re.IGNORECASE)


def validate_tavily_query(
    query: str,
    user_name_tokens: list[str] | None = None,
) -> tuple[bool, str | None]:
    """Validate query string before sending to Tavily API.

    Authority: docs/CONTRACT.md invariant I-23, docs/PROMPTS.md section 15,
    and docs/TAVILY_AND_NEW_PACKS.md section 5.4:
    - Allowed characters: letters, digits, space, dot, hyphen, ampersand, apostrophe.
    - At most 80 characters and 12 tokens.
    - Reject if it contains '@', '<', '>', 'http', a run of 6 or more digits,
      a '<PERSON_n>' placeholder, or any token in USER_NAME_TOKENS.

    Returns:
        (True, None) if safe.
        (False, reason) if rejected.
    """
    if not query or len(query.strip()) < 2:
        return False, "Query is empty or too short."

    if len(query) > 80:
        return False, "Query exceeds maximum allowed length of 80 characters."

    tokens = query.strip().split()
    if len(tokens) > 12:
        return False, f"Query exceeds maximum allowed tokens of 12 (found {len(tokens)})."

    if PERSON_TAG.search(query):
        return False, "Query contains redacted person token."

    if DISALLOWED_SUBSTRINGS.search(query):
        return False, "Query contains disallowed patterns (@, <, >, http)."

    if SIX_DIGIT_RUN.search(query):
        return False, "Query contains run of 6 or more digits (potential private identifier)."

    if not ALLOWED_CHARS.match(query):
        return (
            False,
            "Query contains disallowed characters (only letters, digits, space, dot, hyphen, ampersand, apostrophe allowed).",
        )

    if user_name_tokens:
        lower_q = query.lower()
        for token in user_name_tokens:
            cleaned = token.strip().lower()
            if cleaned and cleaned in lower_q:
                return False, f"Query contains blocked user name token: {cleaned}"

    return True, None
