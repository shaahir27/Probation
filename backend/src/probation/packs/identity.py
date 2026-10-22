"""Optional owner identity capability, separate from a read-only world interface."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class UserIdentityView(Protocol):
    """A source may explicitly supply owner addresses; it carries no credentials."""

    @property
    def user_addresses(self) -> list[str] | str | None: ...


def world_user_addresses(world: object) -> list[str] | None:
    """Return a validated optional identity, without requiring every world to have one."""
    if not isinstance(world, UserIdentityView):
        return None
    value = world.user_addresses
    if isinstance(value, str):
        return [address.strip() for address in value.split(",") if address.strip()] or None
    if isinstance(value, list) and all(isinstance(address, str) for address in value):
        return [address.strip() for address in value if address.strip()] or None
    return None
