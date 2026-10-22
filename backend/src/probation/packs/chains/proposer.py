"""Chain follow-up situation creation and proposal emission.

Authority: docs/PACKS_SPEC.md section 4.2 & 4.3 and docs/ENGINE_SPEC.md section 14.6.
One trigger situation can generate several chain follow-up situations,
each with its own immutable proposal and gated independently.
"""

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from probation.core.actions import InvalidAction, parse_action
from probation.core.clock import format_timestamp
from probation.core.enums import GateDecision
from probation.core.hashing import det_id
from probation.core.types import Proposal, Situation
from probation.db.access import Role, RoleAccess
from probation.db.proposals import persist_proposal
from probation.engine.caps import ACTION_CATALOG, get_action_loss, is_recallable
from probation.engine.gate import compute_audit_draw, decide_gate


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO timestamp to UTC datetime."""
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def create_chain_situations_and_proposals(
    conn: sqlite3.Connection,
    trigger_sit: Situation,
    trigger_class_key: str,
    as_of: str,
    reader_features: dict[str, Any] | None = None,
) -> list[tuple[Situation, Proposal]]:
    """Generate chain follow-up situations and independent proposals for active chains.

    Authority: docs/PACKS_SPEC.md section 4.3:
    When a trigger situation is processed, for each active chain on its class key:
    - BLOCK_TIME: requires parseable deadline.
    - CREATE_TASK: title = trigger subject, due = parsed deadline.
    - REPLY: draft reply proposal.
    """
    access = RoleAccess(conn, Role.BRAIN)
    cur = access.conn.cursor()

    # 1. Look for active chains matching this trigger's class key
    cur.execute(
        """
        SELECT id, follow_action, k, n, lift
        FROM chains
        WHERE trigger_class_key = ?
          AND status = 'active';
        """,
        (trigger_class_key,),
    )
    active_chains = cur.fetchall()
    if not active_chains:
        return []

    rdr = reader_features or {}
    deadline_str = rdr.get("deadline") or rdr.get("due_date")
    has_deadline = bool(rdr.get("has_deadline")) or bool(deadline_str)

    results: list[tuple[Situation, Proposal]] = []

    # Parse trigger subject / title
    subject = str(rdr.get("subject") or "Follow-up task")

    for ch in active_chains:
        follow_act = str(ch["follow_action"])
        try:
            parsed = parse_action(follow_act)
        except InvalidAction:
            continue
        if parsed.type not in {"BLOCK_TIME", "CREATE_TASK", "REPLY"}:
            continue
        chain_class_key = f"chain|{trigger_class_key}|{follow_act}"

        # Parameter derivation per PACKS_SPEC section 4.3
        params: dict[str, Any] = {}
        if follow_act == "BLOCK_TIME":
            if not has_deadline or not deadline_str:
                # If reader gave no parseable deadline, do not propose BLOCK_TIME
                continue
            try:
                dl_dt = _parse_ts(str(deadline_str))
                # Block 1 hour before deadline
                block_start = format_timestamp(dl_dt - timedelta(hours=2))
                block_end = format_timestamp(dl_dt - timedelta(hours=1))
            except (ValueError, TypeError):
                continue

            params = {
                "title": f"Focus: {subject}",
                "start": block_start,
                "end": block_end,
                "duration_minutes": 60,
            }

        elif follow_act == "CREATE_TASK":
            params = {
                "title": subject,
                "due": str(deadline_str) if deadline_str else None,
            }

        elif follow_act == "REPLY":
            params = {
                "draft": True,
                "template": f"Acknowledged receipt of: {subject}",
            }

        # Deterministic situation ID: det_id("chain", trigger_sit.id, follow_act)
        sit_id = det_id("chain", trigger_sit.id, follow_act)
        content_hash = det_id(trigger_sit.content_hash, follow_act)

        with access.transaction():
            # Check if already generated (idempotent)
            cur.execute("SELECT id FROM situations WHERE id = ?;", (sit_id,))
            if cur.fetchone() is not None:
                continue

            # Create Situation
            chain_sit = Situation(
                id=sit_id,
                pack="chains",
                family="chain_followup",
                variant=follow_act,
                raw_item_id=trigger_sit.raw_item_id,
                occurred_at=trigger_sit.occurred_at,
                sender_key=trigger_sit.sender_key,
                content_hash=content_hash,
                redacted_text=trigger_sit.redacted_text,
                hands_off_reason=trigger_sit.hands_off_reason,
                created_at=as_of,
            )

            access.insert_chain_situation(chain_sit)

            # Retrieve licence level for chain class key
            cur.execute(
                "SELECT level FROM licence_cache WHERE class_key = ? AND action = ?;",
                (chain_class_key, follow_act),
            )
            lic_row = cur.fetchone()
            licence_level = int(lic_row["level"]) if lic_row else 0

            spec = ACTION_CATALOG.get(follow_act)
            cap = spec.base_cap if spec else 1
            loss = get_action_loss(follow_act)
            recallable = is_recallable(follow_act)
            audit_draw = compute_audit_draw(chain_sit.id)

            # Decide Gate
            p_est = float(ch["k"]) / float(ch["n"]) if int(ch["n"]) > 0 else 0.0
            gate_res = decide_gate(
                action=follow_act,
                p=p_est,
                novel=False,
                licence_level=licence_level,
                cap=cap,
                hands_off=chain_sit.hands_off_reason,
                reader_required=False,
                reader_ok=True,
                deterministic_ok=True,
                loss=loss,
                attention_cost=1.0,
                recallable=recallable,
                audit_draw=audit_draw,
                budget_ok=True,
            )

            prop_id = f"prop-{chain_sit.id}"
            reasons = ["chain_followup", f"mined_chain_lift_{ch['lift']:.1f}"]
            if gate_res.reason:
                reasons.append(gate_res.reason)
            final_gate = gate_res.decision
            if follow_act == "REPLY":
                final_gate = GateDecision.ASK
                reasons.append("draft_unavailable")

            proposal = Proposal(
                id=prop_id,
                situation_id=chain_sit.id,
                family=chain_sit.family,
                class_key=chain_class_key,
                action=follow_act,
                probs={follow_act: p_est, "LEAVE": 1.0 - p_est},
                p_max=p_est,
                novel=False,
                licence_level=licence_level,
                cap=cap,
                gate=final_gate,
                reasons=reasons,
                params=params,
                explanation={
                    "features_hash": "chain",
                    "trigger_situation_id": trigger_sit.id,
                    "chain_id": ch["id"],
                    "k": ch["k"],
                    "n": ch["n"],
                    "lift": ch["lift"],
                },
                policy_version="v1.0",
                features_hash="chain",
                proposed_at=as_of,
            )

            proposal = persist_proposal(access, proposal)

        results.append((chain_sit, proposal))

    return results
