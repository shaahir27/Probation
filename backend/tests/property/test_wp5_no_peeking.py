"""Fifty seeded historical evidence/licence cuts resist future mutations."""

import json
import random

from probation.core.enums import LedgerKind
from probation.db.access import Role, RoleAccess
from probation.engine.evidence import aggregate_evidence
from probation.engine.licence import derive_licences
from tests.unit.test_wp5_licence_derivation import cohort


def test_fifty_permission_cuts_ignore_future_state(memory_db):
    cohort(memory_db)
    rng = random.Random(705)
    for i in range(50):
        cutoff = f"2026-05-{rng.randrange(1, 21):02d}T10:30:00Z"
        evidence = aggregate_evidence(memory_db, cutoff, persist=False)
        licences = derive_licences(memory_db, cutoff)
        future = f"2026-08-01T00:{i:02d}:00Z"
        RoleAccess(memory_db, Role.RESOLVER).append_ledger(
            LedgerKind.OUTCOME,
            f"future-{i}",
            {
                "situation_id": f"s{rng.randrange(70)}",
                "observed_action": "TRASH",
                "source": "footprint",
                "strength": "STRONG",
                "known_at": future,
            },
            created_at=future,
        )
        memory_db.execute(
            "UPDATE raw_items SET payload_json=? WHERE known_at COLLATE UTC_TIMESTAMP > ?",
            (json.dumps({"body": f"changed future {i}"}), cutoff),
        )
        assert aggregate_evidence(memory_db, cutoff, persist=False) == evidence
        assert derive_licences(memory_db, cutoff) == licences
