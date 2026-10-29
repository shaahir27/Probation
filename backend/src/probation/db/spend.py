"""Durable spend accounting: the store the hard cap is actually enforced against.

Authority: docs/CONTRACT.md invariant I-15 and section 3 as extended by the W3-D03 change
request recorded in docs/reports/phase-3.md; docs/wp3/W3_D03_SPEND_ACCOUNTING_REVIEW.md
sections 2-7.

An in-process counter cannot see three things that decide whether a dispatch is affordable:
money another worker is holding, money a worker died holding, and the ordinal history of the
physical sends one logical request already bought. This module makes those durable, and it
derives every total from attempt rows so a crash can neither lose nor invent money.

Everything here denies rather than degrades. A missing table, an unwritable row, a scope
nobody provisioned, a caller transaction that would span a network call, or an exposure
record that disagrees with the attempts that paid for it all stop the dispatch; none of them
falls back to "assume in-process".
"""

import sqlite3

from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.core.hashing import det_id
from probation.db.access import Role, RoleAccess
from probation.db.budget_admin import effective_cap
from probation.db.spend_types import (
    AttemptReservation,
    SpendScope,
    StartupTotals,
    default_lease_owner,
    period_key_for,
    provision_budget_scope,
)
from probation.llm.budget import BudgetExceeded

REQUEST_ID_PREFIX = "llm-request-v1"
ATTEMPT_ID_PREFIX = "llm-attempt-v1"

OWNER_ROLES = frozenset({"brain", "examiner", "webfacts"})
STAGES = frozenset({"structured", "retry", "format_fallback", "repair"})
# Money an attempt may still owe: a reservation, a send in flight, and a send whose outcome
# this process never learned. Lease expiry moves a row between these states; it never leaves
# this set, because the provider may have billed any of them.
OPEN_STATES = ("reserved", "dispatched", "ambiguous")
TRANSITIONS: dict[str, frozenset[str]] = {
    "reserved": frozenset({"dispatched", "never_dispatched"}),
    "dispatched": frozenset({"reconciled", "ambiguous"}),
    "ambiguous": frozenset({"reconciled"}),
    "reconciled": frozenset(),
    "never_dispatched": frozenset(),
}
_TABLES = ("budget_scopes", "llm_requests", "llm_attempts", "budget_cap_increases")


class SpendStore:
    """Row-scoped read/write access to the durable accounting tables for one worker role."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        role: str,
        lease_owner: str,
        clock: Clock | None = None,
        provider: str = "nebius_token_factory",
        account_label: str = "primary",
    ) -> None:
        if role not in OWNER_ROLES:
            raise BudgetExceeded(
                f"Role '{role}' holds no spend authority", code="spend_authority_denied"
            )
        self._conn = conn
        self.role = role
        self.lease_owner = lease_owner
        self.provider = provider
        self.account_label = account_label
        # Operational time only. A replay Clock must never age a lease or move a charge
        # between budget periods, so it is refused here rather than defaulted to.
        given = clock or Clock(mode=ClockMode.LIVE)
        if given.mode is not ClockMode.LIVE:
            raise BudgetExceeded(
                "Spend accounting requires the operational clock", code="spend_authority_denied"
            )
        self._clock = given
        self._access = RoleAccess(conn, Role(role))
        self._require_tables()

    def _require_tables(self) -> None:
        try:
            present = {
                str(row[0])
                for row in self._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        except sqlite3.Error as exc:
            raise self._unavailable(exc) from exc
        missing = [name for name in _TABLES if name not in present]
        if missing:
            raise BudgetExceeded(
                f"Spend accounting tables are missing: {missing}",
                code="accounting_store_unavailable",
            )

    @staticmethod
    def _unavailable(exc: Exception) -> BudgetExceeded:
        return BudgetExceeded(
            f"Spend accounting store is unwritable: {type(exc).__name__}",
            code="accounting_store_unavailable",
        )

    def _now(self) -> str:
        return self._clock.now_iso()

    def _clean(self) -> None:
        """Refuse to reserve inside a caller's open transaction.

        A reservation has to be committed before the socket opens, and a write lock may never
        span a network call, so an enclosing transaction is a denial rather than a savepoint.
        """
        if self._conn.in_transaction:
            raise BudgetExceeded(
                "A durable reservation cannot commit inside an open transaction",
                code="accounting_store_unavailable",
            )

    def scope_for(self, model_id: str) -> SpendScope:
        """The provisioned cap that covers this model right now, or a denial."""
        now = self._now()
        rows = self._conn.execute(
            "SELECT scope_id, provider, account_label, model_id, period_rule, period_key, "
            "cap_units, price_version FROM budget_scopes WHERE model_id = ? "
            "AND provider = ? AND account_label = ? ORDER BY period_rule DESC,scope_id",
            (model_id, self.provider, self.account_label),
        ).fetchall()
        for row in rows:
            if str(row[5]) == period_key_for(str(row[4]), now):
                return SpendScope(
                    scope_id=str(row[0]),
                    provider=str(row[1]),
                    account_label=str(row[2]),
                    model_id=str(row[3]),
                    period_rule=str(row[4]),
                    period_key=str(row[5]),
                    cap_units=effective_cap(self._conn, str(row[0]), int(row[6])),
                    price_version=str(row[7]),
                )
        raise BudgetExceeded(
            f"No budget scope is provisioned for model {model_id}", code="scope_missing"
        )

    def open_request(
        self,
        scope: SpendScope,
        *,
        semantic_digest: str,
        prompt_id: str,
        prompt_version: str,
        model_id: str,
        cache_key: str,
        situation_id: str | None = None,
    ) -> str:
        """Claim one logical request identity once. Existing requests are never reopened.

        The identity is deterministic, so two workers asking the same question converge on the
        same row and the second one cannot pay for an answer the first already bought.
        """
        if scope != self.scope_for(model_id):
            raise BudgetExceeded(
                "Request scope does not match its model/account", code="scope_missing"
            )
        request_id = det_id(
            REQUEST_ID_PREFIX,
            scope.scope_id,
            semantic_digest,
            prompt_id,
            prompt_version,
            model_id,
            situation_id or "",
        )
        self._clean()
        try:
            with self._access.transaction():
                inserted = self._access._execute_write(
                    "llm_requests",
                    """INSERT OR IGNORE INTO llm_requests
                    (request_id, scope_id, owner_role, semantic_digest, prompt_id,
                     prompt_version, model_id, cache_key, situation_id, result_state,
                     created_at_op) VALUES (?,?,?,?,?,?,?,?,?,'open',?)""",
                    (
                        request_id,
                        scope.scope_id,
                        self.role,
                        semantic_digest,
                        prompt_id,
                        prompt_version,
                        model_id,
                        cache_key,
                        situation_id,
                        self._now(),
                    ),
                )
                if inserted.rowcount != 1:
                    raise BudgetExceeded(
                        "This request was already claimed", code="duplicate_request"
                    )
                row = self._conn.execute(
                    "SELECT owner_role, result_state FROM llm_requests WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise self._unavailable(exc) from exc
        if row is None:
            raise self._unavailable(sqlite3.Error("request row vanished"))
        if str(row[0]) != self.role:
            raise BudgetExceeded(
                "This request belongs to another role", code="spend_authority_denied"
            )
        if str(row[1]) == "succeeded":
            raise BudgetExceeded(
                "This semantic request was already answered and paid for",
                code="duplicate_request",
            )
        return request_id

    def reserve(
        self,
        request_id: str,
        *,
        ordinal: int,
        stage: str,
        estimate_units: int,
        tokens_in_bound: int,
        tokens_out_bound: int,
        runtime_cap_units: int | None = None,
    ) -> AttemptReservation:
        """Authorize one physical attempt against derived sums, and commit before the socket.

        The cap check is `charged + open + this estimate <= cap`, where both sums are read
        inside the same write transaction that inserts the reservation, so two workers cannot
        both be authorized for the last unit of the cap.
        """
        if stage not in STAGES:
            raise BudgetExceeded(f"Unknown attempt stage {stage}", code="usage_invalid")
        if any(
            type(x) is not int for x in (ordinal, estimate_units, tokens_in_bound, tokens_out_bound)
        ):
            raise BudgetExceeded("Attempt units and bounds must be integers", code="usage_invalid")
        if runtime_cap_units is not None and (
            type(runtime_cap_units) is not int or runtime_cap_units < 0
        ):
            raise BudgetExceeded("Runtime cap must be integer units", code="amount_invalid")
        if ordinal < 1:
            raise BudgetExceeded("Attempt ordinal starts at 1", code="usage_invalid")
        if estimate_units < 0 or tokens_in_bound < 0 or tokens_out_bound <= 0:
            raise BudgetExceeded("Attempt bounds are invalid", code="usage_invalid")
        attempt_id = det_id(ATTEMPT_ID_PREFIX, request_id, str(ordinal))
        self._clean()
        try:
            with self._access.transaction():
                head = self._conn.execute(
                    "SELECT r.scope_id, s.cap_units, r.owner_role, r.result_state FROM llm_requests r "
                    "JOIN budget_scopes s ON s.scope_id = r.scope_id WHERE r.request_id = ?",
                    (request_id,),
                ).fetchone()
                if head is None:
                    raise BudgetExceeded(
                        f"Request {request_id} has no provisioned scope", code="scope_missing"
                    )
                if str(head[2]) != self.role:
                    raise BudgetExceeded(
                        "This request belongs to another role", code="spend_authority_denied"
                    )
                if str(head[3]) != "open":
                    raise BudgetExceeded(
                        "This request is already settled", code="duplicate_request"
                    )
                owner = self._conn.execute(
                    "SELECT lease_owner FROM llm_attempts WHERE request_id = ? LIMIT 1",
                    (request_id,),
                ).fetchone()
                if owner is not None and owner[0] != self.lease_owner:
                    raise BudgetExceeded(
                        "This request has another lease owner", code="spend_authority_denied"
                    )
                scope_id = str(head[0])
                cap_units = effective_cap(self._conn, scope_id, int(head[1]))
                spent = self._sum_units(scope_id, ("reconciled",), "charged_units")
                held = self._sum_units(scope_id, OPEN_STATES, "estimate_units")
                if spent + held + estimate_units > cap_units:
                    raise BudgetExceeded(
                        f"Durable cap of {cap_units} units reached: spent {spent}, held {held}, "
                        f"requested {estimate_units}",
                        code="cap_exceeded",
                    )
                self._check_account_caps(scope_id, estimate_units, runtime_cap_units)
                self._access._execute_write(
                    "llm_attempts",
                    """INSERT INTO llm_attempts
                    (attempt_id, request_id, scope_id, owner_role, ordinal, stage, state,
                     estimate_units, charged_units, tokens_in_bound, tokens_out_bound,
                     usage_provenance, lease_owner, lease_token, reserved_at_op)
                    VALUES (?,?,?,?,?,?,'reserved',?,0,?,?, 'none',?,0,?)""",
                    (
                        attempt_id,
                        request_id,
                        scope_id,
                        self.role,
                        ordinal,
                        stage,
                        estimate_units,
                        tokens_in_bound,
                        tokens_out_bound,
                        self.lease_owner,
                        self._now(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise BudgetExceeded(
                f"Attempt ordinal {ordinal} was already reserved for this request",
                code="duplicate_request",
            ) from exc
        except sqlite3.Error as exc:
            raise self._unavailable(exc) from exc
        return AttemptReservation(
            attempt_id=attempt_id,
            request_id=request_id,
            scope_id=scope_id,
            ordinal=ordinal,
            estimate_units=estimate_units,
        )

    def _check_account_caps(self, scope_id: str, estimate: int, runtime_cap: int | None) -> None:
        """Every current account cap covers all models, never multiplied by model count.

        Called only inside the reservation write transaction. A daily/monthly cap counts
        attempts by operational reservation time, even when their model used a total scope.
        """
        scope = self._conn.execute(
            "SELECT provider,account_label FROM budget_scopes WHERE scope_id=?", (scope_id,)
        ).fetchone()
        now = self._now()
        caps = self._conn.execute(
            "SELECT scope_id,period_rule,period_key,cap_units FROM budget_scopes "
            "WHERE provider=? AND account_label=?",
            tuple(scope),
        ).fetchall()
        if runtime_cap is not None:
            caps = [*caps, (None, "total", "total", runtime_cap)]
        for cap_scope, rule, key, cap in caps:
            if cap_scope is not None:
                cap = effective_cap(self._conn, str(cap_scope), int(cap))
            if key != period_key_for(rule, now):
                continue
            prefix = "" if rule == "total" else key
            row = self._conn.execute(
                "SELECT COALESCE(SUM(CASE WHEN a.state='reconciled' THEN a.charged_units "
                "WHEN a.state IN ('reserved','dispatched','ambiguous') THEN a.estimate_units "
                "ELSE 0 END),0) FROM llm_attempts a JOIN budget_scopes s "
                "ON s.scope_id=a.scope_id WHERE s.provider=? AND s.account_label=? "
                "AND a.reserved_at_op LIKE ?",
                (*scope, prefix + "%"),
            ).fetchone()
            if int(row[0]) + estimate > int(cap):
                raise BudgetExceeded("Shared account cap reached", code="cap_exceeded")

    def _sum_units(self, scope_id: str, states: tuple[str, ...], column: str) -> int:
        marks = ",".join("?" for _ in states)
        row = self._conn.execute(
            f"SELECT COALESCE(SUM({column}), 0) FROM llm_attempts "
            f"WHERE scope_id = ? AND state IN ({marks})",
            (scope_id, *states),
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def _advance(
        self,
        attempt_id: str,
        *,
        to_state: str,
        assignments: str,
        params: tuple[object, ...],
        from_states: tuple[str, ...],
    ) -> None:
        head = self._conn.execute(
            "SELECT state, owner_role, lease_owner FROM llm_attempts WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        if head is None:
            raise BudgetExceeded(f"Attempt {attempt_id} does not exist", code="usage_invalid")
        if str(head[1]) != self.role:
            raise BudgetExceeded(
                "This attempt belongs to another role", code="spend_authority_denied"
            )
        if str(head[2]) != self.lease_owner:
            raise BudgetExceeded(
                "Only the lease owner may advance this attempt", code="spend_authority_denied"
            )
        current = str(head[0])
        if to_state not in TRANSITIONS.get(current, frozenset()):
            raise BudgetExceeded(
                f"Attempt state cannot move {current} -> {to_state}", code="usage_invalid"
            )
        marks = ",".join("?" for _ in from_states)
        self._clean()
        try:
            with self._access.transaction():
                cursor = self._access._execute_write(
                    "llm_attempts",
                    f"UPDATE llm_attempts SET {assignments} WHERE attempt_id = ? "
                    f"AND state IN ({marks})",
                    (*params, attempt_id, *from_states),
                )
                if cursor.rowcount != 1:
                    raise BudgetExceeded(
                        f"Attempt {attempt_id} was not in a state that allows {to_state}",
                        code="usage_invalid",
                    )
        except sqlite3.Error as exc:
            raise self._unavailable(exc) from exc

    def mark_dispatched(self, attempt_id: str) -> None:
        """Record that bytes left this process. From here the estimate is owed until settled."""
        self._advance(
            attempt_id,
            to_state="dispatched",
            assignments="state = 'dispatched', dispatched_at_op = ?, lease_token = lease_token + 1",
            params=(self._now(),),
            from_states=("reserved",),
        )

    def reconcile(
        self,
        attempt_id: str,
        *,
        charged_units: int,
        usage_provenance: str,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        denial_code: str | None = None,
    ) -> None:
        """Settle one attempt at what it actually cost, which is never less than nothing."""
        if type(charged_units) is not int or charged_units < 0:
            raise BudgetExceeded("A charge cannot be negative", code="usage_invalid")
        if usage_provenance not in {"reported", "estimated"}:
            raise BudgetExceeded(
                "A settled attempt states reported or estimated usage", code="usage_invalid"
            )
        if usage_provenance == "reported" and (tokens_in is None or tokens_out is None):
            raise BudgetExceeded(
                "Reported usage requires the provider's own counts", code="usage_invalid"
            )
        if any(
            value is not None and (type(value) is not int or value < 0)
            for value in (tokens_in, tokens_out)
        ):
            raise BudgetExceeded("Usage counts must be nonnegative integers", code="usage_invalid")
        self._advance(
            attempt_id,
            to_state="reconciled",
            assignments=(
                "state = 'reconciled', charged_units = ?, usage_provenance = ?, "
                "tokens_in = ?, tokens_out = ?, denial_code = ?, reconciled_at_op = ?"
            ),
            params=(
                charged_units,
                usage_provenance,
                tokens_in,
                tokens_out,
                denial_code,
                self._now(),
            ),
            from_states=("dispatched", "ambiguous"),
        )

    def mark_ambiguous(self, attempt_id: str, *, denial_code: str | None = None) -> None:
        """A dispatched attempt whose outcome this process never learned keeps its hold."""
        self._advance(
            attempt_id,
            to_state="ambiguous",
            assignments="state = 'ambiguous', denial_code = ?",
            params=(denial_code,),
            from_states=("dispatched",),
        )

    def mark_never_dispatched(self, attempt_id: str) -> None:
        """The only path that returns a hold: proof the attempt never reached the socket."""
        dispatched = self._conn.execute(
            "SELECT dispatched_at_op FROM llm_attempts WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
        if dispatched is not None and dispatched[0] is not None:
            raise BudgetExceeded(
                "A dispatched attempt may not be returned to the cap", code="usage_invalid"
            )
        self._advance(
            attempt_id,
            to_state="never_dispatched",
            assignments="state = 'never_dispatched', reconciled_at_op = ?",
            params=(self._now(),),
            from_states=("reserved",),
        )

    def settle_request(self, request_id: str, *, result_state: str) -> None:
        """Close the logical request. Only 'open' settles, so history is never rewritten."""
        if result_state not in {"succeeded", "failed_closed", "unavailable"}:
            raise BudgetExceeded("Unknown request result state", code="usage_invalid")
        self._clean()
        owner = self._conn.execute(
            "SELECT lease_owner FROM llm_attempts WHERE request_id=? LIMIT 1", (request_id,)
        ).fetchone()
        if owner is not None and owner[0] != self.lease_owner:
            raise BudgetExceeded("Only the request owner may settle", code="spend_authority_denied")
        try:
            with self._access.transaction():
                self._access._execute_write(
                    "llm_requests",
                    "UPDATE llm_requests SET result_state = ?, settled_at_op = ? "
                    "WHERE request_id = ? AND owner_role = ? AND result_state = 'open'",
                    (result_state, self._now(), request_id, self.role),
                )
        except sqlite3.Error as exc:
            raise self._unavailable(exc) from exc

    def startup_totals(self, scope: SpendScope) -> StartupTotals:
        """Adopt what other processes and dead processes already committed this scope to."""
        spent = self._sum_units(scope.scope_id, ("reconciled",), "charged_units")
        held = self._sum_units(scope.scope_id, OPEN_STATES, "estimate_units")
        verified, unverified = self._verify_exposure(scope)
        return StartupTotals(spent, held, verified, unverified)

    def _verify_exposure(self, scope: SpendScope) -> tuple[int, int]:
        """Cross-check settled requests against the exposure rows their attempts paid for.

        Only rows carrying the integer `cost_units` column can be checked exactly: `cost_usd`
        is a REAL, and rounding a float back to units can move it by one. An unverified row is
        reported, not trusted; a verified row that disagrees denies.
        """
        from probation.db.inference import EXPOSURE_ID_PREFIX

        rows = self._conn.execute(
            "SELECT r.cache_key, COALESCE(SUM(a.charged_units), 0) FROM llm_requests r "
            "LEFT JOIN llm_attempts a ON a.request_id = r.request_id AND a.state = 'reconciled' "
            "WHERE r.scope_id = ? AND r.result_state = 'succeeded' GROUP BY r.request_id",
            (scope.scope_id,),
        ).fetchall()
        verified = unverified = 0
        for cache_key, charged in rows:
            exposure = self._conn.execute(
                "SELECT cost_units, cost_usd FROM exposure_log WHERE id = ?",
                (det_id(EXPOSURE_ID_PREFIX, str(cache_key)),),
            ).fetchone()
            if exposure is None or exposure[0] is None:
                unverified += 1
                continue
            if type(exposure[0]) is not int or exposure[0] < 0 or exposure[0] != int(charged):
                raise BudgetExceeded(
                    "Recorded exposure disagrees with the attempts that paid for it",
                    code="cost_metadata_invalid",
                )
            verified += 1
        return verified, unverified


__all__ = [
    "AttemptReservation",
    "SpendScope",
    "SpendStore",
    "StartupTotals",
    "default_lease_owner",
    "period_key_for",
    "provision_budget_scope",
]
