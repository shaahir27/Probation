"""Contract test for Phase 6: Files Pack.

Authority: docs/PACKS_SPEC.md section 3, docs/ENGINE_SPEC.md sections 4, 8.2, and docs/TEST_PLAN.md.
Tests:
- T-PACK: Conformance checks for files pack.
- T-RESOLVE: Move to subfolder, leave at window close, delete as disagreement.
- T-EXEC: Non-overwriting collision handling ' (1)', undo safety when original occupied.
- T-HANDSOFF: Executable extensions, double extensions, right-to-left override character.
"""

import json
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from probation.config import settings
from probation.core.enums import EvidenceStrength
from probation.core.history import HistoryView
from probation.core.types import Action, ActionStatus, Situation
from probation.db.connection import apply_schema
from probation.packs.files import files_pack
from probation.packs.files.clues import (
    extract_ext_group,
    extract_files_clues,
    extract_origin_group,
    extract_size_bucket,
)
from probation.packs.files.exam_ops import (
    apply_files_code_operator,
    validate_files_operator_result,
)
from probation.packs.files.executor import execute_files_action, undo_files_action
from probation.packs.files.resolver import resolve_files_outcome
from probation.synth.world import SimWorld


def test_t_pack_files_catalog() -> None:
    """T-PACK: Files action catalog conforms to specifications."""
    catalog = files_pack.action_catalog()
    assert len(catalog) >= 2
    by_type = {s.type: s for s in catalog}

    assert "MOVE_TO_FOLDER" in by_type
    move_spec = by_type["MOVE_TO_FOLDER"]
    assert move_spec.base_cap == 3
    assert move_spec.loss == 5.0
    assert move_spec.recallable is True

    assert "LEAVE" in by_type
    leave_spec = by_type["LEAVE"]
    assert leave_spec.base_cap == 0


def test_t_handsoff_files_detection() -> None:
    """T-HANDSOFF: Strict detection of blocked executables, double extensions, and RLO."""
    # 1. Blocked extension
    raw_exe = {
        "id": "raw-f1",
        "pack": "files",
        "item_kind": "file",
        "occurred_at": "2026-03-01T10:00:00Z",
        "payload_json": json.dumps(
            {"rel_path": "Downloads/installer.exe", "filename": "installer.exe"}
        ),
    }
    sits_exe = files_pack.iter_situations(raw_exe)
    assert len(sits_exe) == 1
    assert sits_exe[0].hands_off_reason is not None
    assert "executable" in sits_exe[0].hands_off_reason.lower()
    assert files_pack.level_cap("MOVE_TO_FOLDER:Apps", sits_exe[0], None) == 0  # type: ignore

    # 2. Double extension (e.g. invoice.pdf.exe)
    raw_double = {
        "id": "raw-f2",
        "pack": "files",
        "item_kind": "file",
        "occurred_at": "2026-03-01T10:00:00Z",
        "payload_json": json.dumps(
            {"rel_path": "Downloads/invoice.pdf.exe", "filename": "invoice.pdf.exe"}
        ),
    }
    sits_double = files_pack.iter_situations(raw_double)
    assert len(sits_double) == 1
    assert sits_double[0].hands_off_reason is not None
    assert "double extension" in sits_double[0].hands_off_reason.lower()

    # 3. Unicode right-to-left override character U+202E
    rlo_name = "document\u202egpn.exe"
    raw_rlo = {
        "id": "raw-f3",
        "pack": "files",
        "item_kind": "file",
        "occurred_at": "2026-03-01T10:00:00Z",
        "payload_json": json.dumps({"rel_path": f"Downloads/{rlo_name}", "filename": rlo_name}),
    }
    sits_rlo = files_pack.iter_situations(raw_rlo)
    assert len(sits_rlo) == 1
    assert sits_rlo[0].hands_off_reason is not None

    # 4. Safe file: no hands off
    raw_safe = {
        "id": "raw-f4",
        "pack": "files",
        "item_kind": "file",
        "occurred_at": "2026-03-01T10:00:00Z",
        "payload_json": json.dumps(
            {"rel_path": "Downloads/lecture_notes.pdf", "filename": "lecture_notes.pdf"}
        ),
    }
    sits_safe = files_pack.iter_situations(raw_safe)
    assert len(sits_safe) == 1
    assert sits_safe[0].hands_off_reason is None


def test_t_pack_files_clues() -> None:
    """T-PACK: Deterministic clues extraction strictly bounded by HistoryView."""
    # Test helper extractors
    assert extract_origin_group("https://canvas.stanford.edu/files/123/download") == "stanford.edu"
    assert extract_origin_group("https://sub.univ.ac.in/notes.pdf") == "univ.ac.in"
    assert extract_origin_group("") == "unknown"

    assert extract_ext_group("pdf") == "doc"
    assert extract_ext_group("xlsx") == "sheet"
    assert extract_ext_group("py") == "code"
    assert extract_ext_group("mp4") == "audio_video"
    assert extract_ext_group("unknown_xyz") == "other"

    assert extract_size_bucket(50000) == "xs"
    assert extract_size_bucket(500000) == "s"
    assert extract_size_bucket(5000000) == "m"
    assert extract_size_bucket(50000000) == "l"

    with tempfile.TemporaryDirectory() as tmp_dir:
        conn = sqlite3.connect(str(Path(tmp_dir) / "clues.db"))
        apply_schema(conn)

        sit = Situation(
            id="sit-test-file-01",
            raw_item_id="raw-01",
            pack="files",
            family="file_destination",
            variant="",
            occurred_at="2026-04-10T14:30:00Z",
            sender_key="stanford.edu",
            content_hash="h1",
            redacted_text="",
            hands_off_reason=None,
            created_at="2026-04-10T14:30:00Z",
        )
        hist = HistoryView(conn, as_of=sit.occurred_at)

        payload = {
            "rel_path": "Downloads/CS101_Assignment_1.pdf",
            "filename": "CS101_Assignment_1.pdf",
            "ext": "pdf",
            "size_bytes": 250000,
            "origin_url": "https://canvas.stanford.edu/assignments/1",
        }
        clues = extract_files_clues(sit, hist, payload)

        assert clues["origin_group"] == "stanford.edu"
        assert clues["ext_group"] == "doc"
        assert clues["size_bucket"] == "s"
        assert clues["name_has_digits"] is True
        assert clues["name_len"] == len("CS101_Assignment_1.pdf")
        assert clues["n_prior_from_origin"] == 0
        assert clues["tok_assignment"] is True
        assert clues["tok_invoice"] is False
        conn.close()


def test_t_exec_files_move_collision_and_undo() -> None:
    """T-EXEC: Moves files without overwrite, handles collision with ' (1)', and fails undo safely."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root_dir = Path(tmp_dir) / "fs"
        downloads_dir = root_dir / "Downloads"
        courses_dir = root_dir / "Courses" / "CS101"

        downloads_dir.mkdir(parents=True, exist_ok=True)
        courses_dir.mkdir(parents=True, exist_ok=True)

        # Configure allowed roots
        settings.files_allowed_roots = str(root_dir)

        test_file = downloads_dir / "lab_report.pdf"
        test_file.write_text("content v1")

        action = Action(
            id="act-f1",
            proposal_id="prop-f1",
            pack="files",
            type="MOVE_TO_FOLDER:Courses/CS101",
            params={"path": str(test_file)},
            level_required=2,
            recallable=True,
            status=ActionStatus.PENDING,
            hold_until=None,
            undo=None,
            created_at="2026-03-01T12:00:00Z",
            updated_at="2026-03-01T12:00:00Z",
        )

        # 1. Execute first move
        res1 = execute_files_action(action, None)  # type: ignore
        assert res1.success is True
        dest1 = courses_dir / "lab_report.pdf"
        assert dest1.exists()
        assert not test_file.exists()
        assert res1.undo_data is not None

        # 2. Collision test: Create another file with the same name and move it
        test_file.write_text("content v2")
        action_col = Action(
            id="act-f2",
            proposal_id="prop-f2",
            pack="files",
            type="MOVE_TO_FOLDER:Courses/CS101",
            params={"path": str(test_file)},
            level_required=2,
            recallable=True,
            status=ActionStatus.PENDING,
            hold_until=None,
            undo=None,
            created_at="2026-03-01T12:05:00Z",
            updated_at="2026-03-01T12:05:00Z",
        )
        res2 = execute_files_action(action_col, None)  # type: ignore
        assert res2.success is True
        dest2 = courses_dir / "lab_report (1).pdf"
        assert dest2.exists()
        assert dest1.read_text() == "content v1"
        assert dest2.read_text() == "content v2"

        # 3. Safe Undo test
        # Recreating file in original path to test occupied safety
        test_file.write_text("intruder occupying path")
        action_with_undo = action.model_copy(update={"undo": res1.undo_data})
        undo_occupied = undo_files_action(action_with_undo, None)  # type: ignore
        assert undo_occupied.success is False
        assert "occupied" in undo_occupied.error.lower()
        assert dest1.exists()  # Kept intact

        # Clear occupant and perform undo cleanly
        test_file.unlink()
        undo_clean = undo_files_action(action_with_undo, None)  # type: ignore
        assert undo_clean.success is True
        assert test_file.exists()
        assert test_file.read_text() == "content v1"
        assert not dest1.exists()


def test_t_resolve_files_outcomes() -> None:
    """T-RESOLVE: Move to subfolder (STRONG), delete (STRONG), leave at window close (WEAK)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        world = SimWorld(str(Path(tmp_dir) / "world.db"))
        sit = Situation(
            id="sit-res-01",
            raw_item_id="raw-res-01",
            pack="files",
            family="file_destination",
            variant="",
            occurred_at="2026-03-01T10:00:00Z",
            sender_key="unknown",
            content_hash="h1",
            redacted_text="",
            hands_off_reason=None,
            created_at="2026-03-01T10:00:00Z",
        )

        now_during_window = datetime(2026, 3, 5, 10, 0, 0, tzinfo=UTC)
        now_after_window = datetime(2026, 3, 20, 10, 0, 0, tzinfo=UTC)

        # 1. Explicit move observed in payload
        res_move = resolve_files_outcome(
            sit,
            world,
            now_during_window,
            raw_payload={"observed_action": "MOVE_TO_FOLDER:Archive/Docs"},
        )
        assert res_move is not None
        assert res_move.observed_action == "MOVE_TO_FOLDER:Archive/Docs"
        assert res_move.strength == EvidenceStrength.STRONG

        # 2. File deleted
        res_del = resolve_files_outcome(
            sit,
            world,
            now_during_window,
            raw_payload={"observed_action": "DELETE"},
        )
        assert res_del is not None
        assert res_del.observed_action == "DELETE"
        assert res_del.strength == EvidenceStrength.STRONG

        # 3. File unacted before window close -> None (unresolved)
        res_pending = resolve_files_outcome(
            sit,
            world,
            now_during_window,
            raw_payload={"observed_action": "LEAVE"},
        )
        assert res_pending is None

        # 4. File unacted at window close -> LEAVE (WEAK)
        res_leave = resolve_files_outcome(
            sit,
            world,
            now_after_window,
            raw_payload={"observed_action": "LEAVE"},
        )
        assert res_leave is not None
        assert res_leave.observed_action == "LEAVE"
        assert res_leave.strength == EvidenceStrength.WEAK
        world.close()


def test_t_exam_files_operators() -> None:
    """T-EXAM: Files perturbation operators run and validate correctly."""
    base_payload = {
        "name": "homework_3.pdf",
        "ext": ".pdf",
        "size": 50000,
        "origin_url": "https://college.edu/hw3.pdf",
    }

    # 1. rename_trivial
    p_rename = apply_files_code_operator("rename_trivial", base_payload)
    assert validate_files_operator_result("rename_trivial", base_payload, p_rename)

    # 2. size_jitter
    p_size = apply_files_code_operator("size_jitter", base_payload)
    assert validate_files_operator_result("size_jitter", base_payload, p_size)

    # 3. executable_extension
    p_exe = apply_files_code_operator("executable_extension", base_payload)
    assert validate_files_operator_result("executable_extension", base_payload, p_exe)

    # 4. double_extension
    p_double = apply_files_code_operator("double_extension", base_payload)
    assert validate_files_operator_result("double_extension", base_payload, p_double)
