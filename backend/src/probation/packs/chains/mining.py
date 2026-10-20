"""Action chain mining across historical user interactions.

Authority: docs/PACKS_SPEC.md section 4.1 and docs/ENGINE_SPEC.md section 14.
Discovers cross-tool sequence patterns within (t, t + CHAIN_WINDOW_HOURS].
"""

import json
import math
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from probation.config import settings
from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.core.types import Chain

_WORD_REGEX = re.compile(r"\b[a-zA-Z]{3,}\b")


def _tokenize(text: str) -> set[str]:
    """Tokenize text into lowercase words of length >= 3."""
    return set(_WORD_REGEX.findall(text.lower()))


def compute_text_similarity(text1: str, text2: str) -> float:
    """Compute token cosine similarity between trigger text and follow-up title."""
    tokens1 = _tokenize(text1)
    tokens2 = _tokenize(text2)
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1.intersection(tokens2)
    denom = math.sqrt(float(len(tokens1) * len(tokens2)))
    return float(len(intersection)) / denom if denom > 0 else 0.0


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO timestamp to UTC datetime."""
    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def mine_chains(
    conn: sqlite3.Connection,
    as_of: str | None = None,
    clock: Clock | None = None,
    min_support: int | None = None,
    min_p: float | None = None,
    min_lift: float | None = None,
    link_min_sim: float | None = None,
    window_hours: int | None = None,
) -> list[Chain]:
    """Mine candidate chain associations (trigger_class_key -> follow_action).

    Authority: docs/ENGINE_SPEC.md section 14:
    1. Triggers: situations with a class key (mail, invite, file).
    2. Follow-ups: user events within (t, t + CHAIN_WINDOW_HOURS].
    3. Linking: explicit thread link -> STRONG; text similarity >= 0.45 -> WEAK.
    4. For each (trigger_class, follow_action):
       n = triggers in class, k = triggers with linked follow-up,
       base_rate = share of days containing >=1 user event of that type,
       lift = (k/n) / base_rate.
    5. Keep if n >= 20, k/n >= 0.60, lift >= 1.5.
    6. Persist to chains table.
    """
    cur = conn.cursor()
    if as_of is not None:
        now_iso = as_of
    elif clock is not None:
        now_iso = clock.now_iso()
    else:
        cur.execute("SELECT MAX(occurred_at) FROM situations;")
        max_row = cur.fetchone()
        now_iso = (
            str(max_row[0]) if max_row and max_row[0] else Clock(mode=ClockMode.REPLAY).now_iso()
        )

    min_supp = min_support if min_support is not None else settings.chain_min_support
    m_p = min_p if min_p is not None else settings.chain_min_p
    m_lift = min_lift if min_lift is not None else settings.chain_min_lift
    sim_threshold = link_min_sim if link_min_sim is not None else settings.chain_link_min_sim
    win_h = window_hours if window_hours is not None else settings.chain_window_hours

    # 1. Fetch triggers from proposals/situations with occurred_at <= as_of
    cur.execute(
        """
        SELECT
            s.id AS situation_id,
            s.raw_item_id,
            s.pack,
            s.family,
            s.occurred_at,
            s.redacted_text,
            p.class_key,
            r.payload_json
        FROM situations s
        JOIN proposals p ON s.id = p.situation_id
        LEFT JOIN raw_items r ON s.raw_item_id = r.id
        WHERE s.occurred_at <= ?
          AND s.family != 'chain_followup'
        ORDER BY s.occurred_at ASC;
        """,
        (now_iso,),
    )
    trigger_rows = cur.fetchall()
    if not trigger_rows:
        return []

    # 2. Fetch user-initiated events across timeline up to as_of
    # A: User sent messages
    cur.execute(
        """
        SELECT id, occurred_at, payload_json
        FROM raw_items
        WHERE item_kind = 'mail_sent'
          AND occurred_at <= ?
        ORDER BY occurred_at ASC;
        """,
        (now_iso,),
    )
    sent_mail_rows = cur.fetchall()

    # B: Calendar events (blocking time or user-created meetings)
    cur.execute(
        """
        SELECT id, occurred_at, payload_json
        FROM raw_items
        WHERE item_kind IN ('cal_event', 'invite')
          AND occurred_at <= ?
        ORDER BY occurred_at ASC;
        """,
        (now_iso,),
    )
    cal_rows = cur.fetchall()

    # Extract user follow-up events
    followup_events: list[dict[str, Any]] = []

    for sm in sent_mail_rows:
        payload = json.loads(sm["payload_json"]) if sm["payload_json"] else {}
        followup_events.append(
            {
                "id": str(sm["id"]),
                "action": "REPLY",
                "occurred_at": str(sm["occurred_at"]),
                "thread_id": str(payload.get("thread_id") or ""),
                "in_reply_to": str(payload.get("in_reply_to") or ""),
                "text": f"{payload.get('subject', '')} {payload.get('body', '')}",
            }
        )

    for ce in cal_rows:
        payload = json.loads(ce["payload_json"]) if ce["payload_json"] else {}
        title = str(payload.get("title") or payload.get("summary") or "")
        followup_events.append(
            {
                "id": str(ce["id"]),
                "action": "BLOCK_TIME",
                "occurred_at": str(ce["occurred_at"]),
                "thread_id": "",
                "in_reply_to": "",
                "text": title,
            }
        )

    # 3. Compute base rates per action: share of days containing >=1 event of that type
    cur.execute(
        """
        SELECT DISTINCT SUBSTR(occurred_at, 1, 10)
        FROM raw_items
        WHERE occurred_at <= ?;
        """,
        (now_iso,),
    )
    raw_days = {str(r[0]) for r in cur.fetchall()}
    all_days = raw_days if raw_days else {fe["occurred_at"][:10] for fe in followup_events}

    day_counts: dict[str, set[str]] = {"REPLY": set(), "BLOCK_TIME": set(), "CREATE_TASK": set()}
    for fe in followup_events:
        d_str = fe["occurred_at"][:10]
        day_counts[fe["action"]].add(d_str)

    total_days = max(1, len(all_days))
    base_rates: dict[str, float] = {
        act: max(0.01, float(len(days)) / float(total_days)) for act, days in day_counts.items()
    }

    # 4. Group triggers by class_key
    triggers_by_class: dict[str, list[dict[str, Any]]] = {}
    for tr in trigger_rows:
        ck = str(tr["class_key"])
        payload = json.loads(tr["payload_json"]) if tr["payload_json"] else {}
        triggers_by_class.setdefault(ck, []).append(
            {
                "situation_id": str(tr["situation_id"]),
                "class_key": ck,
                "occurred_at": str(tr["occurred_at"]),
                "thread_id": str(payload.get("thread_id") or ""),
                "message_id": str(payload.get("message_id") or ""),
                "subject": str(payload.get("subject") or ""),
                "text": str(tr["redacted_text"] or payload.get("body") or ""),
            }
        )

    mined_chains: list[Chain] = []

    for ck, trs in triggers_by_class.items():
        n = len(trs)
        if n < min_supp:
            continue

        for follow_act in ("REPLY", "BLOCK_TIME", "CREATE_TASK"):
            k = 0
            for t in trs:
                t_dt = _parse_ts(t["occurred_at"])
                window_end = t_dt + timedelta(hours=win_h)

                # Look for matching follow-up event
                matched = False
                for fe in followup_events:
                    if fe["action"] != follow_act:
                        continue
                    fe_dt = _parse_ts(fe["occurred_at"])
                    if not (t_dt < fe_dt <= window_end):
                        continue

                    # Explicit thread link (STRONG)
                    if follow_act == "REPLY":
                        if t["thread_id"] and fe["thread_id"] == t["thread_id"]:
                            matched = True
                            break
                        if t["message_id"] and fe["in_reply_to"] == t["message_id"]:
                            matched = True
                            break

                    # Cosine/text similarity (WEAK)
                    sim_subj = compute_text_similarity(t["subject"], fe["text"])
                    sim_full = compute_text_similarity(f"{t['subject']} {t['text']}", fe["text"])
                    if max(sim_subj, sim_full) >= sim_threshold:
                        matched = True
                        break

                if matched:
                    k += 1

            p_cond = float(k) / float(n)
            base_rate = base_rates.get(follow_act, 0.1)
            lift = p_cond / base_rate

            if p_cond >= m_p and lift >= m_lift:
                chain_id = f"chain-{uuid.uuid4().hex[:12]}"
                cur.execute(
                    """
                    INSERT INTO chains
                    (id, trigger_class_key, follow_action, k, n, base_rate, lift, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
                    ON CONFLICT(trigger_class_key, follow_action) DO UPDATE SET
                        k = excluded.k,
                        n = excluded.n,
                        base_rate = excluded.base_rate,
                        lift = excluded.lift,
                        status = 'active',
                        created_at = excluded.created_at;
                    """,
                    (chain_id, ck, follow_act, k, n, base_rate, lift, now_iso),
                )
                mined_chains.append(
                    Chain(
                        id=chain_id,
                        trigger_class_key=ck,
                        follow_action=follow_act,
                        k=k,
                        n=n,
                        base_rate=base_rate,
                        lift=lift,
                        status="active",
                        created_at=now_iso,
                    )
                )

    conn.commit()
    return mined_chains
