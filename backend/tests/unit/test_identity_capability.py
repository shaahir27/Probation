"""WP0: owner identity is optional and is not a requirement on WorldView."""

from probation.packs.identity import world_user_addresses


def test_read_only_world_without_identity_is_valid() -> None:
    assert world_user_addresses(object()) is None


def test_optional_identity_capability() -> None:
    class OwnerWorld:
        user_addresses: list[str] | str | None = "owner@example.test, alias@example.test"

    world = OwnerWorld()
    assert world_user_addresses(world) == ["owner@example.test", "alias@example.test"]
    world.user_addresses = [" owner@example.test ", ""]
    assert world_user_addresses(world) == ["owner@example.test"]
    world.user_addresses = " , "
    assert world_user_addresses(world) is None
