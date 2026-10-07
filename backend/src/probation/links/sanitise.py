"""URL sanitisation and safety verification.

Authority: docs/CONTRACT.md invariant I-24 and docs/TAVILY_AND_NEW_PACKS.md section 7.
"""

import ipaddress
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def is_url_hands_off(url: str) -> str | None:
    """Check if a URL is forbidden or dangerous.

    Returns reason string if forbidden, or None if safe.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL format"

    if parsed.scheme not in ("http", "https"):
        return f"Disallowed scheme: {parsed.scheme}"

    hostname = parsed.hostname or ""
    if not hostname:
        return "Missing hostname"

    if hostname.lower() in ("localhost", "127.0.0.1", "::1"):
        return "Localhost destination prohibited"

    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback:
            return f"Private IP range prohibited: {hostname}"
    except ValueError:
        pass  # Named domain, valid

    return None


def sanitise_url(url: str) -> str:
    """Strip common tracking query parameters from URL."""
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)

    tracking_keys = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
    }
    filtered_params = {k: v for k, v in query_params.items() if k.lower() not in tracking_keys}

    new_query = urlencode(filtered_params, doseq=True)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        )
    )
