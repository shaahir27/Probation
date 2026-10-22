"""Chains pack: Multi-step intent follow-up workflows.

Authority: docs/PACKS_SPEC.md section 4.
"""

from datetime import datetime, timedelta
from typing import Any

from probation.core.enums import EvidenceStrength
from probation.core.history import HistoryView
from probation.core.types import (
    Action,
    ActionSpec,
    ExamOperator,
    ExecResult,
    Features,
    Outcome,
    RawItem,
    ReaderSpec,
    Situation,
)
from probation.engine.caps import ACTION_CATALOG
from probation.packs.base import ExecutorIO, WorldView


class ChainsPack:
    """Pack adapter for multi-step follow-up chains."""

    name: str = "chains"
    families: tuple[str, ...] = ("chain_followup",)

    def iter_situations(self, raw_item: RawItem | dict[str, Any]) -> list[Situation]:
        """Chain situations are generated from trigger situations at proposal time."""
        return []

    def deterministic_clues(self, s: Situation, hist: HistoryView) -> dict[str, float | str | bool]:
        """Compute deterministic clues for chain follow-up situation."""
        return {"variant": s.variant, "is_chain": True}

    def reader_spec(self) -> ReaderSpec | None:
        """Chains rely on trigger situation reader features."""
        return None

    def class_key(self, s: Situation, f: Features) -> str:
        """Derive class key: chain|{variant}."""
        return f"chain|{s.variant}"

    def action_catalog(self) -> list[ActionSpec]:
        """Catalog of follow-up actions."""
        return [
            ACTION_CATALOG["BLOCK_TIME"],
            ACTION_CATALOG["CREATE_TASK"],
            ACTION_CATALOG["REPLY"],
        ]

    def level_cap(self, action: str, s: Situation, f: Features) -> int:
        """Autonomy level caps for chain follow-up actions."""
        spec = ACTION_CATALOG.get(action.upper())
        return spec.base_cap if spec else 0

    def hands_off(self, s: Situation) -> str | None:
        """Return non-null string reason if auto-acting is strictly forbidden."""
        return None

    def execute(self, a: Action, io: ExecutorIO) -> ExecResult:
        """Perform side-effect action."""
        from probation.packs.chains.executor import execute_chain_action

        return execute_chain_action(a, io)

    def undo(self, a: Action, io: ExecutorIO) -> ExecResult:
        """Reverse executed side-effect action."""
        from probation.packs.chains.executor import undo_chain_action

        return undo_chain_action(a.undo or {}, io)

    def window(self, s: Situation) -> timedelta:
        """Observation window duration (CHAIN_WINDOW_HOURS = 24h)."""
        return timedelta(hours=24)

    def resolve_outcome(self, s: Situation, world: WorldView, now: datetime) -> Outcome | None:
        """Resolve observed outcome for a chain follow-up situation.

        Authority: docs/PACKS_SPEC.md section 4.4 & docs/ENGINE_SPEC.md section 14:
        - At the end of the window with no response and no link -> NONE (WEAK).
        """
        # Default fallback outcome when window elapses
        return Outcome(
            situation_id=s.id,
            observed_action="NONE",
            strength=EvidenceStrength.WEAK,
            known_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    def exam_operators(self) -> list[ExamOperator]:
        """Perturbation operators for exam board."""
        return []


chains_pack = ChainsPack()
