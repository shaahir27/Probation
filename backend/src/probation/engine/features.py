"""Feature encoding and featurization hash computation.

Authority: docs/ENGINE_SPEC.md section 2.
"""

import hashlib
from typing import Any

from probation.core.hashing import canonical_json


def compute_features_hash(deterministic_data: dict[str, Any], reader_data: dict[str, Any]) -> str:
    """Compute sha256 hash across normalized feature dictionaries."""
    combined = canonical_json({"det": deterministic_data, "reader": reader_data})
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()
