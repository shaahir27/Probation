"""Accounting regression cases found while verifying the unfinished handoff."""

import sqlite3

import httpx
import pytest

from probation.db.access import Role, RoleAccess
from probation.db.guards import AccessError
from probation.db.migrations import migrate_spend_accounting
from probation.db.spend import AttemptReservation, SpendStore
from probation.llm.budget import BudgetExceeded
from tests.unit.test_wp3_spend_store import (
    BOUND,
    BOUND_IN,
    MAX_TOKENS,
    MODEL,
    _open,
    _provision,
    _store,
)


def _reserve(store: SpendStore, request_id: str) -> AttemptReservation:
    return store.reserve(
        request_id,
        ordinal=1,
        stage="structured",
        estimate_units=BOUND,
        tokens_in_bound=BOUND_IN,
        tokens_out_bound=MAX_TOKENS,
    )


def test_unsettled_duplicate_request_is_denied(memory_db: sqlite3.Connection) -> None:
    scope = _provision(memory_db, cap_units=BOUND * 4)
    _open(memory_db, scope)
    with pytest.raises(BudgetExceeded, match="already"):
        _open(memory_db, scope)


def test_settled_failure_cannot_reserve_another_attempt(memory_db: sqlite3.Connection) -> None:
    scope = _provision(memory_db, cap_units=BOUND * 4)
    request = _open(memory_db, scope)
    store = _store(memory_db)
    store.settle_request(request, result_state="failed_closed")
    with pytest.raises(BudgetExceeded):
        _reserve(store, request)


def test_account_cap_is_shared_across_models(memory_db: sqlite3.Connection) -> None:
    scope = _provision(memory_db, cap_units=BOUND)
    other = "nvidia/other"
    _provision(memory_db, cap_units=BOUND, model=other)
    store = _store(memory_db)
    first = _open(memory_db, scope)
    _reserve(store, first)
    request = store.open_request(
        store.scope_for(other),
        semantic_digest="other",
        prompt_id="reader.mail",
        prompt_version="v3",
        model_id=other,
        cache_key="other",
    )
    with pytest.raises(BudgetExceeded):
        _reserve(store, request)


@pytest.mark.parametrize(
    "field,value",
    [
        ("attempt_id", "'changed'"),
        ("lease_owner", "'intruder'"),
        ("state", "'reconciled'"),
    ],
)
def test_sql_cannot_rewrite_reserved_history(
    memory_db: sqlite3.Connection, field: str, value: str
) -> None:
    scope = _provision(memory_db, cap_units=BOUND)
    attempt = _reserve(_store(memory_db), _open(memory_db, scope))
    with pytest.raises(sqlite3.IntegrityError):
        memory_db.execute(
            f"UPDATE llm_attempts SET {field}={value} WHERE attempt_id=?", (attempt.attempt_id,)
        )


def test_generic_role_writer_cannot_bypass_row_ownership(memory_db: sqlite3.Connection) -> None:
    scope = _provision(memory_db, cap_units=BOUND)
    request = _open(memory_db, scope)
    with pytest.raises(AccessError):
        RoleAccess(memory_db, Role.EXAMINER).execute_write(
            "llm_requests",
            "UPDATE llm_requests SET result_state='failed_closed' WHERE request_id=?",
            (request,),
        )


def test_other_lease_cannot_reserve_under_active_request(memory_db: sqlite3.Connection) -> None:
    scope = _provision(memory_db, cap_units=BOUND * 4)
    request = _open(memory_db, scope)
    _reserve(_store(memory_db), request)
    with pytest.raises(BudgetExceeded):
        _store(memory_db, owner="intruder").reserve(
            request,
            ordinal=2,
            stage="retry",
            estimate_units=BOUND,
            tokens_in_bound=BOUND_IN,
            tokens_out_bound=MAX_TOKENS,
        )


def test_connect_failure_is_audited_without_releasing_dispatched_hold(
    memory_db: sqlite3.Connection,
) -> None:
    from probation.llm.budget import BudgetGuard
    from probation.llm.client import LLMClient
    from tests.unit.test_wp3_spend_store import SCHEMA, SYSTEM, TABLE, USER

    _provision(memory_db, cap_units=BOUND * 4)

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("synthetic", request=request)

    client = LLMClient(
        api_key="test",
        spend_store=_store(memory_db),
        max_retries=0,
        budget_guard=BudgetGuard(limit_usd="1", price_table=TABLE),
        transport=httpx.MockTransport(unavailable),
    )
    with pytest.raises(httpx.ConnectError):
        client.chat_json(
            kind="reader",
            model=MODEL,
            system=SYSTEM,
            user=USER,
            schema=SCHEMA,
            cache_parts={"content_hash": "connection-failure"},
            max_tokens=MAX_TOKENS,
            conn=memory_db,
        )
    row = memory_db.execute("SELECT state, estimate_units FROM llm_attempts").fetchone()
    assert tuple(row) == ("ambiguous", BOUND)


def test_runtime_limit_is_also_shared_not_only_operator_scope(
    memory_db: sqlite3.Connection,
) -> None:
    scope = _provision(memory_db, cap_units=BOUND * 10)
    store = _store(memory_db)
    _reserve(store, _open(memory_db, scope))
    request = _open(memory_db, scope, digest="second")
    with pytest.raises(BudgetExceeded):
        store.reserve(
            request,
            ordinal=1,
            stage="structured",
            estimate_units=1,
            tokens_in_bound=BOUND_IN,
            tokens_out_bound=MAX_TOKENS,
            runtime_cap_units=BOUND,
        )


def test_unconfigured_account_cannot_borrow_another_accounts_scope(
    memory_db: sqlite3.Connection,
) -> None:
    _provision(memory_db, cap_units=BOUND)
    with pytest.raises(BudgetExceeded):
        SpendStore(memory_db, role="brain", lease_owner="other", account_label="other").scope_for(
            MODEL
        )


@pytest.mark.parametrize("amount", [True, 1.5, -1])
def test_noninteger_money_is_not_a_reservation(
    memory_db: sqlite3.Connection, amount: object
) -> None:
    scope = _provision(memory_db, cap_units=BOUND)
    store = _store(memory_db)
    with pytest.raises(BudgetExceeded):
        store.reserve(
            _open(memory_db, scope),
            ordinal=1,
            stage="structured",
            estimate_units=amount,
            tokens_in_bound=BOUND_IN,
            tokens_out_bound=MAX_TOKENS,
        )


def test_migration_replaces_a_weaker_existing_transition_trigger(
    memory_db: sqlite3.Connection,
) -> None:
    memory_db.execute("DROP TRIGGER llm_attempts_no_history_update")
    memory_db.execute(
        "CREATE TRIGGER llm_attempts_no_history_update BEFORE UPDATE ON llm_attempts BEGIN SELECT 1; END"
    )
    memory_db.commit()
    assert migrate_spend_accounting(memory_db) is True
    assert migrate_spend_accounting(memory_db) is False
    scope = _provision(memory_db, cap_units=BOUND)
    attempt = _reserve(_store(memory_db), _open(memory_db, scope))
    with pytest.raises(sqlite3.IntegrityError):
        memory_db.execute(
            "UPDATE llm_attempts SET state='reconciled' WHERE attempt_id=?", (attempt.attempt_id,)
        )
