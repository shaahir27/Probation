"""Domain pack registry for probation.

Authority: docs/PACKS_SPEC.md section 0.
"""

from probation.packs.base import PackAdapter


class PackRegistry:
    """Registry maintaining active domain packs."""

    def __init__(self) -> None:
        self._packs: dict[str, PackAdapter] = {}

    def register(self, pack: PackAdapter) -> None:
        """Register a new pack adapter."""
        self._packs[pack.name] = pack

    def get(self, name: str) -> PackAdapter:
        """Retrieve pack adapter by name."""
        if name not in self._packs:
            raise KeyError(f"Pack '{name}' is not registered.")
        return self._packs[name]

    def list_packs(self) -> list[str]:
        """List registered pack names."""
        return list(self._packs.keys())


registry = PackRegistry()
