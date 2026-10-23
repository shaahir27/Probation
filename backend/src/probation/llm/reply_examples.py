"""Conservative owner-reply examples over a caller-bounded HistoryView.

Legacy Sent without actor provenance is deliberately not assumed human-authored.
No similarity backend is created here; WP4 supplies an approved local ranking function.
"""

import json
from collections.abc import Callable, Mapping, Sequence

from probation.core.history import HistoryView
from probation.core.identity import normalize_address, normalize_user_addresses


def owner_reply_examples(
    history: HistoryView,
    *,
    current_raw_id: str,
    owner_addresses: Sequence[str],
    rank: Callable[[str, str], float] | None = None,
    incoming: str = "",
    scores: Mapping[str, float] | None = None,
    display_names_out: list[str] | None = None,
) -> tuple[tuple[str, str], ...]:
    if rank is None and scores is None:
        return ()
    owners = set(normalize_user_addresses(list(owner_addresses)))
    raw = {str(r["id"]): r for r in history.get_raw_items(pack="mail")}
    sent = {}
    for row in raw.values():
        p = json.loads(row["payload_json"])
        if row["item_kind"] != "mail_sent" or p.get("actor") != "user":
            continue
        if normalize_address(str(p.get("from", ""))) not in owners:
            continue
        sent[str(p.get("message_id", ""))] = p
    outcomes = history.get_decision_projection()
    choices = []
    for s in history.get_situations(pack="mail"):
        rid = str(s["raw_item_id"])
        outcome = outcomes.get(str(s["id"]))
        if rid == current_raw_id or rid not in raw or outcome is None:
            continue
        if (
            not outcome.get("eligible")
            or outcome.get("observed_action") != "REPLY"
            or outcome.get("strength") != "STRONG"
        ):
            continue
        details = outcome.get("details", {})
        reply = sent.get(str(details.get("reply_message_id", "")))
        source = json.loads(raw[rid]["payload_json"])
        if not reply or reply.get("in_reply_to") != source.get("message_id"):
            continue
        text, body = str(source.get("body", "")), str(reply.get("body", ""))
        if text and body:
            score = (
                scores.get(str(s["id"]))
                if scores is not None
                else rank(incoming, text)
                if rank is not None
                else None
            )
            if isinstance(score, (int, float)) and float("-inf") < score < float("inf"):
                from probation.llm.context import redaction_names

                names = redaction_names(
                    source.get("from", ""),
                    source.get("to", ""),
                    reply.get("from", ""),
                    reply.get("to", ""),
                )
                choices.append((-score, str(s["id"]), text, body, names))
    choices.sort()
    if display_names_out is not None:
        display_names_out.extend(name for _, _, _, _, names in choices[:3] for name in names)
    return tuple((text, body) for _, _, text, body, _ in choices[:3])
