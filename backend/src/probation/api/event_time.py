"""Validate user-event ordering using the request's actual context clock."""

from fastapi import HTTPException

from probation.core.clock import get_clock, parse_timestamp


def response_time(proposed_at: str, created_at: str | None = None) -> str:
    """I-7 requires a later response; never manufacture a timestamp to satisfy it."""
    try:
        now = get_clock().now_iso()
        instant = parse_timestamp(now)
        if instant <= parse_timestamp(proposed_at):
            raise ValueError("Response must be later than its proposal")
        if created_at is not None and instant < parse_timestamp(created_at):
            raise ValueError("Response precedes action creation")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Inconsistent response clock") from exc
    return now
