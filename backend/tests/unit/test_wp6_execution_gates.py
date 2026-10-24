"""Saved suggestions/audits cannot be converted into automatic authority by callers."""

from pathlib import Path

import pytest

from probation.core.enums import GateDecision
from probation.core.lifecycle import LifecycleDenied
from probation.core.review_binding import build_review_binding
from probation.workers.executor import Executor
from tests.unit.wp6_mail_fixture import GRANT, NOW, seed


@pytest.mark.parametrize("executing,audit", [(False, False), (True, True)])
def test_callers_cannot_upgrade_a_saved_suggestion_or_audit(
    tmp_path: Path, executing: bool, audit: bool
) -> None:
    conn, world = seed(tmp_path, autonomous=executing, audit_holdout=audit)
    binding = build_review_binding(
        conn,
        "proposal",
        grant=GRANT,
        owner_id="owner",
        restriction_revision="0",
        as_of=NOW,
        response="accept",
    )
    executor = Executor(conn, world, licence_checker=lambda *_: 3, grant_resolver=lambda _: GRANT)
    with pytest.raises(LifecycleDenied, match="proposal_not_executable"):
        executor.create_action(
            "proposal",
            "mail",
            "ARCHIVE",
            binding.params,
            2,
            True,
            GateDecision.EXECUTE_UNDO,
            NOW,
            binding=binding,
        )
    assert "INBOX" in world.get_message("<m@test.local>")["labels"]
    assert conn.execute("SELECT count(*) FROM actions").fetchone()[0] == 0
    world.close()
    conn.close()
