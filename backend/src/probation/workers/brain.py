"""Brain worker: Featurization, proposals, and drafting.

Authority: docs/CONTRACT.md section 3 and docs/ENGINE_SPEC.md sections 1-3.
Enforces Role.BRAIN database write boundaries.
"""

import hashlib
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from probation.core.hashing import canonical_json
from probation.core.history import HistoryView
from probation.core.types import Situation
from probation.db.access import Role, RoleAccess
from probation.packs.registry import registry

FEATURIZER_VERSION = "v1.0"


def extract_features_for_situations(
    conn: sqlite3.Connection,
    reader_callable: (Callable[[Situation], tuple[dict[str, Any] | None, bool]] | None) = None,
) -> int:
    """Compute and store features for unfeaturized situations.

    Authority: docs/ENGINE_SPEC.md section 3 and docs/DATA_MODEL.md section 1.
    """
    access_conn = RoleAccess(conn, Role.BRAIN)
    read_cursor = conn.cursor()

    # Find situations without features
    read_cursor.execute(
        """
        SELECT s.*
        FROM situations s
        LEFT JOIN features f ON s.id = f.situation_id
        WHERE f.situation_id IS NULL
        ORDER BY s.occurred_at ASC;
        """
    )
    rows = read_cursor.fetchall()
    count = 0

    for row in rows:
        sit = Situation(
            id=row["id"],
            raw_item_id=row["raw_item_id"],
            pack=row["pack"],
            family=row["family"],
            variant=row["variant"],
            occurred_at=row["occurred_at"],
            sender_key=row["sender_key"],
            content_hash=row["content_hash"],
            redacted_text=row["redacted_text"],
            hands_off_reason=row["hands_off_reason"],
            created_at=row["created_at"],
        )

        try:
            pack = registry.get(sit.pack)
        except KeyError:
            continue

        # Invariant I-6: History bounded strictly by as_of=occurred_at
        hist = HistoryView(conn, as_of=sit.occurred_at)
        det_clues = pack.deterministic_clues(sit, hist)

        reader_dict: dict[str, Any] | None = None
        reader_ok = True

        if reader_callable is not None:
            reader_dict, reader_ok = reader_callable(sit)

        det_json = canonical_json(det_clues)
        reader_json = canonical_json(reader_dict) if reader_dict is not None else None

        # Compute deterministic features_hash
        raw_hash_input = f"{det_json}|{reader_json or '{}'}|{FEATURIZER_VERSION}".encode()
        features_hash = hashlib.sha256(raw_hash_input).hexdigest()

        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        access_conn.execute_write(
            "features",
            """
            INSERT OR IGNORE INTO features
            (situation_id, deterministic_json, reader_json, reader_ok, featurizer_version, model_id, prompt_version, features_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                sit.id,
                det_json,
                reader_json,
                1 if reader_ok else 0,
                FEATURIZER_VERSION,
                "stub" if reader_callable else None,
                "v1" if reader_callable else None,
                features_hash,
                now_iso,
            ),
        )
        count += 1

    access_conn.commit()
    return count
