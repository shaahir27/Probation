"""Test T-EVIDENCE: Evidence accumulation, filtering, and licence derivation.

Authority: docs/CONTRACT.md I-10, I-11, I-12, docs/ENGINE_SPEC.md sections 6.1, 6.3, 10, and docs/TEST_PLAN.md T-EVIDENCE.
"""

from pathlib import Path

from probation.core.enums import LicenceLevel
from probation.db.connection import apply_schema, get_connection
from probation.engine.evidence import aggregate_evidence
from probation.engine.licence import derive_licence_level


def test_t_evidence_filtering_and_counts(tmp_path: Path) -> None:
    """Verify auto-executed items excluded, audit holdouts included, weak in all only, and undo excluded from Beta counts."""
    db_file = tmp_path / "test_probation.db"
    conn = get_connection(db_file)
    apply_schema(conn)

    cur = conn.cursor()
    as_of = "2026-06-01T00:00:00Z"
    c_key = "mail|request|known"
    act = "ARCHIVE"

    # Add source and raw items
    cur.execute(
        """
        INSERT INTO sources (id, pack, kind, ref, imported_at)
        VALUES ('src-1', 'mail', 'mbox', 'ref-1', '2026-05-01T00:00:00Z');
        """
    )
    for i in range(1, 6):
        cur.execute(
            """
            INSERT INTO raw_items (id, source_id, pack, item_kind, source_ref, occurred_at, known_at, payload_json, content_hash)
            VALUES (?, 'src-1', 'mail', 'mail_in', ?, '2026-05-10T00:00:00Z', '2026-05-10T00:00:00Z', '{}', 'h');
            """,
            (f"raw-{i}", f"ref-msg-{i}"),
        )

    # 1. Proposal with gate=SHADOW and STRONG agreement outcome
    cur.executescript(
        """
        INSERT INTO situations (id, raw_item_id, pack, family, occurred_at, content_hash, created_at)
        VALUES ('sit-1', 'raw-1', 'mail', 'email_action', '2026-05-10T10:00:00Z', 'hash1', '2026-05-10T10:00:00Z');
        INSERT INTO proposals (id, situation_id, family, class_key, action, probs_json, p_max, novelty, novel, licence_level, cap, gate, reasons_json, policy_version, features_hash, audit_holdout, proposed_at, ledger_seq)
        VALUES ('prop-1', 'sit-1', 'email_action', 'mail|request|known', 'ARCHIVE', '{}', 0.9, 0.1, 0, 0, 3, 'SHADOW', '[]', 'v1', 'h1', 0, '2026-05-10T10:00:00Z', 1);
        INSERT INTO outcomes (situation_id, observed_action, strength, source, observed_at, known_at, details_json, ledger_seq)
        VALUES ('sit-1', 'ARCHIVE', 'STRONG', 'footprint', '2026-05-10T11:00:00Z', '2026-05-10T11:00:00Z', '{}', 2);
        """
    )

    # 2. Proposal with gate=SUGGEST and WEAK agreement outcome
    cur.executescript(
        """
        INSERT INTO situations (id, raw_item_id, pack, family, occurred_at, content_hash, created_at)
        VALUES ('sit-2', 'raw-2', 'mail', 'email_action', '2026-05-11T10:00:00Z', 'hash2', '2026-05-11T10:00:00Z');
        INSERT INTO proposals (id, situation_id, family, class_key, action, probs_json, p_max, novelty, novel, licence_level, cap, gate, reasons_json, policy_version, features_hash, audit_holdout, proposed_at, ledger_seq)
        VALUES ('prop-2', 'sit-2', 'email_action', 'mail|request|known', 'ARCHIVE', '{}', 0.9, 0.1, 0, 1, 3, 'SUGGEST', '[]', 'v1', 'h2', 0, '2026-05-11T10:00:00Z', 3);
        INSERT INTO outcomes (situation_id, observed_action, strength, source, observed_at, known_at, details_json, ledger_seq)
        VALUES ('sit-2', 'ARCHIVE', 'WEAK', 'window_close', '2026-05-18T10:00:00Z', '2026-05-18T10:00:00Z', '{}', 4);
        """
    )

    # 3. Proposal with gate=EXECUTE_UNDO (auto-executed) -> MUST BE EXCLUDED FROM EVIDENCE COUNTS
    cur.executescript(
        """
        INSERT INTO situations (id, raw_item_id, pack, family, occurred_at, content_hash, created_at)
        VALUES ('sit-3', 'raw-3', 'mail', 'email_action', '2026-05-12T10:00:00Z', 'hash3', '2026-05-12T10:00:00Z');
        INSERT INTO proposals (id, situation_id, family, class_key, action, probs_json, p_max, novelty, novel, licence_level, cap, gate, reasons_json, policy_version, features_hash, audit_holdout, proposed_at, ledger_seq)
        VALUES ('prop-3', 'sit-3', 'email_action', 'mail|request|known', 'ARCHIVE', '{}', 0.9, 0.1, 0, 2, 3, 'EXECUTE_UNDO', '[]', 'v1', 'h3', 0, '2026-05-12T10:00:00Z', 5);
        INSERT INTO outcomes (situation_id, observed_action, strength, source, observed_at, known_at, details_json, ledger_seq)
        VALUES ('sit-3', 'ARCHIVE', 'WEAK', 'window_close', '2026-05-19T10:00:00Z', '2026-05-19T10:00:00Z', '{}', 6);
        """
    )

    # 4. Proposal with audit_holdout=1 and gate=SUGGEST with STRONG outcome -> MUST BE INCLUDED
    cur.executescript(
        """
        INSERT INTO situations (id, raw_item_id, pack, family, occurred_at, content_hash, created_at)
        VALUES ('sit-4', 'raw-4', 'mail', 'email_action', '2026-05-13T10:00:00Z', 'hash4', '2026-05-13T10:00:00Z');
        INSERT INTO proposals (id, situation_id, family, class_key, action, probs_json, p_max, novelty, novel, licence_level, cap, gate, reasons_json, policy_version, features_hash, audit_holdout, proposed_at, ledger_seq)
        VALUES ('prop-4', 'sit-4', 'email_action', 'mail|request|known', 'ARCHIVE', '{}', 0.9, 0.1, 0, 2, 3, 'SUGGEST', '[]', 'v1', 'h4', 1, '2026-05-13T10:00:00Z', 7);
        INSERT INTO outcomes (situation_id, observed_action, strength, source, observed_at, known_at, details_json, ledger_seq)
        VALUES ('sit-4', 'ARCHIVE', 'STRONG', 'user_response', '2026-05-13T12:00:00Z', '2026-05-13T12:00:00Z', '{}', 8);
        """
    )

    # 5. Outcome from undo (source='undo') -> excluded from Beta counts
    cur.executescript(
        """
        INSERT INTO situations (id, raw_item_id, pack, family, occurred_at, content_hash, created_at)
        VALUES ('sit-5', 'raw-5', 'mail', 'email_action', '2026-05-14T10:00:00Z', 'hash5', '2026-05-14T10:00:00Z');
        INSERT INTO proposals (id, situation_id, family, class_key, action, probs_json, p_max, novelty, novel, licence_level, cap, gate, reasons_json, policy_version, features_hash, audit_holdout, proposed_at, ledger_seq)
        VALUES ('prop-5', 'sit-5', 'email_action', 'mail|request|known', 'ARCHIVE', '{}', 0.9, 0.1, 0, 2, 3, 'EXECUTE_UNDO', '[]', 'v1', 'h5', 0, '2026-05-14T10:00:00Z', 9);
        INSERT INTO outcomes (situation_id, observed_action, strength, source, observed_at, known_at, details_json, ledger_seq)
        VALUES ('sit-5', 'UNDO', 'STRONG', 'undo', '2026-05-14T11:00:00Z', '2026-05-14T11:00:00Z', '{}', 10);
        """
    )
    conn.commit()

    from tests.unit.wp5_fixture_ledger import commit_fixture_decisions

    commit_fixture_decisions(conn)
    stats = aggregate_evidence(conn, as_of=as_of)
    assert (c_key, act) in stats
    s = stats[(c_key, act)]

    assert s.n_strong == 2, f"Expected n_strong=2, got {s.n_strong}"
    assert s.k_strong == 2, f"Expected k_strong=2, got {s.k_strong}"
    assert s.n_all == 3, f"Expected n_all=3, got {s.n_all}"
    assert s.k_all == 3, f"Expected k_all=3, got {s.k_all}"
    assert s.n_recent == 2

    conn.close()


def test_t_licence_ladder_derivation() -> None:
    """Verify level progression and demotion requirements."""
    # Action ARCHIVE (recallable=True, base_cap=3)
    # Level 0: default
    l0 = derive_licence_level(
        action="ARCHIVE",
        n_all=10,
        lb_all=0.50,
        n_strong=10,
        lb_strong=0.50,
        n_recent=5,
        exam_ok_fn=lambda lvl: True,
    )
    assert l0 == LicenceLevel.WATCH

    # Level 1: n_all >= 20 and lb_all >= 0.70
    l1 = derive_licence_level(
        action="ARCHIVE",
        n_all=25,
        lb_all=0.75,
        n_strong=15,
        lb_strong=0.70,
        n_recent=10,
        exam_ok_fn=lambda lvl: False,
    )
    assert l1 == LicenceLevel.SUGGEST

    # Level 2 requires exam_ok(level=2)
    l2_no_exam = derive_licence_level(
        action="ARCHIVE",
        n_all=70,
        lb_all=0.96,
        n_strong=65,
        lb_strong=0.96,
        n_recent=25,
        exam_ok_fn=lambda lvl: False,
    )
    assert l2_no_exam == LicenceLevel.SUGGEST  # Falls back to level 1

    l2_too_thin = derive_licence_level(
        action="ARCHIVE",
        n_all=70,
        lb_all=0.96,
        n_strong=55,
        lb_strong=0.96,
        n_recent=25,
        exam_ok_fn=lambda lvl: lvl <= 2,
    )
    assert l2_too_thin == LicenceLevel.SUGGEST

    l2_ok = derive_licence_level(
        action="ARCHIVE",
        n_all=70,
        lb_all=0.96,
        n_strong=65,
        lb_strong=0.96,
        n_recent=25,
        exam_ok_fn=lambda lvl: lvl <= 2,
    )
    assert l2_ok == LicenceLevel.DO_WITH_UNDO

    # Level 3 requires recallable=True, lb_strong >= 0.98, exam_ok(level=3)
    l3_ok = derive_licence_level(
        action="ARCHIVE",
        n_all=150,
        lb_all=0.985,
        n_strong=150,
        lb_strong=0.985,
        n_recent=30,
        exam_ok_fn=lambda lvl: True,
    )
    assert l3_ok == LicenceLevel.DO_SILENTLY

    # Non-recallable action (e.g. REPLY) CANNOT achieve Level 3 (Invariant I-20)
    l3_non_recallable = derive_licence_level(
        action="REPLY",
        n_all=150,
        lb_all=0.985,
        n_strong=150,
        lb_strong=0.985,
        n_recent=30,
        exam_ok_fn=lambda lvl: True,
    )
    assert l3_non_recallable <= LicenceLevel.DO_WITH_UNDO
