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


def _run_full_pipeline(conn: sqlite3.Connection, owner: list[str]) -> dict[str, str]:
    """Execute full import -> ingest -> resolve -> replay pipeline."""
    fixture_dir = Path(__file__).parent.parent / "fixtures" / "tiny_synth"
    mbox = fixture_dir / "mailbox.mbox"
    ics = fixture_dir / "calendar.ics"
    world_db = fixture_dir / "world.db"

    import_mail(mbox, conn, user_addresses=owner)
    import_calendar(ics, conn, user_addresses=owner)
    ingest_situations(conn)

    clock = Clock(mode=ClockMode.REPLAY)
    with SimWorld(world_db) as world:
        report = run_replay(conn, clock=clock, world=world)
    return report


def test_t_e2e_backtest_ledger_and_metrics(tiny_synth_owner: list[str]) -> None:
    """T-E2E: Full replay produces verified ledger and consistent metrics."""
    conn = get_connection(":memory:")
    apply_schema(conn)

    report = _run_full_pipeline(conn, tiny_synth_owner)

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

    # 4. A backtest observes; it never performs a side-effect. Reaching ASK is the point of the
    #    run -- with real evidence the model does propose actions -- so what must hold is that no
    #    proposal is gated for execution and nothing was dispatched (CONTRACT: only the Executor
    #    acts, and it is not part of a replay).
    cur.execute("SELECT DISTINCT gate FROM proposals;")
    gates = {r[0] for r in cur.fetchall()}
    executing = {
        GateDecision.HOLD_THEN_EXECUTE.value,
        GateDecision.EXECUTE_UNDO.value,
        GateDecision.EXECUTE_SILENT.value,
    }
    assert not (gates & executing), f"Replay reached an executing gate: {sorted(gates & executing)}"
    assert gates <= {
        GateDecision.SHADOW.value,
        GateDecision.SUGGEST.value,
        GateDecision.ASK.value,
    }, f"Unexpected gates in a backtest: {sorted(gates)}"
    cur.execute("SELECT COUNT(*) FROM actions;")
    assert cur.fetchone()[0] == 0, "A backtest must not execute any action"

    conn.close()


def test_t_e2e_cryptographic_determinism(tiny_synth_owner: list[str]) -> None:
    """T-E2E: Two runs with identical seeds produce byte-identical ledger head hashes."""
    conn1 = get_connection(":memory:")
    apply_schema(conn1)
    _run_full_pipeline(conn1, tiny_synth_owner)

    conn2 = get_connection(":memory:")
    apply_schema(conn2)
    _run_full_pipeline(conn2, tiny_synth_owner)

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


def test_t_e2e_family_filtering(tiny_synth_owner: list[str]) -> None:
    """T-E2E: Filtering replay by family restricts processing strictly to that family."""
    conn = get_connection(":memory:")
    apply_schema(conn)

    fixture_dir = Path(__file__).parent.parent / "fixtures" / "tiny_synth"
    import_mail(fixture_dir / "mailbox.mbox", conn, user_addresses=tiny_synth_owner)
    import_calendar(fixture_dir / "calendar.ics", conn, user_addresses=tiny_synth_owner)
    ingest_situations(conn)

    clock = Clock(mode=ClockMode.REPLAY)
    with SimWorld(fixture_dir / "world.db") as world:
        report = run_replay(conn, clock=clock, family="email_action", world=world)

    assert report["family"] == "email_action"

    # Chain follow-ups are derived by the chains pack from the situations this filtered replay
    # actually processed, so they are a consequence of replaying email_action rather than a leak
    # of another family. What must not appear is any other *ingested* family.
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT family FROM proposals;")
    distinct_fams = {r[0] for r in cur.fetchall()}
    assert "email_action" in distinct_fams, f"No email_action proposals: {sorted(distinct_fams)}"
    assert distinct_fams <= {"email_action", "chain_followup"}, (
        f"Family filter leaked other families: {sorted(distinct_fams)}"
    )

    # Keep the filter honest: the calendar is imported here, so there is invite_rsvp input that a
    # broken filter would have replayed. Without it this test could pass while filtering nothing.
    cur.execute("SELECT COUNT(*) FROM situations WHERE family <> 'email_action';")
    assert cur.fetchone()[0] > 0, "No non-email_action input, so the filter is not exercised"

    conn.close()


def test_t_e2e_ledger_chronology(tiny_synth_owner: list[str]) -> None:
    """T-E2E: Proposal ledger sequence strictly precedes outcome ledger sequence (Invariant I-7)."""
    conn = get_connection(":memory:")
    apply_schema(conn)
    _run_full_pipeline(conn, tiny_synth_owner)

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
        assert r["proposed_at"] < r["known_at"], (
            f"Invariant I-7 violation for {r['situation_id']}: proposed_at "
            f"{r['proposed_at']} is not strictly before known_at {r['known_at']}"
        )
    conn.close()
