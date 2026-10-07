"""Cryptographic and deterministic hashing utilities.

Authority: docs/CONTRACT.md section 4, invariants I-7, I-8.
"""

import hashlib
import json
from typing import Any


def canonical_json(data: Any) -> str:
    """Serialize data to deterministic, canonical JSON string.

    Keys are sorted, separators are compact (",", ":"), and no trailing whitespace.
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def det_id(*parts: str) -> str:
    """Compute deterministic SHA-256 hex digest from concatenated component strings."""
    joined = ":".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def ledger_hash(prev_hash: str, seq: int, event_type: str, payload_json: str) -> str:
    """Compute the SHA-256 hash for a tamper-evident ledger entry.

    Hash chain structure: sha256(prev_hash + ":" + str(seq) + ":" + event_type + ":" + payload_json)
    """
    content = f"{prev_hash}:{seq}:{event_type}:{payload_json}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
