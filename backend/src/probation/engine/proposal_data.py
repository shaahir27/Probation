"""Build immutable target bindings from the situation's bounded source record.

No connector, executable adapter, writer or network capability is imported here.
Complete writer/chain/connector payload validation is extended in WP3/WP6; missing
data is reported explicitly so that persistence cannot enable an incomplete effect.
"""

import json
from typing import Any

from probation.core.actions import InvalidAction, parse_action
from probation.core.history import HistoryView
from probation.core.types import Situation


def proposal_parameters(
    situation: Situation,
    action: str,
    history: HistoryView,
    reader: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    try:
        parsed = parse_action(action)
    except InvalidAction:
        return {}, ["unsupported_action"]
    if parsed.is_noop:
        return {}, []
    row = history.get_raw_item(situation.raw_item_id)
    if row is None:
        return {}, ["source_not_known"]
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError):
        return {}, ["invalid_source_record"]
    if not isinstance(payload, dict):
        return {}, ["invalid_source_record"]
    params: dict[str, Any] = {}
    source_ref = str(row["source_ref"])
    required: tuple[str, ...] = ()
    if situation.pack == "mail":
        params["message_id"] = payload.get("message_id") or source_ref
        required = ("message_id",)
        if parsed.type in {"REPLY", "FORWARD"}:
            # No fabricated draft/recipient can become executable by fixing storage.
            return params, ["draft_unavailable" if parsed.type == "REPLY" else "recipient_required"]
    elif situation.pack == "calendar":
        params["uid"] = payload.get("uid") or source_ref
        required = ("uid",)
        if parsed.type == "BLOCK_TIME":
            return params, ["block_parameters_required"]
    elif situation.pack == "files":
        params = {
            "path": payload.get("path") or payload.get("rel_path"),
            "folder": parsed.parameter,
        }
        required = ("path", "folder")
    elif situation.pack == "reading":
        params = {
            key: (reader or {}).get(key, payload.get(key))
            for key in ("url", "title", "topic", "content_type")
        }
        params["collection"] = (
            parsed.parameter if parsed.type == "FILE_TO_COLLECTION" else "archive"
        )
        required = ("url",)
    elif situation.pack == "radar":
        params = {
            key: (reader or {}).get(key)
            for key in ("title", "organiser", "opp_type", "deadline_date", "fee_mentioned")
        }
        return params, ["validated_tracker_payload_required"]
    else:
        return {}, ["unsupported_action_binding"]
    missing = [
        key for key in required if not isinstance(params.get(key), str) or not params[key].strip()
    ]
    return params, [f"missing_parameter:{key}" for key in missing]
