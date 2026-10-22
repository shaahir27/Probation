"""Integration test T-E2E: End-to-end replay, ledger verification, and determinism.

Authority: docs/CONTRACT.md section 2 and docs/TEST_PLAN.md (T-E2E).
Verifies:
1. Full import -> ingest -> featurize -> resolve -> replay cycle executes cleanly on tiny_synth.
2. Ledger verifies intact with zero corruption or broken sequence numbers.
3. Exactly one proposal is emitted per situation.
4. Report card counts sum correctly (same + different + censored == total_proposals).
5. Two independent runs from scratch produce identical final ledger hashes (bit-exact determinism).
"""

import sqlite3
from pathlib import Path

from probation.core.clock import Clock
from probation.core.enums import ClockMode, GateDecision
from probation.db.connection import apply_schema, get_connection
from probation.db.ledger import verify_ledger
from probation.engine.replay import run_replay
from probation.synth.importers import import_calendar, import_mail
from probation.synth.world import SimWorld
from probation.workers.ingestor import ingest_situations


def _run_full_pipeline(conn: sqlite3.Connection) -> dict[str, str]:
    """Execute full import -> ingest -> resolve -> replay pipeline."""
    fixture_dir = Path(__file__).parent.parent / "fixtures" / "tiny_synth"
    mbox = fixture_dir / "mailbox.mbox"
    ics = fixture_dir / "calendar.ics"
    world_db = fixture_dir / "world.db"

    import_mail(mbox, conn, user_addresses=["meena.k@example.ac.in"])
    import_calendar(ics, conn, user_addresses=["meena.k@example.ac.in"])
    ingest_situations(conn)

    clock = Clock(mode=ClockMode.REPLAY)
    with SimWorld(world_db) as world:
        report = run_replay(conn, clock=clock, world=world)
    return report


def test_t_e2e_backtest_ledger_and_metrics() -> None:
    """T-E2E: Full replay produces verified ledger and consistent metrics."""
    conn = get_connection(":memory:")
    apply_schema(conn)

    report = _run_full_pipeline(conn)

    # 1. Ledger integrity verification
    is_intact, corrupt_seq = verify_ledger(conn)
    assert is_intact, f"Ledger corrupted at sequence {corrupt_seq}!"

    # 2. Exactly one proposal per situation
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM situations;")
    total_situations = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM proposals;")
    total_proposals = cur.fetchone()[0]

    assert total_proposals == total_situations, (
        f"Proposal count mismatch: {total_proposals} proposals vs {total_situations} situations"
    )

    # 3. Report card metrics sum correctly
    same = report["same"]
    different = report["different"]
    censored = report["censored"]
    assert same + different + censored == total_proposals, (
        f"Metrics sum mismatch: {same} + {different} + {censored} != {total_proposals}"
    )

    # 4. In Phase 4, proposals use GateDecision.SHADOW
    cur.execute("SELECT DISTINCT gate FROM proposals;")
    gates = [r[0] for r in cur.fetchall()]
    assert gates == [GateDecision.SHADOW.value], f"Unexpected gates in Phase 4: {gates}"

    conn.close()


def test_t_e2e_cryptographic_determinism() -> None:
    """T-E2E: Two runs with identical seeds produce byte-identical ledger head hashes."""
    conn1 = get_connection(":memory:")
    apply_schema(conn1)
    _run_full_pipeline(conn1)

    conn2 = get_connection(":memory:")
    apply_schema(conn2)
    _run_full_pipeline(conn2)

    cur1 = conn1.cursor()
    cur1.execute("SELECT hash, seq FROM ledger ORDER BY seq DESC LIMIT 1;")
    head1 = cur1.fetchone()

    cur2 = conn2.cursor()
    cur2.execute("SELECT hash, seq FROM ledger ORDER BY seq DESC LIMIT 1;")
    head2 = cur2.fetchone()

    assert head1 is not None and head2 is not None
    assert head1["seq"] == head2["seq"], "Sequence numbers differed between identical runs"
    assert head1["hash"] == head2["hash"], (
        f"Cryptographic determinism violation: ledger head hashes differed!\n"
        f"Run 1: {head1['hash']}\nRun 2: {head2['hash']}"
    )

    conn1.close()
    conn2.close()


def test_t_e2e_family_filtering() -> None:
    """T-E2E: Filtering replay by family restricts processing strictly to that family."""
    conn = get_connection(":memory:")
    apply_schema(conn)

    fixture_dir = Path(__file__).parent.parent / "fixtures" / "tiny_synth"
    import_mail(fixture_dir / "mailbox.mbox", conn, user_addresses=["meena.k@example.ac.in"])
    import_calendar(fixture_dir / "calendar.ics", conn, user_addresses=["meena.k@example.ac.in"])
    ingest_situations(conn)

    clock = Clock(mode=ClockMode.REPLAY)
    with SimWorld(fixture_dir / "world.db") as world:
        report = run_replay(conn, clock=clock, family="email_action", world=world)

    assert report["family"] == "email_action"

    cur = conn.cursor()
    cur.execute("SELECT DISTINCT family FROM proposals;")
    distinct_fams = [r[0] for r in cur.fetchall()]
    assert distinct_fams == ["email_action"], f"Unexpected families emitted: {distinct_fams}"

    conn.close()


def test_t_e2e_ledger_chronology() -> None:
    """T-E2E: Proposal ledger sequence strictly precedes outcome ledger sequence (Invariant I-7)."""
    conn = get_connection(":memory:")
    apply_schema(conn)
    _run_full_pipeline(conn)

    cur = conn.cursor()
    cur.execute(
        """
        SELECT p.situation_id, p.ledger_seq as p_seq, o.ledger_seq as o_seq, p.proposed_at, o.known_at
        FROM proposals p
        JOIN outcomes o ON p.situation_id = o.situation_id;
        """
    )
    rows = cur.fetchall()
    assert len(rows) > 0, "Expected outcomes joined with proposals"
    for r in rows:
        assert r["p_seq"] < r["o_seq"], (
            f"Invariant I-7 violation for {r['situation_id']}: "
            f"Proposal seq ({r['p_seq']}) not strictly before outcome seq ({r['o_seq']})"
        )
        assert r["proposed_at"] <= r["known_at"], (
            f"Temporal violation for {r['situation_id']}: {r['proposed_at']} > {r['known_at']}"
        )
    conn.close()
