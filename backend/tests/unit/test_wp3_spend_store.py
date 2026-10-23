"""Durable spend accounting: the cap holds across processes, crashes and restarts.

Authority: docs/wp3/W3_D03_SPEND_ACCOUNTING_REVIEW.md sections 3-7, W3-T14 to W3-T18 and
W3-T31. Fake transport only; no provider is contacted and no money is spent.
"""

import sqlite3
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.db.connection import get_connection, init_db
from probation.db.migrations import drop_spend_accounting, migrate_spend_accounting
from probation.db.spend import (
    SpendStore,
    default_lease_owner,
    period_key_for,
    provision_budget_scope,
)
from probation.llm.budget import BudgetExceeded, BudgetGuard, cost_units, input_token_bound
from probation.llm.client import LLMClient

MODEL = "nvidia/priced"
TABLE = {MODEL: (Decimal("0.06"), Decimal("0.24"))}
SYSTEM = "Validator"
USER = "Validate this item"
MAX_TOKENS = 64
SCHEMA: dict[str, object] = {"type": "object"}
BOUND_IN = input_token_bound(len(SYSTEM) + len(USER))
BOUND = cost_units(BOUND_IN, MAX_TOKENS, *TABLE[MODEL])
NOW = "2026-10-23T09:00:00Z"


def _provision(
    conn: sqlite3.Connection, *, cap_units: int, model: str = MODEL, rule: str = "total"
) -> str:
    return provision_budget_scope(
        conn,
        provider="nebius_token_factory",
        account_label="primary",
        model_id=model,
        period_rule=rule,
        period_key=period_key_for(rule, NOW),
        cap_units=cap_units,
        price_version="prices-test-v1",
        created_at_op=NOW,
    )


def _store(conn: sqlite3.Connection, *, role: str = "brain", owner: str = "brain-1") -> SpendStore:
    return SpendStore(conn, role=role, lease_owner=owner)


def _open(conn: sqlite3.Connection, scope_id: str, *, digest: str = "digest-a") -> str:
    store = _store(conn)
    scope = store.scope_for(MODEL)
    assert scope.scope_id == scope_id
    return store.open_request(
        scope,
        semantic_digest=digest,
        prompt_id="reader.mail",
        prompt_version="v3",
        model_id=MODEL,
        cache_key="cache-key-a",
        situation_id="sit-a",
    )


def _file_db(tmp_path: Path) -> Path:
    target = tmp_path / "spend.db"
    init_db(target)
    return target


def test_schema_declares_the_durable_accounting_objects(
    memory_db: sqlite3.Connection,
) -> None:
    """W3-T14 precondition: a fresh database carries the objects the cap is enforced on."""
    names = {row[0] for row in memory_db.execute("SELECT name FROM sqlite_master")}
    assert {"budget_scopes", "llm_requests", "llm_attempts"} <= names
    assert {"llm_attempts_open_by_scope", "llm_attempts_charged_by_scope"} <= names
    assert "llm_attempts_no_history_update" in names
    assert "cost_units" in {row[1] for row in memory_db.execute("PRAGMA table_info(exposure_log)")}


def test_migration_is_rerunnable_and_the_rollback_leaves_every_other_table_alone(
    tmp_path: Path,
) -> None:
    """The readiness gate requires an additive, re-runnable migration with a real rollback."""
    target = _file_db(tmp_path)
    conn = get_connection(target)
    try:
        conn.execute("INSERT INTO sources VALUES ('src','mail','synthetic','test',?)", (NOW,))
        conn.execute(
            "INSERT INTO raw_items VALUES ('r1','src','mail','mail_in','ref',?,?,'{}','h')",
            (NOW, NOW),
        )
        conn.execute(
            "INSERT INTO situations (id,pack,family,raw_item_id,occurred_at,sender_key,"
            "content_hash,redacted_text,variant,created_at) VALUES "
            "('s1','mail','email_action','r1',?,'k','h','t','REPLY',?)",
            (NOW, NOW),
        )
        conn.commit()
        assert migrate_spend_accounting(conn) is False  # already applied by ensure_schema
        drop_spend_accounting(conn)
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert "llm_attempts" not in names
        assert conn.execute("SELECT COUNT(*) FROM situations").fetchone()[0] == 1
        assert migrate_spend_accounting(conn) is True
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert {"budget_scopes", "llm_requests", "llm_attempts"} <= names
    finally:
        conn.close()


def test_two_processes_cannot_both_be_authorized_for_the_last_unit(tmp_path: Path) -> None:
    """W3-T14: the durable cap serializes two workers; an in-process counter cannot."""
    target = _file_db(tmp_path)
    first = get_connection(target)
    second = get_connection(target)
    try:
        scope_id = _provision(first, cap_units=BOUND)
        request_a = _open(first, scope_id, digest="digest-a")
        request_b = _open(second, scope_id, digest="digest-b")

        worker_a = SpendStore(first, role="brain", lease_owner="brain-a")
        worker_a.reserve(
            request_a,
            ordinal=1,
            stage="structured",
            estimate_units=BOUND,
            tokens_in_bound=BOUND_IN,
            tokens_out_bound=MAX_TOKENS,
        )

        worker_b = SpendStore(second, role="brain", lease_owner="brain-b")
        with pytest.raises(BudgetExceeded) as denial:
            worker_b.reserve(
                request_b,
                ordinal=1,
                stage="structured",
                estimate_units=1,
                tokens_in_bound=BOUND_IN,
                tokens_out_bound=MAX_TOKENS,
            )
        assert denial.value.code == "cap_exceeded"
    finally:
        first.close()
        second.close()


def test_a_killed_dispatch_keeps_holding_its_money(tmp_path: Path) -> None:
    """W3-T15: a restart adopts the dead worker's hold instead of forgetting it."""
    target = _file_db(tmp_path)
    conn = get_connection(target)
    try:
        scope_id = _provision(conn, cap_units=BOUND * 2)
        request_id = _open(conn, scope_id)
        dead = SpendStore(conn, role="brain", lease_owner="brain-dead")
        reservation = dead.reserve(
            request_id,
            ordinal=1,
            stage="structured",
            estimate_units=BOUND,
            tokens_in_bound=BOUND_IN,
            tokens_out_bound=MAX_TOKENS,
        )
        dead.mark_dispatched(reservation.attempt_id)

        # A new process, new lease: the dispatched row is still money the provider may bill.
        revived = SpendStore(conn, role="brain", lease_owner="brain-revived")
        totals = revived.startup_totals(revived.scope_for(MODEL))
        assert totals.held_units == BOUND
        assert totals.spent_units == 0
        guard = BudgetGuard(limit_usd="1.00", price_table=TABLE)
        guard.adopt_durable(spent_units=totals.spent_units, held_units=totals.held_units)
        assert guard.held_units == BOUND

        with pytest.raises(BudgetExceeded) as denial:
            revived.mark_never_dispatched(reservation.attempt_id)
        assert denial.value.code in {"usage_invalid", "spend_authority_denied"}

        # A different lease cannot reclaim an attempt merely because the worker restarted.
        with pytest.raises(BudgetExceeded):
            revived.reconcile(
                reservation.attempt_id, charged_units=BOUND, usage_provenance="estimated"
            )
        # The original owner can reconcile if it resumes; no silent lease takeover.
        dead.reconcile(
            reservation.attempt_id,
            charged_units=BOUND,
            usage_provenance="estimated",
            tokens_in=BOUND_IN,
            tokens_out=MAX_TOKENS,
            denial_code="transport",
        )
        after = revived.startup_totals(revived.scope_for(MODEL))
        assert (after.spent_units, after.held_units) == (BOUND, 0)
    finally:
        conn.close()


def test_a_repeated_ordinal_for_one_request_is_refused(tmp_path: Path) -> None:
    """W3-T16: one logical request cannot pay twice for the same physical attempt."""
    target = _file_db(tmp_path)
    conn = get_connection(target)
    try:
        scope_id = _provision(conn, cap_units=BOUND * 4)
        request_id = _open(conn, scope_id)
        store = _store(conn)
        bounds = {
            "estimate_units": BOUND,
            "tokens_in_bound": BOUND_IN,
            "tokens_out_bound": MAX_TOKENS,
        }
        store.reserve(request_id, ordinal=1, stage="structured", **bounds)
        with pytest.raises(BudgetExceeded) as denial:
            store.reserve(request_id, ordinal=1, stage="retry", **bounds)
        assert denial.value.code == "duplicate_request"
        store.reserve(request_id, ordinal=2, stage="retry", **bounds)
        assert conn.execute("SELECT COUNT(*) FROM llm_attempts").fetchone()[0] == 2
    finally:
        conn.close()


def test_an_already_answered_request_cannot_be_bought_again(tmp_path: Path) -> None:
    """Single-flight at the identity level: a settled success is not reopened."""
    target = _file_db(tmp_path)
    conn = get_connection(target)
    try:
        scope_id = _provision(conn, cap_units=BOUND * 4)
        request_id = _open(conn, scope_id)
        _store(conn).settle_request(request_id, result_state="succeeded")
        with pytest.raises(BudgetExceeded) as denial:
            _open(conn, scope_id)
        assert denial.value.code == "duplicate_request"
    finally:
        conn.close()


def test_an_unavailable_accounting_store_denies_the_dispatch(tmp_path: Path) -> None:
    """W3-T17/W3-T31: no store means no send, never a silent in-process fallback."""
    target = _file_db(tmp_path)
    conn = get_connection(target)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    try:
        drop_spend_accounting(conn)
        with pytest.raises(BudgetExceeded) as denial:
            SpendStore(conn, role="brain", lease_owner="brain-1")
        assert denial.value.code == "accounting_store_unavailable"

        migrate_spend_accounting(conn)
        scope_id = _provision(conn, cap_units=BOUND * 4)
        store = _store(conn)
        client = LLMClient(
            api_key="test-key",
            budget_guard=BudgetGuard(limit_usd="1.00", price_table=TABLE),
            transport=httpx.MockTransport(handler),
            max_retries=0,
            spend_store=store,
        )
        # A caller transaction that would span the network call is a denial, not a savepoint.
        conn.execute("BEGIN IMMEDIATE")
        with pytest.raises(BudgetExceeded) as denied:
            client.chat_json(
                kind="reader",
                model=MODEL,
                system=SYSTEM,
                user=USER,
                schema=SCHEMA,
                cache_parts={"content_hash": "hash-unavailable"},
                max_tokens=MAX_TOKENS,
                conn=conn,
            )
        conn.rollback()
        assert denied.value.code == "accounting_store_unavailable"
        assert calls == []

        # A scope nobody provisioned denies the call rather than pricing itself.
        with pytest.raises(BudgetExceeded) as unpriced:
            client.chat_json(
                kind="reader",
                model="nvidia/unprovisioned",
                system=SYSTEM,
                user=USER,
                schema=SCHEMA,
                cache_parts={"content_hash": "hash-noscope"},
                max_tokens=MAX_TOKENS,
                conn=conn,
            )
        assert unpriced.value.code == "scope_missing"
        assert calls == []
        assert scope_id
    finally:
        conn.close()


def test_a_role_may_only_touch_its_own_rows(tmp_path: Path) -> None:
    """W3-D03 section 4: row-scoped grants, not a blanket table allowlist."""
    target = _file_db(tmp_path)
    conn = get_connection(target)
    try:
        scope_id = _provision(conn, cap_units=BOUND * 4)
        request_id = _open(conn, scope_id)
        brain = _store(conn, role="brain", owner="brain-1")
        reservation = brain.reserve(
            request_id,
            ordinal=1,
            stage="structured",
            estimate_units=BOUND,
            tokens_in_bound=BOUND_IN,
            tokens_out_bound=MAX_TOKENS,
        )
        brain.mark_dispatched(reservation.attempt_id)

        examiner = _store(conn, role="examiner", owner="examiner-1")
        with pytest.raises(BudgetExceeded) as denied:
            examiner.reconcile(
                reservation.attempt_id, charged_units=BOUND, usage_provenance="estimated"
            )
        assert denied.value.code == "spend_authority_denied"

        # A different lease of the same role cannot advance someone else's attempt either.
        fenced = _store(conn, role="brain", owner="brain-2")
        with pytest.raises(BudgetExceeded) as fenced_out:
            fenced.reconcile(
                reservation.attempt_id, charged_units=BOUND, usage_provenance="estimated"
            )
        assert fenced_out.value.code == "spend_authority_denied"
        assert (
            conn.execute(
                "SELECT state FROM llm_attempts WHERE attempt_id = ?", (reservation.attempt_id,)
            ).fetchone()[0]
            == "dispatched"
        )
    finally:
        conn.close()


def test_attempt_history_cannot_be_rewritten(tmp_path: Path) -> None:
    """The bound, the ordinal and the reservation time are history; a charge only grows."""
    target = _file_db(tmp_path)
    conn = get_connection(target)
    try:
        scope_id = _provision(conn, cap_units=BOUND * 4)
        request_id = _open(conn, scope_id)
        store = _store(conn)
        reservation = store.reserve(
            request_id,
            ordinal=1,
            stage="structured",
            estimate_units=BOUND,
            tokens_in_bound=BOUND_IN,
            tokens_out_bound=MAX_TOKENS,
        )
        store.mark_dispatched(reservation.attempt_id)
        store.reconcile(reservation.attempt_id, charged_units=BOUND, usage_provenance="estimated")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE llm_attempts SET estimate_units = 1 WHERE attempt_id = ?",
                (reservation.attempt_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE llm_attempts SET charged_units = 0 WHERE attempt_id = ?",
                (reservation.attempt_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE llm_attempts SET state = 'reserved' WHERE attempt_id = ?",
                (reservation.attempt_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM llm_attempts WHERE attempt_id = ?", (reservation.attempt_id,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE budget_scopes SET cap_units = 1 WHERE scope_id = ?", (scope_id,))
        row = conn.execute(
            "SELECT state, estimate_units, charged_units FROM llm_attempts WHERE attempt_id = ?",
            (reservation.attempt_id,),
        ).fetchone()
        assert (row[0], row[1], row[2]) == ("reconciled", BOUND, BOUND)
    finally:
        conn.close()


def test_startup_reconciliation_denies_when_exposure_disagrees(tmp_path: Path) -> None:
    """W3-T18: a recorded exposure that its attempts do not support is untrusted metadata."""
    target = _file_db(tmp_path)
    conn = get_connection(target)
    try:
        scope_id = _provision(conn, cap_units=BOUND * 4)
        request_id = _open(conn, scope_id)
        store = _store(conn)
        reservation = store.reserve(
            request_id,
            ordinal=1,
            stage="structured",
            estimate_units=BOUND,
            tokens_in_bound=BOUND_IN,
            tokens_out_bound=MAX_TOKENS,
        )
        store.mark_dispatched(reservation.attempt_id)
        store.reconcile(
            reservation.attempt_id,
            charged_units=BOUND,
            usage_provenance="reported",
            tokens_in=10,
            tokens_out=5,
        )
        store.settle_request(request_id, result_state="succeeded")
        from probation.core.hashing import det_id
        from probation.db.inference import EXPOSURE_ID_PREFIX

        exposure_id = det_id(EXPOSURE_ID_PREFIX, "cache-key-a")
        conn.execute(
            "INSERT INTO exposure_log (id, situation_id, call_kind, model_id, tokens_in, "
            "tokens_out, redaction_counts_json, cost_usd, cost_units, created_at) "
            "VALUES (?,'sit-a','reader',?,10,5,'{}',0.0,?,?)",
            (exposure_id, MODEL, BOUND, NOW),
        )
        conn.commit()
        assert store.startup_totals(store.scope_for(MODEL)).verified_exposure_rows == 1

        conn.execute(
            "UPDATE exposure_log SET cost_units = ? WHERE id = ?", (BOUND + 1, exposure_id)
        )
        conn.commit()
        with pytest.raises(BudgetExceeded) as denial:
            store.startup_totals(store.scope_for(MODEL))
        assert denial.value.code == "cost_metadata_invalid"
    finally:
        conn.close()


def test_reservations_are_not_effects_and_never_append_to_the_ledger(tmp_path: Path) -> None:
    """I-8: only an executed action is an effect, so the ledger is untouched by accounting."""
    target = _file_db(tmp_path)
    conn = get_connection(target)
    try:
        before = conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
        scope_id = _provision(conn, cap_units=BOUND * 4)
        request_id = _open(conn, scope_id)
        store = _store(conn)
        reservation = store.reserve(
            request_id,
            ordinal=1,
            stage="structured",
            estimate_units=BOUND,
            tokens_in_bound=BOUND_IN,
            tokens_out_bound=MAX_TOKENS,
        )
        store.mark_dispatched(reservation.attempt_id)
        store.reconcile(reservation.attempt_id, charged_units=BOUND, usage_provenance="estimated")
        store.settle_request(request_id, result_state="succeeded")
        assert conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == before
    finally:
        conn.close()


def test_the_semantic_replay_clock_cannot_age_a_lease(tmp_path: Path) -> None:
    """W3-D03 section 2: operational timestamps only, from a separately injected clock."""
    target = _file_db(tmp_path)
    conn = get_connection(target)
    try:
        with pytest.raises(BudgetExceeded) as denial:
            SpendStore(
                conn,
                role="brain",
                lease_owner="brain-1",
                clock=Clock(mode=ClockMode.REPLAY),
            )
        assert denial.value.code == "spend_authority_denied"
        assert period_key_for("calendar_day", NOW) == "2026-10-23"
        assert period_key_for("calendar_month", NOW) == "2026-10"
        assert period_key_for("total", NOW) == "total"
    finally:
        conn.close()


def test_a_full_dispatch_records_one_reconciled_attempt_per_send(
    memory_db: sqlite3.Connection,
) -> None:
    """The client books every physical send durably, and the exposure row agrees with it."""
    scope_id = _provision(memory_db, cap_units=BOUND * 8)
    store = _store(memory_db, owner=default_lease_owner("brain"))
    client = LLMClient(
        api_key="test-key",
        budget_guard=BudgetGuard(limit_usd="1.00", price_table=TABLE),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": '{"verdict": "valid"}'}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )
        ),
        max_retries=0,
        spend_store=store,
    )
    client.chat_json(
        kind="reader",
        model=MODEL,
        system=SYSTEM,
        user=USER,
        schema=SCHEMA,
        cache_parts={"content_hash": "hash-durable"},
        max_tokens=MAX_TOKENS,
        conn=memory_db,
        situation_id="sit-durable",
    )
    memory_db.commit()

    attempt = memory_db.execute(
        "SELECT ordinal, stage, state, estimate_units, charged_units, usage_provenance, "
        "tokens_in, tokens_out, denial_code FROM llm_attempts"
    ).fetchone()
    reported = cost_units(10, 5, *TABLE[MODEL])
    assert tuple(attempt) == (
        1,
        "structured",
        "reconciled",
        BOUND,
        reported,
        "reported",
        10,
        5,
        None,
    )
    request = memory_db.execute("SELECT result_state, scope_id FROM llm_requests").fetchone()
    assert (request[0], request[1]) == ("succeeded", scope_id)
    exposure = memory_db.execute("SELECT cost_units FROM exposure_log").fetchone()
    assert exposure[0] == reported

    totals = store.startup_totals(store.scope_for(MODEL))
    assert totals.spent_units == reported
    assert totals.held_units == 0
    assert totals.verified_exposure_rows == 1
    assert totals.unverified_exposure_rows == 0
