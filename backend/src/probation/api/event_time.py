"""Validate event chronology without inventing a later observation timestamp."""

from fastapi import HTTPException

from probation.core.clock import get_clock, parse_timestamp


def response_time(proposed_at: str, *, created_at: str | None = None) -> str:
    try:
        now = get_clock().now_iso()
        instant = parse_timestamp(now)
        if instant <= parse_timestamp(proposed_at):
            raise ValueError("Response is not strictly after its proposal")
        if created_at is not None and instant < parse_timestamp(created_at):
            raise ValueError("Response precedes action creation")
        return now
    except ValueError as exc:
        raise HTTPException(409, "Clock conflict: advance the context before responding") from exc
