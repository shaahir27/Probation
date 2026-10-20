"""Human study measurement and comparison harness.

Authority: docs/EVALUATION_PLAN.md section 6.
Simulates and evaluates 150-item synthetic human decisions (60 mails, 40 invites, 50 files)
to compute learning curves and level 1 licence acquisition under noisy human actions.
"""

import random
from dataclasses import dataclass
from typing import Any

from probation.eval.metrics import compute_agreement


@dataclass(frozen=True)
class HumanStudyResult:
    participant_id: str
    total_items: int
    learning_curve: list[tuple[int, float]]  # (labels_seen, agreement)
    final_agreement: float
    classes_at_level_1: list[str]


def simulate_human_decisions(
    truth_items: list[dict[str, Any]],
    human_noise: float = 0.15,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Simulate realistic human decisions on 150 synthetic items with human noise."""
    rng = random.Random(seed)
    participant_items: list[dict[str, Any]] = []

    for item in truth_items:
        true_act = str(item.get("true_action", "LEAVE"))
        fam = str(item.get("family", "email_action"))

        # Alternate action options for noise injection
        if fam == "email_action":
            options = ["REPLY", "ARCHIVE", "TRASH", "LEAVE"]
        elif fam == "invite_rsvp":
            options = ["ACCEPT", "DECLINE", "TENTATIVE"]
        elif fam == "file_destination":
            options = ["MOVE_TO_FOLDER:Documents", "MOVE_TO_FOLDER:College", "DELETE", "LEAVE"]
        else:
            options = ["TRACK", "DISMISS", "LEAVE"]

        if rng.random() < human_noise:
            # Pick a noisy alternative
            alt_options = [o for o in options if o != true_act]
            chosen_act = rng.choice(alt_options) if alt_options else true_act
        else:
            chosen_act = true_act

        participant_items.append(
            {
                "situation_id": item.get("situation_id", f"sit-{len(participant_items)}"),
                "family": fam,
                "class_key": item.get("class_key", f"{fam}|known"),
                "human_action": chosen_act,
                "true_action": true_act,
            }
        )

    return participant_items


def evaluate_human_study_participant(
    participant_id: str,
    predictions: list[str],
    human_decisions: list[dict[str, Any]],
    step_interval: int = 15,
) -> HumanStudyResult:
    """Compute learning curve and level 1 licence acquisition for a participant."""
    n = min(len(predictions), len(human_decisions))
    if n == 0:
        return HumanStudyResult(
            participant_id=participant_id,
            total_items=0,
            learning_curve=[],
            final_agreement=0.0,
            classes_at_level_1=[],
        )

    curve: list[tuple[int, float]] = []
    class_evidence: dict[str, int] = {}

    for i in range(1, n + 1):
        p_sub = predictions[:i]
        h_sub = [h["human_action"] for h in human_decisions[:i]]
        agr = compute_agreement(p_sub, h_sub).agreement_all

        # Check evidence for class
        ck = str(human_decisions[i - 1]["class_key"])
        if p_sub[-1] == h_sub[-1]:
            class_evidence[ck] = class_evidence.get(ck, 0) + 1

        if i % step_interval == 0 or i == n:
            curve.append((i, agr))

    final_agr = compute_agreement(
        predictions[:n], [h["human_action"] for h in human_decisions[:n]]
    ).agreement_all

    # Any class with >= 5 consistent successes earns level 1 eligibility
    classes_l1 = [ck for ck, count in class_evidence.items() if count >= 5]

    return HumanStudyResult(
        participant_id=participant_id,
        total_items=n,
        learning_curve=curve,
        final_agreement=final_agr,
        classes_at_level_1=classes_l1,
    )


def evaluate_participant_learning_curve(
    participant_id: str,
    predictions: list[str],
    human_decisions: list[dict[str, Any]],
    step_interval: int = 15,
) -> HumanStudyResult:
    """Alias for evaluate_human_study_participant."""
    return evaluate_human_study_participant(
        participant_id=participant_id,
        predictions=predictions,
        human_decisions=human_decisions,
        step_interval=step_interval,
    )


def generate_human_study_items(seed: int = 42) -> list[dict[str, Any]]:
    """Generate 150 synthetic items (60 mails, 40 invites, 50 files) for human study.

    Authority: docs/EVALUATION_PLAN.md section 6.
    """
    rng = random.Random(seed)
    items: list[dict[str, Any]] = []

    # 1. 60 emails
    mail_actions = ["REPLY", "ARCHIVE", "TRASH", "LEAVE"]
    for i in range(60):
        act = rng.choice(mail_actions)
        items.append(
            {
                "situation_id": f"study-mail-{i:03d}",
                "family": "email_action",
                "class_key": f"email_action|pattern_{i % 4}",
                "true_action": act,
                "text": f"Simulated email subject and inquiry #{i}",
            }
        )

    # 2. 40 calendar invites
    cal_actions = ["ACCEPT", "DECLINE"]
    for i in range(40):
        act = rng.choice(cal_actions)
        items.append(
            {
                "situation_id": f"study-cal-{i:03d}",
                "family": "invite_rsvp",
                "class_key": f"invite_rsvp|pattern_{i % 3}",
                "true_action": act,
                "text": f"Meeting invite #{i}",
            }
        )

    # 3. 50 files
    file_actions = ["MOVE_TO_FOLDER:Documents", "MOVE_TO_FOLDER:College", "DELETE", "LEAVE"]
    for i in range(50):
        act = rng.choice(file_actions)
        items.append(
            {
                "situation_id": f"study-file-{i:03d}",
                "family": "file_destination",
                "class_key": f"file_destination|ext_{i % 3}",
                "true_action": act,
                "text": f"Downloaded document_{i}.pdf",
            }
        )

    # Shuffle to interleave families
    rng.shuffle(items)
    return items


def run_human_study_simulation(
    seed: int = 42,
    n_participants: int = 6,
    noise_range: tuple[float, float] = (0.05, 0.20),
) -> dict[str, Any]:
    """Run full synthetic human study simulation across multiple participants."""
    items = generate_human_study_items(seed=seed)
    rng = random.Random(seed)
    results: list[HumanStudyResult] = []

    total_steps = len(items)
    step_agreements: dict[int, list[float]] = {i: [] for i in range(1, total_steps + 1)}

    for p_idx in range(n_participants):
        p_seed = seed + p_idx * 17
        noise = rng.uniform(noise_range[0], noise_range[1])
        decisions = simulate_human_decisions(items, human_noise=noise, seed=p_seed)

        preds: list[str] = []
        history: dict[str, str] = {}
        for d in decisions:
            ck = d["class_key"]
            if ck in history:
                pred_act = history[ck]
            else:
                pred_act = d["true_action"]
            history[ck] = d["human_action"]
            preds.append(pred_act)

        eval_res = evaluate_human_study_participant(
            participant_id=f"P{p_idx + 1}",
            predictions=preds,
            human_decisions=decisions,
            step_interval=1,
        )
        results.append(eval_res)

        for step, agr in eval_res.learning_curve:
            step_agreements[step].append(agr)

    mean_curve = [
        (step, float(sum(agrs) / len(agrs)))
        for step, agrs in sorted(step_agreements.items())
        if agrs
    ]
    mean_final = float(sum(r.final_agreement for r in results) / len(results)) if results else 0.0

    return {
        "participants": [
            {
                "id": r.participant_id,
                "final_agreement": r.final_agreement,
                "classes_at_level_1": r.classes_at_level_1,
            }
            for r in results
        ],
        "learning_curve": mean_curve,
        "mean_final_agreement": mean_final,
    }
