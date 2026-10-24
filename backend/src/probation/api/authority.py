"""Injected authenticated owner boundary; production auth remains a D4 obligation."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException

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


def optional_owner() -> OwnerContext | None:
    return None


def require_owner(owner: Annotated[OwnerContext | None, Depends(optional_owner)]) -> OwnerContext:
    """A deployment must override this with a real authenticated owner provider."""
    if owner is None or not owner.owner_id:
        raise HTTPException(status_code=403, detail="authenticated_owner_required")
    return owner
