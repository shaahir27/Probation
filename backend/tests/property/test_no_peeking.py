"""Contract property test T-NOPEEK: strict temporal isolation (acceptance criterion V08).

Authority: docs/CONTRACT.md invariants I-6 and I-7, docs/TEST_PLAN.md (T-NOPEEK) and
docs/CHANGES_IMPLEMENTATION_PLAN.md V08: "future raw / footprint / final-state mutation at 50 cuts
leaves pre-cut features, probabilities, gates and ledger commitments unchanged".

The future is not only the outcomes table. At a cut it is also raw items that had not arrived, the
final label state an export bakes into a mail payload (defect C9), the world's dated footprint
stream, and the world's item catalog. Each is mutated here, and everything at or before the cut is
compared field by field -- the features the policy was built from, the proposals they produced, the
evidence rows the run claims to know, the ledger chain they were committed into, and what the gate
would have decided had the licence been earned. Comparing verdicts alone is not enough: a truncated
run can resolve an outcome past its horizon, record it, and still print the same argmax, because the
leak feeds the next retrain rather than the current proposal.

Two construction rules keep the harness from testing nothing:

* Only pre-replay input is copied into a cut -- ``sources``, ``raw_items``, ``situations``, ``meta``.
  Copying ``features`` would defeat the point, because features are precisely what a leak changes;
  replay rebuilds them per situation at that situation's own cutoff (plan section 6.3.3).
  Copying ``proposals`` is worse: replay derives follow-up ``chain_followup`` situations as a
  byproduct, and the idempotence guard that stops them being proposed twice reads the proposals
  table, so importing those situations without their proposals pushes them down the generic
  cold-start path and manufactures a difference that is a harness artifact, not a peek.
* Outcomes are never copied or hand-mutated. Replay re-derives them from the mutated world, so the
  mutation reaches the resolver through the same door the evidence came in through.

The physical file scan is deliberately left inert. ``resolve_files_outcome`` step 3 reports a
file's *current* location with ``known_at`` set to the observation-window close, so scanning a real
tree makes provisional resolutions depend on wall-clock position in a way that legitimately differs
between a prefix and a full run. That is a design question for the files pack, not a leak, and
testing it here would either fail for the wrong reason or have to be weakened.
"""

import json
import random
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from probation.config import settings
from probation.core.clock import Clock, timestamp_key
from probation.core.enums import ClockMode, GateDecision
from probation.core.hashing import canonical_json
from probation.db.connection import apply_schema, get_connection
from probation.db.ledger import verify_ledger
from probation.engine.caps import get_action_loss, is_recallable
from probation.engine.gate import compute_audit_draw, decide_gate
from probation.engine.replay import run_replay
from probation.synth.importers import import_calendar, import_files, import_mail
from probation.synth.world import SimWorld
from probation.workers.ingestor import ingest_situations

CUTS = 50
SEED = 42
INPUT_TABLES = ("sources", "raw_items", "situations", "meta")
EXECUTING_GATES = frozenset(
    {
        GateDecision.HOLD_THEN_EXECUTE.value,
        GateDecision.EXECUTE_UNDO.value,
        GateDecision.EXECUTE_SILENT.value,
    }
)
PROPOSAL_COLUMNS = (
    "family",
    "class_key",
    "action",
    "probs_json",
    "p_max",
    "novelty",
    "novel",
    "licence_level",
    "cap",
    "gate",
    "reasons_json",
    "params_json",
    "explanation_json",
    "web_json",
    "policy_version",
    "features_hash",
    "audit_holdout",
    "proposed_at",
    "ledger_seq",
)
FEATURE_COLUMNS = (
    "deterministic_json",
    "reader_json",
    "reader_ok",
    "featurizer_version",
    "model_id",
    "prompt_version",
    "features_hash",
)
OUTCOME_COLUMNS = (
    "observed_action",
    "strength",
    "source",
    "observed_at",
    "known_at",
    "details_json",
)


def _build_pristine_input(fixture: Path, owner: list[str]) -> sqlite3.Connection:
    """Import the fixture and ingest situations, then stop before anything is derived."""
    conn = get_connection(":memory:")
    apply_schema(conn)
    import_mail(fixture / "mailbox.mbox", conn, user_addresses=owner)
    import_calendar(fixture / "calendar.ics", conn, user_addresses=owner)
    import_files(fixture / "files_manifest.json", conn)
    ingest_situations(conn)
    return conn


def _copy_input(pristine: sqlite3.Connection) -> sqlite3.Connection:
    """Open a fresh database holding exactly the pre-replay input."""
    conn = get_connection(":memory:")
    apply_schema(conn)
    cur = pristine.cursor()
    for table in INPUT_TABLES:
        cur.execute(f"SELECT * FROM {table};")
        rows = [tuple(r) for r in cur.fetchall()]
        if rows:
            conn.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(rows[0]))});", rows)
    conn.commit()
    return conn


def _drop_future_items(conn: sqlite3.Connection, t_cut: str) -> int:
    """Remove arrivals the observer at ``t_cut`` never received, and report how many.

    ``known_at`` and ``occurred_at`` are the same instant for every pack importer, so a raw item
    that has not arrived cannot have a situation that has.
    """
    cut = timestamp_key(t_cut)
    cur = conn.cursor()
    cur.execute("SELECT id, known_at FROM raw_items;")
    gone = [str(r["id"]) for r in cur.fetchall() if timestamp_key(str(r["known_at"])) > cut]
    cur.execute("SELECT id, occurred_at, raw_item_id FROM situations;")
    later = [str(r["id"]) for r in cur.fetchall() if timestamp_key(str(r["occurred_at"])) > cut]
    for sit_id in later:
        conn.execute("DELETE FROM situations WHERE id = ?;", (sit_id,))
    for raw_id in gone:
        conn.execute("DELETE FROM raw_items WHERE id = ?;", (raw_id,))
    conn.commit()
    still = {
        str(r["raw_item_id"]) for r in conn.execute("SELECT raw_item_id FROM situations;")
    } & set(gone)
    assert not still, f"situations retained without their raw item: {sorted(still)[:3]}"
    return len(gone) + len(later)


def _project_payload_labels(conn: sqlite3.Connection, world: SimWorld, t_cut: str) -> int:
    """Rewrite each mail payload's baked final labels to what they were at ``t_cut`` (C9).

    An export taken at ``t_cut`` can only show the labels the owner had applied by then. The
    generator's ``render_mbox`` writes the *final* ``X-Gmail-Labels`` and ``import_mail`` copies
    them into ``payload_json``, so without this the corpus would carry the end of the story into
    the middle of it. ``content_hash`` is left alone: it is an identity and de-duplication token,
    not a feature.
    """
    changed = 0
    cur = conn.cursor()
    cur.execute("SELECT id, source_ref, payload_json FROM raw_items WHERE pack = 'mail';")
    rows = cur.fetchall()
    for row in rows:
        payload = json.loads(str(row["payload_json"]))
        seen = world.get_message(str(row["source_ref"]), as_of=t_cut)
        as_of_labels = ["INBOX"] if seen is None else list(seen["labels"])
        if list(payload.get("labels", [])) != as_of_labels:
            changed += 1
        payload["labels"] = as_of_labels
        conn.execute(
            "UPDATE raw_items SET payload_json = ? WHERE id = ?;",
            (canonical_json(payload), str(row["id"])),
        )
    conn.commit()
    return changed


def _cut_world(src: Path, dst: Path, t_cut: str, rng: random.Random) -> int:
    """Copy the world, then damage everything the copy dates after ``t_cut``."""
    shutil.copyfile(src, dst)
    conn = sqlite3.connect(str(dst))
    conn.row_factory = sqlite3.Row
    cut = timestamp_key(t_cut)
    touched = 0
    cur = conn.execute("SELECT id, acted_at FROM user_actions;")
    for row in cur.fetchall():
        if timestamp_key(str(row["acted_at"])) <= cut:
            continue
        touched += 1
        if rng.random() > 0.5:
            conn.execute("DELETE FROM user_actions WHERE id = ?;", (row["id"],))
        else:
            conn.execute(
                "UPDATE user_actions SET action_type = 'BOGUS_FUTURE_ACTION' WHERE id = ?;",
                (row["id"],),
            )
    for table, column, attr in (
        ("messages", "message_id", "received_at"),
        ("files", "path", "downloaded_at"),
    ):
        cur = conn.execute(f"SELECT {column} AS k, {attr} AS at FROM {table};")
        for row in cur.fetchall():
            if timestamp_key(str(row["at"])) > cut:
                conn.execute(f"DELETE FROM {table} WHERE {column} = ?;", (row["k"],))
    conn.commit()
    conn.close()
    return touched


def _proposal_map(conn: sqlite3.Connection, t_cut: str | None) -> dict[str, dict[str, Any]]:
    cols = ", ".join(PROPOSAL_COLUMNS)
    if t_cut is None:
        rows = conn.execute(f"SELECT situation_id, {cols} FROM proposals;").fetchall()
    else:
        rows = conn.execute(
            f"SELECT situation_id, {cols} FROM proposals WHERE proposed_at <= ?;", (t_cut,)
        ).fetchall()
    return {str(r["situation_id"]): dict(r) for r in rows}


def _feature_map(conn: sqlite3.Connection, t_cut: str) -> dict[str, dict[str, Any]]:
    """The rebuilt feature vectors for situations that arrived by ``t_cut``.

    V08 names features, not only verdicts: a proposal can survive a changed feature vector if the
    argmax happens to land in the same place, so the input the policy saw is compared separately.
    """
    cols = ", ".join(FEATURE_COLUMNS)
    rows = conn.execute(
        f"SELECT f.situation_id AS sid, {cols} FROM features f "
        "JOIN situations s ON s.id = f.situation_id "
        "WHERE s.occurred_at COLLATE UTC_TIMESTAMP <= ?;",
        (t_cut,),
    ).fetchall()
    return {str(r["sid"]): {c: r[c] for c in FEATURE_COLUMNS} for r in rows}


def _outcome_map(conn: sqlite3.Connection, horizon: str | None) -> dict[str, dict[str, Any]]:
    """Outcomes the run claims to know, optionally limited to those knowable by ``horizon``.

    With a horizon the query is deliberately a filter rather than an assertion: passing ``None``
    returns the whole table so a caller can prove nothing leaked past the cut.
    """
    cols = ", ".join(OUTCOME_COLUMNS)
    if horizon is None:
        rows = conn.execute(f"SELECT situation_id, {cols} FROM outcomes;").fetchall()
    else:
        rows = conn.execute(
            f"SELECT situation_id, {cols} FROM outcomes WHERE known_at COLLATE UTC_TIMESTAMP <= ?;",
            (horizon,),
        ).fetchall()
    return {str(r["situation_id"]): {c: r[c] for c in OUTCOME_COLUMNS} for r in rows}


def _ledger_prefix(conn: sqlite3.Connection, length: int) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT seq, kind, ref_id, payload_json, prev_hash, hash, created_at "
        "FROM ledger ORDER BY seq ASC LIMIT ?;",
        (length,),
    ).fetchall()


def _as_if_licensed(conn: sqlite3.Connection, row: dict[str, Any]) -> tuple[str, str | None, str]:
    """Recompute what the gate would have decided for this proposal at licence 3.

    No licence in the tiny corpus can be earned -- every class bottoms out at level 0, because the
    Beta posterior lower bound needs about 58 agreeing trials and the fixture has 223 situations
    spread over twenty classes. So the licensed tier is tested as the property that actually
    matters: given the inputs each proposal persisted for itself, lifting only the licence must
    produce the same decision and the same bound execution parameters whether or not the future was
    mutated. That is what CONTRACT D3/D4 and FP-D13 make the gate commit to ("binds exact
    account/resource/recipient/body"), and ``cap`` is taken from the proposal so the hard-coded
    caps still apply.
    """
    sit_id = str(row["situation_id"])
    hands_off = conn.execute(
        "SELECT hands_off_reason FROM situations WHERE id = ?;", (sit_id,)
    ).fetchone()
    feats = conn.execute(
        "SELECT reader_ok,deterministic_json FROM features WHERE situation_id = ?;", (sit_id,)
    ).fetchone()
    statuses = json.loads(feats["deterministic_json"]) if feats is not None else {}
    result = decide_gate(
        action=str(row["action"]),
        p=float(row["p_max"]),
        novel=bool(row["novel"]),
        licence_level=3,
        cap=int(row["cap"]),
        hands_off=None if hands_off is None else hands_off["hands_off_reason"],
        reader_required=bool(statuses.get("__reader_required", True)),
        reader_ok=False if feats is None else bool(feats["reader_ok"]),
        deterministic_ok=bool(statuses.get("__deterministic_ok", False)),
        loss=get_action_loss(str(row["action"])),
        attention_cost=1.0,
        recallable=is_recallable(str(row["action"])),
        audit_draw=compute_audit_draw(sit_id, seed=settings.audit_seed),
        audit_fraction=settings.audit_fraction,
        budget_ok=bool(statuses.get("__budget_ok", False)),
    )
    return result.decision.value, result.reason, str(row["params_json"])


def test_t_nopeek_future_mutation_leaves_the_past_intact(
    tiny_synth_dir: Path,
    tiny_synth_owner: list[str],
    writable_world_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-NOPEEK / V08: 50 cuts of mutated future data leave every pre-cut commitment identical."""
    # The physical scan is only reached when a configured root exists; pin it absent so the run is
    # independent of whatever data/synth happens to be on the machine running the suite.
    monkeypatch.setattr(settings, "files_allowed_roots", str(tmp_path / "no-such-root"))
    monkeypatch.setattr(settings, "files_watch_dirs", "Downloads,Desktop")

    # Explicit small-data harness override, not a production threshold change.
    # Preserve the trained-policy and licensed-execution assertions below.
    from probation.engine import replay
    from probation.engine.novelty import NoveltyDetector
    from tests.stubs.embeddings import RecordedEmbeddings

    monkeypatch.setattr(settings, "cold_start_min_situations", 20)

    def test_novelty(*args: Any, **kwargs: Any) -> NoveltyDetector:
        kwargs["embedder"] = RecordedEmbeddings()
        return NoveltyDetector(*args, **kwargs)

    monkeypatch.setattr(replay, "NoveltyDetector", test_novelty)

    from tests.stubs.stub_reader import StubReader

    reader = StubReader(tiny_synth_dir / "truth.json")
    pristine = _build_pristine_input(tiny_synth_dir, tiny_synth_owner)
    world_db = writable_world_db

    baseline = _copy_input(pristine)
    with SimWorld(world_db) as world:
        run_replay(
            baseline, clock=Clock(mode=ClockMode.REPLAY), world=world, reader_callable=reader
        )

    full = _proposal_map(baseline, None)
    assert len(full) >= CUTS, f"only {len(full)} proposals; V08 needs at least {CUTS} cut points"
    assert verify_ledger(baseline)[0], "baseline ledger failed verification before any mutation"
    baseline_ledger = _ledger_prefix(
        baseline, len(baseline.execute("SELECT seq FROM ledger;").fetchall())
    )

    # Invariant I-7, strictly: a proposal must precede the outcome it was scored against.
    joined = baseline.execute(
        """SELECT p.situation_id AS sid, p.proposed_at AS pa, o.known_at AS ka,
                  p.ledger_seq AS ps, o.ledger_seq AS os
           FROM proposals p JOIN outcomes o ON p.situation_id = o.situation_id;"""
    ).fetchall()
    assert joined, "no proposal/outcome pairs, so chronology is not being exercised"
    for r in joined:
        assert str(r["pa"]) < str(r["ka"]), f"I-7: {r['sid']} proposed_at {r['pa']} !< {r['ka']}"
        assert r["ps"] < r["os"], f"I-7: {r['sid']} ledger seq {r['ps']} !< {r['os']}"

    # A backtest observes; it never acts.
    assert not EXECUTING_GATES & {str(row["gate"]) for row in full.values()}, (
        "a replay emitted an executing gate"
    )

    # The licensed tier must not be an empty claim.
    baseline_licensed = {sid: _as_if_licensed(baseline, row) for sid, row in full.items()}
    assert any(decision in EXECUTING_GATES for decision, _, _ in baseline_licensed.values()), (
        "no proposal would execute even at licence 3, so the licensed case proves nothing"
    )

    # The evidence the policy learns from, and the vectors it was built from, are the two things a
    # truncated run can quietly get wrong while still printing the same verdict.
    baseline_outcomes = _outcome_map(baseline, None)
    assert len(baseline_outcomes) > 0, "baseline run recorded no outcomes to compare against"

    stamps = sorted(str(row["proposed_at"]) for row in full.values())
    rng = random.Random(SEED)
    cuts = [stamps[i] for i in sorted(rng.sample(range(len(stamps)), CUTS))]

    totals = {"arrivals": 0, "final_state": 0, "footprints": 0, "outcomes_held": 0}
    for cut_idx, t_cut in enumerate(cuts):
        conn = _copy_input(pristine)
        dropped = _drop_future_items(conn, t_cut)
        with SimWorld(world_db) as world:
            relabelled = _project_payload_labels(conn, world, t_cut)
        cut_world_db = tmp_path / f"world-cut-{cut_idx}.db"
        damaged = _cut_world(world_db, cut_world_db, t_cut, rng)
        totals["arrivals"] += dropped
        totals["final_state"] += relabelled
        totals["footprints"] += damaged
        assert dropped + relabelled + damaged > 0, f"cut {t_cut} had no future left to mutate"

        with SimWorld(cut_world_db) as mutated:
            run_replay(
                conn,
                clock=Clock(mode=ClockMode.REPLAY),
                world=mutated,
                until=t_cut,
                reader_callable=reader,
            )

        got = _proposal_map(conn, None)
        want = {sid: row for sid, row in full.items() if str(row["proposed_at"]) <= t_cut}
        assert got.keys() == want.keys(), (
            f"cut {cut_idx} (t={t_cut}): {len(want)} pre-cut proposals became {len(got)}"
        )
        for sid, want_row in want.items():
            got_row = got[sid]
            assert got_row == want_row, (
                f"cut {cut_idx} (t={t_cut}): situation {sid} changed in the past. "
                + "; ".join(
                    f"{col}: {want_row[col]!r} -> {got_row[col]!r}"
                    for col in PROPOSAL_COLUMNS
                    if got_row[col] != want_row[col]
                )
            )
            assert _as_if_licensed(conn, got_row) == baseline_licensed[sid], (
                f"cut {cut_idx} (t={t_cut}): licensed decision moved for {sid}"
            )

        # Everything the cut run knows must have been knowable by now. An outcome dated after the
        # horizon is a peek even when it leaves every verdict untouched -- it is what the next
        # retrain and the licence maths read, and plan 6.3.4 requires `until` to bind derived
        # events and finalization, not only proposals.
        want_outcomes = {
            sid: row for sid, row in baseline_outcomes.items() if str(row["known_at"]) <= t_cut
        }
        got_outcomes = _outcome_map(conn, None)
        assert got_outcomes.keys() == want_outcomes.keys(), (
            f"cut {cut_idx} (t={t_cut}): the horizon was not enforced; "
            f"{sorted(set(got_outcomes) - set(want_outcomes))[:3]} leaked past it"
        )
        totals["outcomes_held"] += len(baseline_outcomes) - len(want_outcomes)
        for sid, want_row in want_outcomes.items():
            got_row = got_outcomes[sid]
            assert got_row == want_row, (
                f"cut {cut_idx} (t={t_cut}): outcome for {sid} changed. "
                + "; ".join(
                    f"{col}: {want_row[col]!r} -> {got_row[col]!r}"
                    for col in OUTCOME_COLUMNS
                    if got_row[col] != want_row[col]
                )
            )

        want_features = _feature_map(baseline, t_cut)
        got_features = _feature_map(conn, t_cut)
        assert got_features.keys() == want_features.keys(), (
            f"cut {cut_idx} (t={t_cut}): "
            f"{len(want_features)} pre-cut feature vectors became {len(got_features)}"
        )
        for sid, want_row in want_features.items():
            got_row = got_features[sid]
            assert got_row == want_row, (
                f"cut {cut_idx} (t={t_cut}): features for {sid} were rebuilt from other than "
                "the past: "
                + "; ".join(
                    f"{col}: {str(want_row[col])[:80]!r} -> {str(got_row[col])[:80]!r}"
                    for col in FEATURE_COLUMNS
                    if got_row[col] != want_row[col]
                )
            )

        cut_ledger = _ledger_prefix(conn, len(conn.execute("SELECT seq FROM ledger;").fetchall()))
        assert cut_ledger == baseline_ledger[: len(cut_ledger)], (
            f"cut {cut_idx} (t={t_cut}): the ledger is not a prefix of the untruncated run"
        )
        assert verify_ledger(conn)[0], f"cut {cut_idx}: mutated ledger failed verification"

        conn.close()
        cut_world_db.unlink(missing_ok=True)

    # Every axis V08 names has to have been exercised across the 50 cuts, or the run above proved
    # only that an unmutated prefix replays identically to itself.
    assert all(count > 0 for count in totals.values()), (
        f"a V08 mutation axis was never exercised: {totals}"
    )

    baseline.close()
    pristine.close()
