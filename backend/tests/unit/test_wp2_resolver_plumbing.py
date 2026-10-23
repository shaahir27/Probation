"""WP2 regression tests: raw-observation plumbing and realizable synthetic truth.

Authority: docs/CONTRACT.md section 5, CONTRACT amendment D5/CCR-E, docs/PACKS_SPEC.md
sections 1.6, 2.5 and 3.7, and docs/CHANGES_IMPLEMENTATION_PLAN.md sections 6.1-6.2.

A `Situation` carries only hashes and redacted text, so a resolver cannot recover the source
record it needs. These tests pin the internal seam that hands that record over, and the generator
invariant that every truth label is something the world actually recorded.
"""

import json
import random
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from probation.config import settings
from probation.core.actions import FAMILY_ACTIONS, NOOP_ACTIONS, PARAMETER_ACTIONS
from probation.core.enums import EvidenceStrength
from probation.core.types import Situation
from probation.packs.calendar import CalendarPack
from probation.packs.chains import ChainsPack
from probation.packs.descriptor import PackDescriptor
from probation.packs.files import FilesPack
from probation.packs.files.resolver import resolve_files_outcome
from probation.synth.generator import SyntheticGenerator
from probation.synth.habits_dsl import FAMILY_DEFAULT_DISTRIBUTIONS, evaluate_habit
from probation.synth.personas import get_persona
from probation.synth.world import SimWorld

OWNER = "meena.k@national.ac.in"
ACTED_AT = "2026-02-11T09:30:00Z"


class FootprintWorld:
    """Minimal world exposing only the dated footprint stream a resolver reads."""

    def __init__(self, actions: list[dict[str, Any]]) -> None:
        self._actions = actions

    def get_user_actions(
        self,
        item_id: str | None = None,
        as_of: str | None = None,
        actor: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = [
            a
            for a in self._actions
            if (item_id is None or a["item_id"] == item_id)
            and (as_of is None or str(a["acted_at"]) <= as_of)
            and (actor is None or a.get("actor", "user") == actor)
        ]
        return sorted(rows, key=lambda a: str(a["acted_at"]))

    def get_messages(self, label: str | None = None, as_of: str | None = None) -> list[dict]:
        return []

    def get_message(self, message_id: str, as_of: str | None = None) -> dict[str, Any] | None:
        return None

    def get_events(self, as_of: str | None = None) -> list[dict]:
        return []

    def get_event(self, uid: str, as_of: str | None = None) -> dict[str, Any] | None:
        return None


def _file_situation() -> Situation:
    return Situation(
        id="sit-file-1",
        raw_item_id="raw-file-1",
        pack="files",
        family="file_destination",
        occurred_at="2026-02-10T08:00:00Z",
        content_hash="h1",
        created_at="2026-02-10T08:00:00Z",
    )


def test_a_dated_move_footprint_resolves_strong_at_its_own_timestamp() -> None:
    """A recorded move is STRONG evidence known when the user made it, not at the window close."""
    world = FootprintWorld(
        [
            {
                "item_id": "Downloads/report.pdf",
                "action_type": "MOVE_TO_FOLDER",
                "acted_at": ACTED_AT,
                "actor": "user",
                "details": {"destination_folder": "College/CO301"},
            }
        ]
    )
    now = datetime(2026, 2, 12, tzinfo=UTC)

    outcome = resolve_files_outcome(
        _file_situation(), world, now, raw_payload={"rel_path": "Downloads/report.pdf"}
    )

    assert outcome is not None
    assert outcome.observed_action == "MOVE_TO_FOLDER:College/CO301"
    assert outcome.strength == EvidenceStrength.STRONG
    assert outcome.known_at == ACTED_AT


def test_a_footprint_after_the_observation_point_is_not_visible() -> None:
    """The move is dated, so asking earlier must not see it (invariant I-6)."""
    world = FootprintWorld(
        [
            {
                "item_id": "Downloads/report.pdf",
                "action_type": "MOVE_TO_FOLDER",
                "acted_at": ACTED_AT,
                "actor": "user",
                "details": {"destination_folder": "College/CO301"},
            }
        ]
    )
    before = datetime(2026, 2, 11, 8, 0, tzinfo=UTC)

    outcome = resolve_files_outcome(
        _file_situation(), world, before, raw_payload={"rel_path": "Downloads/report.pdf"}
    )

    assert outcome is None, "a move that has not happened yet resolved as an observed outcome"


def test_an_absent_root_is_not_evidence_that_the_file_was_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scan that never ran cannot conclude anything, least of all a STRONG disagreement.

    Every configured root is skipped when it does not exist on disk, so the old fall-through read
    "not found anywhere" as "the user deleted it". That invents deletion evidence for every
    left-alone file, the policy then learns the deletion and proposes an action the pack cannot
    render.
    """
    monkeypatch.setattr(settings, "files_allowed_roots", str(tmp_path / "unmounted"))
    monkeypatch.setattr(settings, "files_watch_dirs", "Downloads")
    world = FootprintWorld([])
    after_window = datetime(2026, 3, 1, tzinfo=UTC)

    outcome = resolve_files_outcome(
        _file_situation(), world, after_window, raw_payload={"rel_path": "Downloads/report.pdf"}
    )

    assert outcome is None, (
        f"a misconfigured root resolved as {outcome and outcome.observed_action}"
    )


def test_a_file_absent_from_a_scanned_root_still_resolves_as_a_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard above must not switch the physical scan off: a real scan finding nothing is evidence."""
    root = tmp_path / "root"
    (root / "College").mkdir(parents=True)
    monkeypatch.setattr(settings, "files_allowed_roots", str(root))
    monkeypatch.setattr(settings, "files_watch_dirs", "Downloads")
    after_window = datetime(2026, 3, 1, tzinfo=UTC)

    outcome = resolve_files_outcome(
        _file_situation(), FootprintWorld([]), after_window, raw_payload={"rel_path": "a.pdf"}
    )

    assert outcome is not None
    assert outcome.observed_action == "DELETE"
    assert outcome.strength == EvidenceStrength.STRONG


def test_a_file_found_outside_a_watched_folder_resolves_as_the_observed_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file sitting in an unwatched folder under a scanned root is where the user moved it."""
    root = tmp_path / "root"
    (root / "College" / "CO301").mkdir(parents=True)
    (root / "College" / "CO301" / "report.pdf").write_bytes(b"")
    monkeypatch.setattr(settings, "files_allowed_roots", str(root))
    monkeypatch.setattr(settings, "files_watch_dirs", "Downloads")
    after_window = datetime(2026, 3, 1, tzinfo=UTC)

    outcome = resolve_files_outcome(
        _file_situation(),
        FootprintWorld([]),
        after_window,
        raw_payload={"rel_path": "Downloads/report.pdf"},
    )

    assert outcome is not None
    assert outcome.observed_action == "MOVE_TO_FOLDER:College/CO301"


def test_the_descriptor_hands_the_raw_payload_to_a_pack_that_can_use_it() -> None:
    """The public three-argument boundary cannot recover the source path; the internal one can."""
    world = FootprintWorld(
        [
            {
                "item_id": "Downloads/report.pdf",
                "action_type": "MOVE_TO_FOLDER",
                "acted_at": ACTED_AT,
                "actor": "user",
                "details": {"destination_folder": "College/CO301"},
            }
        ]
    )
    sit = _file_situation()
    now = datetime(2026, 2, 12, tzinfo=UTC)
    descriptor = PackDescriptor(FilesPack())

    with_payload = descriptor.resolve_observed_outcome(
        sit, world, now, {"rel_path": "Downloads/report.pdf"}
    )
    without_payload = descriptor.resolve_outcome(sit, world, now)

    assert with_payload is not None
    assert with_payload.observed_action == "MOVE_TO_FOLDER:College/CO301"
    assert with_payload.strength == EvidenceStrength.STRONG
    assert without_payload is None or without_payload.strength == EvidenceStrength.WEAK


def test_a_pack_without_the_capability_is_still_called_through_the_public_boundary() -> None:
    """Declaring the internal seam must not change behaviour for a pack that has no use for it."""
    descriptor = PackDescriptor(ChainsPack())
    sit = Situation(
        id="sit-chain-1",
        raw_item_id="raw-chain-1",
        pack="chains",
        family="chain_followup",
        occurred_at="2026-02-10T08:00:00Z",
        content_hash="h1",
        created_at="2026-02-10T08:00:00Z",
    )
    now = datetime(2026, 3, 1, tzinfo=UTC)
    world = FootprintWorld([])

    observed = descriptor.resolve_observed_outcome(sit, world, now, {"rel_path": "ignored"})
    public = descriptor.resolve_outcome(sit, world, now)

    assert (observed is None) == (public is None)
    if observed is not None and public is not None:
        assert observed.observed_action == public.observed_action


def test_a_calendar_rsvp_footprint_resolves_strong_through_the_descriptor() -> None:
    """An RSVP is attributed from the dated footprint the world recorded for that invite."""
    world = FootprintWorld(
        [
            {
                "item_id": "inv-1@national.ac.in",
                "action_type": "ACCEPT",
                "acted_at": ACTED_AT,
                "actor": "user",
                "details": {},
            }
        ]
    )
    sit = Situation(
        id="sit-cal-1",
        raw_item_id="raw-cal-1",
        pack="calendar",
        family="invite_rsvp",
        occurred_at="2026-02-10T08:00:00Z",
        content_hash="h1",
        created_at="2026-02-10T08:00:00Z",
    )
    descriptor = PackDescriptor(CalendarPack(user_addresses=[OWNER]))
    now = datetime(2026, 2, 20, tzinfo=UTC)

    outcome = descriptor.resolve_observed_outcome(
        sit, world, now, {"uid": "inv-1@national.ac.in", "my_status": "NEEDS_ACTION"}
    )

    assert outcome is not None
    assert outcome.observed_action == "ACCEPT"
    assert outcome.strength == EvidenceStrength.STRONG


def test_noise_only_substitutes_actions_the_world_can_render() -> None:
    """Noise may change which action the user took, but not invent one nothing can record.

    The families the generator actually evaluates are checked with the noise roll forced on every
    call, so any unrealizable spelling in the alternative set appears here immediately. A bare
    `MOVE_TO_FOLDER` carries no destination: the file tree and the footprint stream both need one,
    so truth would claim a move that the world never made.
    """
    habits = replace(
        SyntheticGenerator(persona=get_persona(0), seed=11, size="tiny").habits, noise=1.0
    )
    rng = random.Random(5)

    for family in ("email_action", "invite_rsvp", "file_destination"):
        realizable = set(FAMILY_DEFAULT_DISTRIBUTIONS[family])
        for rule in habits.rules:
            if rule.family == family:
                realizable |= set(rule.then)
        for _ in range(60):
            result = evaluate_habit(habits, family, {}, 0, rng)
            assert result.final_action in realizable, (
                f"{family}: noise produced {result.final_action!r}, which nothing can render"
            )
            assert result.noise_applied
            assert result.final_action != result.candidate_action
            assert _is_renderable(result.final_action, family)


def _is_renderable(action: str, family: str) -> bool:
    """A parameterized action type is only renderable with its parameter supplied."""
    action_type, _, parameter = action.partition(":")
    if action_type not in FAMILY_ACTIONS[family]:
        return False
    return bool(parameter) if action_type in PARAMETER_ACTIONS else not parameter


def test_every_uncensored_truth_label_has_a_matching_footprint(tmp_path: Path) -> None:
    """Truth may only claim actions the world actually recorded, with a destination where needed.

    Compared as multisets per family: a label the generator emitted but never rendered shows up as
    a claim with no footprint behind it, which is what makes that family unevaluable.
    """
    out_dir = tmp_path / "synth"
    SyntheticGenerator(persona=get_persona(0), seed=7, size="tiny").generate(out_dir=out_dir)

    truth: dict[str, dict[str, Any]] = json.loads(
        (out_dir / "truth.json").read_text(encoding="utf-8")
    )
    with SimWorld(out_dir / "world.db") as world:
        actions = world.get_user_actions()

    claimed: Counter[str] = Counter()
    for record in truth.values():
        if record.get("is_censored"):
            continue
        action_type, _, parameter = str(record["true_action"]).partition(":")
        if action_type in NOOP_ACTIONS:
            continue
        claimed[_footprint_key(action_type, parameter)] += 1

    recorded: Counter[str] = Counter()
    for action in actions:
        details = action.get("details") or {}
        parameter = str(details.get("destination_folder") or "")
        recorded[_footprint_key(str(action["action_type"]), parameter)] += 1

    unrendered = {key: count for key, count in claimed.items() if recorded[key] < count}
    assert not unrendered, (
        f"truth claims footprints the world never recorded (claimed - recorded): {unrendered}"
    )


def _footprint_key(action_type: str, parameter: str) -> str:
    """One comparable spelling of an action, so a claim and its footprint can be matched."""
    return f"{action_type}:{parameter}" if parameter else action_type
