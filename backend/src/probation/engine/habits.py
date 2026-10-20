"""Habit mining and Benjamini-Hochberg FDR correction.

Authority: docs/ENGINE_SPEC.md section 13 and docs/PROMPTS.md section 7.
Mined habits are explanatory patterns only; they never enter policy models
and never grant permissions (CONTRACT.md invariant I-16).
"""

import json
import re
import sqlite3
import uuid
from collections import Counter
from typing import Any

import numpy as np
import scipy.stats

from probation.config import settings
from probation.core.clock import Clock
from probation.core.enums import ClockMode
from probation.core.hashing import canonical_json
from probation.core.types import Habit

_NUMBER_REGEX = re.compile(r"\b\d+(?:\.\d+)?\b")

_ACTION_VERBS = {
    "REPLY": "replied to",
    "ARCHIVE": "archived",
    "TRASH": "trashed",
    "FORWARD": "forwarded",
    "LEAVE": "left",
    "ACCEPT": "accepted",
    "DECLINE": "declined",
    "TENTATIVE": "tentatively accepted",
}


def extract_numbers(text: str) -> list[str]:
    """Extract numbers from text for multiset comparison."""
    return _NUMBER_REGEX.findall(text)


def validate_wording_sentence(template: str, candidate: str) -> bool:
    """Validate that candidate reworded sentence preserves exact numbers and length.

    Authority: docs/PROMPTS.md section 7:
    - Extract all numbers from template and candidate.
    - Two multisets of numbers must be identical.
    - Length must be between 20 and 160 characters.
    """
    if not candidate or len(candidate) < 20 or len(candidate) > 160:
        return False

    t_nums = extract_numbers(template)
    c_nums = extract_numbers(candidate)

    return Counter(t_nums) == Counter(c_nums)


def build_habit_template(
    family: str, clue: str, clue_value: str, action: str, k: int, n: int
) -> str:
    """Build deterministic template statement from counts.

    Authority: docs/ENGINE_SPEC.md section 13 step 5.
    Examples:
    - "You declined 31 of 33 invites with start_hour_bucket=early."
    - "You archived 45 of 48 emails with intent=newsletter."
    """
    verb = _ACTION_VERBS.get(action.upper())
    if not verb:
        if action.startswith("MOVE_TO_FOLDER:"):
            folder = action.split(":", 1)[1]
            verb = f"moved to {folder}"
        else:
            verb = f"chose {action} on"

    if family in ("email_action", "mail"):
        target_noun = "emails"
    elif family in ("invite_rsvp", "calendar"):
        target_noun = "invites"
    elif family in ("file_destination", "files"):
        target_noun = "files"
    else:
        target_noun = "situations"

    return f"You {verb} {k} of {n} {target_noun} with {clue}={clue_value}."


def reword_statement(
    template: str,
    llm_client: Any = None,
    clock: Clock | None = None,
) -> str:
    """Reword template statement via LLM wording.v1 with strict fallback."""
    if llm_client is None:
        return template

    prompt_sys = (
        "Reword the template into one clear English sentence. Keep every number exactly as "
        'written. Add no new facts and no new numbers. Output ONLY JSON: {"sentence": string}.'
    )
    user_msg = f"<template>{template}</template>"

    try:
        resp = llm_client.complete_json(
            prompt_id="wording.v1",
            system_prompt=prompt_sys,
            user_message=user_msg,
            model_id=settings.model_wording,
        )
        candidate = str(resp.get("sentence", "")).strip()
        if validate_wording_sentence(template, candidate):
            return candidate
    except Exception:
        pass

    return template


def _bin_numeric_clues(
    rows: list[dict[str, Any]], numeric_clues: list[str]
) -> dict[str, dict[str, str]]:
    """Bin continuous numerical values into quartiles (q1..q4)."""
    binned_map: dict[str, dict[str, str]] = {r["situation_id"]: {} for r in rows}

    for c in numeric_clues:
        vals = []
        sit_ids = []
        for r in rows:
            v = r.get(c)
            if v is not None and isinstance(v, (int, float)):
                vals.append(float(v))
                sit_ids.append(r["situation_id"])

        if len(vals) < 4:
            continue

        q25, q50, q75 = np.percentile(vals, [25, 50, 75])
        for sid, v in zip(sit_ids, vals, strict=False):
            if v <= q25:
                bucket = "q1"
            elif v <= q50:
                bucket = "q2"
            elif v <= q75:
                bucket = "q3"
            else:
                bucket = "q4"
            binned_map[sid][c] = bucket

    return binned_map


def mine_habits(
    conn: sqlite3.Connection,
    as_of: str | None = None,
    llm_client: Any = None,
    clock: Clock | None = None,
    min_support: int | None = None,
    min_lift: float | None = None,
    q_threshold: float | None = None,
) -> list[Habit]:
    """Mine candidate habit associations and apply Benjamini-Hochberg FDR filtering.

    Authority: docs/ENGINE_SPEC.md section 13:
    1. Query strong outcomes with occurred_at <= as_of.
    2. Extract clue table (clue_name, clue_value, action), binning numerics into quartiles.
    3. Compute k, n, lift = (k/n) / P(action).
    4. Fisher's exact test (one-vs-rest) with Benjamini-Hochberg FDR correction (q < 0.01).
    5. Filter on support, lift, and q-value.
    6. Construct template statement and reword with number validation.
    7. Persist to habits table.
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

    min_supp = min_support if min_support is not None else settings.habit_min_support
    min_l = min_lift if min_lift is not None else settings.habit_min_lift
    q_max = q_threshold if q_threshold is not None else settings.habit_q

    # Query strong outcomes
    cur.execute(
        """
        SELECT
            s.id AS situation_id,
            s.family,
            s.occurred_at,
            o.observed_action,
            f.deterministic_json,
            f.reader_json
        FROM situations s
        JOIN outcomes o ON s.id = o.situation_id
        LEFT JOIN features f ON s.id = f.situation_id
        WHERE o.strength = 'STRONG'
          AND s.occurred_at <= ?
        ORDER BY s.occurred_at ASC;
        """,
        (now_iso,),
    )
    raw_rows = cur.fetchall()
    if not raw_rows:
        return []

    # Group by family
    by_family: dict[str, list[dict[str, Any]]] = {}
    for r in raw_rows:
        fam = str(r["family"])
        det = json.loads(r["deterministic_json"]) if r["deterministic_json"] else {}
        rdr = json.loads(r["reader_json"]) if r["reader_json"] else {}
        merged = {**det, **rdr}
        merged["situation_id"] = str(r["situation_id"])
        merged["observed_action"] = str(r["observed_action"])
        by_family.setdefault(fam, []).append(merged)

    all_mined_habits: list[Habit] = []

    for fam, f_rows in by_family.items():
        total_situations = len(f_rows)
        if total_situations < min_supp:
            continue

        # Identify numeric clues to bin
        numeric_clues: list[str] = []
        sample = f_rows[0]
        for k_clue, val in sample.items():
            if k_clue in ("situation_id", "observed_action"):
                continue
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                numeric_clues.append(k_clue)

        binned_clues = _bin_numeric_clues(f_rows, numeric_clues)

        # Count action totals in family for P(action)
        action_totals = Counter(r["observed_action"] for r in f_rows)

        # Build clue pairs: (clue_name, clue_value) -> list of rows
        clue_pairs: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for r in f_rows:
            sid = r["situation_id"]
            for k_clue, val in r.items():
                if k_clue in ("situation_id", "observed_action"):
                    continue
                if k_clue in numeric_clues:
                    q_val = binned_clues.get(sid, {}).get(k_clue)
                    if q_val:
                        clue_pairs.setdefault((k_clue, q_val), []).append(r)
                else:
                    clue_pairs.setdefault((k_clue, str(val)), []).append(r)

        # Test candidate associations
        candidates: list[dict[str, Any]] = []
        p_values: list[float] = []

        distinct_actions = sorted(action_totals.keys())
        for (clue_name, clue_val), matching_rows in clue_pairs.items():
            n = len(matching_rows)
            if n < min_supp:
                continue

            matching_action_counts = Counter(mr["observed_action"] for mr in matching_rows)

            for act in distinct_actions:
                k = matching_action_counts.get(act, 0)
                if k < 5:
                    continue

                p_action = float(action_totals[act]) / float(total_situations)
                if p_action <= 0.0:
                    continue

                lift = (float(k) / float(n)) / p_action
                if lift < min_l:
                    continue

                # Contingency table for one-vs-rest Fisher's exact test
                n_rest = total_situations - n
                k_rest = action_totals[act] - k
                table = [
                    [k, n - k],
                    [k_rest, n_rest - k_rest],
                ]

                # Run Fisher's exact test
                try:
                    _, p_val = scipy.stats.fisher_exact(table, alternative="greater")
                except Exception:
                    p_val = 1.0

                candidates.append(
                    {
                        "family": fam,
                        "clue": clue_name,
                        "clue_value": clue_val,
                        "action": act,
                        "k": k,
                        "n": n,
                        "lift": lift,
                        "p_value": float(p_val),
                        "example_ids": [mr["situation_id"] for mr in matching_rows[:5]],
                    }
                )
                p_values.append(float(p_val))

        if not candidates:
            continue

        # Benjamini-Hochberg FDR correction across family tests
        q_vals = scipy.stats.false_discovery_control(p_values)

        for cand, q_val in zip(candidates, q_vals, strict=False):
            if float(q_val) < q_max:
                cur.execute(
                    "SELECT id, status FROM habits WHERE family = ? AND clue = ? AND clue_value = ? AND action = ?;",
                    (cand["family"], cand["clue"], cand["clue_value"], cand["action"]),
                )
                existing = cur.fetchone()
                if existing:
                    if str(existing["status"]) == "denied":
                        # User explicitly denied this habit; do not show or re-add
                        continue
                    habit_id = str(existing["id"])
                    template = build_habit_template(
                        family=cand["family"],
                        clue=cand["clue"],
                        clue_value=cand["clue_value"],
                        action=cand["action"],
                        k=cand["k"],
                        n=cand["n"],
                    )
                    statement = reword_statement(template, llm_client=llm_client, clock=clock)
                    cur.execute(
                        """
                        UPDATE habits
                        SET k = ?, n = ?, lift = ?, q_value = ?, statement = ?, examples_json = ?, created_at = ?
                        WHERE id = ?;
                        """,
                        (
                            cand["k"],
                            cand["n"],
                            cand["lift"],
                            float(q_val),
                            statement,
                            canonical_json(cand["example_ids"]),
                            now_iso,
                            habit_id,
                        ),
                    )
                else:
                    habit_id = f"habit-{uuid.uuid4().hex[:12]}"
                    template = build_habit_template(
                        family=cand["family"],
                        clue=cand["clue"],
                        clue_value=cand["clue_value"],
                        action=cand["action"],
                        k=cand["k"],
                        n=cand["n"],
                    )
                    statement = reword_statement(template, llm_client=llm_client, clock=clock)
                    cur.execute(
                        """
                        INSERT INTO habits
                        (id, family, clue, clue_value, action, k, n, lift, q_value, statement, examples_json, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?);
                        """,
                        (
                            habit_id,
                            cand["family"],
                            cand["clue"],
                            cand["clue_value"],
                            cand["action"],
                            cand["k"],
                            cand["n"],
                            cand["lift"],
                            float(q_val),
                            statement,
                            canonical_json(cand["example_ids"]),
                            now_iso,
                        ),
                    )

                all_mined_habits.append(
                    Habit(
                        id=habit_id,
                        family=cand["family"],
                        clue=cand["clue"],
                        clue_value=cand["clue_value"],
                        action=cand["action"],
                        k=cand["k"],
                        n=cand["n"],
                        lift=cand["lift"],
                        q_value=float(q_val),
                        statement=statement,
                        examples=cand["example_ids"],
                        status="active",
                        created_at=now_iso,
                    )
                )

    conn.commit()
    return all_mined_habits
