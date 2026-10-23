"""DSL defining hidden user habit rules, chains, noise, and temporal drift.

Authority: docs/EVALUATION_PLAN.md section 2.2 and docs/PACKS_SPEC.md section 0.4.
Evaluates ground-truth persona actions given situation attributes.
"""

import random
from dataclasses import dataclass
from typing import Any

from probation.synth.personas import Persona

# Baseline default action distributions when no explicit rule matches.
# Keys are realizable actions, spelled exactly as the world records them; the canonical action-type
# vocabulary for each family lives in core/actions.py and is not duplicated here.
FAMILY_DEFAULT_DISTRIBUTIONS: dict[str, dict[str, float]] = {
    "email_action": {
        "LEAVE": 0.50,
        "ARCHIVE": 0.30,
        "REPLY": 0.15,
        "TRASH": 0.04,
        "FORWARD": 0.01,
    },
    "invite_rsvp": {
        "ACCEPT": 0.60,
        "DECLINE": 0.30,
        "TENTATIVE": 0.10,
    },
    "file_destination": {
        "LEAVE": 0.60,
        "MOVE_TO_FOLDER:Downloads/Misc": 0.40,
    },
    "opportunity_triage": {
        "DISMISS": 0.60,
        "TRACK": 0.30,
        "LEAVE": 0.10,
    },
    "link_triage": {
        "LEAVE": 0.50,
        "ARCHIVE_LINK": 0.30,
        "FILE_TO_COLLECTION": 0.20,
    },
}


@dataclass(frozen=True)
class HabitRule:
    """A single conditional habit rule."""

    id: str
    family: str
    when: dict[str, Any]
    then: dict[str, float]  # Action -> probability


@dataclass(frozen=True)
class ChainRule:
    """Multi-pack sequence trigger."""

    trigger: dict[str, Any]
    follow: list[dict[str, Any]]  # List of {action, p, delay_hours: [min, max]}


@dataclass(frozen=True)
class DriftSpec:
    """Temporal habit drift configuration occurring at a specific day."""

    at_day: int
    changes: list[dict[str, Any]]  # List of {"rule": rule_id, "then": dict[str, float]}


@dataclass
class PersonaHabits:
    """Complete collection of hidden rules, chains, and drift for a persona."""

    persona_id: int
    noise: float
    rules: list[HabitRule]
    chains: list[ChainRule]
    drift: DriftSpec

    def to_dict(self) -> dict[str, Any]:
        """Convert habits specification to serializable dictionary."""
        return {
            "persona_id": self.persona_id,
            "noise": self.noise,
            "rules": [
                {"id": r.id, "family": r.family, "when": r.when, "then": r.then} for r in self.rules
            ],
            "chains": [{"trigger": c.trigger, "follow": c.follow} for c in self.chains],
            "drift": {
                "at_day": self.drift.at_day,
                "changes": self.drift.changes,
            },
        }


@dataclass(frozen=True)
class EvaluationResult:
    """Result of evaluating a situation against persona habits."""

    candidate_action: str
    final_action: str
    rule_id: str
    is_drifted: bool
    noise_applied: bool


def _matches_when(condition: dict[str, Any], attributes: dict[str, Any]) -> bool:
    """Check if situation attributes satisfy all conditions in 'when'."""
    for key, expected in condition.items():
        actual = attributes.get(key)
        if actual is None:
            return False
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def _sample_action(distribution: dict[str, float], rng: random.Random) -> str:
    """Sample an action according to normalized probabilities."""
    actions = list(distribution.keys())
    weights = [max(0.0, float(w)) for w in distribution.values()]
    total = sum(weights)
    if total <= 0:
        return actions[0]
    norm_weights = [w / total for w in weights]
    return rng.choices(actions, weights=norm_weights, k=1)[0]


def evaluate_habit(
    habits: PersonaHabits,
    family: str,
    attributes: dict[str, Any],
    day_idx: int,
    rng: random.Random,
) -> EvaluationResult:
    """Evaluate persona habit rule, applying drift and noise.

    Authority: docs/EVALUATION_PLAN.md section 2.2.
    """
    is_drift_period = day_idx >= habits.drift.at_day
    drift_map: dict[str, dict[str, float]] = {}
    if is_drift_period:
        for chg in habits.drift.changes:
            drift_map[chg["rule"]] = chg["then"]

    matched_rule: HabitRule | None = None
    distribution: dict[str, float] | None = None
    is_drifted = False

    for rule in habits.rules:
        if rule.family == family and _matches_when(rule.when, attributes):
            matched_rule = rule
            if rule.id in drift_map:
                distribution = drift_map[rule.id]
                is_drifted = True
            else:
                distribution = rule.then
            break

    if matched_rule is None or distribution is None:
        rule_id = "DEFAULT"
        distribution = FAMILY_DEFAULT_DISTRIBUTIONS.get(
            family, {"LEAVE": 0.8, "ARCHIVE": 0.1, "REPLY": 0.1}
        )
    else:
        rule_id = matched_rule.id

    candidate_action = _sample_action(distribution, rng)

    # Apply noise: with probability `noise`, substitute a different realizable action.
    # Alternatives come from the rule and default distributions rather than a declared action-type
    # vocabulary, because those are the only actions the world can actually render. A bare type
    # name such as `MOVE_TO_FOLDER` carries no destination, so nothing is written to user_actions
    # or to the file tree, and truth.json would claim a footprint that does not exist.
    noise_applied = False
    final_action = candidate_action
    if rng.random() < habits.noise:
        realizable = sorted(set(distribution) | set(FAMILY_DEFAULT_DISTRIBUTIONS.get(family, {})))
        alternatives = [a for a in realizable if a != candidate_action]
        if alternatives:
            final_action = rng.choice(alternatives)
            noise_applied = True

    return EvaluationResult(
        candidate_action=candidate_action,
        final_action=final_action,
        rule_id=rule_id,
        is_drifted=is_drifted,
        noise_applied=noise_applied,
    )


def build_habits_for_persona(persona: Persona, seed: int = 42) -> PersonaHabits:
    """Generate deterministic habit rules, chains, and drift for a persona."""
    course_folder = persona.folders[0] if persona.folders else "College/Coursework"
    lab_folder = persona.folders[1] if len(persona.folders) > 1 else "College/Lab"

    rules: list[HabitRule] = [
        # Mail habits
        HabitRule(
            id="R1",
            family="email_action",
            when={"sender_role": "professor", "intent": "request"},
            then={"REPLY": 0.95, "LEAVE": 0.05},
        ),
        HabitRule(
            id="R2",
            family="email_action",
            when={"intent": "newsletter"},
            then={"ARCHIVE": 0.96, "TRASH": 0.04},
        ),
        HabitRule(
            id="R3",
            family="email_action",
            when={"sender_role": "service", "intent": "notification"},
            then={"ARCHIVE": 0.92, "LEAVE": 0.08},
        ),
        HabitRule(
            id="R4",
            family="email_action",
            when={"sender_role": "friend", "intent": "chat"},
            then={"REPLY": 0.90, "LEAVE": 0.10},
        ),
        HabitRule(
            id="R5",
            family="email_action",
            when={"sender_role": "recruiter", "intent": "opportunity"},
            then={"REPLY": 0.88, "ARCHIVE": 0.12},
        ),
        HabitRule(
            id="R6",
            family="email_action",
            when={"intent": "receipt"},
            then={"ARCHIVE": 0.94, "LEAVE": 0.06},
        ),
        HabitRule(
            id="R7",
            family="email_action",
            when={"intent": "sales"},
            then={"TRASH": 0.85, "ARCHIVE": 0.15},
        ),
        # Calendar invite habits
        HabitRule(
            id="R8",
            family="invite_rsvp",
            when={"start_hour_bucket": "early"},  # Before 9:00 AM
            then={"DECLINE": 0.93, "ACCEPT": 0.07},
        ),
        HabitRule(
            id="R9",
            family="invite_rsvp",
            when={"organizer_role": "professor"},
            then={"ACCEPT": 0.97, "DECLINE": 0.03},
        ),
        HabitRule(
            id="R10",
            family="invite_rsvp",
            when={"organizer_role": "club"},
            then={"ACCEPT": 0.86, "DECLINE": 0.14},
        ),
        HabitRule(
            id="R11",
            family="invite_rsvp",
            when={"start_hour_bucket": "weekend"},
            then={"DECLINE": 0.80, "ACCEPT": 0.20},
        ),
        # File destination habits
        HabitRule(
            id="R12",
            family="file_destination",
            when={"origin_site": persona.origin_sites[0]},  # College portal
            then={f"MOVE_TO_FOLDER:{course_folder}": 0.96, "LEAVE": 0.04},
        ),
        HabitRule(
            id="R13",
            family="file_destination",
            when={"origin_site": "arxiv.org"},
            then={f"MOVE_TO_FOLDER:{lab_folder}": 0.95, "LEAVE": 0.05},
        ),
        HabitRule(
            id="R14",
            family="file_destination",
            when={"ext": "pdf", "origin_site": "moodle.college.edu"},
            then={f"MOVE_TO_FOLDER:{course_folder}": 0.97, "LEAVE": 0.03},
        ),
    ]

    chains: list[ChainRule] = [
        ChainRule(
            trigger={
                "family": "email_action",
                "sender_role": "professor",
                "has_deadline": True,
            },
            follow=[
                {"action": "REPLY", "p": 0.95},
                {"action": "BLOCK_TIME", "p": 0.85, "delay_hours": [2, 20]},
            ],
        )
    ]

    drift = DriftSpec(
        at_day=120,
        changes=[
            # R8 (Early invites): previously 93% DECLINE, now shifts to 80% ACCEPT
            {"rule": "R8", "then": {"ACCEPT": 0.80, "DECLINE": 0.20}},
            # R2 (Newsletters): previously 96% ARCHIVE, now 50% LEAVE / 50% ARCHIVE
            {"rule": "R2", "then": {"ARCHIVE": 0.50, "LEAVE": 0.50}},
        ],
    )

    return PersonaHabits(
        persona_id=persona.id,
        noise=0.07,
        rules=rules,
        chains=chains,
        drift=drift,
    )
