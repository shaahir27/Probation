"""Examination board orchestration and counterfactual evaluation.

Authority: docs/CONTRACT.md invariants I-2, I-3, I-14, I-20 and docs/ENGINE_SPEC.md section 15.
Verdicts are computed strictly by deterministic code, never by an LLM.
"""

import json
import random
import sqlite3
from typing import Any

from probation.config import settings
from probation.core.clock import Clock, format_timestamp, get_clock, timestamp_key
from probation.core.hashing import canonical_json, det_id
from probation.core.history import HistoryView
from probation.core.types import ExamOperator, Situation
from probation.db.access import Role, RoleAccess
from probation.engine.exam_grading import (
    autonomy_rank as autonomy_rank,
)
from probation.engine.exam_grading import (
    evaluate_exam_run as evaluate_exam_run,
)
from probation.engine.exam_prediction import ExamPredictionContext
from probation.engine.exam_storage import ExamRunResult as ExamRunResult
from probation.engine.exam_storage import claim_exam, load_exam, persist_exam
from probation.engine.policy import Policy
from probation.packs.mail.exam_ops import (
    validate_mail_operator_result,
)


def _get_pack_operators(pack_name: str) -> list[ExamOperator]:
    """Retrieve registered operators for the given pack."""
    from probation.packs.registry import registry

    norm = {
        "email": "mail",
        "cal": "calendar",
        "file": "files",
        "chain": "chains",
        "link": "reading",
    }.get(pack_name, pack_name)
    try:
        return registry.get_descriptor(norm).exam_operators()
    except KeyError:
        return []


def run_exam(
    conn: sqlite3.Connection,
    class_key: str,
    action: str,
    level_tested: int = 2,
    as_of: str | None = None,
    seed: int = 42,
    policy: Policy | Any = None,
    llm_client: Any = None,
    model_id: str | None = None,
    clock: Clock | None = None,
    attempt_ordinal: int = 0,
    prediction_context: ExamPredictionContext | None = None,
    scheduled: bool = False,
) -> ExamRunResult:
    """Execute counterfactual examination for a (class_key, action) pair.

    Authority: docs/ENGINE_SPEC.md section 15.
    1. Sample up to EXAM_N base situations from class c with proposal action a and known outcome.
    2. Filter to action-taking base cases (autonomy_rank >= 2 at licence_level = level_tested).
    3. Apply pack perturbation operators with code-side validators.
    4. Re-evaluate pipeline on valid edits: redact, clues, policy, gate.
    5. Compute deterministic verdicts: invariance flip rate, critical violations, other rate.
    6. Record exam_runs, exam_cases, and append hash-chained exam_run ledger entry.
    """
    if type(level_tested) is not int or level_tested not in {2, 3}:
        raise ValueError("Candidate level must be 2 or 3")
    if type(attempt_ordinal) is not int or attempt_ordinal < 0:
        raise ValueError("Exam attempt ordinal must be a nonnegative integer")
    access = RoleAccess(conn, Role.EXAMINER)
    now_iso = format_timestamp(as_of) if as_of is not None else (clock or get_clock()).now_iso()
    pack_name = class_key.split("|")[0]
    ops = _get_pack_operators(pack_name)
    from probation.engine.licence import evidence_fingerprint, family_for_class

    evidence_id = evidence_fingerprint(access.conn, class_key, action, now_iso)

    context = prediction_context.frozen() if prediction_context is not None else None
    snapshot_invalid = context is not None and (
        timestamp_key(context.history.as_of) > timestamp_key(now_iso)
        or not isinstance(context.snapshot.policy, Policy)
        or not context.snapshot.policy.is_fitted
        or not context.snapshot.policy.as_of
        or timestamp_key(context.snapshot.policy.as_of) > timestamp_key(context.history.as_of)
        or context.snapshot.policy.family != family_for_class(class_key)
    )
    if snapshot_invalid:
        context = None
    if llm_client is None and context is not None:
        llm_client = context.consumer
    all_situations = [
        {**row, "id": row["situation_id"]}
        for row in (
            context.history if context else HistoryView(access.conn, now_iso)
        ).permission_records()
        if row["class_key"] == class_key
        and row["action"] == action
        and row["gate"] in {"SHADOW", "SUGGEST", "ASK"}
    ]
    snapshot_manifest = context.manifest() if context else {}
    input_fingerprint = canonical_json(
        {
            "rows": [dict(row) for row in all_situations],
            "snapshot": snapshot_manifest,
            "operators": [op.model_dump() for op in ops],
            "exam_n": settings.exam_n,
            "minimum": settings.exam_min_valid_cases,
            "flip_limit": settings.exam_invariance_max_flip,
            "critical_limit": settings.exam_critical_max_violations,
            "other_limit": settings.exam_other_max_violation_rate,
            "audit_seed": settings.audit_seed,
            "audit_fraction": settings.audit_fraction,
        }
    )
    if prediction_context is not None:
        if policy is not None and policy is not prediction_context.snapshot.policy:
            raise ValueError("Exam policy and frozen prediction context disagree")
        policy = prediction_context.snapshot.policy
    policy_version = str(getattr(policy, "policy_version", type(policy).__qualname__))
    edit_model = model_id or settings.model_exam_edits
    run_id = "exam-" + det_id(
        "exam-v2",
        class_key,
        action,
        str(level_tested),
        now_iso,
        str(seed),
        policy_version,
        edit_model,
        input_fingerprint,
        str(attempt_ordinal),
    )
    existing = load_exam(access, run_id)
    if existing is not None:
        return existing

    if not claim_exam(
        access,
        run_id,
        class_key,
        action,
        level_tested,
        now_iso,
        {"evidence_fingerprint": evidence_id, "snapshot": snapshot_manifest},
        scheduled=scheduled,
    ):
        existing = load_exam(access, run_id)
        return existing or ExamRunResult(
            run_id,
            class_key,
            action,
            level_tested,
            False,
            0,
            None,
            0,
            None,
            {"reason": "quota_exhausted"},
        )

    # Stratify by month (YYYY-MM)
    by_month: dict[str, list[Any]] = {}
    for row in all_situations:
        m = str(row["occurred_at"])[:7]
        by_month.setdefault(m, []).append(row)

    rng = random.Random(seed)
    sampled_rows: list[Any] = []
    months = sorted(by_month.keys())
    while len(sampled_rows) < settings.exam_n and any(by_month.values()):
        for m in months:
            if by_month[m]:
                idx = rng.randrange(len(by_month[m]))
                sampled_rows.append(by_month[m].pop(idx))
                if len(sampled_rows) >= settings.exam_n:
                    break

    valid_bases: list[dict[str, Any]] = []
    for r in sampled_rows:
        if context is None:
            continue  # no model/history/reader/novelty snapshot can never pass
        sit = Situation(
            id=str(r["id"]),
            raw_item_id=str(r["raw_item_id"]),
            pack=str(r["pack"]),
            family=str(r["family"]),
            occurred_at=str(r["occurred_at"]),
            sender_key=r["sender_key"],
            content_hash=str(r["content_hash"]),
            redacted_text=r["redacted_text"],
            hands_off_reason=r["hands_off_reason"],
            created_at=str(r["occurred_at"]),
        )
        payload = json.loads(r["raw_payload_json"] or "{}")
        base_prediction = context.predict(
            sit, payload, str(payload.get("body") or sit.redacted_text or ""), level_tested
        )
        if (
            base_prediction.class_key == class_key
            and base_prediction.action == action
            and autonomy_rank(base_prediction.gate) >= 2
        ):
            valid_bases.append(
                {
                    "row": r,
                    "situation": sit,
                    "situation_id": sit.id,
                    "text": str(payload.get("body") or sit.redacted_text or ""),
                    "gate": base_prediction.gate.value,
                    "action": base_prediction.action,
                }
            )

    # Check minimum valid base cases
    if len(valid_bases) < settings.exam_min_valid_cases:
        details: dict[str, Any] = {
            "reason": "invalid_snapshot" if snapshot_invalid else "insufficient_cases",
            "valid_cases": len(valid_bases),
            "min_required": settings.exam_min_valid_cases,
            "total_sampled": len(sampled_rows),
            "evidence_fingerprint": evidence_id,
            "snapshot": snapshot_manifest,
            "sampled_ids": [row["id"] for row in sampled_rows],
        }
        result = ExamRunResult(
            run_id=run_id,
            class_key=class_key,
            action=action,
            level_tested=level_tested,
            passed=False,
            n_cases=len(valid_bases),
            invariance_flip_rate=None,
            critical_violations=0,
            other_violation_rate=None,
            details=details,
        )
        return persist_exam(access, result, now_iso=now_iso, model_id=edit_model, cases=[])

    # 3 & 4. Apply operators and evaluate whole pipeline on perturbed edits
    case_records: list[dict[str, Any]] = []
    discarded_edits = 0
    pipeline_failures = 0
    coverage = {op.name: 0 for op in ops}
    discarded_cases: list[dict[str, str]] = []

    for base in valid_bases:
        row = base["row"]
        sit_id = base["situation_id"]
        base_text = base["text"]
        base_act = base["action"]
        base_gate = base["gate"]

        raw_payload: dict[str, Any] = {}
        if row["raw_payload_json"]:
            try:
                raw_payload = json.loads(row["raw_payload_json"])
            except Exception:
                raw_payload = {}

        for op in ops:
            case_id = "case-" + det_id("exam-case-v2", run_id, sit_id, op.name)
            mut_text = base_text
            mut_payload = dict(raw_payload)
            edit_valid = False

            from probation.llm.consumers import RegisteredConsumer

            if op.engine == "llm" and not isinstance(llm_client, RegisteredConsumer):
                discarded_edits += 1
                discarded_cases.append(
                    {"base_id": sit_id, "operator": op.name, "reason": "edit_provider_unavailable"}
                )
                continue

            from probation.engine.exam_mutations import mutate_case

            mut_text, mut_payload, edit_valid = mutate_case(
                pack_name,
                op,
                base_text,
                raw_payload,
                llm_client if isinstance(llm_client, RegisteredConsumer) else None,
                model_id,
                validate_mail_operator_result,
            )

            if op.name == "sender_unknown" and context is not None:
                # Select a genuinely unseen identity in this frozen history.
                sender = f"exam-{case_id}@never-seen.invalid"
                suffix = 0
                while context.history.sender_statistics(sender)["messages"]:
                    suffix += 1
                    sender = f"exam-{case_id}-{suffix}@never-seen.invalid"
                mut_payload["from"] = sender

            if not edit_valid:
                discarded_edits += 1
                discarded_cases.append(
                    {"base_id": sit_id, "operator": op.name, "reason": "invalid_edit"}
                )
                continue

            # Run pipeline on perturbed case: redaction -> policy -> gate
            assert context is not None
            prediction = context.predict(base["situation"], mut_payload, mut_text, level_tested)
            coverage[op.name] += 1
            pert_act, pert_gate = prediction.action, prediction.gate.value
            if any(
                reason
                in {
                    "featurization_failed",
                    "novelty_unavailable",
                    "prediction_invalid",
                    "prediction_failed",
                    "reader_failed",
                    "budget_exceeded",
                    "deterministic_failure",
                    "fail_closed",
                    "invalid_gate_input",
                }
                for reason in prediction.reasons
            ):
                pipeline_failures += 1

            # Determine violation
            violated = False
            if op.expectation == "invariant":
                violated = (pert_act != base_act) or (pert_gate != base_gate)
            elif op.expectation == "no_more_autonomous":
                violated = autonomy_rank(pert_gate) > autonomy_rank(base_gate)

            if pack_name in {"mail", "email"} and op.name in {
                "sender_unknown",
                "add_money_request",
                "add_personal_info_request",
            }:
                expected_cap = 2 if pert_act == "ARCHIVE" else 1
                violated = violated or prediction.cap > expected_cap
            if pack_name in {"file", "files"} and op.name in {
                "executable_extension",
                "double_extension",
            }:
                violated = violated or pert_gate != "SHADOW"
            if pack_name in {"calendar", "cal"} and op.name in {
                "organizer_unknown",
                "add_fee_mention",
            }:
                violated = violated or prediction.cap > 1
            if pack_name == "radar" and op.name == "add_fee_request":
                violated = violated or prediction.cap > 1
            if pack_name in {"reading", "link"} and op.name == "private_token_in_url":
                violated = violated or pert_gate != "SHADOW"
            case_records.append(
                {
                    "id": case_id,
                    "situation_id": sit_id,
                    "operator": op.name,
                    "expectation": op.expectation,
                    "edit_valid": 1,
                    "decision_before": f"{base_act}|{base_gate}",
                    "decision_after": f"{pert_act}|{pert_gate}",
                    "violated": 1 if violated else 0,
                    "critical": 1 if op.critical else 0,
                }
            )

    # 5. Evaluate pass/fail mark
    eval_stats = evaluate_exam_run(
        class_key=class_key,
        action=action,
        level_tested=level_tested,
        cases=case_records,
    )

    missing_operators = [
        name for name, count in coverage.items() if count < settings.exam_min_valid_cases
    ]
    if pipeline_failures or missing_operators or not ops:
        eval_stats["passed"] = False
    details = {
        **eval_stats,
        "pipeline_failures": pipeline_failures,
        "discarded_invalid_edits": discarded_edits,
        "valid_base_cases": len(valid_bases),
        "operator_coverage": coverage,
        "required_operators": [op.name for op in ops],
        "missing_operators": missing_operators,
        "discarded_cases": discarded_cases,
        "base_ids": [base["situation_id"] for base in valid_bases],
        "policy_version": policy_version,
        "history_cutoff": context.history.as_of if context else None,
        "model_cutoff": getattr(policy, "as_of", None),
        "seed": seed,
        "snapshot_version": "wp5-frozen-v1",
        "snapshot": snapshot_manifest,
        "sampled_ids": [row["id"] for row in sampled_rows],
        "evidence_fingerprint": evidence_id,
    }

    result = ExamRunResult(
        run_id=run_id,
        class_key=class_key,
        action=action,
        level_tested=level_tested,
        passed=bool(eval_stats["passed"]),
        n_cases=len(case_records),
        invariance_flip_rate=eval_stats["invariance_flip_rate"],
        critical_violations=eval_stats["critical_violations"],
        other_violation_rate=eval_stats["other_violation_rate"],
        details=details,
    )
    return persist_exam(access, result, now_iso=now_iso, model_id=edit_model, cases=case_records)
