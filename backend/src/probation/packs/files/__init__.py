"""Files and downloads domain pack adapter.

Authority: docs/PACKS_SPEC.md section 3, docs/ENGINE_SPEC.md section 4, and docs/CONTRACT.md section 5.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from probation.config import settings
from probation.core.hashing import canonical_situation_id, normalize_rel_path
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
from probation.engine.handsoff import is_hands_off
from probation.llm.jobs import FileReader
from probation.packs.base import ExecutorIO, PackAdapter, WorldView
from probation.packs.files.clues import (
    extract_files_clues,
    extract_origin_group,
)
from probation.packs.files.exam_ops import FILES_EXAM_OPERATORS
from probation.packs.files.resolver import DEFAULT_FILE_WINDOW_DAYS, resolve_files_outcome

FILES_ACTION_CATALOG = [
    ActionSpec(type="MOVE_TO_FOLDER", recallable=True, base_cap=3, loss=5.0),
    ActionSpec(type="LEAVE", recallable=True, base_cap=0, loss=0.0),
]

FILE_READER_SCHEMA = FileReader.model_json_schema()


class FilesPack(PackAdapter):
    """Files and downloads pack adapter."""

    name: str = "files"
    families: tuple[str, ...] = ("file_destination",)

    def iter_situations(self, raw_item: RawItem | dict[str, Any]) -> list[Situation]:
        """Extract situations from ingested file records in watched directories."""
        if isinstance(raw_item, dict):
            raw_id = raw_item["id"]
            item_kind = raw_item.get("item_kind", "")
            occurred_at = raw_item["occurred_at"]
            payload_str = raw_item.get("payload_json", "{}")
            content_hash = raw_item.get("content_hash", "")
        else:
            raw_id = raw_item.id
            item_kind = raw_item.item_kind
            occurred_at = raw_item.occurred_at
            payload_str = raw_item.payload_json
            content_hash = raw_item.content_hash

        if item_kind != "file":
            return []

        try:
            payload = json.loads(payload_str)
        except Exception:
            payload = {}

        rel_path = payload.get("rel_path", "")
        filename = payload.get("filename") or Path(rel_path).name
        origin_url = payload.get("origin_url", "")

        # Check watched directories (default Downloads, Desktop)
        watched_dirs = [
            w.strip().replace("\\", "/").strip("/")
            for w in settings.files_watch_dirs.split(",")
            if w.strip()
        ]
        norm_rel_path = normalize_rel_path(rel_path)

        in_watched = False
        for w in watched_dirs:
            w_name = Path(w).name.lower()
            if (
                norm_rel_path == w
                or norm_rel_path.startswith(f"{w}/")
                or norm_rel_path.lower() == w_name
                or norm_rel_path.lower().startswith(f"{w_name}/")
                or any(part.lower() == w_name for part in Path(norm_rel_path).parts[:-1])
            ):
                in_watched = True
                break

        # If rel_path is simply a filename with no directory, treat as in watched directory
        if "/" not in norm_rel_path and norm_rel_path:
            in_watched = True

        if not in_watched and rel_path:
            return []

        origin_group = extract_origin_group(origin_url)
        hands_off_reason = is_hands_off(filename=filename)

        source_ref = (
            (
                raw_item.get("source_ref")
                if isinstance(raw_item, dict)
                else getattr(raw_item, "source_ref", None)
            )
            or norm_rel_path
            or raw_id
        )
        source_ref = normalize_rel_path(source_ref)

        situation_id = canonical_situation_id(
            "files", source_ref, occurred_at, "file_destination", ""
        )
        redacted_text = f"Filename: {filename}\nPath: {norm_rel_path}\nOrigin: {origin_url}"

        sit = Situation(
            id=situation_id,
            pack=self.name,
            family="file_destination",
            raw_item_id=raw_id,
            occurred_at=occurred_at,
            sender_key=origin_group,
            content_hash=content_hash,
            redacted_text=redacted_text,
            hands_off_reason=hands_off_reason,
            variant="",
            created_at=occurred_at,
        )
        return [sit]

    def deterministic_clues(self, s: Situation, hist: HistoryView) -> dict[str, float | str | bool]:
        """Compute clues strictly through HistoryView (Invariant I-6)."""
        raw_items = hist.get_raw_items(pack=self.name)
        payload: dict[str, Any] = {}
        for row in raw_items:
            if row["id"] == s.raw_item_id:
                try:
                    payload = json.loads(row["payload_json"])
                except Exception:
                    pass
                break
        return extract_files_clues(s, hist, payload)

    def reader_spec(self) -> ReaderSpec | None:
        """Prompt descriptor for file reader (optional)."""
        if not settings.files_reader_enabled:
            return None
        return ReaderSpec(
            prompt_id="reader.file",
            prompt_version="v1",
            json_schema=FILE_READER_SCHEMA,
            redaction_profile="file",
        )

    def class_key(self, s: Situation, f: Features) -> str:
        """Derive class key: file|{origin_group}|{ext_group} per PACKS_SPEC section 3.6."""
        origin_group = str(f.deterministic.get("origin_group", s.sender_key or "unknown"))
        ext_group = str(f.deterministic.get("ext_group", "other"))
        return f"file|{origin_group}|{ext_group}"

    def action_catalog(self) -> list[ActionSpec]:
        """Return action catalog for files."""
        return FILES_ACTION_CATALOG

    def level_cap(self, action: str, s: Situation, f: Features | None = None) -> int:
        """Apply conditional caps per ENGINE_SPEC section 8.1."""
        if s.hands_off_reason or self.hands_off(s):
            return 0
        act_upper = action.upper()
        if act_upper.startswith("MOVE_TO_FOLDER"):
            return 3
        return 0

    def hands_off(self, s: Situation) -> str | None:
        """Return hands-off reason if applicable."""
        if s.hands_off_reason:
            return s.hands_off_reason
        filename = ""
        if s.redacted_text and "Filename: " in s.redacted_text:
            filename = s.redacted_text.split("Filename: ", 1)[1].split("\n", 1)[0].strip()
        return is_hands_off(filename=filename) if filename else None

    def execute(self, a: Action, io: ExecutorIO) -> ExecResult:
        """Execute file side effect."""
        from probation.packs.files.executor import execute_files_action

        return execute_files_action(a, io)

    def undo(self, a: Action, io: ExecutorIO) -> ExecResult:
        """Undo executed file action."""
        from probation.packs.files.executor import undo_files_action

        return undo_files_action(a, io)

    def window(self, s: Situation) -> timedelta:
        """Observation window duration."""
        days = getattr(settings, "outcome_window_file_days", DEFAULT_FILE_WINDOW_DAYS)
        return timedelta(days=days)

    def resolve_outcome(self, s: Situation, world: WorldView, now: datetime) -> Outcome | None:
        """Resolve observed outcome from world state."""
        return resolve_files_outcome(s, world, now)

    def exam_operators(self) -> list[ExamOperator]:
        """Return perturbation operators for exam board evaluation."""
        return FILES_EXAM_OPERATORS


files_pack = FilesPack()
