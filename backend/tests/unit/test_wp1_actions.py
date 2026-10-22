"""WP1: canonical action types preserve parameters and enforce pack membership."""

import sqlite3

import pytest

from probation.core.enums import GateDecision
from probation.engine.caps import get_action_cap, get_action_loss, is_recallable
from probation.engine.gate import decide_gate
from probation.workers.executor import Executor


@pytest.mark.parametrize("label", ["MOVE_TO_FOLDER:College/Lab", "move_to_folder:College/Lab"])
def test_parameterized_move_uses_type_metadata(label: str) -> None:
    assert get_action_cap(label, family="file_destination") == 3
    assert get_action_loss(label) == 5
    assert is_recallable(label)


def test_parsed_action_keeps_parameter_case() -> None:
    from probation.core.actions import parse_action

    parsed = parse_action("move_to_folder:College/Sem3/Lab")
    assert parsed.type == "MOVE_TO_FOLDER"
    assert parsed.parameter == "College/Sem3/Lab"
    assert parsed.label == "MOVE_TO_FOLDER:College/Sem3/Lab"


@pytest.mark.parametrize(
    "label",
    [
        "MOVE_TO_FOLDER:",
        "MOVE_TO_FOLDER: ",
        "MOVE_TO_FOLDER::bad",
        "REPLY:bad",
        "SNOOZE",
        " ARCHIVE",
        "MOVE_TO_FOLDER:bad\x00path",
    ],
)
def test_malformed_actions_fail_closed(label: str) -> None:
    assert get_action_cap(label) == 0
    assert not is_recallable(label)


@pytest.mark.parametrize(
    "pack, action",
    [
        ("mail", "CREATE_TASK"),
        ("mail", "STAR"),
        ("calendar", "ARCHIVE"),
        ("mail", "LEAVE"),
        ("calendar", "NO_RESPONSE"),
        ("mail", "ABSTAIN"),
    ],
)
def test_executor_rejects_off_catalog_and_noop_before_creating_rows(
    memory_db: sqlite3.Connection, pack: str, action: str
) -> None:
    with pytest.raises(ValueError):
        Executor(memory_db).create_action(
            "missing-proposal",
            pack,
            action,
            {},
            2,
            True,
            GateDecision.EXECUTE_UNDO,
            "2026-01-01T00:00:00Z",
        )
    assert memory_db.execute("SELECT count(*) FROM actions").fetchone()[0] == 0
    assert memory_db.execute("SELECT count(*) FROM ledger").fetchone()[0] == 0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_probability_never_authorizes_an_effect(bad: float) -> None:
    assert (
        decide_gate(
            action="ARCHIVE", p=bad, licence_level=3, cap=3, loss=5, recallable=True
        ).decision
        == GateDecision.ASK
    )


def test_read_pack_descriptor_exposes_no_execution_interface() -> None:
    from probation.packs.registry import registry

    descriptor = registry.get_descriptor("mail")
    assert descriptor.name == "mail"
    assert descriptor.action_catalog()
    assert not hasattr(descriptor, "execute")
    assert not hasattr(descriptor, "undo")


@pytest.mark.parametrize(
    "action,family",
    [
        ("CREATE_TASK", "email_action"),
        ("ARCHIVE", "invite_rsvp"),
        ("MOVE_TO_FOLDER:Lab", "link_triage"),
    ],
)
def test_family_mismatch_has_no_cap(action: str, family: str) -> None:
    assert get_action_cap(action, family=family) == 0


@pytest.mark.parametrize("action", ["ABSTAIN", "NONE", "invented", "MOVE_TO_FOLDER:"])
def test_invalid_or_noop_cannot_acquire_a_derived_licence(action: str) -> None:
    from probation.engine.licence import derive_licence_level

    assert (
        derive_licence_level(action, 200, 0.999, 200, 0.999, 200, exam_ok_fn=lambda level: True)
        == 0
    )


def test_decision_registry_transitive_imports_exclude_executable_adapters() -> None:
    import subprocess
    import sys

    script = "import sys; from probation.packs.registry import registry; registry.get_descriptor('mail'); assert not [name for name in sys.modules if name.startswith('probation.packs.') and name.endswith('.executor')]"
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)
