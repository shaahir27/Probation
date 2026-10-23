"""Immutable spend records and bootstrap-only scope provisioning (W3-D03)."""

import os
import secrets
import sqlite3
from dataclasses import dataclass

from probation.core.hashing import det_id
from probation.llm.budget import BudgetExceeded

SCOPE_ID_PREFIX = "budget-scope-v1"


def period_key_for(period_rule: str, now_iso: str) -> str:
    """The operational period a scope's cap applies to, from the operational clock only."""
    if period_rule == "calendar_day":
        return now_iso[:10]
    if period_rule == "calendar_month":
        return now_iso[:7]
    return "total"


@dataclass(frozen=True, slots=True)
class SpendScope:
    """One provider/account/model/period cap. Immutable once provisioned."""

    scope_id: str
    provider: str
    account_label: str
    model_id: str
    period_rule: str
    period_key: str
    cap_units: int
    price_version: str


@dataclass(frozen=True, slots=True)
class AttemptReservation:
    """One physical send's authorization, durable before its bytes leave the process."""

    attempt_id: str
    request_id: str
    scope_id: str
    ordinal: int
    estimate_units: int


@dataclass(frozen=True, slots=True)
class StartupTotals:
    """What a worker adopts at start-up instead of assuming it is the only spender."""

    spent_units: int
    held_units: int
    verified_exposure_rows: int
    unverified_exposure_rows: int


def provision_budget_scope(
    conn: sqlite3.Connection,
    *,
    provider: str,
    account_label: str,
    model_id: str,
    period_rule: str,
    period_key: str,
    cap_units: int,
    price_version: str,
    created_at_op: str,
) -> str:
    """Operator-initiated provisioning of a cap. No worker role may call this.

    A worker that finds no scope row denies its call; only this administration step, run on a
    clean bootstrap connection, may create one. `account_label` is a non-secret label and
    `price_version` identifies the price-table entry the cap was quoted against.
    """
    if conn.in_transaction or getattr(conn, "bound_role", None) is not None:
        raise ValueError("Scope provisioning requires a clean bootstrap connection")
    if period_rule not in {"total", "calendar_day", "calendar_month"}:
        raise BudgetExceeded(f"Unknown period rule {period_rule}", code="amount_invalid")
    if type(cap_units) is not int or not 0 <= cap_units <= 9223372036854775807:
        raise BudgetExceeded("A cap cannot be negative", code="amount_invalid")
    scope_id = det_id(SCOPE_ID_PREFIX, provider, account_label, model_id, period_rule, period_key)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """INSERT OR IGNORE INTO budget_scopes
            (scope_id, provider, account_label, model_id, period_rule, period_key,
             cap_units, price_version, created_at_op) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                scope_id,
                provider,
                account_label,
                model_id,
                period_rule,
                period_key,
                cap_units,
                price_version,
                created_at_op,
            ),
        )
        row = conn.execute(
            "SELECT cap_units, price_version FROM budget_scopes WHERE scope_id = ?", (scope_id,)
        ).fetchone()
        if row is None or int(row[0]) != int(cap_units) or str(row[1]) != price_version:
            raise BudgetExceeded(
                f"Scope {scope_id} is already provisioned with a different cap",
                code="amount_invalid",
            )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return scope_id


def default_lease_owner(role: str) -> str:
    """A per-process lease token. It fences a dead worker; it never releases its money."""
    return f"{role}-{os.getpid()}-{secrets.token_hex(3)}"
