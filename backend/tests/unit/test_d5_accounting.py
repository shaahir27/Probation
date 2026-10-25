"""D5 physical-attempt budgets, crash liability and private-query regressions."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import httpx
import pytest

from probation.core.clock import Clock, parse_timestamp
from probation.core.enums import ClockMode
from probation.db.connection import apply_schema, get_connection
from probation.db.tavily_migration import migrate_tavily_accounting
from probation.llm.budget import BudgetExceeded
from probation.web.accounting import TavilyAccounting
from probation.web.client import TavilyClient


class OperationalClock(Clock):
    def __init__(self, value: str = "2026-10-25T12:00:00Z") -> None:
        super().__init__(ClockMode.LIVE)
        self.value = value

    def now_iso(self) -> str:
        return self.value

    def now(self, tz: object = None) -> object:
        return parse_timestamp(self.value)


def database(path: Path):  # type: ignore[no-untyped-def]
    conn = get_connection(path)
    apply_schema(conn)
    migrate_tavily_accounting(conn)
    return conn


def client(conn, handler, **kwargs):  # type: ignore[no-untyped-def]
    return TavilyClient(
        api_key="test-not-a-credential",
        conn=conn,
        transport=httpx.MockTransport(handler),
        accounting_clock=OperationalClock(),
        **kwargs,
    )


def test_missing_store_denies_both_endpoints() -> None:
    sent = []
    c = client(None, lambda request: sent.append(request))
    assert c.search("example.org official website")["status"] == "not_checked"
    assert c.extract("https://example.org/")["status"] == "not_checked"
    assert sent == []


def test_reservation_committed_before_bearer_request_and_usage_recorded(tmp_path: Path) -> None:
    conn = database(tmp_path / "audit.db")
    requests = []

    def provider(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        observer = get_connection(tmp_path / "audit.db")
        row = observer.execute("SELECT state FROM tavily_calls").fetchone()
        observer.close()
        assert row[0] == "dispatched"
        body = json.loads(request.content)
        assert body["include_usage"] is True
        assert "api_key" not in body
        assert request.headers["Authorization"] == "Bearer test-not-a-credential"
        return httpx.Response(200, json={"results": [], "usage": {"credits": 0.5}})

    result = client(conn, provider).search("example.org official website")
    assert result["status"] == "ok"
    assert result["credits"] == 0.5
    row = conn.execute("SELECT * FROM tavily_calls").fetchone()
    assert row["charged_units"] == 500
    assert row["state"] == "reconciled"
    assert "test-not-a-credential" not in row["params_json"]
    assert len(requests) == 1


def test_unknown_usage_and_extract_zero_remain_held(tmp_path: Path) -> None:
    conn = database(tmp_path / "audit.db")
    c = client(conn, lambda r: httpx.Response(200, json={"results": []}))
    assert c.search("example.org official website")["credits"] is None
    c = client(conn, lambda r: httpx.Response(200, json={"results": [], "usage": {"credits": 0}}))
    result = c.extract("https://example.org/", extract_depth="advanced")
    assert result["credits"] == 0
    assert result["held_credits"] == 2
    rows = conn.execute("SELECT state,charged_units,reserved_units FROM tavily_calls").fetchall()
    assert tuple(rows[0]) == ("ambiguous", None, 1000)
    assert tuple(rows[1]) == ("ambiguous", 0, 2000)


def test_timeout_is_ambiguous_without_automatic_resend(tmp_path: Path) -> None:
    conn = database(tmp_path / "audit.db")
    sent = []

    def timeout(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        raise httpx.ReadTimeout("private-provider-body", request=request)

    result = client(conn, timeout).search("example.org official website")
    assert result["status"] == "not_checked"
    assert "private-provider-body" not in str(result)
    assert len(sent) == 1
    assert conn.execute("SELECT state FROM tavily_calls").fetchone()[0] == "ambiguous"


def test_retry_records_each_physical_attempt(tmp_path: Path) -> None:
    conn = database(tmp_path / "audit.db")
    sent = []

    def provider(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(
            503 if len(sent) == 1 else 200,
            json={"results": [], "usage": {"credits": 1}},
        )

    result = client(conn, provider).search("example.org official website")
    assert result["status"] == "ok"
    rows = conn.execute(
        "SELECT attempt_ordinal,state FROM tavily_calls ORDER BY attempt_ordinal"
    ).fetchall()
    assert [tuple(row) for row in rows] == [(1, "reconciled"), (2, "reconciled")]


def test_run_ceiling_survives_restart_and_model_reset(tmp_path: Path) -> None:
    path = tmp_path / "audit.db"
    conn = database(path)

    def provider(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [], "usage": {"credits": 1}})

    assert (
        client(conn, provider, run_credit_limit=1).search("example.org official website")["status"]
        == "ok"
    )
    conn.close()
    conn = get_connection(path)
    sent = []
    assert (
        client(conn, lambda r: sent.append(r), run_credit_limit=1).search(
            "other.org official website"
        )["status"]
        == "not_checked"
    )
    assert sent == []


def test_two_clients_race_for_last_credit(tmp_path: Path) -> None:
    path = tmp_path / "audit.db"
    database(path).close()
    barrier = Barrier(2)

    def dispatch(_: int) -> str:
        conn = get_connection(path)
        c = client(
            conn,
            lambda r: httpx.Response(200, json={"results": [], "usage": {"credits": 1}}),
            run_credit_limit=1,
        )
        barrier.wait()
        result = str(c.search("example.org official website")["status"])
        conn.close()
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(dispatch, range(2))) == ["not_checked", "ok"]


def test_private_query_is_not_stored_or_dispatched(tmp_path: Path) -> None:
    conn = database(tmp_path / "audit.db")
    private = "private-person@example.org token=secret123"
    sent = []
    assert client(conn, lambda r: sent.append(r)).search(private)["status"] == "not_checked"
    rows = [dict(row) for row in conn.execute("SELECT * FROM tavily_calls")]
    assert private not in json.dumps(rows)
    assert "secret123" not in json.dumps(rows)
    assert sent == []


def test_migration_preserves_legacy_and_denies_unknown_balance(tmp_path: Path) -> None:
    conn = database(tmp_path / "audit.db")
    conn.execute(
        "INSERT INTO tavily_calls(id,endpoint,purpose,query_text,params_json,credits,ok,created_at) "
        "VALUES('legacy','search','vet_ident','example.org','{}',0,0,'2026-10-25T12:00:00Z')"
    )
    conn.commit()
    migrate_tavily_accounting(conn)
    sent = []
    assert (
        client(conn, lambda r: sent.append(r)).search("example.org official website")["status"]
        == "not_checked"
    )
    assert conn.execute("SELECT id,credits FROM tavily_calls WHERE id='legacy'").fetchone()[1] == 0
    assert sent == []


def test_replay_operational_clock_refused(tmp_path: Path) -> None:
    conn = database(tmp_path / "audit.db")
    with pytest.raises(ValueError, match="operational"):
        TavilyAccounting(conn, clock=Clock.replay())


def test_extract_options_and_unsafe_url(tmp_path: Path) -> None:
    conn = database(tmp_path / "audit.db")
    sent = []

    def provider(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [], "usage": {"credits": 0.2}})

    c = client(conn, provider)
    assert (
        c.extract(
            "https://example.org/",
            extract_depth="advanced",
            query="deadline eligibility",
            chunks_per_source=3,
            format="text",
        )["status"]
        == "ok"
    )
    assert sent[0]["extract_depth"] == "advanced"
    assert sent[0]["query"] == "deadline eligibility"
    assert sent[0]["format"] == "text"
    assert c.extract("http://127.0.0.1/")["status"] == "not_checked"
    assert len(sent) == 1


def test_missing_audit_table_denies_before_dispatch(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "empty.db")
    sent = []
    assert (
        client(conn, lambda r: sent.append(r)).search("example.org official website")["status"]
        == "not_checked"
    )
    assert sent == []


def reserve(store: TavilyAccounting):  # type: ignore[no-untyped-def]
    return store.reserve(
        endpoint="search",
        purpose="vet_ident",
        query="example.org official website",
        params={"query": "example.org official website"},
        maximum_units=1000,
        situation_id=None,
    )


def test_reservations_cannot_be_replaced_deleted_or_moved_backwards(tmp_path: Path) -> None:
    conn = database(tmp_path / "audit.db")
    store = TavilyAccounting(conn, clock=OperationalClock())
    attempt = reserve(store)
    for sql in (
        "DELETE FROM tavily_calls",
        "UPDATE tavily_calls SET query_text='changed'",
        "UPDATE tavily_calls SET state=NULL",
        "INSERT OR REPLACE INTO tavily_calls SELECT * FROM tavily_calls",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql)
        conn.rollback()
    store.dispatch(attempt)
    with pytest.raises(BudgetExceeded):
        store.dispatch(attempt)
    with pytest.raises(BudgetExceeded):
        store.release_unused(attempt)
    with pytest.raises(BudgetExceeded):
        store.reserve(
            endpoint="search",
            purpose="vet_ident",
            query="example.org official website",
            params={},
            maximum_units=1000,
            situation_id=None,
            request_id=attempt.request_id,
        )
    assert conn.execute("SELECT state FROM tavily_calls").fetchone()[0] == "dispatched"


def test_only_proven_undispatched_reservation_can_release(tmp_path: Path) -> None:
    conn = database(tmp_path / "audit.db")
    store = TavilyAccounting(conn, clock=OperationalClock(), run_credit_limit=1)
    attempt = reserve(store)
    store.release_unused(attempt)
    assert reserve(store).ordinal == 1


def test_operational_day_month_and_previous_unknown_liability(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from probation.config import settings

    conn = database(tmp_path / "audit.db")
    clock = OperationalClock("2026-10-31T23:59:59Z")
    store = TavilyAccounting(conn, clock=clock)
    pending = reserve(store)
    monkeypatch.setattr(settings, "tavily_max_calls_per_day", 1)
    with pytest.raises(BudgetExceeded):
        reserve(store)
    clock.value = "2026-11-01T00:00:00Z"
    monkeypatch.setattr(settings, "tavily_monthly_credit_budget", 1)
    with pytest.raises(BudgetExceeded):
        reserve(store)  # Old unknown liability cannot escape into a new billing period.
    store.release_unused(pending)
    assert reserve(store).ordinal == 1


@pytest.mark.parametrize("stage", ["reservation", "dispatch", "finish"])
def test_audit_persistence_failure_never_authorizes_unaccounted_success(
    tmp_path: Path, stage: str
) -> None:
    conn = database(tmp_path / "audit.db")
    clause = {
        "reservation": "BEFORE INSERT",
        "dispatch": "BEFORE UPDATE",
        "finish": "BEFORE UPDATE",
    }[stage]
    when = (
        ""
        if stage == "reservation"
        else "WHEN NEW.state=" + ("'dispatched'" if stage == "dispatch" else "'reconciled'")
    )
    conn.execute(
        f"CREATE TRIGGER test_write_failure {clause} ON tavily_calls {when} BEGIN SELECT RAISE(ABORT,'test_failure'); END"
    )
    conn.commit()
    sent = []

    def provider(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"results": [], "usage": {"credits": 1}})

    result = client(conn, provider).search("example.org official website")
    assert result["status"] == "not_checked"
    assert len(sent) == (1 if stage == "finish" else 0)
    if stage == "finish":
        assert conn.execute("SELECT state FROM tavily_calls").fetchone()[0] == "dispatched"


def test_outer_transaction_denies_http(tmp_path: Path) -> None:
    conn = database(tmp_path / "audit.db")
    conn.execute("BEGIN")
    sent = []
    assert (
        client(conn, lambda r: sent.append(r)).search("example.org official website")["status"]
        == "not_checked"
    )
    assert sent == []
    conn.rollback()


def test_changed_client_limit_cannot_raise_existing_run_allowance(tmp_path: Path) -> None:
    conn = database(tmp_path / "audit.db")

    def provider(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [], "usage": {"credits": 1}})

    assert (
        client(conn, provider, run_credit_limit=1).search("example.org official website")["status"]
        == "ok"
    )
    assert (
        client(conn, provider, run_credit_limit=20).search("other.org official website")["status"]
        == "not_checked"
    )


def test_complete_aggregate_and_safe_search_proof(tmp_path: Path) -> None:
    from probation.web.accounting import accounting_summary

    conn = database(tmp_path / "audit.db")

    def provider(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.org/",
                        "title": "<b>Official</b>",
                        "content": "raw-injection-not-audit",
                    },
                    {"url": "https://example.org/?token=private", "title": "bad"},
                ],
                "usage": {"credits": 0.1},
            },
        )

    c = client(conn, provider)
    for _ in range(51):
        assert c.search("example.org official website", purpose="find_official")["status"] == "ok"
    totals = accounting_summary(conn)
    assert totals["total_calls"] == 51
    assert totals["total_credits"] == 5.1
    audit = json.loads(conn.execute("SELECT params_json FROM tavily_calls LIMIT 1").fetchone()[0])
    assert audit["result_urls"] == ["https://example.org/"]
    assert "private" not in json.dumps(audit)
    assert "raw-injection" not in json.dumps(audit)


def test_schema_migration_failure_is_atomic_and_preserves_ledger(tmp_path: Path) -> None:
    conn = get_connection(tmp_path / "old.db")
    conn.execute(
        "CREATE TABLE tavily_calls(id TEXT,endpoint TEXT,purpose TEXT,query_text TEXT,params_json TEXT,credits REAL,ok INTEGER,latency_ms INTEGER,situation_id TEXT,created_at TEXT)"
    )
    conn.execute("CREATE TABLE ledger(payload TEXT)")
    conn.execute("INSERT INTO ledger VALUES('protected')")
    conn.commit()
    conn.set_authorizer(
        lambda action, name, *args: (
            sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_CREATE_TRIGGER and name == "tavily_attempt_transition"
            else sqlite3.SQLITE_OK
        )
    )
    with pytest.raises(sqlite3.DatabaseError):
        migrate_tavily_accounting(conn)
    conn.set_authorizer(None)
    assert "accounting_version" not in {
        row[1] for row in conn.execute("PRAGMA table_info(tavily_calls)")
    }
    assert conn.execute("SELECT payload FROM ledger").fetchone()[0] == "protected"
