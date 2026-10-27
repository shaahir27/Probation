"""Source grants from the registered connector rows. One builder for API and Executor."""

from __future__ import annotations

from probation.core.lifecycle import SourceGrant
from probation.db.gmail_store import ConnectorAccess


def gmail_source_id(connection_id: str) -> str:
    """Canonical engine source identity persisted by the Gmail ingestion bridge."""
    return f"gmail-source:{connection_id}"


def source_grants_for_owner(access: ConnectorAccess, owner_id: str) -> tuple[SourceGrant, ...]:
    """Every registered connection this owner holds; the rows are the only source of grants."""
    rows = access.query(
        "SELECT connection_id, account_id, authorized_at FROM gmail_connections "
        "WHERE owner_id = ? ORDER BY connection_id",
        (owner_id,),
    )
    return tuple(
        SourceGrant(
            source_id=gmail_source_id(str(row["connection_id"])),
            connection_id=str(row["connection_id"]),
            account_id=str(row["account_id"]),
            from_addr=str(row["account_id"]),
            authorized_at=(str(row["authorized_at"]) if row["authorized_at"] is not None else None),
        )
        for row in rows
    )


def source_grant_for(
    access: ConnectorAccess, owner_id: str, connection_id: str, account_id: str
) -> SourceGrant | None:
    """The one grant a bound execution may use, or None. Never inferred from a request."""
    return next(
        (
            grant
            for grant in source_grants_for_owner(access, owner_id)
            if grant.connection_id == connection_id and grant.account_id == account_id
        ),
        None,
    )
