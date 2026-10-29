"""Operator budget increases preserve prior charges and fail closed at the new cap."""

import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probation.api.authority import OwnerContext
from probation.api.routes import demo
from probation.db.access import Role
from probation.db.connection import get_connection, get_role_connection, init_db
from probation.db.spend import SpendStore
from probation.db.spend_types import provision_budget_scope
from probation.llm.budget import BudgetExceeded


def test_increase_keeps_original_cap_and_charges(tmp_path: Path) -> None:
    from probation.db.budget_admin import increase_budget_cap

    path = tmp_path / "engine.db"
    init_db(path)
    conn = get_connection(path)
    scope_id = provision_budget_scope(
        conn,
        provider="nebius_token_factory",
        account_label="primary",
        model_id="test-model",
        period_rule="total",
        period_key="total",
        cap_units=100,
        price_version="test",
        created_at_op="2026-10-29T10:00:00Z",
    )
    store = SpendStore(conn, role="webfacts", lease_owner="test")
    scope = store.scope_for("test-model")
    request = store.open_request(
        scope,
        semantic_digest="first",
        prompt_id="reader.mail",
        prompt_version="v4",
        model_id="test-model",
        cache_key="first",
    )
    reservation = store.reserve(
        request,
        ordinal=1,
        stage="structured",
        estimate_units=100,
        tokens_in_bound=1,
        tokens_out_bound=1,
    )
    store.mark_dispatched(reservation.attempt_id)
    store.reconcile(reservation.attempt_id, charged_units=100, usage_provenance="estimated")
    increase_budget_cap(
        conn, scope_id=scope_id, cap_units=1000, created_at_op="2026-10-29T10:01:00Z"
    )
    increase_budget_cap(
        conn, scope_id=scope_id, cap_units=1000, created_at_op="2026-10-29T10:02:00Z"
    )
    assert conn.execute("SELECT cap_units FROM budget_scopes").fetchone()[0] == 100
    assert conn.execute("SELECT COUNT(*) FROM budget_cap_increases").fetchone()[0] == 1
    assert store.scope_for("test-model").cap_units == 1000
    assert store.startup_totals(store.scope_for("test-model")).spent_units == 100
    request = store.open_request(
        store.scope_for("test-model"),
        semantic_digest="next",
        prompt_id="reader.mail",
        prompt_version="v4",
        model_id="test-model",
        cache_key="next",
    )
    store.reserve(
        request,
        ordinal=1,
        stage="structured",
        estimate_units=900,
        tokens_in_bound=1,
        tokens_out_bound=1,
    )
    with pytest.raises(BudgetExceeded, match="cap"):
        store.reserve(
            request,
            ordinal=2,
            stage="retry",
            estimate_units=1,
            tokens_in_bound=1,
            tokens_out_bound=1,
        )
    with pytest.raises(BudgetExceeded):
        increase_budget_cap(
            conn, scope_id=scope_id, cap_units=999, created_at_op="2026-10-29T10:03:00Z"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE budget_cap_increases SET cap_units=2000")
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM budget_cap_increases")
    conn.rollback()
    conn.close()
    role_conn = get_role_connection(path, Role.WEBFACTS)
    with pytest.raises(ValueError, match="bootstrap"):
        increase_budget_cap(
            role_conn, scope_id=scope_id, cap_units=2000, created_at_op="2026-10-29T10:04:00Z"
        )
    role_conn.close()


def test_missing_demo_scope_has_a_specific_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "engine.db"
    init_db(path)
    monkeypatch.setattr(demo.settings, "db_path", path)
    monkeypatch.setattr(demo.settings, "llm_api_key", "synthetic-test-key")
    app = FastAPI()
    app.include_router(demo.router)
    app.dependency_overrides[demo.demo_owner] = lambda: OwnerContext("test-owner", ())
    response = TestClient(app).post("/api/demo/analyze", json={"text": "Subject: Test\nA notice."})
    assert response.status_code == 503
    assert response.json()["detail"] == "scope_missing"


def test_funded_workspace_cannot_be_reset(tmp_path: Path) -> None:
    from probation.db.demo_reset import ensure_resettable

    path = tmp_path / "engine.db"
    init_db(path)
    ensure_resettable(path)
    conn = get_connection(path)
    provision_budget_scope(
        conn,
        provider="nebius_token_factory",
        account_label="primary",
        model_id="test-model",
        period_rule="total",
        period_key="total",
        cap_units=100,
        price_version="test",
        created_at_op="2026-10-29T10:00:00Z",
    )
    conn.close()
    with pytest.raises(BudgetExceeded, match="reset"):
        ensure_resettable(path)
