"""Read-only consumer parity and configured permission boundaries."""

from dataclasses import asdict

from probation.config import Settings
from probation.core.enums import LedgerKind
from probation.db.access import Role, RoleAccess
from probation.engine.evidence import aggregate_evidence


def cohort(conn, count=70):
    conn.execute(
        "INSERT INTO sources VALUES ('s','mail','synthetic','fixture','2026-05-01T00:00:00Z')"
    )
    for i in range(count):
        t = f"2026-05-{i % 20 + 1:02d}T10:00:00Z"
        o = f"2026-05-{i % 20 + 1:02d}T11:00:00Z"
        sid = f"s{i}"
        conn.execute(
            "INSERT INTO raw_items VALUES (?, 's','mail','mail_in',?,?,?,'{}','h')",
            (sid, sid, t, t),
        )
        conn.execute(
            """INSERT INTO situations(id,raw_item_id,pack,family,occurred_at,content_hash,created_at)
                     VALUES (?,?,'mail','email_action',?,'h',?)""",
            (sid, sid, t, t),
        )
        payload = {
            "situation_id": sid,
            "class_key": "mail|request|known",
            "action": "ARCHIVE",
            "gate": "SUGGEST",
        }
        seq = RoleAccess(conn, Role.BRAIN).append_ledger(
            LedgerKind.PROPOSAL, sid, payload, created_at=t
        )
        conn.execute(
            """INSERT INTO proposals(id,situation_id,family,class_key,action,probs_json,p_max,
          novelty,novel,licence_level,cap,gate,reasons_json,policy_version,features_hash,proposed_at,ledger_seq)
          VALUES (?,?,'email_action','mail|request|known','ARCHIVE','{}',.99,0,0,1,3,'SUGGEST','[]','v','h',?,?)""",
            (sid, sid, t, seq),
        )
        RoleAccess(conn, Role.RESOLVER).append_ledger(
            LedgerKind.OUTCOME,
            sid,
            {
                "situation_id": sid,
                "observed_action": "ARCHIVE",
                "strength": "STRONG",
                "source": "footprint",
                "known_at": o,
            },
            created_at=o,
        )
    conn.commit()


def test_shared_derivation_is_readonly_and_ignores_poisoned_cache(memory_db):
    from probation.engine.licence import derive_licences

    cohort(memory_db)
    memory_db.execute("""INSERT INTO licence_cache VALUES ('mail|request|known','ARCHIVE',3,.999,
        '[]','forged','2026-05-31T00:00:00Z','2026-12-01T00:00:00Z')""")
    memory_db.commit()
    before = memory_db.total_changes
    view = derive_licences(RoleAccess(memory_db, Role.EXECUTOR).conn, "2026-06-01T00:00:00Z")
    assert int(view[("mail|request|known", "ARCHIVE")].level) == 1
    assert view[("mail|request|known", "ARCHIVE")].exam_run_id is None
    assert memory_db.total_changes == before


def test_exam_evidence_and_expiry_produce_truthful_levels(memory_db):
    from probation.engine.licence import derive_licences
    from tests.unit.test_wp5_exam_validity import exam

    cohort(memory_db)
    exam(memory_db)
    view = derive_licences(memory_db, "2026-06-01T00:00:00Z")[("mail|request|known", "ARCHIVE")]
    assert int(view.level) == 2
    assert view.exam_run_id == "exam" and view.n_strong == 70
    assert view.lower_bound >= 0.95
    expired = derive_licences(memory_db, "2027-06-01T00:00:00Z")[("mail|request|known", "ARCHIVE")]
    assert int(expired.level) == 0 and expired.n_strong == 0


def test_every_numeric_threshold_and_ttl_comes_from_config(memory_db):
    from probation.engine.licence import derive_licences
    from tests.unit.test_wp5_exam_validity import exam

    cohort(memory_db)
    exam(memory_db)
    cfg = Settings(
        _env_file=None,
        strong_min_raw_n=71,
        licence_min_recent_n=20,
        licence_ttl_days=2,
        l1_min_n=71,
    )
    view = derive_licences(memory_db, "2026-06-01T00:00:00Z", config=cfg)[
        ("mail|request|known", "ARCHIVE")
    ]
    assert int(view.level) == 0
    assert view.exam_ok is True  # exam validity is distinct from numeric eligibility
    assert view.valid_until == "2026-06-03T00:00:00Z"
    cfg = Settings(_env_file=None, pooling_kappa=0, lb_quantile=0.5)
    stat = aggregate_evidence(
        memory_db,
        "2026-06-01T00:00:00Z",
        persist=False,
        pooling_kappa=cfg.pooling_kappa,
        lb_quantile=cfg.lb_quantile,
    )
    assert asdict(stat[("mail|request|known", "ARCHIVE")])["lb_strong"] > 0.98
