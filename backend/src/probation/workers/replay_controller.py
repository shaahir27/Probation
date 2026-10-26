"""Examiner-owned durable replay state controller.

Authority: docs/CONTRACT.md section 3 (the Examiner owns `command_receipts`), section 9,
docs/wp9/D6_API_CONTRACT.md.

Everything the run knows about itself is durable: the checkpoint body lives in the Examiner's own
command receipt, the claim that authorises progression is re-derived from the receipt row on every
tick rather than remembered in process-local state, and the simulated instant the engine reads is
projected by ``engine.replay_kernel.project_replay_state`` - the same single function the API read
surface calls. Operational time (leases, receipts, liveness) and simulated time (historical
evidence, replay events) never share a variable here.
"""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from probation.core.clock import format_timestamp, parse_timestamp, timestamp_key
from probation.core.lifecycle import ReceiptClaim, StaleClaim
from probation.core.replay_controls import REPLAY_SPEEDS
from probation.db.access import RoleAccess
from probation.db.lifecycle_base import lease_end
from probation.db.lifecycle_receipts import ReceiptStore
from probation.db.replay_commands import ReplayCommandStore
from probation.engine.replay_kernel import (
    ReplayPosition,
    open_decision_count,
    project_replay_state,
)

_REPLAY_LEASE_SECONDS = 30
_DEFAULT_SPEED = 1

#: Derived read-side markers. They are projected from durable state on every read, so storing
#: them back would let a stale guess about liveness outlive the record it was derived from.
_DERIVED_KEYS = frozenset(
    {
        "simulated_date",
        "receipt_state",
        "receipt_id",
        "receipt_fence",
        "claim_owner",
        "lease_until",
        "valid_until",
        "must_resume",
        "available",
        "resumable",
        "reason",
    }
)


class ReplayController:
    def __init__(
        self,
        access: RoleAccess,
        *,
        workspace_id: str,
        run_id: str,
        controller_id: str,
        lease_seconds: int = _REPLAY_LEASE_SECONDS,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("replay lease must be positive")
        self.access = access
        self.workspace_id = workspace_id
        self.run_id = run_id
        self.controller_id = controller_id
        self.lease_seconds = lease_seconds
        self.commands = ReplayCommandStore(access)
        # A cursor cache for this process only, never authority: the claim, the position and the
        # simulated instant are all re-read from the durable receipt on every tick.
        self._session: Any = None

    # ------------------------------------------------------------- durable state --

    def _stored(self) -> dict[str, Any]:
        """The durable checkpoint body for this scope, or nothing if there is no valid one."""
        saved = self.commands.checkpoint(workspace_id=self.workspace_id, run_id=self.run_id)
        if saved is None:
            return {}
        if saved.get("workspace_id") not in (None, self.workspace_id) or saved.get(
            "run_id"
        ) not in (None, self.run_id):
            return {}
        return dict(saved)

    @staticmethod
    def _clean(body: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in body.items() if key not in _DERIVED_KEYS}

    def _empty(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "run_id": self.run_id,
            "running": False,
            "speed": _DEFAULT_SPEED,
            "simulated_at": None,
            "available": True,
            "resumable": False,
            "must_resume": False,
            "last_request_id": None,
            "position": None,
            "reason": "no_replay_command",
        }

    def state(self, *, operational_at: str | None = None) -> dict[str, Any]:
        """The one projection, shared with the API read surface.

        Without `operational_at` it reports the durable instant exactly as stored, which is what
        a restart must see: no simulated time is counted for a lease it does not hold.
        """
        saved = self._stored()
        if not saved:
            anchor = self.commands.anchor(workspace_id=self.workspace_id, run_id=self.run_id)
            if anchor is not None:
                # A claim exists whose checkpoint cannot be read: fail closed rather than invent
                # a position the durable record does not support.
                return {
                    **self._empty(),
                    "available": False,
                    "reason": "unreadable_checkpoint",
                }
            return self._empty()
        reference = operational_at or str(saved.get("operational_at") or "")
        if not reference:
            return {**self._empty(), "available": False, "reason": "unstamped_checkpoint"}
        simulated_anchor = saved.get("simulated_at")
        decisions = open_decision_count(
            self.access.conn, simulated_at=str(simulated_anchor or reference), limit=20
        )
        projection = project_replay_state(
            saved,
            operational_at=reference,
            default_simulated_at=str(simulated_anchor or reference),
            mode="replay",
            open_decisions=decisions,
        )
        return {
            **self._clean(saved),
            "running": projection.running,
            "speed": projection.speed,
            "simulated_at": projection.simulated_at,
            "available": projection.available,
            "resumable": projection.resumable,
            "must_resume": projection.must_resume,
            "last_request_id": projection.last_request_id,
            "position": None if projection.position is None else projection.position.as_json(),
            "reason": projection.reason,
            "workspace_id": self.workspace_id,
            "run_id": self.run_id,
        }

    def simulated_as_of(self, *, operational_at: str, fallback_iso: str) -> str:
        """The simulated instant the engine pipeline must read for this tick.

        While the run holds its lease this is the projected historical instant, never process
        time; otherwise the caller keeps its own injected clock. This is the seam that makes a
        replay control change engine state instead of only the dashboard.
        """
        projected = self.state(operational_at=operational_at)
        if projected.get("running") and isinstance(projected.get("simulated_at"), str):
            return str(projected["simulated_at"])
        return fallback_iso

    # ------------------------------------------------------------------- claims ---

    def _anchor(self, exclude_command_id: str | None = None) -> dict[str, Any] | None:
        return self.commands.anchor(
            workspace_id=self.workspace_id,
            run_id=self.run_id,
            exclude_command_id=exclude_command_id,
        )

    @staticmethod
    def _lease_live(anchor: dict[str, Any], operational_at: str) -> bool:
        lease_until = anchor.get("lease_until")
        return isinstance(lease_until, str) and timestamp_key(operational_at) < timestamp_key(
            lease_until
        )

    def _owned_live_anchor(
        self, operational_at: str, exclude: str | None = None
    ) -> dict[str, Any] | None:
        """The claim this controller holds right now, read from the receipt row."""
        anchor = self._anchor(exclude)
        if anchor is None or not self._lease_live(anchor, operational_at):
            return None
        if anchor.get("claim_owner") != self.controller_id:
            return None
        return anchor

    def _holder_live(self, operational_at: str, exclude: str | None = None) -> bool:
        """Whether any controller currently holds the run's claim."""
        anchor = self._anchor(exclude)
        return anchor is not None and self._lease_live(anchor, operational_at)

    def _claim_for(self, anchor: dict[str, Any], operational_at: str) -> ReceiptClaim | None:
        """The claim for this controller, taking over only a lease that has actually lapsed."""
        command_id = str(anchor["command_id"])
        if anchor.get("claim_owner") == self.controller_id and self._lease_live(
            anchor, operational_at
        ):
            receipt = self.access.conn.execute(
                "SELECT id FROM command_receipts WHERE command_id=? AND consumer='examiner'",
                (command_id,),
            ).fetchone()
            if receipt is None:
                return None
            return ReceiptClaim(
                receipt_id=str(receipt["id"]),
                request_id=command_id,
                request_kind="command",
                consumer="examiner",
                owner=self.controller_id,
                fence=int(anchor["fence"]),
            )
        if self._lease_live(anchor, operational_at):
            # Another controller owns the run until its lease lapses: it is fenced out, not us.
            return None
        return ReceiptStore(self.access).claim_command(
            command_id,
            now=operational_at,
            owner=self.controller_id,
            lease_seconds=self.lease_seconds,
        )

    def _live_claim(self, operational_at: str, exclude: str | None = None) -> ReceiptClaim | None:
        anchor = self._anchor(exclude)
        if anchor is None:
            return None
        return self._claim_for(anchor, operational_at)

    # ----------------------------------------------------------------- commands ---

    def _body(self, *, request_id: str) -> dict[str, Any]:
        """The next checkpoint body, anchored on the durable one, never on memory."""
        saved = self._stored()
        body = self._clean(saved)
        position = ReplayPosition.from_json(body.get("position"))
        if position is not None:
            body["position"] = position.as_json()
        body["speed"] = int(body.get("speed") or _DEFAULT_SPEED)
        body["last_request_id"] = str(body.get("last_request_id") or request_id)
        body["workspace_id"] = self.workspace_id
        body["run_id"] = self.run_id
        return body

    def process_pending(
        self,
        *,
        operational_at: str,
        initial_simulated_at: str,
        limit: int = 32,
    ) -> int:
        """Consume durable replay intents into durable state."""
        commands = self.commands.pending(operational_at, limit)
        receipts = ReceiptStore(self.access)
        processed = 0
        for command in commands:
            if (command.scope.workspace_id, command.scope.run_id) != (
                self.workspace_id,
                self.run_id,
            ):
                continue
            # Read the claim state before this intent creates its own receipt, otherwise the
            # claim being taken here would look like a run already in progress.
            held = self._holder_live(operational_at, exclude=command.request_id)
            claim = receipts.claim_command(
                command.request_id,
                now=operational_at,
                owner=self.controller_id,
                lease_seconds=self.lease_seconds,
            )
            if claim is None:
                continue
            body = self._body(request_id=command.request_id)
            if command.type == "replay_start":
                if held:
                    # Already running under a live claim: the intent is satisfied and the run
                    # keeps the anchor it has instead of swapping it mid-flight.
                    receipts.finish(
                        claim,
                        now=operational_at,
                        status="succeeded",
                        result={**body, "running": True},
                    )
                    processed += 1
                    continue
                body["running"] = True
                body["simulated_at"] = body.get("simulated_at") or initial_simulated_at
                body["resumable"] = True
                body.pop("stopped_reason", None)
                self._persist(claim, body, operational_at)
            elif command.type == "replay_pause":
                if held and not self._owned(operational_at, command.request_id):
                    # Another controller holds the lease: leave this intent unconsumed so it is
                    # retried once that lease lapses, rather than reporting a pause that is not.
                    continue
                body["running"] = False
                body["resumable"] = True
                body["stopped_reason"] = "owner_paused"
                self._release_anchor(body, operational_at, receipts, command.request_id)
                receipts.finish(claim, now=operational_at, status="succeeded", result=body)
            elif command.type == "replay_speed" and command.speed in REPLAY_SPEEDS:
                if held and not self._owned(operational_at, command.request_id):
                    continue
                body["speed"] = command.speed
                receipts.finish(claim, now=operational_at, status="succeeded", result=body)
                anchor_claim = self._live_claim(operational_at, command.request_id)
                if anchor_claim is not None:
                    self._persist(anchor_claim, body, operational_at)
            else:
                receipts.finish(
                    claim,
                    now=operational_at,
                    status="failed",
                    safe_code="invalid_replay_command",
                )
                continue
            processed += 1
        return processed

    def _owned(self, operational_at: str, exclude: str | None = None) -> bool:
        return self._owned_live_anchor(operational_at, exclude) is not None

    def _release_anchor(
        self,
        body: dict[str, Any],
        operational_at: str,
        receipts: ReceiptStore,
        exclude: str | None = None,
    ) -> None:
        claim = self._live_claim(operational_at, exclude)
        if claim is None:
            return
        try:
            receipts.finish(
                claim, now=operational_at, status="succeeded", result={**body, "running": False}
            )
        except StaleClaim:
            pass

    # -------------------------------------------------------------- progression ---

    def advance(self, *, elapsed_seconds: float, operational_at: str) -> dict[str, Any]:
        """Progress the simulated instant and persist it under the run's live claim.

        Only the stored anchor is used for the increment: the read projection may add the time
        since the last checkpoint, and counting both would advance replay twice.
        """
        if (
            elapsed_seconds < 0
            or elapsed_seconds != elapsed_seconds
            or elapsed_seconds in (float("inf"), float("-inf"))
        ):
            raise ValueError("elapsed duration must be finite and non-negative")
        saved = self._stored()
        if not saved.get("running") or not isinstance(saved.get("simulated_at"), str):
            return self.state(operational_at=operational_at)
        claim = self._live_claim(operational_at)
        if claim is None:
            # Fenced out: another controller owns the lease. Nothing is written and nothing this
            # controller reports is counted as advanced.
            return {
                **self.state(operational_at=operational_at),
                "running": False,
                "available": False,
                "reason": "claim_held_elsewhere",
            }
        speed = int(saved.get("speed") or _DEFAULT_SPEED)
        simulated = parse_timestamp(str(saved["simulated_at"])) + timedelta(
            seconds=elapsed_seconds * speed
        )
        body = self._clean(saved)
        body["simulated_at"] = format_timestamp(simulated)
        try:
            self._persist(claim, body, operational_at)
        except StaleClaim:
            return {
                **self.state(operational_at=operational_at),
                "running": False,
                "available": False,
                "reason": "stale_controller_epoch",
            }
        return self.state(operational_at=operational_at)

    def _persist(self, claim: ReceiptClaim, body: dict[str, Any], operational_at: str) -> None:
        checkpoint = self._clean(body)
        checkpoint.update(
            {
                "workspace_id": self.workspace_id,
                "run_id": self.run_id,
                "operational_at": operational_at,
                "valid_until": lease_end(operational_at, self.lease_seconds),
                "controller_epoch": claim.fence,
                "command_consumed": True,
                "last_request_id": claim.request_id,
            }
        )
        ReceiptStore(self.access).checkpoint_command(
            claim,
            now=operational_at,
            lease_seconds=self.lease_seconds,
            result=checkpoint,
        )

    def pause_and_finish(self, operational_at: str) -> None:
        """Stop honestly at a durable, resumable point; never claim to be running.

        The receipt records a command that was consumed and finished normally, while the state
        records that nothing advances any more and that the same simulated instant is resumable.
        A later start therefore continues the run instead of being deduped against a surface
        that had become unreadable.
        """
        claim = self._live_claim(operational_at)
        if claim is None:
            return
        saved = self._stored()
        body = self._clean(saved)
        body.update(
            {
                "running": False,
                "resumable": True,
                "stopped_reason": "controller_stopped",
            }
        )
        try:
            ReceiptStore(self.access).finish(
                claim, now=operational_at, status="succeeded", result=body
            )
        except StaleClaim:
            pass

    shutdown = pause_and_finish

    # --------------------------------------------------------------------- pump ---

    def engine_position(self) -> ReplayPosition | None:
        """The last event whose effects the durable run has already reached."""
        return ReplayPosition.from_json(self._stored().get("position"))

    def pump(
        self,
        session_factory: Callable[[], Any],
        *,
        operational_at: str,
    ) -> int:
        """Drive the shared replay engine to the simulated instant this run owns.

        This is what makes a replay control change engine state: the pipeline runs to the stored
        simulated instant, never to process time. The session is a cursor cache for this process
        only - authority lives in the durable receipt - so after a restart a fresh session
        re-reaches the stream and the engine skips every effect that is already durable.
        Reconciling a crash therefore cannot duplicate a proposal, an outcome or a ledger entry.
        """
        saved = self._stored()
        if not saved.get("running") or not isinstance(saved.get("simulated_at"), str):
            return 0
        claim = self._live_claim(operational_at)
        if claim is None:
            return 0
        if self._session is None:
            try:
                self._session = session_factory()
            except Exception:
                # Fail closed: a run that cannot reach its engine must say so and stop, rather
                # than keep projecting a simulated clock nothing is processing. Reaching the
                # engine needs a replay-capable connection (CONTRACT section 3 allows one process
                # to call the role functions in sequence, which is what a backtest does); a
                # single-role bound connection cannot write another role's tables.
                self._session = False
                body = self._clean(saved)
                body.update({"running": False, "stopped_reason": "replay_engine_unavailable"})
                try:
                    ReceiptStore(self.access).finish(
                        claim, now=operational_at, status="succeeded", result=body
                    )
                except StaleClaim:
                    pass
                return 0
        if self._session is False:
            return 0
        session = self._session
        if session is None:
            return 0
        applied: int = int(session.advance_to(str(saved["simulated_at"])))
        if applied:
            body = self._clean(saved)
            position = session.position
            if position is not None:
                body["position"] = position.as_json()
            self._persist(claim, body, operational_at)
        return applied
