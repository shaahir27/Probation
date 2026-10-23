"""Optional owner identity capability, separate from a read-only world interface."""

import sqlite3
from typing import Any, Protocol, runtime_checkable

from probation.core.identity import normalize_user_addresses


@runtime_checkable
class MetaReader(Protocol):
    """Anything that can run one read query: a raw cursor or a role-guarded cursor."""

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> object: ...

    def fetchone(self) -> sqlite3.Row | None: ...


@runtime_checkable
class UserIdentityView(Protocol):
    """A source may explicitly supply owner addresses; it carries no credentials."""

    @property
    def user_addresses(self) -> list[str] | str | None: ...


def world_user_addresses(world: object) -> list[str] | None:
    """Return a validated optional identity, without requiring every world to have one.

    `None` means "this world does not say", which is distinct from an empty identity, so
    callers can fall through to the persisted or configured owner instead of concluding that
    nobody owns the mailbox. Addresses are normalized centrally rather than here so that a
    world, an import and a resolver cannot disagree about spelling.
    """
    if not isinstance(world, UserIdentityView):
        return None
    value = world.user_addresses
    if isinstance(value, str):
        return normalize_user_addresses(value) or None
    if isinstance(value, list) and all(isinstance(address, str) for address in value):
        return normalize_user_addresses(value) or None
    return None


def persisted_or_configured_owner(cur: MetaReader) -> list[str]:
    """The owner recorded on import, falling back to configuration.

    A blank or absent `meta.user_addresses` means "not recorded", never "ownerless": with an empty
    identity nothing counts as the owner's own sent mail, so no reply can be attributed and every
    outcome collapses to its WEAK default. The read is guarded because it may run before migration.
    """
    try:
        cur.execute("SELECT value FROM meta WHERE key = 'user_addresses';")
        meta_row = cur.fetchone()
    except sqlite3.Error:
        meta_row = None
    if meta_row and meta_row[0]:
        return normalize_user_addresses(str(meta_row[0]))

    from probation.config import settings

    return normalize_user_addresses(settings.user_addresses)
