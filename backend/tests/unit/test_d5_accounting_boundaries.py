"""Accounting edge evidence: exact usage, shared quotas, restart and old-schema upgrade."""

import sqlite3
from pathlib import Path

import httpx
import pytest

from probation.config import settings
from probation.db.access import Role
from probation.db.connection import get_connection, get_role_connection
from probation.db.tavily_migration import migrate_tavily_accounting
from probation.llm.budget import BudgetExceeded
from probation.web.accounting import TavilyAccounting, accounting_summary, credit_units
from probation.web.client import TavilyClient

from .test_d5_accounting import OperationalClock, database


def provider(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"results": [], "usage": {"credits": 1}})


def test_recreated_client_cannot_blindly_resend_same_ambiguous_query(tmp_path: Path) -> None:
    path = tmp_path / "restart-query.db"
    conn = database(path)
    calls = []

    def timeout(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("synthetic ambiguous response")

    for _ in range(2):
        restarted = TavilyClient(
            api_key="synthetic",
            conn=conn,
            accounting_clock=OperationalClock(),
            transport=httpx.MockTransport(timeout),
        )
        assert restarted.search("example.org official website")["status"] == "not_checked"
    assert len(calls) == 1
    assert conn.execute("SELECT COUNT(*) FROM tavily_calls").fetchone()[0] == 1
    conn.close()


def bounded_client(conn: sqlite3.Connection, clock: OperationalClock, **kwargs) -> TavilyClient:  # type: ignore[no-untyped-def]
    return TavilyClient(
        api_key="synthetic-test-key",
        conn=conn,
        accounting_clock=clock,
        transport=httpx.MockTransport(provider),
        **kwargs,
    )


@pytest.mark.parametrize(
    "usage,expected",
    [
        (0.5, 500),
        (0.2, 200),
        ("0.001", 1),
        (0, 0),
        (None, None),
        (True, None),
        (-1, None),
        ("NaN", None),
        ("Infinity", None),
        ("0.0001", None),
        ("1e40", None),
    ],
)
def test_confirmed_usage_is_exact_or_unknown(usage: object, expected: int | None) -> None:
    assert credit_units(usage, exact=True) == expected


def test_subunit_provider_usage_holds_liability_instead_of_inventing_charge(tmp_path: Path) -> None:
    conn = database(tmp_path / "audit.db")
    c = TavilyClient(
        api_key="synthetic-test-key",
        conn=conn,
        accounting_clock=OperationalClock(),
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"results": [], "usage": {"credits": 0.0001}})
        ),
    )
    result = c.search("example.org official website")
    assert result["status"] == "ok"
    assert result["credits"] is None
    assert result["held_credits"] == 1
    assert accounting_summary(conn)["total_credits"] == 0
    assert accounting_summary(conn)["unknown_attempts"] == 1


def test_daily_monthly_quotas_shared_across_run_ids(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    conn = database(tmp_path / "audit.db")
    clock = OperationalClock("2026-10-30T23:59:59Z")
    monkeypatch.setattr(settings, "tavily_max_calls_per_day", 1)
    monkeypatch.setattr(settings, "tavily_monthly_credit_budget", 2)
    first = bounded_client(conn, clock, run_id="one")
    second = bounded_client(conn, clock, run_id="two")
    assert first.search("example.org official website")["status"] == "ok"
    assert second.search("other.org official website")["status"] == "not_checked"
    clock.value = "2026-10-31T00:00:00Z"
    assert second.search("other.org official website")["status"] == "ok"
    clock.value = "2026-10-31T12:00:00Z"
    monkeypatch.setattr(settings, "tavily_max_calls_per_day", 10)
    assert first.search("third.org official website")["status"] == "not_checked"
    clock.value = "2026-11-01T00:00:00Z"
    assert first.search("third.org official website")["status"] == "ok"
    assert accounting_summary(conn)["total_calls"] == 3


def test_fixed_run_cap_does_not_reset_on_month_boundary(tmp_path: Path) -> None:
    conn = database(tmp_path / "audit.db")
    clock = OperationalClock("2026-10-31T23:59:59Z")
    c = bounded_client(conn, clock, run_credit_limit=1)
    assert c.search("example.org official website")["status"] == "ok"
    clock.value = "2026-11-01T00:00:00Z"
    assert c.search("other.org official website")["status"] == "not_checked"
    assert accounting_summary(conn)["total_calls"] == 1


def test_ambiguous_liability_survives_reopen_and_denies_retry(tmp_path: Path) -> None:
    path = tmp_path / "audit.db"
    conn = database(path)
    clock = OperationalClock()
    c = TavilyClient(
        api_key="synthetic-test-key",
        conn=conn,
        accounting_clock=clock,
        run_credit_limit=1,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"results": []})),
    )
    result = c.search("example.org official website")
    conn.close()
    conn = get_connection(path)
    store = TavilyAccounting(conn, clock=clock, run_credit_limit=1)
    with pytest.raises(BudgetExceeded):
        store.reserve(
            endpoint="search",
            purpose="vet_ident",
            query="example.org official website",
            params={},
            maximum_units=1000,
            situation_id=None,
            request_id=result["request_id"],
        )
    assert (
        bounded_client(conn, clock, run_credit_limit=1).search("other.org official website")[
            "status"
        ]
        == "not_checked"
    )
    assert accounting_summary(conn)["held_credits"] == 1


def test_retry_ceiling_counts_charges_and_unique_ordinals(tmp_path: Path) -> None:
    conn = database(tmp_path / "audit.db")
    sent = []

    def unavailable(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(503, headers={"Retry-After": "0"}, json={"usage": {"credits": 1}})

    c = TavilyClient(
        api_key="synthetic-test-key",
        conn=conn,
        accounting_clock=OperationalClock(),
        max_retries=99,
        transport=httpx.MockTransport(unavailable),
    )
    assert c.search("example.org official website")["status"] == "not_checked"
    rows = conn.execute(
        "SELECT attempt_ordinal,charged_units FROM tavily_calls ORDER BY attempt_ordinal"
    ).fetchall()
    assert [tuple(row) for row in rows] == [(1, 1000), (2, 1000), (3, 1000)]
    assert len(sent) == 3
    assert accounting_summary(conn)["total_credits"] == 3
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO tavily_calls SELECT 'different-id',endpoint,purpose,query_text,params_json,credits,ok,latency_ms,situation_id,created_at,accounting_version,account_label,run_id,request_id,attempt_ordinal,'reserved',reserved_units,charged_units,usage_provenance,dispatched_at,reconciled_at,error_code,request_hash,run_cap_units FROM tavily_calls WHERE attempt_ordinal=1"
        )
    conn.rollback()


def test_unwritable_store_denies_dispatch(tmp_path: Path) -> None:
    path = tmp_path / "audit.db"
    database(path).close()
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    sent = []
    c = TavilyClient(
        api_key="synthetic-test-key",
        conn=conn,
        accounting_clock=OperationalClock(),
        transport=httpx.MockTransport(lambda r: sent.append(r)),
    )
    assert c.search("example.org official website")["status"] == "not_checked"
    assert sent == []


def test_populated_old_schema_upgrade_rerun_preserves_exact_rows(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "old.db")
    conn.execute(
        "CREATE TABLE tavily_calls(id TEXT PRIMARY KEY,endpoint TEXT,purpose TEXT,query_text TEXT,params_json TEXT,credits REAL,ok INTEGER,latency_ms INTEGER,situation_id TEXT,created_at TEXT)"
    )
    conn.execute("CREATE TABLE ledger(seq INTEGER,payload_json TEXT,hash TEXT)")
    conn.execute("INSERT INTO ledger VALUES(1,'{\"protected\":true}','original-hash')")
    conn.execute(
        "INSERT INTO tavily_calls VALUES('old','search','vet_ident','example.org','{}',0.5,1,5,NULL,'2026-01-01T00:00:00Z')"
    )
    conn.commit()
    before = tuple(conn.execute("SELECT * FROM tavily_calls").fetchone())
    ledger = tuple(conn.execute("SELECT * FROM ledger").fetchone())
    migrate_tavily_accounting(conn)
    migrate_tavily_accounting(conn)
    row = tuple(conn.execute("SELECT * FROM tavily_calls").fetchone())
    assert row[: len(before)] == before
    assert tuple(conn.execute("SELECT * FROM ledger").fetchone()) == ledger
    assert accounting_summary(conn)["legacy_rows"] == 1
    assert (
        bounded_client(conn, OperationalClock()).search("other.org official website")["status"]
        == "not_checked"
    )


def test_role_bound_connections_share_authority_but_cannot_migrate(tmp_path: Path) -> None:
    path = tmp_path / "audit.db"
    database(path).close()
    conn = get_role_connection(path, Role.WEBFACTS)
    assert (
        bounded_client(conn, OperationalClock(), run_credit_limit=1).search(
            "example.org official website"
        )["status"]
        == "ok"
    )
    with pytest.raises(ValueError, match="bootstrap"):
        migrate_tavily_accounting(conn)
    conn.close()
    observer = get_connection(path)
    assert accounting_summary(observer)["total_credits"] == 1
