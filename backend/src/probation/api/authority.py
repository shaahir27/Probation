"""Authenticated owner boundary for private API routes."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from probation.core.lifecycle import SourceGrant


@dataclass(frozen=True, slots=True)
class OwnerContext:
    owner_id: str
    grants: tuple[SourceGrant, ...]
    forward_recipients: tuple[str, ...] = ()

    def grant_for(self, source_id: str) -> SourceGrant:
        matches = [grant for grant in self.grants if grant.source_id == source_id]
        if len(matches) != 1:
            raise HTTPException(status_code=403, detail="source_grant_required")
        return matches[0]


def optional_owner(request: Request) -> OwnerContext | None:
    """Resolve the verified local owner through the existing Gmail credential boundary.

    Kept optional for dependency overrides in isolated API tests; production resolution itself
    fails closed when the private connector API is not configured or authentication fails.
    """
    from probation.api.owner_auth import owner_for_request

    return owner_for_request(request)


def require_owner(owner: Annotated[OwnerContext | None, Depends(optional_owner)]) -> OwnerContext:
    """Require the real verified owner for every private route."""
    if owner is None or not owner.owner_id:
        raise HTTPException(status_code=403, detail="authenticated_owner_required")
    return owner
