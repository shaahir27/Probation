"""URL sanitisation and safety verification.

Authority: docs/CONTRACT.md invariant I-24 and docs/TAVILY_AND_NEW_PACKS.md section 7.
Enforces:
1. Scheme must be http or https. No userinfo. No IP-literal hosts. Reject localhost, .local, .internal, .lan, and private ranges.
2. Strip fragment and tracking parameters (utm_*, fbclid, gclid).
3. Hands-off (private_token): query keys in sensitive set, or param length >= 40, or Shannon entropy >= 4.0 with length >= 24.
4. Hands-off (sensitive_page): path contains login, signin, sign-in, checkout, cart, payment, account, reset.
5. Maximum length 2,048 chars.
"""

import ipaddress
import math
import re
from collections import Counter
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

MAX_URL_LENGTH = 2048
REDIRECTOR_DOMAINS = frozenset({"bit.ly", "t.co", "tinyurl.com", "goo.gl", "ow.ly", "buff.ly"})

TRACKING_QUERY_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
    }
)

SENSITIVE_PARAM_NAMES = frozenset(
    {
        "token",
        "key",
        "sig",
        "signature",
        "auth",
        "session",
        "sid",
        "code",
        "password",
        "pwd",
        "otp",
        "access_token",
        "id_token",
        "jwt",
        "apikey",
        "api_key",
    }
)

SENSITIVE_PATH_KEYWORDS = (
    "login",
    "signin",
    "sign-in",
    "checkout",
    "cart",
    "payment",
    "account",
    "reset",
)


def compute_shannon_entropy(data: str) -> float:
    """Calculate the Shannon entropy of a string."""
    if not data:
        return 0.0
    entropy = 0.0
    length = len(data)
    counts = Counter(data)
    for count in counts.values():
        p_x = float(count) / length
        if p_x > 0:
            entropy -= p_x * math.log2(p_x)
    return entropy


def is_url_hands_off(url: str) -> str | None:
    """Check if a URL triggers hard-coded hands-off rules.

    Returns reason string if forbidden/hands-off, or None if safe.
    """
    if not url:
        return "Empty URL"

    if len(url) > MAX_URL_LENGTH:
        return f"URL length {len(url)} exceeds limit {MAX_URL_LENGTH}"
    if any(ord(char) < 33 or ord(char) == 127 for char in url) or "\\" in url:
        return "Control characters, spaces or backslashes prohibited"

    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL format"

    # 1. Scheme must be http or https
    if parsed.scheme.lower() not in ("http", "https"):
        return f"Disallowed scheme: {parsed.scheme}"

    # 2. No userinfo allowed (user:pass@host)
    try:
        if parsed.username or parsed.password:
            return "Userinfo embedded in URL is forbidden"
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if parsed.port not in (None, 80 if parsed.scheme.lower() == "http" else 443):
            return "Nonstandard port prohibited"
    except ValueError:
        return "Invalid host or port"
    if not hostname:
        return "Missing hostname"
    if "." not in hostname or not re.fullmatch(r"[a-z0-9.-]+", hostname):
        return "Invalid public hostname"
    if any(
        not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
        for label in hostname.split(".")
    ):
        return "Invalid public hostname"
    if re.fullmatch(r"(?:0x[0-9a-f]+|[0-9.]+)", hostname):
        return "Numeric host prohibited"
    if any(hostname == domain or hostname.endswith("." + domain) for domain in REDIRECTOR_DOMAINS):
        return "Redirector destination prohibited"

    # Reject localhost and internal domains
    if hostname in ("localhost", "127.0.0.1", "::1"):
        return "Localhost destination prohibited"

    if any(hostname.endswith(suffix) for suffix in (".local", ".internal", ".lan")):
        return f"Internal host domain prohibited: {hostname}"

    # Check for IP literal hosts and private/loopback ranges
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
            return f"Private IP range prohibited: {hostname}"
        return f"IP-literal host prohibited: {hostname}"
    except ValueError:
        pass  # Named domain, valid

    # 3. Hands-off (sensitive_page): login, signin, checkout, payment, etc.
    path_lower = unquote(unquote(parsed.path)).lower()
    for segment in path_lower.split("/"):
        if len(segment) >= 40 or (len(segment) >= 24 and compute_shannon_entropy(segment) >= 4.0):
            return "High-risk path token prohibited"
    for kw in SENSITIVE_PATH_KEYWORDS:
        # Check boundary/segment containment
        if re.search(rf"\b{re.escape(kw)}\b", path_lower) or f"/{kw}" in path_lower:
            return f"Sensitive page path prohibited: {kw}"

    # 4. Hands-off (private_token): query parameters
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    for param_name, values in query_params.items():
        name_lower = unquote(unquote(param_name)).lower()
        if name_lower in SENSITIVE_PARAM_NAMES:
            return f"Private token query parameter prohibited: {param_name}"

        for val in values:
            if len(val) >= 40:
                return f"Long high-risk query parameter value prohibited (len={len(val)})"
            if len(val) >= 24 and compute_shannon_entropy(val) >= 4.0:
                return f"High-entropy credential token prohibited in query: {param_name}"

    return None


def sanitise_url(url: str) -> tuple[str, str | None]:
    """Sanitise URL: strip fragment, tracking parameters, and verify hands-off status.

    Returns:
        tuple (cleaned_url, hands_off_reason). If hands_off_reason is not None, URL is unsafe.
    """
    hands_off_reason = is_url_hands_off(url)
    if hands_off_reason is not None:
        return url, hands_off_reason

    parsed = urlparse(url)
    query_params = parse_qs(parsed.query, keep_blank_values=True)

    # Strip tracking parameters (utm_*, fbclid, gclid, etc.)
    filtered_params = {
        k: v
        for k, v in query_params.items()
        if k.lower() not in TRACKING_QUERY_PARAMS and not k.lower().startswith("utm_")
    }

    new_query = urlencode(filtered_params, doseq=True)
    clean_url = urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,
            parsed.params,
            new_query,
            "",  # Strip fragment
        )
    )
    return clean_url, None
