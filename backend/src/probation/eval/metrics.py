"""Core evaluation metrics functions.

Authority: docs/EVALUATION_PLAN.md section 3, docs/TEST_PLAN.md T-EVAL, and docs/CONTRACT.md.
All calculations are pure functions with strict mathematical specifications.
"""

from dataclasses import dataclass
from typing import Any

from probation.engine.caps import get_action_loss


@dataclass(frozen=True)
class AgreementMetrics:
    agreement_all: float
    agreement_non_abstained: float
    total: int
    non_abstained: int


@dataclass(frozen=True)
class InterruptionMetrics:
    asks_per_100: float
    suggestions_per_100: float
    attention_units_per_100: float
    asks: int
    suggestions: int
    total: int


@dataclass(frozen=True)
class CalibrationMetrics:
    ece: float
    brier: float
    bin_accuracies: list[float]
    bin_confidences: list[float]
    bin_counts: list[int]


@dataclass(frozen=True)
class DriftMetrics:
    detection_delay_days: int | None
    detection_delay_situations: int | None
    false_alarms_pre_drift: int
    detected: bool


@dataclass(frozen=True)
class ChainMetrics:
    precision: float
    recall: float
    planted_count: int
    mined_count: int
    matched_count: int


def compute_agreement(
    predictions: list[str],
    ground_truth: list[str],
    abstention_token: str | None = "ABSTAIN",
) -> AgreementMetrics:
    """Compute empirical agreement rate between predictions and human ground truth.

    Reported with abstentions counted as misses (agreement_all),
    and separately among non-abstained items (agreement_non_abstained).
    """
    if not predictions or len(predictions) != len(ground_truth):
        return AgreementMetrics(
            agreement_all=0.0,
            agreement_non_abstained=0.0,
            total=len(predictions),
            non_abstained=0,
        )

    n_total = len(predictions)
    matches_all = 0
    matches_non_abstained = 0
    n_non_abstained = 0

    for pred, truth in zip(predictions, ground_truth, strict=True):
        p_clean = pred.strip()
        t_clean = truth.strip()
        is_abstain = abstention_token is not None and p_clean == abstention_token

        if not is_abstain:
            n_non_abstained += 1
            if p_clean == t_clean:
                matches_non_abstained += 1
                matches_all += 1
        elif p_clean == t_clean:
            # If truth itself was ABSTAIN
            matches_all += 1

    agr_all = float(matches_all) / float(n_total) if n_total > 0 else 0.0
    agr_non_abs = (
        float(matches_non_abstained) / float(n_non_abstained) if n_non_abstained > 0 else 0.0
    )

    return AgreementMetrics(
        agreement_all=agr_all,
        agreement_non_abstained=agr_non_abs,
        total=n_total,
        non_abstained=n_non_abstained,
    )


def compute_precision(k: int, n: int) -> float:
    """Compute empirical precision k / n over an evidence set."""
    if n <= 0:
        return 0.0
    return float(k) / float(n)


def compute_autonomous_error_rate(
    auto_actions: list[str],
    true_actions: list[str],
) -> float:
    """Compute error rate among autonomously executed proposals A.

    Share of A where action != true_action.
    """
    if not auto_actions or len(auto_actions) != len(true_actions):
        return 0.0

    errors = sum(
        1 for a, t in zip(auto_actions, true_actions, strict=True) if a.strip() != t.strip()
    )
    return float(errors) / float(len(auto_actions))


def compute_harm_weighted_error(
    auto_actions: list[str],
    true_actions: list[str],
    losses: dict[str, float] | None = None,
) -> float:
    """Compute harm-weighted error rate among autonomously executed actions A.

    sum(loss(a) for a in A if a != true_action) / sum(loss(a) for a in A).
    """
    if not auto_actions or len(auto_actions) != len(true_actions):
        return 0.0

    total_loss = 0.0
    error_loss = 0.0

    for a, t in zip(auto_actions, true_actions, strict=True):
        act_clean = a.strip()
        loss_val = (
            losses.get(act_clean, get_action_loss(act_clean))
            if losses is not None
            else get_action_loss(act_clean)
        )
        total_loss += loss_val
        if act_clean != t.strip():
            error_loss += loss_val

    if total_loss <= 0.0:
        return 0.0

    return error_loss / total_loss


def compute_autonomous_coverage(
    auto_correct_count: int,
    non_noop_count: int,
) -> float:
    """Compute autonomous coverage among non-noop situations.

    Share of situations whose true action is not a no-op that were handled correctly by A.
    """
    if non_noop_count <= 0:
        return 0.0
    return float(auto_correct_count) / float(non_noop_count)


def compute_interruptions(
    asks: int,
    suggestions: int,
    total_situations: int,
    suggestion_weight: float = 0.3,
) -> InterruptionMetrics:
    """Compute human interruption metrics: asks/100, suggestions/100, attention units/100.

    Attention units per 100 = 100 * (asks + suggestion_weight * suggestions) / N.
    """
    if total_situations <= 0:
        return InterruptionMetrics(
            asks_per_100=0.0,
            suggestions_per_100=0.0,
            attention_units_per_100=0.0,
            asks=asks,
            suggestions=suggestions,
            total=total_situations,
        )

    n = float(total_situations)
    asks_per_100 = 100.0 * float(asks) / n
    sugg_per_100 = 100.0 * float(suggestions) / n
    attention_units = 100.0 * (float(asks) + suggestion_weight * float(suggestions)) / n

    return InterruptionMetrics(
        asks_per_100=asks_per_100,
        suggestions_per_100=sugg_per_100,
        attention_units_per_100=attention_units,
        asks=asks,
        suggestions=suggestions,
        total=total_situations,
    )


def compute_calibration(
    confidences: list[float],
    matches: list[bool],
    num_bins: int = 10,
) -> CalibrationMetrics:
    """Compute Expected Calibration Error (ECE) and Brier score over num_bins equal-width bins.

    Only computed for strong outcomes.
    """
    if not confidences or len(confidences) != len(matches):
        return CalibrationMetrics(
            ece=0.0,
            brier=0.0,
            bin_accuracies=[0.0] * num_bins,
            bin_confidences=[0.0] * num_bins,
            bin_counts=[0] * num_bins,
        )

    n_samples = len(confidences)

    # 1. Brier score = mean((p_i - y_i)^2)
    brier = sum(
        (p - (1.0 if y else 0.0)) ** 2 for p, y in zip(confidences, matches, strict=True)
    ) / float(n_samples)

    # 2. Equal-width bins [0.0, 0.1), [0.1, 0.2), ..., [0.9, 1.0]
    bin_counts = [0] * num_bins
    bin_conf_sums = [0.0] * num_bins
    bin_acc_sums = [0.0] * num_bins

    for p, y in zip(confidences, matches, strict=True):
        p_clamped = max(0.0, min(1.0, float(p)))
        # Bin index: map [0.0, 1.0] -> 0..(num_bins - 1)
        bin_idx = min(int(p_clamped * num_bins), num_bins - 1)
        bin_counts[bin_idx] += 1
        bin_conf_sums[bin_idx] += p_clamped
        if y:
            bin_acc_sums[bin_idx] += 1.0

    bin_accuracies: list[float] = []
    bin_confidences: list[float] = []
    ece = 0.0

    for i in range(num_bins):
        count = bin_counts[i]
        if count > 0:
            avg_acc = bin_acc_sums[i] / float(count)
            avg_conf = bin_conf_sums[i] / float(count)
            bin_accuracies.append(avg_acc)
            bin_confidences.append(avg_conf)
            # ECE weight: (count / n_samples) * |acc - conf|
            ece += (float(count) / float(n_samples)) * abs(avg_acc - avg_conf)
        else:
            bin_accuracies.append(0.0)
            bin_confidences.append(0.0)

    return CalibrationMetrics(
        ece=ece,
        brier=brier,
        bin_accuracies=bin_accuracies,
        bin_confidences=bin_confidences,
        bin_counts=bin_counts,
    )


def compute_drift_metrics(
    alarms: list[dict[str, Any]],
    drift_day: int,
    drift_situation_idx: int | None = None,
    pre_drift_window_days: int = 60,
) -> DriftMetrics:
    """Compute drift detection delay and pre-drift false alarms.

    Authority: docs/EVALUATION_PLAN.md section 3 & 8.
    drift_day is e.g. Day 120.
    """
    pre_drift_alarms = 0
    first_post_drift_day: int | None = None
    first_post_drift_sit: int | None = None

    for a in alarms:
        alarm_day = int(a.get("day", 0))
        alarm_sit = int(a.get("situation_idx", 0)) if "situation_idx" in a else None

        # Check pre-drift false alarm window [drift_day - pre_drift_window_days, drift_day)
        if (drift_day - pre_drift_window_days) <= alarm_day < drift_day:
            pre_drift_alarms += 1

        # Check first post-drift alarm
        if alarm_day >= drift_day:
            if first_post_drift_day is None or alarm_day < first_post_drift_day:
                first_post_drift_day = alarm_day
                first_post_drift_sit = alarm_sit

    delay_days = (first_post_drift_day - drift_day) if first_post_drift_day is not None else None
    delay_sits = None
    if first_post_drift_sit is not None and drift_situation_idx is not None:
        delay_sits = max(0, first_post_drift_sit - drift_situation_idx)

    return DriftMetrics(
        detection_delay_days=delay_days,
        detection_delay_situations=delay_sits,
        false_alarms_pre_drift=pre_drift_alarms,
        detected=first_post_drift_day is not None,
    )


def compute_chain_metrics(
    mined_chains: list[dict[str, Any]],
    planted_chains: list[dict[str, Any]],
) -> ChainMetrics:
    """Compute precision and recall of mined chains against planted ground truth.

    Matching criterion: trigger class/intent and follow action match.
    """
    if not mined_chains and not planted_chains:
        return ChainMetrics(
            precision=1.0,
            recall=1.0,
            planted_count=0,
            mined_count=0,
            matched_count=0,
        )

    def _chain_key(c: dict[str, Any]) -> tuple[str, str]:
        # Extract trigger identifier
        trig = c.get("trigger", {})
        trig_fam = str(trig.get("family", "")).lower() if isinstance(trig, dict) else ""
        trig_intent = (
            str(trig.get("intent", trig.get("sender_role", ""))).lower()
            if isinstance(trig, dict)
            else ""
        )
        trig_key = f"{trig_fam}:{trig_intent}"

        # Extract follow action
        follow = c.get("follow", [])
        act = ""
        if isinstance(follow, list) and follow:
            first_follow = follow[0]
            if isinstance(first_follow, dict):
                act = str(first_follow.get("action", "")).upper()
            else:
                act = str(first_follow).upper()
        elif isinstance(c.get("action"), str):
            act = str(c.get("action")).upper()
        return (trig_key, act)

    planted_keys = {_chain_key(p) for p in planted_chains}
    mined_keys = {_chain_key(m) for m in mined_chains}

    matched = planted_keys.intersection(mined_keys)
    n_matched = len(matched)
    n_mined = len(mined_keys)
    n_planted = len(planted_keys)

    prec = float(n_matched) / float(n_mined) if n_mined > 0 else 0.0
    rec = float(n_matched) / float(n_planted) if n_planted > 0 else 0.0

    return ChainMetrics(
        precision=prec,
        recall=rec,
        planted_count=n_planted,
        mined_count=n_mined,
        matched_count=n_matched,
    )
