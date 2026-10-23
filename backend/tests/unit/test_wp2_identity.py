"""WP2: one centralized owner identity, propagated everywhere and matched exactly.

Authority: docs/PACKS_SPEC.md sections 0.1-0.2 and
docs/CHANGES_IMPLEMENTATION_PLAN.md section 6.1.3 (T-ID).

An owner address that is spelled differently in the importer, the pack, the resolver and the
history view is not a cosmetic mismatch. If nothing matches, every message looks like
unowned incoming mail: no reply is attributed, no REPLY outcome is ever STRONG, and the whole
evidence base silently collapses to WEAK defaults while every test still passes.
"""

import json
import sqlite3
from pathlib import Path

from probation.core.history import HistoryView
from probation.core.identity import normalize_address, normalize_user_addresses
from probation.packs.mail.resolver import MailResolverIndex
from probation.synth.generator import generate_synthetic_world
from probation.synth.importers import import_mail
from probation.synth.personas import get_persona


def test_normalization_strips_display_names_case_and_plus_tags() -> None:
    """PACKS_SPEC 0.2: lower-case, strip display names, remove +tag from the local part."""
    assert (
        normalize_address("Meena Krishnamurthy <Meena.K+co301@National.ac.in>")
        == "meena.k@national.ac.in"
    )
    assert normalize_user_addresses("A <Me@X.test>, me+x@X.TEST ,  , b@y.test") == [
        "me@x.test",
        "b@y.test",
    ]
    assert normalize_user_addresses([" Me@X.test ", "me@x.test"]) == ["me@x.test"]


def test_a_quoted_display_name_containing_a_comma_is_one_address() -> None:
    """Splitting a header on commas would read this as two recipients and inflate n_recipients."""
    assert normalize_user_addresses('"Krishnamurthy, Meena" <m@x.test>, other@y.test') == [
        "m@x.test",
        "other@y.test",
    ]


def test_blank_and_addressless_tokens_cannot_survive_normalization() -> None:
    """An empty token is a substring of every address, so keeping one matches every sender."""
    for value in ("", "   ", ",", " , ", None):
        assert normalize_user_addresses(value) == []
    assert normalize_user_addresses(["", "  "]) == []
    assert normalize_user_addresses("not-an-address") == []


def test_owner_recognition_in_the_resolver_index_is_exact_not_substring() -> None:
    """A stranger whose address merely contains the owner's must not be indexed as owner mail.

    Substring membership here would attribute a third party's reply to the owner and mint
    STRONG evidence for an action the owner never took.
    """
    lookalike = {
        "from_addr": "notme@x.test",
        "in_reply_to": "<orig-1@x.test>",
        "received_at": "2026-01-02T10:00:00Z",
        "subject": "Re: lookalike",
    }
    genuine = {
        "from_addr": "Meena <me@x.test>",
        "in_reply_to": "<orig-2@x.test>",
        "received_at": "2026-01-02T11:00:00Z",
        "subject": "Re: genuine",
    }
    index = MailResolverIndex(["me@x.test"], [lookalike, genuine])
    assert list(index.replies_by_in_reply_to) == ["<orig-2@x.test>"]


def _insert_mail(
    conn: sqlite3.Connection, raw_id: str, from_addr: str, in_reply_to: str, at: str
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO sources (id, pack, kind, ref, imported_at) "
        "VALUES ('id-source', 'mail', 'mbox', 'id.mbox', ?)",
        (at,),
    )
    payload = json.dumps({"from": from_addr, "in_reply_to": in_reply_to, "to": "peer@x.test"})
    conn.execute(
        "INSERT INTO raw_items (id, source_id, pack, item_kind, source_ref, occurred_at, "
        "known_at, payload_json, content_hash) VALUES (?, 'id-source', 'mail', 'mail_in', ?, "
        "?, ?, ?, ?)",
        (raw_id, raw_id, at, at, payload, f"hash-{raw_id}"),
    )


def test_thread_stats_do_not_credit_a_lookalike_sender_as_the_owner(
    memory_db: sqlite3.Connection,
) -> None:
    """`get_prior_thread_stats` must decide owner participation by exact address."""
    _insert_mail(memory_db, "r-look", "notme@x.test", "<orig@x.test>", "2026-01-01T10:00:00Z")
    _insert_mail(memory_db, "r-peer", "peer@x.test", "<orig@x.test>", "2026-01-01T11:00:00Z")
    memory_db.commit()

    hist = HistoryView(memory_db, "2026-02-01T00:00:00Z")
    thread_msgs, user_sent = hist.get_prior_thread_stats(
        msg_id="<orig@x.test>", in_reply_to="", user_addresses=["me@x.test"]
    )
    assert thread_msgs == 2
    assert user_sent is False, "a lookalike sender was credited as the owner"

    _insert_mail(memory_db, "r-owner", "Meena <me@x.test>", "<orig@x.test>", "2026-01-01T12:00:00Z")
    memory_db.commit()
    thread_msgs, user_sent = hist.get_prior_thread_stats(
        msg_id="<orig@x.test>", in_reply_to="", user_addresses=["me@x.test"]
    )
    assert (thread_msgs, user_sent) == (3, True)


def test_sent_recipient_counting_is_exact_not_substring(memory_db: sqlite3.Connection) -> None:
    """`count_prior_sent_to_recipient` must not count a lookalike recipient as the target."""
    memory_db.execute(
        "INSERT OR IGNORE INTO sources (id, pack, kind, ref, imported_at) "
        "VALUES ('id-source', 'mail', 'mbox', 'id.mbox', '2026-01-01T00:00:00Z')"
    )
    for raw_id, to_addr in (("s-look", "bme@x.test"), ("s-real", "Peer <me@x.test>")):
        memory_db.execute(
            "INSERT INTO raw_items (id, source_id, pack, item_kind, source_ref, occurred_at, "
            "known_at, payload_json, content_hash) VALUES (?, 'id-source', 'mail', 'mail_sent', "
            "?, '2026-01-01T10:00:00Z', '2026-01-01T10:00:00Z', ?, ?)",
            (raw_id, raw_id, json.dumps({"to": to_addr}), f"hash-{raw_id}"),
        )
    memory_db.commit()

    hist = HistoryView(memory_db, "2026-02-01T00:00:00Z")
    assert hist.count_prior_sent_to_recipient("me@x.test") == 1


def test_import_without_an_explicit_identity_derives_the_owner_from_the_persona(
    memory_db: sqlite3.Connection, tiny_synth_dir: Path, tiny_synth_owner: list[str]
) -> None:
    """The importer propagates the persona's own identity; no caller has to restate it."""
    import_mail(tiny_synth_dir / "mailbox.mbox", memory_db)

    stored = memory_db.execute("SELECT value FROM meta WHERE key='user_addresses'").fetchone()[0]
    assert normalize_user_addresses(str(stored)) == tiny_synth_owner
    sent = memory_db.execute(
        "SELECT COUNT(*) FROM raw_items WHERE item_kind='mail_sent'"
    ).fetchone()[0]
    assert sent > 0, "owner identity was not recognized, so nothing was classified as sent"


def test_a_non_default_persona_propagates_its_own_identity(
    memory_db: sqlite3.Connection, tmp_path: Path, persona_owner
) -> None:
    """Identity propagation must not be pinned to persona 0's address."""
    persona = get_persona(7)
    expected = normalize_user_addresses(persona.email)
    assert expected != normalize_user_addresses(get_persona(0).email)

    out_dir = tmp_path / "persona7"
    generate_synthetic_world(persona_id=7, seed=3, size="tiny", out_dir=out_dir)
    assert persona_owner(out_dir) == expected

    import_mail(out_dir / "mailbox.mbox", memory_db)
    stored = memory_db.execute("SELECT value FROM meta WHERE key='user_addresses'").fetchone()[0]
    assert normalize_user_addresses(str(stored)) == expected
    sent = memory_db.execute(
        "SELECT COUNT(*) FROM raw_items WHERE item_kind='mail_sent'"
    ).fetchone()[0]
    assert sent > 0, f"persona {persona.id}'s own sent mail was not recognized"
