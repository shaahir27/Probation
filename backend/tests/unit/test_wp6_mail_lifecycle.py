"""Actual mail before-state, correlation and restart boundaries (D3)."""

from dataclasses import replace
from pathlib import Path

import pytest

from probation.core.types import Action
from probation.packs.mail.executor import execute_mail_action, undo_mail_action
from probation.synth.world import SimWorld


def message(world: SimWorld, labels: list[str]) -> None:
    world.add_message(
        "m",
        "<m@test.local>",
        "thread",
        "sender@test.local",
        "owner@test.local",
        "Notice",
        "Some information.",
        labels,
        "2026-10-01T00:00:00Z",
    )


def action(kind: str) -> Action:
    return Action(
        id="a",
        proposal_id="p",
        pack="mail",
        type=kind,
        params={"message_id": "<m@test.local>"},
        level_required=2,
        recallable=True,
        created_at="2026-10-01T01:00:00Z",
        updated_at="2026-10-01T01:00:00Z",
    )


def test_undo_refuses_missing_label_version_proof(tmp_path: Path) -> None:
    from probation.packs.mail.lifecycle_io import MailConflict
    from probation.packs.mail.lifecycle_operations import prepare_undo

    with SimWorld(tmp_path / "world.db") as world:
        message(world, ["INBOX"])
        act = action("ARCHIVE")
        result = execute_mail_action(act, world)
        assert result.success
        current = replace(world.snapshot_mail("<m@test.local>"), label_versions={})
        with pytest.raises(MailConflict, match="undo_label_history_conflict"):
            prepare_undo(act.model_copy(update={"undo": result.undo_data}), current)


@pytest.mark.parametrize(
    "kind,labels", [("ARCHIVE", ["IMPORTANT"]), ("TRASH", ["TRASH", "IMPORTANT"])]
)
def test_undo_never_invents_a_label_change(tmp_path: Path, kind: str, labels: list[str]) -> None:
    with SimWorld(tmp_path / "world.db") as world:
        message(world, labels)
        act = action(kind)
        result = execute_mail_action(act, world)
        assert result.success
        undone = undo_mail_action(act.model_copy(update={"undo": result.undo_data}), world)
        assert undone.success
        assert set(world.get_message("<m@test.local>")["labels"]) == set(labels)  # type: ignore[index]


def test_correlated_effect_survives_reopen_and_rejects_changed_payload(tmp_path: Path) -> None:
    from probation.packs.mail.lifecycle_io import MailConflict
    from probation.packs.mail.lifecycle_operations import payload_digest

    path = tmp_path / "world.db"
    with SimWorld(path) as world:
        message(world, ["INBOX"])
        before = world.snapshot_mail("<m@test.local>")
        payload = {
            "type": "labels",
            "resource_id": before.resource_id,
            "add_labels": [],
            "remove_labels": ["INBOX"],
        }
        payload_hash = payload_digest(payload)
        receipt = world.apply_mail("operation", payload_hash, payload, before.revision)
        assert receipt.outcome == "confirmed"
    with SimWorld(path) as world:
        assert world.reconcile_mail("operation", payload_hash) == receipt
        assert world.apply_mail("operation", payload_hash, payload, before.revision) == receipt
        with pytest.raises(MailConflict):
            world.apply_mail("operation", "different", payload, before.revision)
        assert world.reconcile_mail("missing", "hash").outcome == "unknown"


def test_undo_preserves_unrelated_labels_and_rejects_touched_conflict(tmp_path: Path) -> None:
    with SimWorld(tmp_path / "world.db") as world:
        message(world, ["INBOX"])
        act = action("ARCHIVE")
        result = execute_mail_action(act, world)
        world.update_message_labels("<m@test.local>", add_labels=["IMPORTANT"])
        assert undo_mail_action(act.model_copy(update={"undo": result.undo_data}), world).success
        assert set(world.get_message("<m@test.local>")["labels"]) == {"INBOX", "IMPORTANT"}  # type: ignore[index]
        result = execute_mail_action(action("ARCHIVE").model_copy(update={"id": "b"}), world)
        world.update_message_labels("<m@test.local>", add_labels=["INBOX"])
        assert not undo_mail_action(
            act.model_copy(update={"undo": result.undo_data}), world
        ).success


def test_undo_rejects_label_removed_and_reapplied_by_another_actor(tmp_path: Path) -> None:
    with SimWorld(tmp_path / "world.db") as world:
        message(world, ["INBOX"])
        act = action("TRASH")
        result = execute_mail_action(act, world)
        assert result.success
        world.update_message_labels("<m@test.local>", remove_labels=["TRASH"])
        world.update_message_labels("<m@test.local>", add_labels=["TRASH"])
        assert not undo_mail_action(
            act.model_copy(update={"undo": result.undo_data}), world
        ).success
        assert "TRASH" in world.get_message("<m@test.local>")["labels"]
