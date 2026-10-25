"""Durable Tavily reservations; ambiguous liability never disappears on restart."""

import hashlib
import sqlite3
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any

from probation.config import settings
from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.core.hashing import canonical_json, det_id
from probation.db.access import Role, RoleAccess
from probation.llm.budget import BudgetExceeded

CREDIT_UNITS = 1000


def credit_units(value: object, *, exact: bool = False) -> int | None:
    """Unknown and invalid usage stays unknown; fractions reserve upwards exactly."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0:
            return None
        scaled = number * CREDIT_UNITS
        units = int(scaled.to_integral_value(rounding=ROUND_CEILING))
        if exact and scaled != units:
            return None
        return units if units <= 9_223_372_036_854_775_807 else None
    except (ValueError, InvalidOperation):
        return None


@dataclass(frozen=True)
class Attempt:
    id: str
    request_id: str
    ordinal: int
    reserved_units: int


class TavilyAccounting:
    """One persistent accounting connection shared by all D5 Tavily dispatches."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        clock: Clock | None = None,
        run_id: str = "d5-nemotron-tavily",
        run_credit_limit: float = 20,
        account_label: str = "primary",
    ) -> None:
        self.clock = clock or Clock.live()
        if self.clock.mode != ClockMode.LIVE:
            raise ValueError("Tavily quotas require an operational live clock")
        cap = credit_units(run_credit_limit)
        if cap is None or not run_id or not account_label:
            raise ValueError("Invalid Tavily budget identity")
        self.conn = conn
        self.access = RoleAccess(conn, Role.WEBFACTS)
        self.run_id, self.cap, self.account = run_id, min(cap, 20_000), account_label

    def _clean(self) -> None:
        if self.conn.in_transaction:
            raise BudgetExceeded(
                "Tavily requires committed accounting", code="accounting_store_unavailable"
            )

    def reserve(
        self,
        *,
        endpoint: str,
        purpose: str,
        query: str,
        params: dict[str, Any],
        maximum_units: int,
        situation_id: str | None,
        request_id: str | None = None,
    ) -> Attempt:
        self._clean()
        now = self.clock.now_iso()
        request_hash = hashlib.sha256(canonical_json(params).encode()).hexdigest()
        try:
            with self.access.transaction():
                legacy = self.conn.execute(
                    "SELECT 1 FROM tavily_calls WHERE accounting_version=0 LIMIT 1"
                ).fetchone()
                if legacy:
                    raise BudgetExceeded(
                        "Legacy Tavily balance requires reconciliation",
                        code="accounting_store_unavailable",
                    )
                if self.conn.execute(
                    "SELECT 1 FROM tavily_calls WHERE account_label=? AND endpoint=? AND purpose=? "
                    "AND request_hash=? AND state IN('reserved','dispatched','ambiguous') LIMIT 1",
                    (self.account, endpoint, purpose, request_hash),
                ).fetchone():
                    raise BudgetExceeded(
                        "Unresolved semantic Tavily request cannot be resent",
                        code="accounting_store_unavailable",
                    )
                rows = self.conn.execute(
                    "SELECT * FROM tavily_calls WHERE account_label=? AND accounting_version=1",
                    (self.account,),
                ).fetchall()
                liability, monthly, daily = 0, 0, 0
                cap = self.cap
                for row in rows:
                    state = row["state"]
                    if state in {"rejected", "never_dispatched"}:
                        continue
                    charged = int(row["charged_units"] or 0)
                    held = (
                        max(0, int(row["reserved_units"]) - charged)
                        if state in {"reserved", "dispatched", "ambiguous"}
                        else 0
                    )
                    if row["run_id"] == self.run_id:
                        liability += charged + held
                        cap = min(cap, int(row["run_cap_units"]))
                    if str(row["created_at"])[:7] == now[:7]:
                        monthly += charged
                    monthly += held
                    if str(row["created_at"])[:10] == now[:10]:
                        daily += 1
                monthly_cap = credit_units(settings.tavily_monthly_credit_budget)
                if (
                    daily >= settings.tavily_max_calls_per_day
                    or monthly_cap is None
                    or monthly + maximum_units > monthly_cap
                    or liability + maximum_units > cap
                ):
                    raise BudgetExceeded("Tavily allowance exhausted", code="budget_exceeded")
                # Allocation occurs under the same lock as quota checking.
                serial = int(self.conn.execute("SELECT COUNT(*) FROM tavily_calls").fetchone()[0])
                req = request_id or det_id(
                    "tavily-request-v1", self.account, self.run_id, now, str(serial)
                )
                if self.conn.execute(
                    "SELECT 1 FROM tavily_calls WHERE account_label=? AND request_id=? "
                    "AND state IN('reserved','dispatched','ambiguous') LIMIT 1",
                    (self.account, req),
                ).fetchone():
                    raise BudgetExceeded(
                        "Unresolved Tavily request cannot be resent",
                        code="accounting_store_unavailable",
                    )
                ordinal = 1 + int(
                    self.conn.execute(
                        "SELECT COALESCE(MAX(attempt_ordinal),0) FROM tavily_calls WHERE account_label=? AND request_id=?",
                        (self.account, req),
                    ).fetchone()[0]
                )
                if ordinal > 3:
                    raise BudgetExceeded("Tavily attempt limit exhausted", code="budget_exceeded")
                attempt_id = det_id("tavily-attempt-v1", self.account, req, str(ordinal))
                self.access.execute_write(
                    "tavily_calls",
                    """INSERT INTO tavily_calls
                    (id,endpoint,purpose,query_text,params_json,credits,ok,latency_ms,situation_id,
                    created_at,accounting_version,account_label,run_id,request_id,attempt_ordinal,
                    state,reserved_units,usage_provenance,request_hash,run_cap_units)
                    VALUES (?,?,?,?,?,0,0,0,?,?,1,?,?,?,?, 'reserved',?,'reservation',?,?)""",
                    (
                        attempt_id,
                        endpoint,
                        purpose,
                        query,
                        canonical_json(params),
                        situation_id,
                        now,
                        self.account,
                        self.run_id,
                        req,
                        ordinal,
                        maximum_units,
                        request_hash,
                        cap,
                    ),
                )
            return Attempt(attempt_id, req, ordinal, maximum_units)
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise BudgetExceeded(
                "Tavily accounting unavailable", code="accounting_store_unavailable"
            ) from exc

    def dispatch(self, attempt: Attempt) -> None:
        self._clean()
        with self.access.transaction():
            cursor = self.access.execute_write(
                "tavily_calls",
                "UPDATE tavily_calls SET state='dispatched',dispatched_at=? WHERE id=? AND state='reserved'",
                (self.clock.now_iso(), attempt.id),
            )
            if cursor.rowcount != 1:
                raise BudgetExceeded(
                    "Tavily duplicate dispatch denied", code="accounting_store_unavailable"
                )

    def finish(
        self,
        attempt: Attempt,
        *,
        usage: int | None,
        ok: bool,
        latency_ms: int,
        params: dict[str, Any],
        endpoint: str,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        self._clean()
        now = self.clock.now_iso()
        # Extract bills batches of five; a reported zero is known but not final liability.
        unknown = usage is None or (endpoint == "extract" and usage == 0)
        state = "ambiguous" if unknown else "reconciled"
        provenance = (
            "missing"
            if usage is None
            else ("provider_zero_pending_batch" if unknown else "provider")
        )
        with self.access.transaction():
            cursor = self.access.execute_write(
                "tavily_calls",
                """UPDATE tavily_calls SET state=?,charged_units=?,credits=?,ok=?,latency_ms=?,
                usage_provenance=?,reconciled_at=?,error_code=?,params_json=?
                WHERE id=? AND state='dispatched'""",
                (
                    state,
                    usage,
                    (usage or 0) / CREDIT_UNITS,
                    int(ok),
                    latency_ms,
                    provenance,
                    now,
                    error_code,
                    canonical_json(params),
                    attempt.id,
                ),
            )
            if cursor.rowcount != 1:
                raise BudgetExceeded(
                    "Tavily reconciliation refused", code="accounting_store_unavailable"
                )
        return {
            "attempt_id": attempt.id,
            "request_id": attempt.request_id,
            "fetched_at": now,
            "credits": None if usage is None else usage / CREDIT_UNITS,
            "held_credits": max(0, attempt.reserved_units - (usage or 0)) / CREDIT_UNITS
            if unknown
            else 0.0,
            "usage_provenance": provenance,
        }

    def release_unused(self, attempt: Attempt) -> None:
        """Only a still-reserved row proves no socket was authorized for this attempt."""
        self._clean()
        with self.access.transaction():
            cursor = self.access.execute_write(
                "tavily_calls",
                """UPDATE tavily_calls SET state='never_dispatched',charged_units=0,
                usage_provenance='not_dispatched',reconciled_at=?
                WHERE id=? AND state='reserved'""",
                (self.clock.now_iso(), attempt.id),
            )
            if cursor.rowcount != 1:
                raise BudgetExceeded(
                    "Dispatched Tavily liability cannot be released",
                    code="accounting_store_unavailable",
                )

    def reject(self, *, endpoint: str, purpose: str, safe_code: str) -> None:
        """Retain only rejection metadata, never the rejected private query or URL."""
        self._clean()
        now = self.clock.now_iso()
        with self.access.transaction():
            serial = int(self.conn.execute("SELECT COUNT(*) FROM tavily_calls").fetchone()[0])
            req = det_id("tavily-rejection-v1", self.account, self.run_id, now, str(serial))
            self.access.execute_write(
                "tavily_calls",
                """INSERT INTO tavily_calls(id,endpoint,purpose,query_text,params_json,credits,ok,
                created_at,accounting_version,account_label,run_id,request_id,attempt_ordinal,
                state,reserved_units,charged_units,usage_provenance,error_code,run_cap_units)
                VALUES(?,?,?,'','{}',0,0,?,1,?,?,?,1,'rejected',0,0,'not_dispatched',?,?)""",
                (req, endpoint, purpose, now, self.account, self.run_id, req, safe_code, self.cap),
            )


def accounting_summary(conn: sqlite3.Connection) -> dict[str, int | float]:
    """Aggregate the complete recorded population, independently of a UI page limit."""
    rows = conn.execute(
        "SELECT accounting_version,state,reserved_units,charged_units FROM tavily_calls"
    ).fetchall()
    calls = confirmed = held = unknown = legacy = rejected = 0
    for row in rows:
        if row["accounting_version"] != 1:
            legacy += 1
            unknown += 1
            continue
        state = row["state"]
        if state == "rejected":
            rejected += 1
            continue
        if state == "never_dispatched":
            continue
        if state != "reserved":
            calls += 1
        charged = int(row["charged_units"] or 0)
        confirmed += charged
        if state in {"reserved", "dispatched", "ambiguous"}:
            held += max(0, int(row["reserved_units"]) - charged)
            unknown += 1
    return {
        "total_calls": calls + legacy,
        "physical_attempts": calls,
        "total_credits": confirmed / CREDIT_UNITS,
        "held_credits": held / CREDIT_UNITS,
        "unknown_attempts": unknown,
        "legacy_rows": legacy,
        "rejected_queries": rejected,
    }
