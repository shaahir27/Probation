"""Executor-owned durable mail dispatch; no model/provider or API dependencies."""

import json
import logging
from dataclasses import asdict
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Literal

from probation.core.clock import format_timestamp, parse_timestamp
from probation.core.enums import ActionStatus
from probation.core.hashing import det_id
from probation.core.history import HistoryView
from probation.core.lifecycle import AttemptClaim, LifecycleError, OutcomeEvent
from probation.core.review_binding import validate_review_binding
from probation.core.types import Action, ExecResult, Features, Situation
from probation.db.lifecycle_actions import ActionStore
from probation.db.lifecycle_attempts import AttemptStore
from probation.db.lifecycle_events import EventStore
from probation.packs.mail import MailPack
from probation.packs.mail.lifecycle_io import MailExecutionIO, MailReceipt
from probation.packs.mail.lifecycle_operations import prepare_effect, prepare_undo
from probation.workers.drift import has_pending_drift
from probation.workers.restrictions import current_restrictions, current_web_cap

if TYPE_CHECKING:
    from probation.workers.executor import Executor

logger = logging.getLogger(__name__)


class MailLifecycle:
    def __init__(self, executor: "Executor") -> None:
        self.worker = executor
        self.access = executor.role_access
        self.actions = ActionStore(self.access)
        self.attempts = AttemptStore(self.access)

    def _now(self, fallback: str) -> str:
        """Use the shared clock after blocking I/O; explicit replay cutoffs stay monotonic."""
        current = self.worker.clock.now_iso()
        return current if parse_timestamp(current) > parse_timestamp(fallback) else fallback

    def authorize(self, action: Action, now: str, *, for_undo: bool = False) -> str | None:
        """Return a safe denial; explicit consent never impersonates licence evidence."""
        binding = self.actions.get_binding(action.id)
        authority = self.actions.get_authority(action.id)
        resolver = self.worker.grant_resolver
        grant = resolver(binding) if resolver else None
        if grant is None:
            return "source_grant_unavailable"
        validate_review_binding(
            self.access.conn,
            action.proposal_id,
            binding,
            grant=grant,
            as_of=now,
            allowed_forward_recipients=self.worker.allowed_forward_recipients,
        )
        row = self.access.conn.execute(
            "SELECT class_key,cap FROM proposals WHERE id=?", (action.proposal_id,)
        ).fetchone()
        if row is None:
            return "proposal_unavailable"
        restrictions = current_restrictions(
            self.worker.conn, binding, now, class_key=str(row["class_key"])
        )
        if restrictions.blocked or restrictions.revision != binding.restriction_revision:
            return "restriction_changed"
        if for_undo:
            return None
        if authority.kind == "explicit_user":
            return None
        self.actions.validate_autonomous(action)
        if action.type == "FORWARD":
            return "forward_requires_explicit_approval"
        if has_pending_drift(self.worker.conn, str(row["class_key"]), action.type, now):
            return "drift_review_pending"
        hist = HistoryView(self.access.conn, now)
        record = hist.get_execution_features(action.proposal_id)
        if record is None or not record["reader_ok"] or not record["reader_json"]:
            return "current_features_unavailable"
        situation = Situation.model_validate(
            {name: record[name] for name in Situation.model_fields if name in record}
        )
        pack = MailPack(user_addresses=[grant.from_addr])
        current = Features(
            situation_id=situation.id,
            deterministic=pack.deterministic_clues(situation, hist),
            reader=json.loads(record["reader_json"]),
            reader_ok=True,
            featurizer_version=record["featurizer_version"],
            features_hash=record["features_hash"],
            created_at=record["features_created_at"],
        )
        cap = min(
            int(row["cap"]),
            pack.level_cap(action.type, situation, current),
            current_web_cap(self.worker.conn, action.proposal_id, now),
        )
        level = self.worker.licence_checker(str(row["class_key"]), action.type, now)
        if level < action.level_required or cap < action.level_required:
            return "licence_lost"
        return None

    def execute(self, action_id: str, now: str) -> ExecResult:
        action = self.actions.get(action_id)
        if action is None:
            return ExecResult(success=False, action_id=action_id, error="action_missing")
        result = self._run(action, "execute", now)
        if not result.success:
            logger.warning(
                "mail_action_not_applied action_id=%s operation=execute safe_code=%s",
                action_id,
                result.error,
            )
        return result

    def undo(self, action_id: str, now: str) -> ExecResult:
        action = self.actions.get(action_id)
        if action is None:
            return ExecResult(success=False, action_id=action_id, error="action_missing")
        request = self.access.conn.execute(
            """SELECT id FROM user_responses
            WHERE action_id=? AND response='undo' AND schema_version=2
            AND responded_at COLLATE UTC_TIMESTAMP<=? ORDER BY responded_at COLLATE UTC_TIMESTAMP,id LIMIT 1""",
            (action_id, now),
        ).fetchone()
        if request is None:
            return ExecResult(success=False, action_id=action_id, error="undo_request_required")
        if action.status in {ActionStatus.PENDING, ActionStatus.HELD}:
            try:
                with self.access.transaction():
                    self._cancel(action, now, "user_cancelled")
                    self._correction(action, "cancel", now, str(request["id"]))
                return ExecResult(success=True, action_id=action_id)
            except LifecycleError:
                return ExecResult(
                    success=False, action_id=action_id, error="cancellation_unconfirmed"
                )
        result = self._run(action, "undo", now)
        if not result.success:
            logger.warning(
                "mail_action_not_applied action_id=%s operation=undo safe_code=%s",
                action_id,
                result.error,
            )
        return result

    def _run(self, action: Action, operation: Literal["execute", "undo"], now: str) -> ExecResult:
        io = self.worker.world
        if not isinstance(io, MailExecutionIO):
            return ExecResult(
                success=False, action_id=action.id, error="mail_capability_unavailable"
            )
        try:
            binding = self.actions.get_binding(action.id)
            authority = self.actions.get_authority(action.id)
            old = self.attempts.get(action.id, operation)
            if old and old.state in {"confirmed", "failed"}:
                return ExecResult(
                    success=old.state == "confirmed", action_id=action.id, error=old.safe_code
                )
            if operation == "execute" and action.status not in {
                ActionStatus.PENDING,
                ActionStatus.HELD,
            }:
                return ExecResult(success=False, action_id=action.id, error="action_terminal")
            if operation == "undo" and (
                not action.recallable or action.status != ActionStatus.DONE
            ):
                return ExecResult(success=False, action_id=action.id, error="action_not_recallable")
            # Already dispatched operations reconcile even after permission/window expiry.
            reconciling = old is not None and old.state in {"dispatched", "unknown"}
            if not reconciling:
                if operation == "execute":
                    if action.status == ActionStatus.HELD and (
                        not action.hold_until
                        or parse_timestamp(now) < parse_timestamp(action.hold_until)
                    ):
                        return ExecResult(success=False, action_id=action.id, error="hold_pending")
                    reason = self.authorize(action, now)
                    if reason:
                        if reason != "drift_review_pending":
                            self._cancel(action, now, reason)
                        return ExecResult(success=False, action_id=action.id, error=reason)
                else:
                    reason = self.authorize(action, now, for_undo=True)
                    if reason:
                        return ExecResult(success=False, action_id=action.id, error=reason)
                    if not authority.undo_deadline or parse_timestamp(now) > parse_timestamp(
                        authority.undo_deadline
                    ):
                        return ExecResult(success=False, action_id=action.id, error="undo_expired")
                    self._restore_undo_anchor(io, action, binding)
                snap = io.snapshot_mail(binding.resource_id)
                if (
                    binding.native_message_id
                    and snap.native_message_id != binding.native_message_id
                ):
                    return ExecResult(
                        success=False, action_id=action.id, error="native_identity_changed"
                    )
                payload_action = action.model_copy(
                    update={"params": {**binding.params, "body": binding.body_text}}
                )
                prepared = (
                    prepare_effect(payload_action, snap, now)
                    if operation == "execute"
                    else prepare_undo(action, snap)
                )
            else:
                prepared = old.before_state
            now = self._now(now)
            claim = self.attempts.prepare(
                action.id, operation, authority.binding_hash, prepared, now, self.worker.worker_id
            )
            if claim is None:
                return ExecResult(success=False, action_id=action.id, error="operation_busy")
            prepared = claim.before_state
            if claim.mode == "reconcile":
                try:
                    receipt = io.reconcile_mail(claim.attempt_id, str(prepared["payload_hash"]))
                except Exception:
                    self.attempts.mark_unknown(claim, self._now(now), "reconciliation_unavailable")
                    return ExecResult(
                        success=False, action_id=action.id, error="needs_reconciliation"
                    )
            else:
                now = self._now(now)
                if operation == "execute":
                    reason = self.authorize(action, now)
                    if reason:
                        with self.access.transaction():
                            self.attempts.cancel_prepared(claim, now, reason)
                            self._cancel(action, now, reason)
                        return ExecResult(success=False, action_id=action.id, error=reason)
                else:
                    reason = self.authorize(action, now, for_undo=True)
                    if not reason and (
                        not authority.undo_deadline
                        or parse_timestamp(now) > parse_timestamp(authority.undo_deadline)
                    ):
                        reason = "undo_expired"
                    if reason:
                        self.attempts.cancel_prepared(claim, now, reason)
                        return ExecResult(success=False, action_id=action.id, error=reason)
                now = self._now(now)
                self.attempts.mark_dispatched(claim, now)
                try:
                    receipt = io.apply_mail(
                        claim.attempt_id,
                        str(prepared["payload_hash"]),
                        prepared["payload"],
                        str(prepared["snapshot"]["revision"]),
                    )
                except Exception:
                    self.attempts.mark_unknown(claim, self._now(now), "provider_result_unknown")
                    return ExecResult(
                        success=False, action_id=action.id, error="needs_reconciliation"
                    )
            return self._complete(action, claim, prepared, receipt, self._now(now))
        except (LifecycleError, ValueError, KeyError, TypeError) as exc:
            safe_code = (
                getattr(exc, "safe_code", None)
                or getattr(exc, "code", None)
                or (str(exc) if str(exc) else None)
                or type(exc).__name__
            )
            logger.warning(
                "mail_state_invalid action_id=%s operation=%s safe_code=%s",
                action.id,
                operation,
                safe_code,
            )
            return ExecResult(
                success=False, action_id=action.id, error="mail_authority_or_state_invalid"
            )

    @staticmethod
    def _restore_undo_anchor(
        io: Any, action: Action, binding: Any
    ) -> None:
        """Reinstall the durable effect anchor stored with a label undo proof.

        Without it, a cursor that moved past the effect would compare absolute label versions
        from different windows and refuse a truthful undo. Legacy proofs without the anchor
        keep the old fail-closed behavior.
        """
        restore = getattr(io, "restore_effect_anchor", None)
        if restore is None or not isinstance(action.undo, dict):
            return
        anchor = action.undo.get("anchor_history_id")
        before = action.undo.get("before_revision")
        baseline = action.undo.get("baseline")
        if (
            not isinstance(anchor, int)
            or not isinstance(before, str)
            or not isinstance(baseline, dict)
        ):
            return
        restore(
            native_message_id=binding.native_message_id,
            anchor_history_id=anchor,
            before_revision=before,
            baseline=baseline,
        )

    def _complete(
        self,
        action: Action,
        claim: AttemptClaim,
        prepared: dict[str, Any],
        receipt: MailReceipt,
        now: str,
    ) -> ExecResult:
        if receipt.outcome == "failed" and (
            receipt.confirmed_no_effect or receipt.after_state.get("confirmed_no_effect") is True
        ):
            with self.access.transaction():
                self.attempts.finish(
                    claim,
                    now,
                    "failed",
                    asdict(receipt),
                    receipt.safe_code,
                    non_effect_proof={"confirmed_no_effect": True},
                )
                if claim.operation == "execute":
                    self.actions.transition(
                        action.id, action.status, ActionStatus.FAILED, now, claim=claim
                    )
                self.access.append_ledger(
                    "action",
                    action.id,
                    {
                        "action_id": action.id,
                        "operation": claim.operation,
                        "result": "confirmed_failure",
                        "safe_code": receipt.safe_code,
                    },
                    now,
                )
            return ExecResult(
                success=False,
                action_id=action.id,
                error=receipt.safe_code or "provider_confirmed_failure",
            )
        if receipt.outcome != "confirmed":
            self.attempts.mark_unknown(claim, now, receipt.safe_code or "provider_result_unknown")
            return ExecResult(success=False, action_id=action.id, error="needs_reconciliation")
        with self.access.transaction():
            self.attempts.finish(claim, now, "confirmed", asdict(receipt))
            if claim.operation == "execute":
                executed = str(
                    receipt.after_state.get("executed_at")
                    or prepared["payload"].get("performed_at")
                    or now
                )
                deadline = format_timestamp(
                    parse_timestamp(executed) + timedelta(days=self.worker.undo_days)
                )
                self.actions.transition(
                    action.id,
                    action.status,
                    ActionStatus.DONE,
                    now,
                    executed_at=executed,
                    undo_data=prepared.get("undo"),
                    undo_deadline=deadline if action.recallable else None,
                    claim=claim,
                )
            else:
                self.actions.transition(
                    action.id, ActionStatus.DONE, ActionStatus.UNDONE, now, claim=claim
                )
                self._correction(action, "undo", now)
            self.access.append_ledger(
                "action",
                action.id,
                {
                    "action_id": action.id,
                    "status": "DONE" if claim.operation == "execute" else "UNDONE",
                    "attempt_id": claim.attempt_id,
                },
                now,
            )
        return ExecResult(success=True, action_id=action.id, undo_data=prepared.get("undo"))

    def _cancel(self, action: Action, now: str, reason: str) -> None:
        with self.access.transaction():
            self.actions.transition(action.id, action.status, ActionStatus.CANCELLED, now)
            self.access.append_ledger(
                "action",
                action.id,
                {
                    "action_id": action.id,
                    "status": "CANCELLED",
                    "reason": reason,
                    "licence_lost_followup_requested": reason == "licence_lost",
                },
                now,
            )

    def _correction(
        self,
        action: Action,
        kind: Literal["undo", "cancel"],
        now: str,
        response_id: str | None = None,
    ) -> None:
        if response_id is None:
            request = self.access.conn.execute(
                """SELECT id FROM user_responses WHERE action_id=?
                AND response='undo' AND schema_version=2 AND responded_at COLLATE UTC_TIMESTAMP<=?
                ORDER BY responded_at COLLATE UTC_TIMESTAMP,id LIMIT 1""",
                (action.id, now),
            ).fetchone()
            response_id = str(request["id"]) if request else None
        row = self.access.conn.execute(
            "SELECT situation_id FROM proposals WHERE id=?", (action.proposal_id,)
        ).fetchone()
        if row is None:
            raise ValueError("correction_proposal_missing")
        EventStore(self.access).append(
            OutcomeEvent(
                event_id=det_id("correction", action.id, kind),
                situation_id=str(row["situation_id"]),
                proposal_id=action.proposal_id,
                kind=kind,
                source="undo",
                source_key=f"{action.id}:{kind}",
                strength="STRONG",
                observed_at=now,
                known_at=now,
                action_id=action.id,
                response_id=response_id,
            )
        )
