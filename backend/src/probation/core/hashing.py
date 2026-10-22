"""Cryptographic and deterministic hashing utilities.

Authority: docs/CONTRACT.md section 4, invariants I-7, I-8, and docs/DATA_MODEL.md sections 2, 4.
"""

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any

from probation.core.clock import format_timestamp

GENESIS = "0" * 64


def _normalise(obj: Any) -> Any:
    """Normalize floats to 6 decimal places, datetimes to ISO-8601 UTC 'Z', and dicts recursively."""
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError("Canonical JSON rejects non-finite numbers")
        return round(obj, 6)
    elif isinstance(obj, datetime):
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=UTC)
        else:
            obj = obj.astimezone(UTC)
        return format_timestamp(obj)
    elif isinstance(obj, dict):
        return {str(k): _normalise(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_normalise(item) for item in obj]
    return obj


def canonical_json(obj: Any) -> str:
    """Serialize data to deterministic, canonical JSON string.

    Conforming to docs/DATA_MODEL.md section 4:
    - sorted keys
    - no spaces (separators=(",", ":"))
    - UTF-8 (ensure_ascii=False)
    - floats rounded to 6 decimals
    - datetimes as ISO-8601 UTC 'Z' strings
    """
    if isinstance(obj, str):
        try:
            parsed = json.loads(obj)
            return json.dumps(
                _normalise(parsed), sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
        except json.JSONDecodeError:
            return obj
    return json.dumps(_normalise(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def det_id(*parts: str) -> str:
    """Compute deterministic ID as the first 32 hex chars of sha256("\x1f".join(parts)).

    Authority: docs/DATA_MODEL.md section 2.
    """
    joined = "\x1f".join(str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


def ledger_hash(prev_hash: str, kind: str, ref_id: str, payload: dict[str, Any] | str) -> str:
    """Compute SHA-256 hash for a tamper-evident ledger entry.

    Authority: docs/DATA_MODEL.md section 4:
    material = "\n".join([prev_hash, kind, ref_id, canonical_json(payload)])
    """
    if isinstance(payload, str):
        try:
            payload_obj = json.loads(payload)
        except Exception:
            payload_obj = payload
    else:
        payload_obj = payload

    material = "\n".join([prev_hash, str(kind), str(ref_id), canonical_json(payload_obj)])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
