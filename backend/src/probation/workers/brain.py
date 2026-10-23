"""Brain worker: Featurization, proposals, and drafting.

Authority: docs/CONTRACT.md section 3 and docs/ENGINE_SPEC.md sections 1-3.
Enforces Role.BRAIN database write boundaries.
"""

import logging
import sqlite3
from collections.abc import Callable
from typing import Any

from probation.config import settings
from probation.core.clock import Clock, get_clock
from probation.core.hashing import canonical_json
from probation.core.history import HistoryView
from probation.core.types import Situation
from probation.db.access import Role, RoleAccess
from probation.llm.client import LLMClient
from probation.llm.consumers import RegisteredConsumer, offline_consumer
from probation.llm.feature_pipeline import compute_features
from probation.llm.gateway import JobGateway, transport_authority
from probation.packs.registry import registry

logger = logging.getLogger(__name__)

FEATURIZER_VERSION = "wp3-reader-v1"


def build_reader_client(clock: Clock | None, allow_live_llm: bool) -> LLMClient | None:
    """Build the live reader once per run, or return None when reading is deterministic.

    A replay featurizes one situation per event, so constructing the client inline would
    rebuild it hundreds of times. Callers that opt in to live reading build it once here
    and pass it to `extract_features_for_situations`.
    """
    if not settings.llm_api_key:
        return None
    if not allow_live_llm:
        logger.warning(
            "LLM API key is configured but live reading was not requested; featurizing "
            "deterministically. Pass allow_live_llm=True to spend against the reader model."
        )
        return None
    from probation.llm.budget import BudgetExceeded

    try:
        return LLMClient(api_key=settings.llm_api_key, clock=clock or get_clock())
    except BudgetExceeded:
        logger.warning("Reader accounting unavailable; required reader will fail closed")
        return None


def extract_features_for_situations(
    conn: sqlite3.Connection,
    reader_callable: (Callable[[Situation], tuple[dict[str, Any] | None, bool]] | None) = None,
    clock: Clock | None = None,
    allow_live_llm: bool = False,
    situation_id: str | None = None,
    llm_client: LLMClient | None = None,
    until: str | None = None,
) -> int:
    """Compute and store features for unfeaturized situations.

    Authority: docs/ENGINE_SPEC.md section 3 and docs/DATA_MODEL.md section 1.
    A live reader is used only when `allow_live_llm` is passed explicitly: it spends
    real money and its output is not reproducible, so a replay must never trigger one
    just because an API key happens to be configured.

    Pass `situation_id` to featurize exactly one situation. A replay must do this at the
    moment that situation's event fires: history clues count prior outcomes, and a batch
    run before the timeline starts reads an empty `outcomes` table, collapsing every
    reply-history clue to its degenerate default (plan section 6.3.3).
    """
    access_conn = RoleAccess(conn, Role.BRAIN)
    read_cursor = access_conn.conn.cursor()

    if llm_client is None and reader_callable is None:
        # A per-situation call inside a replay is handed the run's client by its caller, so
        # it must not rebuild one (or re-warn) for every situation on the timeline.
        if allow_live_llm or situation_id is None:
            llm_client = build_reader_client(clock, allow_live_llm)

    # Find situations without features
    query = """
        SELECT s.*
        FROM situations s
        LEFT JOIN features f ON s.id = f.situation_id
        WHERE f.situation_id IS NULL
        """
    params: list[Any] = []
    if situation_id is not None:
        query += " AND s.id = ?"
        params.append(situation_id)
    if until is not None:
        query += " AND s.occurred_at COLLATE UTC_TIMESTAMP <= ?"
        params.append(until)
    query += " ORDER BY s.occurred_at COLLATE UTC_TIMESTAMP ASC;"
    read_cursor.execute(query, tuple(params))
    rows = read_cursor.fetchall()
    count = 0

    clk = clock or get_clock()

    consumer = (
        offline_consumer(conn)
        if llm_client is None
        else RegisteredConsumer(
            JobGateway(llm_client, conn=conn),
            transport_authority(llm_client, allow_live_dispatch=allow_live_llm),
        )
    )

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
            registry.get_descriptor(sit.pack)
        except KeyError:
            continue

        # Invariant I-6: History bounded strictly by as_of=occurred_at
        hist = HistoryView(conn, as_of=sit.occurred_at)

        features = compute_features(sit, hist, consumer=consumer, reader_callable=reader_callable)
        det_json = canonical_json(features.deterministic)
        reader_json = canonical_json(features.reader) if features.reader is not None else None
        reader_ok = features.reader_ok
        model_id, prompt_version = features.model_id, features.prompt_version
        features_hash = features.features_hash

        now_iso = clk.now_iso()

        access_conn.execute_write(
            "features",
            """
            INSERT OR IGNORE INTO features
            (situation_id, deterministic_json, reader_json, reader_ok, featurizer_version, model_id, prompt_version, features_hash, created_at, provenance_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                sit.id,
                det_json,
                reader_json,
                1 if reader_ok else 0,
                features.featurizer_version,
                model_id,
                prompt_version,
                features_hash,
                now_iso,
                features.provenance_json,
            ),
        )
        count += 1

    return count
