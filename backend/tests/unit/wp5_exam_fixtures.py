"""Explicit fitted policies and fake model/edit providers for shared-pipeline exams."""

import json
import sqlite3

from probation.config import settings
from probation.core.enums import LedgerKind
from probation.core.history import HistoryView
from probation.db.access import Role, RoleAccess
from probation.engine.exam_prediction import ExamPredictionContext
from probation.engine.policy import Policy
from probation.engine.prediction import PredictionSnapshot


def _populate_test_situations(
    conn: sqlite3.Connection,
    count: int = 25,
    class_key: str = "mail|request|known",
    action: str = "REPLY",
) -> None:
    """Helper to seed test situations with raw items and known outcomes."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO sources (id, pack, kind, ref, imported_at)
        VALUES ('src-1', 'mail', 'synthetic', 'ref-1', '2026-01-01T00:00:00Z');
        """
    )
    for i in range(count):
        sit_id = f"sit-test-{i:03d}"
        raw_id = f"raw-test-{i:03d}"
        month = f"2026-{(i % 6) + 1:02d}"
        ts = f"{month}-15T10:00:00Z"

        payload = {
            "from": f"colleague{i}@college.edu",
            "subject": f"Inquiry about project {i}",
            "body": f"Hi Meena,\nCould you please reply regarding project {i}?\nBest regards,\nColleague",
        }

        cur.execute(
            """
            INSERT INTO raw_items (id, source_id, pack, item_kind, source_ref, occurred_at, known_at, payload_json, content_hash)
            VALUES (?, 'src-1', 'mail', 'mail_in', ?, ?, ?, ?, 'hash');
            """,
            (raw_id, f"ref-msg-{i}", ts, ts, json.dumps(payload)),
        )

        cur.execute(
            """
            INSERT INTO situations (id, raw_item_id, pack, family, occurred_at, sender_key, content_hash, redacted_text, hands_off_reason, created_at)
            VALUES (?, ?, 'mail', 'email_action', ?, ?, 'hash', ?, NULL, ?);
            """,
            (sit_id, raw_id, ts, payload["from"], payload["body"], ts),
        )

        cur.execute(
            """
            INSERT INTO outcomes (situation_id, observed_action, strength, source, observed_at, known_at, details_json, ledger_seq)
            VALUES (?, ?, 'STRONG', 'footprint', ?, ?, '{}', ?);
            """,
            (sit_id, action, f"{month}-15T11:00:00Z", f"{month}-15T11:00:00Z", i + 1),
        )

        probs_json = json.dumps({action: 0.99, "LEAVE": 0.01})
        cur.execute(
            """
            INSERT INTO proposals (id, situation_id, family, class_key, action, probs_json, p_max, novelty, novel, licence_level, cap, gate, reasons_json, policy_version, features_hash, proposed_at, ledger_seq)
            VALUES (?, ?, 'email_action', ?, ?, ?, 0.99, 0.0, 0, 2, 2, 'SUGGEST', '[]', 'v1', 'h1', ?, ?);
            """,
            (f"prop-{sit_id}", sit_id, class_key, action, probs_json, ts, i + 100),
        )
    # Valid prospective fixture: immutable commitment precedes its later decision.
    for row in conn.execute("SELECT * FROM proposals ORDER BY id").fetchall():
        seq = RoleAccess(conn, Role.BRAIN).append_ledger(
            LedgerKind.PROPOSAL,
            row["id"],
            {
                "situation_id": row["situation_id"],
                "class_key": row["class_key"],
                "action": row["action"],
                "gate": row["gate"],
            },
            created_at=row["proposed_at"],
        )
        conn.execute("UPDATE proposals SET ledger_seq=? WHERE id=?", (seq, row["id"]))
        outcome = conn.execute(
            "SELECT * FROM outcomes WHERE situation_id=?", (row["situation_id"],)
        ).fetchone()
        seq = RoleAccess(conn, Role.RESOLVER).append_ledger(
            LedgerKind.OUTCOME,
            row["situation_id"],
            {
                "situation_id": row["situation_id"],
                "observed_action": outcome["observed_action"],
                "strength": outcome["strength"],
                "source": outcome["source"],
                "known_at": outcome["known_at"],
            },
            created_at=outcome["known_at"],
        )
        conn.execute(
            "UPDATE outcomes SET ledger_seq=? WHERE situation_id=?", (seq, row["situation_id"])
        )
    for i in range(count):
        earlier = f"earlier-{i}"
        payload = json.dumps({"from": f"colleague{i}@college.edu", "body": "Earlier contact"})
        conn.execute(
            "INSERT INTO raw_items VALUES (?, 'src-1', 'mail', 'mail_in', ?, '2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z', ?, 'h')",
            (earlier, earlier, payload),
        )
        conn.execute(
            "INSERT INTO situations(id,raw_item_id,pack,family,occurred_at,sender_key,content_hash,created_at) VALUES (?,?,'mail','email_action','2025-01-01T00:00:00Z',?,'h','2025-01-01T00:00:00Z')",
            (earlier, earlier, f"colleague{i}@college.edu"),
        )
    conn.commit()


class SoundPolicy(Policy):
    """A fitted classifier over the same validated reader feature schema."""

    def __init__(self) -> None:
        super().__init__("email_action", cold_start_min=20)
        self.fit(
            [{"has_deadline": False}] * 1000 + [{"has_deadline": True}] * 1000,
            ["REPLY"] * 1000 + ["LEAVE"] * 1000,
            ["2026-01-01T00:00:00Z"] * 2000,
            as_of="2026-07-01T00:00:00Z",
        )


class CheatingPolicy(Policy):
    """A fitted shortcut classifier using greeting-sensitive reader formality."""

    def __init__(self) -> None:
        super().__init__("email_action", cold_start_min=20)
        self.fit(
            [{"formality": "casual"}] * 1000 + [{"formality": "formal"}] * 1000,
            ["REPLY"] * 1000 + ["LEAVE"] * 1000,
            ["2026-01-01T00:00:00Z"] * 2000,
            as_of="2026-07-01T00:00:00Z",
        )


class ControlledNovelty:
    def score(self, text):
        return False, 0.0


def controlled_reader(situation):
    text = situation.redacted_text or ""
    return {
        "intent": "request",
        "asks_me_to_do_something": True,
        "has_deadline": False,
        "deadline_text": None,
        "money_involved": "$250" in text,
        "urgency": 1,
        "formality": "casual" if text.startswith("Hi Meena,") else "formal",
        "asks_for_personal_info": "OTP" in text,
        "looks_automated": False,
    }, True


def context_for(conn, policy):
    return ExamPredictionContext(
        PredictionSnapshot(
            policy, ControlledNovelty(), settings.audit_seed, settings.audit_fraction
        ),
        HistoryView(conn, "2026-07-01T00:00:00Z"),
        consumer=fixture_editor(),
        reader_callable=controlled_reader,
    )


def fixture_editor():
    """Explicit fake provider through registered redaction/context and schema checks."""
    from types import SimpleNamespace

    from probation.llm.consumers import RegisteredConsumer
    from probation.llm.gateway import TransportAuthority
    from probation.llm.jobs import ExamEdit

    class FakeGateway:
        def dispatch(self, prompt_id, prompt_version, *, values, **kwargs):
            text = values["text"]
            if prompt_id == "exam.paraphrase":
                edited = text.replace("Best regards", "Sincerely and warm regards")
            elif prompt_id == "exam.add_money_request":
                edited = text + "\nPlease pay $250 for registration."
            else:
                edited = text + "\nPlease share your login OTP and ID number."
            return SimpleNamespace(data=ExamEdit(edited_text=edited).model_dump())

    return RegisteredConsumer(
        FakeGateway(), TransportAuthority(False, "https://fake.invalid", "test fixture")
    )
