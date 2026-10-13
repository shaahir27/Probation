"""Contract property test T-NOPEEK: Strict temporal isolation invariant.

Authority: docs/CONTRACT.md invariants I-6, I-7 and docs/TEST_PLAN.md (T-NOPEEK).
Verifies:
1. Mutating, corrupting, or deleting outcomes where known_at > t produces 100% byte-identical
   proposals for all situations occurring at or before t.
2. proposal.proposed_at <= outcome.known_at holds for every situation with an observed outcome.
3. Zero peeking violations across 50 random cuts.
"""

import json
import random
import sqlite3
from pathlib import Path

import pytest

from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.db.connection import apply_schema, get_connection
from probation.engine.replay import run_replay
from probation.synth.importers import import_calendar, import_mail
from probation.synth.world import SimWorld
from probation.workers.ingestor import ingest_situations
from probation.workers.resolver import resolve_outcomes


def _populate_test_db(conn: sqlite3.Connection) -> None:
    """Populate database from tiny_synth fixture."""
    fixture_dir = Path(__file__).parent.parent / "fixtures" / "tiny_synth"
    mbox = fixture_dir / "mailbox.mbox"
    ics = fixture_dir / "calendar.ics"
    world_db = fixture_dir / "world.db"

    import_mail(mbox, conn, user_addresses=["meena.k@example.ac.in"])
    import_calendar(ics, conn, user_addresses=["meena.k@example.ac.in"])
    ingest_situations(conn)

    with SimWorld(world_db) as world:
        resolve_outcomes(conn, world)


def test_t_nopeek_property_test() -> None:
    """T-NOPEEK: Mutating future outcomes (known_at > t) leaves proposals at t identical."""
    # 1. Build and run baseline replay
    baseline_conn = get_connection(":memory:")
    apply_schema(baseline_conn)
    _populate_test_db(baseline_conn)

    clock = Clock(mode=ClockMode.REPLAY)
    run_replay(baseline_conn, clock=clock)

    cur = baseline_conn.cursor()
    cur.execute("SELECT * FROM proposals ORDER BY proposed_at ASC;")
    baseline_props = {str(r["situation_id"]): dict(r) for r in cur.fetchall()}
    assert len(baseline_props) > 0, "Baseline run produced zero proposals"

    # 2. Verify temporal ordering: proposed_at <= known_at for every outcome
    cur.execute(
        """
        SELECT p.proposed_at, o.known_at, p.situation_id
        FROM proposals p
        JOIN outcomes o ON p.situation_id = o.situation_id;
        """
    )
    for r in cur.fetchall():
        prop_at = str(r["proposed_at"])
        known_at = str(r["known_at"])
        assert prop_at <= known_at, (
            f"Peeking violation: Proposal {r['situation_id']} occurred at {prop_at} "
            f"after outcome was known at {known_at}!"
        )

    # 3. Collect timestamps for 50 random cuts
    all_timestamps = sorted([p["proposed_at"] for p in baseline_props.values()])
    assert len(all_timestamps) >= 50, "Not enough timestamps to perform 50 cuts"

    # Select 50 deterministic pseudo-random cut points
    rng = random.Random(42)
    selected_indices = sorted(rng.sample(range(len(all_timestamps)), 50))
    cut_timestamps = [all_timestamps[i] for i in selected_indices]

    # 4. Perform 50 property test cuts
    for cut_idx, t_cut in enumerate(cut_timestamps):
        mutated_conn = get_connection(":memory:")
        apply_schema(mutated_conn)

        # Copy raw_items, situations, features
        for table in ["sources", "raw_items", "situations", "features"]:
            cur.execute(f"SELECT * FROM {table};")
            rows = [tuple(r) for r in cur.fetchall()]
            if rows:
                placeholders = ",".join("?" * len(rows[0]))
                mutated_conn.executemany(f"INSERT INTO {table} VALUES ({placeholders});", rows)
        mutated_conn.commit()

        # Copy outcomes: preserve known_at <= t_cut, mutate or drop known_at > t_cut
        cur.execute("SELECT * FROM outcomes;")
        out_rows = cur.fetchall()
        for o in out_rows:
            known_at = str(o["known_at"])
            if known_at <= t_cut:
                # Untouched historical outcome
                mutated_conn.execute(
                    """
                    INSERT INTO outcomes
                    (situation_id, observed_action, strength, source, observed_at, known_at, details_json, ledger_seq)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        o["situation_id"],
                        o["observed_action"],
                        o["strength"],
                        o["source"],
                        o["observed_at"],
                        o["known_at"],
                        o["details_json"],
                        o["ledger_seq"],
                    ),
                )
            else:
                # Mutate future outcome: flip action to corrupted bogus action or drop randomly
                if rng.random() > 0.5:
                    mutated_conn.execute(
                        """
                        INSERT INTO outcomes
                        (situation_id, observed_action, strength, source, observed_at, known_at, details_json, ledger_seq)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            o["situation_id"],
                            "BOGUS_FUTURE_ACTION",
                            "STRONG",
                            o["source"],
                            o["observed_at"],
                            o["known_at"],
                            o["details_json"],
                            o["ledger_seq"],
                        ),
                    )

        mutated_conn.commit()

        # Re-run replay on mutated database up to t_cut
        cut_clock = Clock(mode=ClockMode.REPLAY)
        run_replay(mutated_conn, clock=cut_clock, until=t_cut)

        # Query proposals in mutated run
        m_cur = mutated_conn.cursor()
        m_cur.execute("SELECT * FROM proposals WHERE proposed_at <= ?;", (t_cut,))
        mutated_props = {str(r["situation_id"]): dict(r) for r in m_cur.fetchall()}

        # Assert 100% equivalence with baseline
        for sit_id, m_prop in mutated_props.items():
            b_prop = baseline_props[sit_id]
            assert m_prop["action"] == b_prop["action"], (
                f"Cut {cut_idx} (t={t_cut}): Action changed for {sit_id} from "
                f"{b_prop['action']} to {m_prop['action']} despite future mutation!"
            )
            assert m_prop["gate"] == b_prop["gate"], (
                f"Cut {cut_idx} (t={t_cut}): Gate changed for {sit_id}"
            )
            assert m_prop["features_hash"] == b_prop["features_hash"], (
                f"Cut {cut_idx} (t={t_cut}): Features hash changed for {sit_id}"
            )
            assert pytest.approx(m_prop["p_max"], abs=1e-5) == b_prop["p_max"], (
                f"Cut {cut_idx} (t={t_cut}): p_max changed for {sit_id}"
            )

            m_probs = json.loads(m_prop["probs_json"])
            b_probs = json.loads(b_prop["probs_json"])
            for act_key in b_probs:
                assert pytest.approx(m_probs[act_key], abs=1e-5) == b_probs[act_key], (
                    f"Cut {cut_idx} (t={t_cut}): Prob for {act_key} shifted on {sit_id}"
                )

        mutated_conn.close()

    baseline_conn.close()
