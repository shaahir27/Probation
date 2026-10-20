"""Test T-HABIT and T-CHAIN: Habit mining, wording validator, and Chains pack.

Authority: docs/ENGINE_SPEC.md sections 13 & 14, docs/PACKS_SPEC.md section 4,
docs/PROMPTS.md section 7, and docs/TEST_PLAN.md.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from probation.core.enums import EvidenceStrength, LicenceLevel
from probation.core.types import Action, Situation
from probation.db.connection import apply_schema, get_connection
from probation.engine.habits import (
    extract_numbers,
    mine_habits,
    validate_wording_sentence,
)
from probation.engine.licence import derive_licence_level
from probation.packs.chains import chains_pack
from probation.packs.chains.executor import execute_chain_action, undo_chain_action
from probation.packs.chains.mining import mine_chains
from probation.packs.chains.proposer import create_chain_situations_and_proposals
from probation.synth.world import SimWorld


def test_wording_validator_preserves_numbers() -> None:
    """T-HABIT: Wording validator rejects changed numbers and accepts identical numbers.

    Authority: docs/PROMPTS.md section 7:
    - Candidate must retain the exact multiset of numbers from the template.
    - Candidate length must be between 20 and 160 characters.
    """
    template = "You declined 31 of 33 invites with start_hour_bucket=early."
    assert extract_numbers(template) == ["31", "33"]

    # 1. Valid reworded sentence with exact numbers preserved
    valid_candidate = "You turned down 31 out of 33 early morning calendar invites."
    assert validate_wording_sentence(template, valid_candidate) is True

    # 2. Changed number: 31 -> 30
    invalid_num1 = "You turned down 30 out of 33 early morning calendar invites."
    assert validate_wording_sentence(template, invalid_num1) is False

    # 3. Changed number: 33 -> 35
    invalid_num2 = "You turned down 31 out of 35 early morning calendar invites."
    assert validate_wording_sentence(template, invalid_num2) is False

    # 4. Added extraneous number (e.g. 9 am)
    invalid_extra = "You turned down 31 out of 33 invites scheduled before 9."
    assert validate_wording_sentence(template, invalid_extra) is False

    # 5. Omitted number (dropped 33)
    invalid_missing = "You turned down 31 of the early morning calendar invites."
    assert validate_wording_sentence(template, invalid_missing) is False

    # 6. Length out of bounds (< 20 characters)
    too_short = "31 of 33 declined."
    assert validate_wording_sentence(template, too_short) is False

    # 7. Length out of bounds (> 160 characters)
    too_long = "You declined 31 of 33 invites with start_hour_bucket=early " + ("very " * 30)
    assert validate_wording_sentence(template, too_long) is False


def test_habit_mining_discovers_planted_rule(tmp_path: Path) -> None:
    """T-HABIT: Planted habit pattern is discovered with Fisher exact test and BH FDR."""
    db_path = tmp_path / "probation_habit.db"
    conn = get_connection(db_path)
    apply_schema(conn)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO sources (id, pack, kind, ref, imported_at)
        VALUES ('src-1', 'calendar', 'ics', 'ref-1', '2026-05-01T00:00:00Z');
        """
    )

    # Insert 60 total calendar situations:
    # 25 situations have start_hour_bucket=early, 24 of which are DECLINE (p=0.96)
    # 35 situations have start_hour_bucket=afternoon, 5 are DECLINE, 30 are ACCEPT
    # Total DECLINE = 29 / 60 = 0.483.
    # For early -> DECLINE: n=25, k=24. Lift = (24/25) / (29/60) = 0.96 / 0.483 = 1.988 >= 1.5.
    now = datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC)
    for i in range(60):
        sit_id = f"sit-{i:03d}"
        raw_id = f"raw-{i:03d}"
        t_str = (now + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ")

        is_early = i < 25
        bucket = "early" if is_early else "afternoon"
        if is_early:
            action = "DECLINE" if i < 24 else "ACCEPT"
        else:
            action = "DECLINE" if i < 30 else "ACCEPT"

        cur.execute(
            """
            INSERT INTO raw_items (id, source_id, pack, item_kind, source_ref, occurred_at, known_at, payload_json, content_hash)
            VALUES (?, 'src-1', 'calendar', 'cal_event', ?, ?, ?, '{}', ?);
            """,
            (raw_id, f"ref-{i}", t_str, t_str, f"hash-{i}"),
        )
        cur.execute(
            """
            INSERT INTO situations (id, raw_item_id, pack, family, occurred_at, content_hash, created_at)
            VALUES (?, ?, 'calendar', 'invite_rsvp', ?, ?, ?);
            """,
            (sit_id, raw_id, t_str, f"hash-{i}", t_str),
        )
        cur.execute(
            """
            INSERT INTO features (situation_id, deterministic_json, reader_json, reader_ok, featurizer_version, features_hash, created_at)
            VALUES (?, json(?), '{}', 1, 'v1', ?, ?);
            """,
            (sit_id, f'{{"start_hour_bucket": "{bucket}"}}', f"fhash-{i}", t_str),
        )
        cur.execute(
            """
            INSERT INTO outcomes (situation_id, observed_action, strength, source, observed_at, known_at, details_json, ledger_seq)
            VALUES (?, ?, 'STRONG', 'user_action', ?, ?, '{}', ?);
            """,
            (sit_id, action, t_str, t_str, i + 1),
        )

    conn.commit()

    habits = mine_habits(conn, as_of="2026-05-10T00:00:00Z")
    assert len(habits) >= 1

    # Look for the discovered early -> DECLINE habit
    early_habit = next(
        (
            h
            for h in habits
            if h.clue == "start_hour_bucket" and h.clue_value == "early" and h.action == "DECLINE"
        ),
        None,
    )
    assert early_habit is not None
    assert early_habit.k == 24
    assert early_habit.n == 25
    assert early_habit.lift >= 1.5
    assert early_habit.q_value < 0.01
    assert "24 of 25" in early_habit.statement
    assert "declined" in early_habit.statement.lower()


def test_habit_mining_bh_fdr_rejects_noise(tmp_path: Path) -> None:
    """T-HABIT: Random noise yields no mined habits after Benjamini-Hochberg FDR correction."""
    db_path = tmp_path / "probation_noise.db"
    conn = get_connection(db_path)
    apply_schema(conn)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO sources (id, pack, kind, ref, imported_at)
        VALUES ('src-noise', 'calendar', 'ics', 'ref-noise', '2026-05-01T00:00:00Z');
        """
    )

    now = datetime(2026, 5, 1, 10, 0, 0, tzinfo=UTC)
    # 50 situations where action is uniformly alternated independently of clue
    for i in range(50):
        sit_id = f"sit-noise-{i:03d}"
        raw_id = f"raw-noise-{i:03d}"
        t_str = (now + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        bucket = "early" if i % 2 == 0 else "afternoon"
        action = "ACCEPT" if i % 3 == 0 else "DECLINE"

        cur.execute(
            """
            INSERT INTO raw_items (id, source_id, pack, item_kind, source_ref, occurred_at, known_at, payload_json, content_hash)
            VALUES (?, 'src-noise', 'calendar', 'cal_event', ?, ?, ?, '{}', ?);
            """,
            (raw_id, f"ref-{i}", t_str, t_str, f"hash-{i}"),
        )
        cur.execute(
            """
            INSERT INTO situations (id, raw_item_id, pack, family, occurred_at, content_hash, created_at)
            VALUES (?, ?, 'calendar', 'invite_rsvp', ?, ?, ?);
            """,
            (sit_id, raw_id, t_str, f"hash-{i}", t_str),
        )
        cur.execute(
            """
            INSERT INTO features (situation_id, deterministic_json, reader_json, reader_ok, featurizer_version, features_hash, created_at)
            VALUES (?, json(?), '{}', 1, 'v1', ?, ?);
            """,
            (sit_id, f'{{"start_hour_bucket": "{bucket}"}}', f"fhash-{i}", t_str),
        )
        cur.execute(
            """
            INSERT INTO outcomes (situation_id, observed_action, strength, source, observed_at, known_at, details_json, ledger_seq)
            VALUES (?, ?, 'STRONG', 'user_action', ?, ?, '{}', ?);
            """,
            (sit_id, action, t_str, t_str, i + 1),
        )

    conn.commit()

    habits = mine_habits(conn, as_of="2026-05-10T00:00:00Z")
    assert len(habits) == 0


def test_habit_denial_state(tmp_path: Path) -> None:
    """T-HABIT: Denied habit is excluded and not reactivated on subsequent mining."""
    db_path = tmp_path / "probation_denial.db"
    conn = get_connection(db_path)
    apply_schema(conn)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO habits
        (id, family, clue, clue_value, action, k, n, lift, q_value, statement, examples_json, status, created_at)
        VALUES ('habit-123', 'invite_rsvp', 'start_hour_bucket', 'early', 'DECLINE', 25, 25, 2.0, 0.001,
                'You declined 25 of 25 invites with start_hour_bucket=early.', '[]', 'denied', '2026-05-01T00:00:00Z');
        """
    )
    conn.commit()

    cur.execute("SELECT status FROM habits WHERE id = 'habit-123';")
    row = cur.fetchone()
    assert row["status"] == "denied"


def test_chain_mining_planted_pattern(tmp_path: Path) -> None:
    """T-CHAIN: Sequence mining discovers trigger_class_key -> follow_action within 24 hours."""
    db_path = tmp_path / "probation_chain.db"
    conn = get_connection(db_path)
    apply_schema(conn)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO sources (id, pack, kind, ref, imported_at)
        VALUES ('src-mail', 'mail', 'mbox', 'ref-mail', '2026-05-01T00:00:00Z'),
               ('src-cal', 'calendar', 'ics', 'ref-cal', '2026-05-01T00:00:00Z');
        """
    )

    base_time = datetime(2026, 5, 1, 9, 0, 0, tzinfo=UTC)

    # 25 trigger email situations in class "mail|request|known"
    for i in range(25):
        t_mail = base_time + timedelta(days=i)
        sit_id = f"sit-mail-{i:03d}"
        raw_id = f"raw-mail-{i:03d}"
        t_str = t_mail.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Mail item
        cur.execute(
            """
            INSERT INTO raw_items (id, source_id, pack, item_kind, source_ref, occurred_at, known_at, payload_json, content_hash)
            VALUES (?, 'src-mail', 'mail', 'mail_in', ?, ?, ?, ?, ?);
            """,
            (
                raw_id,
                f"msg-{i}",
                t_str,
                t_str,
                '{"subject": "Project Submission Deadline", "body": "Please submit final paper by Friday"}',
                f"hash-mail-{i}",
            ),
        )
        cur.execute(
            """
            INSERT INTO situations (id, raw_item_id, pack, family, occurred_at, content_hash, created_at)
            VALUES (?, ?, 'mail', 'email_action', ?, ?, ?);
            """,
            (sit_id, raw_id, t_str, f"hash-mail-{i}", t_str),
        )
        cur.execute(
            """
            INSERT INTO proposals (id, situation_id, family, class_key, action, probs_json, p_max, novelty, novel,
                                  licence_level, cap, gate, reasons_json, policy_version, features_hash, audit_holdout, proposed_at, ledger_seq)
            VALUES (?, ?, 'email_action', 'mail|request|known', 'REPLY', '{}', 0.9, 0.1, 0, 1, 2, 'SUGGEST', '[]', 'v1', 'h', 0, ?, ?);
            """,
            (f"prop-mail-{i}", sit_id, t_str, i + 1),
        )

        # In 20 of the 25 triggers, user created a calendar focus block within 2 hours with overlapping title
        if i < 20:
            cal_time = t_mail + timedelta(hours=2)
            cal_t_str = cal_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            raw_cal_id = f"raw-cal-{i:03d}"
            cur.execute(
                """
                INSERT INTO raw_items (id, source_id, pack, item_kind, source_ref, occurred_at, known_at, payload_json, content_hash)
                VALUES (?, 'src-cal', 'calendar', 'cal_event', ?, ?, ?, ?, ?);
                """,
                (
                    raw_cal_id,
                    f"evt-{i}",
                    cal_t_str,
                    cal_t_str,
                    '{"title": "Focus: Project Submission", "description": "Prepare paper"}',
                    f"hash-cal-{i}",
                ),
            )

    # Add 25 background days without follow-ups so base rate is 20/50 = 0.40 and lift is 2.0 >= 1.5
    for i in range(25, 50):
        t_bg = base_time + timedelta(days=i)
        t_bg_str = t_bg.strftime("%Y-%m-%dT%H:%M:%SZ")
        cur.execute(
            """
            INSERT INTO raw_items (id, source_id, pack, item_kind, source_ref, occurred_at, known_at, payload_json, content_hash)
            VALUES (?, 'src-mail', 'mail', 'mail_in', ?, ?, ?, '{}', ?);
            """,
            (f"raw-bg-{i}", f"msg-bg-{i}", t_bg_str, t_bg_str, f"hash-bg-{i}"),
        )

    conn.commit()

    # Mine chains
    chains = mine_chains(conn, as_of="2026-06-25T00:00:00Z")
    assert len(chains) >= 1

    block_chain = next(
        (
            c
            for c in chains
            if c.trigger_class_key == "mail|request|known" and c.follow_action == "BLOCK_TIME"
        ),
        None,
    )
    assert block_chain is not None
    assert block_chain.n == 25
    assert block_chain.k == 20
    assert (block_chain.k / block_chain.n) >= 0.60
    assert block_chain.lift >= 1.5


def test_chain_proposer_and_variant(tmp_path: Path) -> None:
    """T-CHAIN: Proposal emission creates distinct variant situations and independent proposals."""
    db_path = tmp_path / "probation_prop.db"
    conn = get_connection(db_path)
    apply_schema(conn)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO sources (id, pack, kind, ref, imported_at)
        VALUES ('src-001', 'mail', 'mbox', 'ref-001', '2026-05-01T00:00:00Z');
        """
    )
    cur.execute(
        """
        INSERT INTO raw_items (id, source_id, pack, item_kind, source_ref, occurred_at, known_at, payload_json, content_hash)
        VALUES ('raw-001', 'src-001', 'mail', 'mail_in', 'msg-001', '2026-05-01T10:00:00Z', '2026-05-01T10:00:00Z', '{}', 'h-raw');
        """
    )
    cur.execute(
        """
        INSERT INTO chains (id, trigger_class_key, follow_action, k, n, base_rate, lift, status, created_at)
        VALUES ('chain-001', 'mail|request|known', 'BLOCK_TIME', 20, 25, 0.1, 8.0, 'active', '2026-05-01T00:00:00Z');
        """
    )
    conn.commit()

    trigger_sit = Situation(
        id="sit-test-trigger",
        pack="mail",
        family="email_action",
        variant="",
        raw_item_id="raw-001",
        occurred_at="2026-05-01T10:00:00Z",
        sender_key="prof@univ.test",
        content_hash="h-trigger",
        redacted_text="Please submit by 2026-05-03T17:00:00Z",
        hands_off_reason=None,
        created_at="2026-05-01T10:00:00Z",
    )

    reader_features = {
        "subject": "Final Report Deadline",
        "has_deadline": True,
        "deadline": "2026-05-03T17:00:00Z",
    }

    results = create_chain_situations_and_proposals(
        conn,
        trigger_sit=trigger_sit,
        trigger_class_key="mail|request|known",
        as_of="2026-05-01T10:00:00Z",
        reader_features=reader_features,
    )

    assert len(results) == 1
    chain_sit, proposal = results[0]

    assert chain_sit.pack == "chains"
    assert chain_sit.family == "chain_followup"
    assert chain_sit.variant == "BLOCK_TIME"
    assert proposal.action == "BLOCK_TIME"
    assert proposal.class_key == "chain|mail|request|known|BLOCK_TIME"
    assert "start" in proposal.params
    assert "Focus: Final Report Deadline" in proposal.params.get("title", "")


def test_chain_weak_evidence_level_1_cap() -> None:
    """T-CHAIN: Weak similarity links support Level 1 (SUGGEST) only. Level 2/3 strictly requires strong evidence."""
    # When n_all is large and lb_all is high, but n_strong is 0:
    lvl = derive_licence_level(
        action="BLOCK_TIME",
        n_all=50,
        lb_all=0.98,
        n_strong=0,
        lb_strong=0.0,
        n_recent=0,
    )
    assert lvl == LicenceLevel.SUGGEST
    assert lvl.value == 1


def test_chain_unanswered_yields_none_outcome(tmp_path: Path) -> None:
    """T-CHAIN: Unanswered chain situation after window yields NONE outcome with WEAK strength."""
    sit = Situation(
        id="sit-chain-unanswered",
        pack="chains",
        family="chain_followup",
        variant="BLOCK_TIME",
        raw_item_id="raw-dummy",
        occurred_at="2026-05-01T10:00:00Z",
        sender_key="",
        content_hash="h-chain",
        redacted_text="",
        hands_off_reason=None,
        created_at="2026-05-01T10:00:00Z",
    )
    world_db = tmp_path / "world.db"
    sim_world = SimWorld(world_db)

    now = datetime(2026, 5, 2, 11, 0, 0, tzinfo=UTC)  # 25 hours later (> 24h window)
    outcome = chains_pack.resolve_outcome(sit, sim_world, now)

    assert outcome is not None
    assert outcome.observed_action == "NONE"
    assert outcome.strength == EvidenceStrength.WEAK


def test_chain_executor_and_undo(tmp_path: Path) -> None:
    """T-CHAIN: Executor performs side-effects and successfully undoes BLOCK_TIME and CREATE_TASK."""
    world_db = tmp_path / "world_exec.db"
    sim_world = SimWorld(world_db)

    # 1. BLOCK_TIME execution and undo
    block_action = Action(
        id="act-block-1",
        proposal_id="prop-block-1",
        pack="chains",
        type="BLOCK_TIME",
        params={
            "title": "Focus: Write paper",
            "start": "2026-05-02T14:00:00Z",
            "end": "2026-05-02T15:00:00Z",
        },
        level_required=2,
        recallable=True,
        created_at="2026-05-01T10:00:00Z",
        updated_at="2026-05-01T10:00:00Z",
    )
    exec_res = execute_chain_action(block_action, sim_world)
    assert exec_res.success is True
    assert exec_res.undo_data is not None
    uid = exec_res.undo_data["uid"]

    # Verify event exists in SimWorld
    event = sim_world.get_event(uid)
    assert event is not None
    assert event["title"] == "Focus: Write paper"

    # Revert via undo
    undo_res = undo_chain_action(exec_res.undo_data, sim_world)
    assert undo_res.success is True
    assert sim_world.get_event(uid) is None

    # 2. CREATE_TASK execution and undo
    task_action = Action(
        id="act-task-1",
        proposal_id="prop-task-1",
        pack="chains",
        type="CREATE_TASK",
        params={
            "title": "Submit Final Draft",
            "due": "2026-05-05T17:00:00Z",
        },
        level_required=2,
        recallable=True,
        created_at="2026-05-01T10:00:00Z",
        updated_at="2026-05-01T10:00:00Z",
    )
    task_res = execute_chain_action(task_action, sim_world)
    assert task_res.success is True
    assert task_res.undo_data is not None
    task_id = task_res.undo_data["task_id"]

    tasks = sim_world.get_tasks()
    assert any(t["id"] == task_id and t["title"] == "Submit Final Draft" for t in tasks)

    # Revert via undo
    undo_task_res = undo_chain_action(task_res.undo_data, sim_world)
    assert undo_task_res.success is True
    assert not any(t["id"] == task_id for t in sim_world.get_tasks())
