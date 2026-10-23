"""Read/decision pack capability; deliberately contains no execution methods."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from probation.core.history import HistoryView
from probation.core.types import (
    ActionSpec,
    ExamOperator,
    Features,
    Outcome,
    RawItem,
    ReaderSpec,
    Situation,
)
from probation.packs.base import PackAdapter, RawObservationResolver, WorldView


@dataclass(frozen=True, slots=True)
class PackDescriptor:
    _adapter: PackAdapter

    @property
    def name(self) -> str:
        return self._adapter.name

    @property
    def families(self) -> tuple[str, ...]:
        return self._adapter.families

    def iter_situations(self, raw_item: RawItem | dict[str, Any]) -> list[Situation]:
        return self._adapter.iter_situations(raw_item)

    def deterministic_clues(self, situation: Situation, history: HistoryView) -> dict[str, Any]:
        return self._adapter.deterministic_clues(situation, history)

    def reader_spec(self) -> ReaderSpec | None:
        return self._adapter.reader_spec()

    def class_key(self, situation: Situation, features: Features) -> str:
        return self._adapter.class_key(situation, features)

    def action_catalog(self) -> list[ActionSpec]:
        return self._adapter.action_catalog()

    def level_cap(self, action: str, situation: Situation, features: Features) -> int:
        return self._adapter.level_cap(action, situation, features)

    def hands_off(self, situation: Situation) -> str | None:
        return self._adapter.hands_off(situation)

    def window(self, situation: Situation) -> timedelta:
        return self._adapter.window(situation)

    def resolve_outcome(
        self, situation: Situation, world: WorldView, now: datetime
    ) -> Outcome | None:
        return self._adapter.resolve_outcome(situation, world, now)

    def resolve_observed_outcome(
        self,
        situation: Situation,
        world: WorldView,
        now: datetime,
        raw_payload: dict[str, Any] | None = None,
    ) -> Outcome | None:
        """Resolve an outcome with its source observation attached, where the pack can use it.

        A pack that does not declare the internal capability is called through the unchanged
        public three-argument boundary, so this cannot alter behaviour for a pack that has no
        use for source identity.
        """
        adapter = self._adapter
        if isinstance(adapter, RawObservationResolver):
            return adapter.resolve_observed_outcome(situation, world, now, raw_payload)
        return adapter.resolve_outcome(situation, world, now)

    def exam_operators(self) -> list[ExamOperator]:
        return self._adapter.exam_operators()
