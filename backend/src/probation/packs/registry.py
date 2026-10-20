"""Domain pack registry for probation.

Authority: docs/PACKS_SPEC.md section 0 and docs/CONTRACT.md section 5.
"""

from probation.packs.base import PackAdapter


def validate_pack(pack: PackAdapter) -> None:
    """Validate that a pack satisfies structural conformance rules."""
    if not pack.name:
        raise ValueError("Pack must have a non-empty name.")
    if not pack.families:
        raise ValueError(f"Pack '{pack.name}' must declare at least one family.")
    catalog = pack.action_catalog()
    if not catalog:
        raise ValueError(f"Pack '{pack.name}' must provide an action catalog.")
    for action_spec in catalog:
        if not (0 <= action_spec.base_cap <= 3):
            raise ValueError(f"Action '{action_spec.type}' has invalid cap: {action_spec.base_cap}")
        if action_spec.loss < 0:
            raise ValueError(f"Action '{action_spec.type}' has negative loss: {action_spec.loss}")


class PackRegistry:
    """Registry maintaining active domain packs."""

    def __init__(self) -> None:
        self._packs: dict[str, PackAdapter] = {}

    def register(self, pack: PackAdapter, validate: bool = True) -> None:
        """Register a new pack adapter."""
        if validate:
            validate_pack(pack)
        self._packs[pack.name] = pack

    def get(self, name: str) -> PackAdapter:
        """Retrieve pack adapter by name."""
        if name not in self._packs:
            raise KeyError(f"Pack '{name}' is not registered.")
        return self._packs[name]

    def get_by_family(self, family: str) -> PackAdapter | None:
        """Retrieve pack adapter that owns the given task family."""
        for pack in self._packs.values():
            if family in pack.families:
                return pack
        return None

    def list_packs(self) -> list[str]:
        """List registered pack names."""
        return list(self._packs.keys())


registry = PackRegistry()

# Auto-register core packs
from probation.packs.calendar import calendar_pack  # noqa: E402
from probation.packs.chains import chains_pack  # noqa: E402
from probation.packs.files import files_pack  # noqa: E402
from probation.packs.mail import mail_pack  # noqa: E402
from probation.packs.radar import radar_pack  # noqa: E402
from probation.packs.reading import reading_pack  # noqa: E402

registry.register(mail_pack)
registry.register(calendar_pack)
registry.register(chains_pack)
registry.register(files_pack)
registry.register(radar_pack)
registry.register(reading_pack)
